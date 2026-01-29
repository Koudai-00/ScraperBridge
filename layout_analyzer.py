import os
import logging
import re
import json
import psycopg2
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai


class LayoutAnalyzer:
    """レシピサイトのレイアウトを解析し、調理モード用のCSSルールを生成するクラス"""

    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.database_url = os.getenv("DATABASE_URL")
        self._gemini_initialized = False
        self.cache_expiry_days = 30

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8'
        })

    def _ensure_gemini_initialized(self):
        """Gemini APIを遅延初期化"""
        if not self._gemini_initialized:
            if not self.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY is required for layout analysis. "
                    "Please set GEMINI_API_KEY environment variable."
                )
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_initialized = True

    def _extract_domain(self, url: str) -> str:
        """URLからドメインを抽出"""
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain

    def _fetch_html(self, url: str) -> str:
        """URLからHTMLを取得"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return response.text
        except requests.RequestException as e:
            logging.error(f"Failed to fetch HTML from {url}: {e}")
            raise ValueError(f"URLからHTMLを取得できませんでした: {str(e)}")

    def _lightweight_html(self, html: str) -> str:
        """HTMLを軽量化（script, style, コメント等を削除）してAIに渡す"""
        soup = BeautifulSoup(html, 'html.parser')

        for tag in soup.find_all(['script', 'style', 'noscript', 'iframe', 'svg', 'path']):
            tag.decompose()

        for comment in soup.find_all(string=lambda text: isinstance(text, type(soup.new_string(''))) and text.parent.name is None):
            pass

        for tag in soup.find_all(True):
            attrs_to_keep = ['class', 'id', 'role', 'aria-label', 'data-testid']
            attrs = dict(tag.attrs)
            for attr in attrs:
                if attr not in attrs_to_keep:
                    del tag.attrs[attr]

        html_text = str(soup)

        html_text = re.sub(r'\s+', ' ', html_text)
        html_text = re.sub(r'>\s+<', '><', html_text)

        max_length = 50000
        if len(html_text) > max_length:
            html_text = html_text[:max_length]
            logging.warning(f"HTML truncated to {max_length} characters")

        return html_text

    def _get_cached_rules(self, site_domain: str) -> Optional[Dict[str, Any]]:
        """DBからキャッシュされたルールを取得（1ヶ月以内のもの）"""
        if not self.database_url:
            logging.warning("DATABASE_URL not set, skipping cache check")
            return None

        try:
            conn = psycopg2.connect(self.database_url)
            cur = conn.cursor()

            expiry_date = datetime.now() - timedelta(days=self.cache_expiry_days)

            cur.execute("""
                SELECT site_domain, hide_selectors, main_content_selector, created_at, updated_at
                FROM layout_rules
                WHERE site_domain = %s AND updated_at > %s
            """, (site_domain, expiry_date))

            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                logging.info(f"Cache hit for domain: {site_domain}")
                return {
                    'site_domain': row[0],
                    'hide_selectors': row[1] if row[1] else [],
                    'main_content_selector': row[2],
                    'created_at': row[3].isoformat() if row[3] else None,
                    'updated_at': row[4].isoformat() if row[4] else None,
                    'cached': True
                }

            logging.info(f"Cache miss for domain: {site_domain}")
            return None

        except Exception as e:
            logging.error(f"Error checking cache: {e}")
            return None

    def _save_rules_to_db(self, site_domain: str, hide_selectors: List[str], main_content_selector: str) -> bool:
        """ルールをDBに保存（UPSERT）"""
        if not self.database_url:
            logging.warning("DATABASE_URL not set, skipping save")
            return False

        try:
            conn = psycopg2.connect(self.database_url)
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO layout_rules (site_domain, hide_selectors, main_content_selector, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (site_domain)
                DO UPDATE SET
                    hide_selectors = EXCLUDED.hide_selectors,
                    main_content_selector = EXCLUDED.main_content_selector,
                    updated_at = NOW()
            """, (site_domain, hide_selectors, main_content_selector))

            conn.commit()
            cur.close()
            conn.close()

            logging.info(f"Saved rules for domain: {site_domain}")
            return True

        except Exception as e:
            logging.error(f"Error saving rules to DB: {e}")
            return False

    def _log_analysis(self, user_id: str, recipe_url: str, site_domain: str) -> bool:
        """利用履歴をDBに記録"""
        if not self.database_url:
            return False

        try:
            conn = psycopg2.connect(self.database_url)
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO layout_analysis_logs (user_id, recipe_url, site_domain, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (user_id, recipe_url, site_domain))

            conn.commit()
            cur.close()
            conn.close()

            logging.info(f"Logged analysis for user: {user_id}, domain: {site_domain}")
            return True

        except Exception as e:
            logging.error(f"Error logging analysis: {e}")
            return False

    def _analyze_with_gemini(self, html: str, site_domain: str) -> Dict[str, Any]:
        """Gemini 2.0 Flash LiteでHTMLを解析してCSSセレクタを抽出"""
        self._ensure_gemini_initialized()

        prompt = f"""あなたはWebページのレイアウト解析の専門家です。
以下のHTML（{site_domain}のレシピページ）を解析し、「調理モード」表示のためのCSSセレクタを抽出してください。

## タスク
1. レシピ閲覧に不要な要素（広告、サイドバー、ナビゲーション、SNSボタン、コメント欄、おすすめ記事など）を非表示にするためのCSSセレクタを特定
2. レシピのメインコンテンツ（料理名、材料、手順）を含む要素のCSSセレクタを特定

## 出力形式
必ず以下のJSON形式で出力してください。それ以外のテキストは不要です。

```json
{{
  "site_domain": "{site_domain}",
  "hide_selectors": [
    ".ad-container",
    "#sidebar",
    ".social-buttons",
    "..."
  ],
  "main_content_selector": ".recipe-main"
}}
```

## 注意事項
- hide_selectorsは配列で、CSSセレクタを文字列で列挙
- 確実に存在する要素のセレクタのみを含める
- 一般的すぎるセレクタ（div, span等）は避ける
- main_content_selectorはレシピ本体を含む最も適切な1つのセレクタ

## 解析対象HTML
{html}
"""

        try:
            model = genai.GenerativeModel('gemini-2.0-flash-lite')
            response = model.generate_content(prompt)

            response_text = response.text.strip()

            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group())

                if 'hide_selectors' not in result:
                    result['hide_selectors'] = []
                if 'main_content_selector' not in result:
                    result['main_content_selector'] = 'body'
                if 'site_domain' not in result:
                    result['site_domain'] = site_domain

                return result

            logging.warning(f"Could not parse JSON from Gemini response: {response_text[:200]}")
            return {
                'site_domain': site_domain,
                'hide_selectors': [],
                'main_content_selector': 'body'
            }

        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error from Gemini: {e}")
            return {
                'site_domain': site_domain,
                'hide_selectors': [],
                'main_content_selector': 'body'
            }
        except Exception as e:
            logging.error(f"Gemini API error: {e}")
            raise ValueError(f"AI解析中にエラーが発生しました: {str(e)}")

    def analyze_layout(self, url: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        URLのレイアウトを解析してCSSルールを返す
        
        1. ドメインを抽出
        2. DBキャッシュを確認（1ヶ月以内のルールがあれば返却）
        3. キャッシュがなければHTMLをフェッチ
        4. HTMLを軽量化
        5. Gemini 2.0 Flash Liteで解析
        6. 結果をDBに保存
        7. 利用履歴を記録
        """
        site_domain = self._extract_domain(url)
        logging.info(f"Analyzing layout for URL: {url}, domain: {site_domain}")

        cached_rules = self._get_cached_rules(site_domain)
        if cached_rules:
            if user_id:
                self._log_analysis(user_id, url, site_domain)
            return cached_rules

        html = self._fetch_html(url)
        logging.info(f"Fetched HTML: {len(html)} characters")

        lightweight_html = self._lightweight_html(html)
        logging.info(f"Lightweight HTML: {len(lightweight_html)} characters")

        result = self._analyze_with_gemini(lightweight_html, site_domain)
        result['cached'] = False

        self._save_rules_to_db(
            site_domain,
            result.get('hide_selectors', []),
            result.get('main_content_selector', 'body')
        )

        if user_id:
            self._log_analysis(user_id, url, site_domain)

        return result

"""
OpenRouter API Client with automatic fallback support.
Provides access to Japanese-capable AI models with automatic fallback on errors.

Model Priority Order (3 models only):
1. google/gemma-3-27b-it:free (OpenRouter)
2. google/gemma-3-12b-it:free (OpenRouter)
3. gemini-2.0-flash-lite (via Gemini API, fallback)

Note: Video analysis uses Gemini API directly (gemini-2.0-flash-lite), not OpenRouter.
"""

import os
import logging
import requests
import time
import base64
import json
import re
import psycopg2
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from typing import Dict, Any, List, Optional



OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 使用するモデルリスト（ユーザー指定）
TEXT_MODELS = [
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]



# 動画解析はGemini API直接使用のため、OpenRouterでは使用しない
VIDEO_CAPABLE_MODELS = []

# すべてのモデル情報（UI表示用）
ALL_MODELS_INFO = {
    "japanese_capable": [
        {"id": m, "name": m.split("/")[1].replace(":free", ""), "category": "日本語対応"} 
        for m in TEXT_MODELS
    ] + [
        {"id": "gemini-2.0-flash-lite", "name": "gemini-2.0-flash-lite", "category": "日本語対応（Gemini API）"}
    ],
}


class OpenRouterClient:
    """Client for OpenRouter API with automatic fallback on rate limits."""
    
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.log_db_url = os.getenv("LOG_DATABASE_URL")
        self.base_url = OPENROUTER_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://replit.com",
            "X-Title": "Recipe Extractor"
        }
        self._gemini_initialized = False
        
        # モデルごとのステータス管理
        self.model_stats = {}
        for m in TEXT_MODELS:
            self.model_stats[m] = {
                "last_used": None,
                "status": "unused",  # unused, success, error
                "success_count": 0,
                "error_count": 0,
                "last_error": None
            }
        # Gemini直接利用のステータスも追加
        self.model_stats["gemini-1.5-flash (direct)"] = {
            "last_used": None,
            "status": "unused",
            "success_count": 0,
            "error_count": 0,
            "last_error": None
        }

    def _log_to_db(self, model: str, status: str, error_message: str = None, tokens: int = 0):
        """データベースへログを保存"""
        if not self.log_db_url:
            return

        try:
            conn = psycopg2.connect(self.log_db_url)
            cur = conn.cursor()
            query = """
                INSERT INTO ai_usage_logs (model_name, status, error_message, tokens_used)
                VALUES (%s, %s, %s, %s)
            """
            cur.execute(query, (model, status, error_message, tokens))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to write log to DB: {e}")

    def _update_model_status(self, model: str, success: bool, error_msg: str = None, tokens: int = 0):
        """モデルの使用状況を更新（メモリ＆DB）"""
        # メモリ上のステータス更新（既存ロジック）
        if model not in self.model_stats:
            self.model_stats[model] = {
                "last_used": None,
                "status": "unused",
                "success_count": 0,
                "error_count": 0,
                "last_error": None
            }
        
        stats = self.model_stats[model]
        # 日本時間 (UTC+9) を取得
        JST = timezone(timedelta(hours=9))
        stats["last_used"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        
        status_str = "success" if success else "error"
        
        if success:
            stats["status"] = "success"
            stats["success_count"] += 1
            stats["last_error"] = None
        else:
            stats["status"] = "error"
            stats["error_count"] += 1
            stats["last_error"] = error_msg

        # DBへログ保存
        self._log_to_db(model, status_str, error_msg, tokens)

    def get_model_status(self) -> Dict[str, Any]:
        """全モデルのステータスを取得（DBがあればDBから集計、なければメモリ）"""
        if not self.log_db_url:
            return self.model_stats

        try:
            conn = psycopg2.connect(self.log_db_url)
            cur = conn.cursor()
            
            # 各モデルの最新状態と集計を取得
            # 注意: ここでは簡易的にメモリ上のstats構造に合わせてデータを構築する
            # 本来はGROUP BYで集計するが、現在のself.model_statsの構造を維持して返す
            
            # ベースとして現在のTEXT_MODELSを使用
            db_stats = {}
            for m in TEXT_MODELS + ["gemini-1.5-flash (direct)"]:
                db_stats[m] = {
                    "last_used": None,
                    "status": "unused",
                    "success_count": 0,
                    "error_count": 0,
                    "last_error": None
                }
            
            # 集計クエリ: モデルごとの成功数、失敗数、最終使用日時、最終エラー
            query = """
                SELECT 
                    model_name,
                    COUNT(*) FILTER (WHERE status = 'success') as success_count,
                    COUNT(*) FILTER (WHERE status = 'error') as error_count,
                    MAX(timestamp) as last_used,
                    (SELECT error_message FROM ai_usage_logs l2 
                     WHERE l2.model_name = l1.model_name AND status = 'error' 
                     ORDER BY timestamp DESC LIMIT 1) as last_error,
                    (SELECT status FROM ai_usage_logs l3 
                     WHERE l3.model_name = l1.model_name 
                     ORDER BY timestamp DESC LIMIT 1) as current_status
                FROM ai_usage_logs l1
                GROUP BY model_name
            """
            cur.execute(query)
            rows = cur.fetchall()
            
            for row in rows:
                model_name = row[0]
                # statsにないモデル（過去のモデルなど）も含まれる可能性があるためチェック
                if model_name not in db_stats:
                     db_stats[model_name] = {}
                
                # DBのUTC時間をJSTに変換 (Neon/Postgresは通常UTCで保存されるため)
                # ただし、保存時に特に変換していなければDB内はすでにJSTかもしれないが、
                # _update_model_statusでnow(JST)を使っているため、DBにはJSTの時刻文字列が入っているはず。
                # ここでは単純に文字列として取得する。
                last_used_str = row[3].strftime("%Y-%m-%d %H:%M:%S") if row[3] else None
                
                db_stats[model_name] = {
                    "success_count": row[1],
                    "error_count": row[2],
                    "last_used": last_used_str,
                    "last_error": row[4],
                    "status": row[5] if row[5] else "unused"
                }

            cur.close()
            conn.close()
            return db_stats
            
        except Exception as e:
            logging.error(f"Failed to fetch stats from DB: {e}")
            return self.model_stats

    def check_all_models(self) -> Dict[str, Any]:
        """全モデルの動作確認を一括実行"""
        results = {}
        
        # 1年以上前のログを削除（メンテナンス作業）
        self.cleanup_old_logs()

        def check_single_model(model_name):
            try:
                # テスト用メッセージ
                messages = [{"role": "user", "content": "Hello"}]
                # 最大トークンを小さくして高速化
                if "direct" in model_name:
                    # Gemini Direct
                    if self._ensure_gemini_initialized():
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        response = model.generate_content("Hello")
                        if response and response.text:
                            self._update_model_status(model_name, True, tokens=0)
                            return True
                        else:
                            raise Exception("No response text")
                    else:
                        raise Exception("Gemini API key not set")
                else:
                    # OpenRouter
                    response = self._call_api(model_name, messages, max_tokens=10)
                    if response.status_code == 200:
                        self._update_model_status(model_name, True, tokens=0)
                        return True
                    else:
                        error_msg = f"HTTP {response.status_code}"
                        try:
                            error_msg += f": {response.json().get('error', {}).get('message', '')}"
                        except:
                            pass
                        raise Exception(error_msg)
            except Exception as e:
                self._update_model_status(model_name, False, str(e))
                return False

        # 並列実行
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_model = {
                executor.submit(check_single_model, m): m 
                for m in TEXT_MODELS + ["gemini-1.5-flash (direct)"]
            }
            for future in as_completed(future_to_model):
                model = future_to_model[future]
                try:
                    success = future.result()
                    results[model] = "OK" if success else "Error"
                except Exception as e:
                    results[model] = f"Error: {e}"
        
        return results

    def cleanup_old_logs(self):
        """1年以上前のログを削除"""
        if not self.log_db_url:
            return
            
        try:
            conn = psycopg2.connect(self.log_db_url)
            cur = conn.cursor()
            # 1年以上前のデータを削除
            query = "DELETE FROM ai_usage_logs WHERE timestamp < NOW() - INTERVAL '1 year'"
            cur.execute(query)
            deleted_count = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} old log entries.")
        except Exception as e:
            logging.error(f"Failed to cleanup old logs: {e}")



    def _ensure_gemini_initialized(self):

        """Gemini APIを初期化"""
        if not self._gemini_initialized and self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self._gemini_initialized = True
        return self._gemini_initialized

    
    def _call_api(self, model: str, messages: List[Dict[str, str]], 
                  max_tokens: int = 4096, temperature: float = 0.7) -> Dict[str, Any]:
        """Make a single API call to OpenRouter."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        response = requests.post(
            self.base_url,
            headers=self.headers,
            json=payload,
            timeout=120
        )
        
        return response
    
    def chat_completion(self, messages: List[Dict[str, str]], 
                        models: Optional[List[str]] = None,
                        max_tokens: int = 4096,
                        temperature: float = 0.7) -> Dict[str, Any]:
        """
        Send a chat completion request with automatic fallback on 429 errors.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            models: List of models to try in order. Defaults to TEXT_MODELS.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            Dict with 'content', 'model_used', 'tokens_used', 'success'
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        
        if models is None:
            models = TEXT_MODELS
        
        last_error = None
        
        for model in models:
            try:
                logging.info(f"Trying OpenRouter model: {model}")
                response = self._call_api(model, messages, max_tokens, temperature)
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    
                    return {
                        "success": True,
                        "content": content,
                        "model_used": model,
                        "tokens_used": usage.get("total_tokens", 0),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    }
                elif response.status_code == 429:
                    self._update_model_status(model, False, f"Rate limit (429)")
                    logging.warning(f"Rate limited on {model}, trying next model...")
                    last_error = f"Rate limit exceeded for {model}"
                    time.sleep(0.5)
                    continue
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", response.text)
                        logging.warning(f"Error from {model} (HTTP {response.status_code}): {error_msg}")
                    except Exception:
                        error_msg = response.text
                        logging.warning(f"Error from {model} (HTTP {response.status_code}): {error_msg}")
                    last_error = error_msg
                    self._update_model_status(model, False, f"HTTP {response.status_code}: {error_msg}")
                    continue
                    
            except requests.exceptions.Timeout:
                self._update_model_status(model, False, "Timeout")
                logging.warning(f"Timeout on {model}, trying next model...")
                last_error = f"Timeout for {model}"
                continue
            except Exception as e:
                self._update_model_status(model, False, str(e))
                logging.warning(f"Exception with {model}: {e}")
                last_error = str(e)
                continue
        
        # OpenRouterが全滅した場合、Gemini APIを直接試行
        if self._ensure_gemini_initialized():
            logging.info("All OpenRouter models failed. Falling back to Gemini API directly.")
            try:
                model = genai.GenerativeModel("gemini-1.5-flash") # 正しいモデルID
                # メッセージ形式をGemini向けに変換
                prompt = "\n".join([m['content'] for m in messages if m['role'] == 'user'])
                response = model.generate_content(prompt)
                
                if response and response.text:
                    self._update_model_status("gemini-1.5-flash (direct)", True, tokens=0)
                    return {
                        "success": True,
                        "content": response.text,
                        "model_used": "gemini-1.5-flash (direct)",
                        "tokens_used": 0, # 直接APIの場合は簡易化
                    }
            except Exception as e:
                self._update_model_status("gemini-1.5-flash (direct)", False, str(e))
                logging.error(f"Direct Gemini API fallback also failed: {e}")
                last_error = f"{last_error} | Gemini fallback error: {str(e)}"
        
        return {
            "success": False,
            "content": None,
            "model_used": None,
            "error": last_error or "All models failed",
            "tokens_used": 0,
        }

    
    def chat_completion_with_vision(self, messages: List[Dict[str, Any]],
                                     models: Optional[List[str]] = None,
                                     max_tokens: int = 4096,
                                     temperature: float = 0.7) -> Dict[str, Any]:
        """
        Send a chat completion request with vision/image support.
        Uses TEXT_MODELS with automatic fallback.
        
        Args:
            messages: List of message dicts, content can include image_url
            models: List of models to try. Defaults to TEXT_MODELS.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            Dict with 'content', 'model_used', 'tokens_used', 'success', 'needs_translation'
        """
        if models is None:
            models = TEXT_MODELS
        
        result = self.chat_completion(messages, models, max_tokens, temperature)
        result["needs_translation"] = False
        
        return result
    
    def translate_to_japanese(self, text: str) -> Dict[str, Any]:
        """
        Translate text to Japanese using the reserved translation model (google/gemma-3-27b-it:free).
        
        This model is kept as the last resort for translation purposes, ensuring it's available
        even when other models hit rate limits.
        
        Args:
            text: Text to translate
            
        Returns:
            Dict with 'content' (translated text), 'model_used', 'success'
        """
        messages = [
            {
                "role": "user",
                "content": f"あなたは優秀な翻訳者です。与えられたテキストを自然な日本語に翻訳してください。レシピの場合は、材料名や調理用語を日本語で適切に表現してください。\n\n以下のテキストを日本語に翻訳してください。レシピ形式を維持し、【材料】【作り方】などのセクション見出しは日本語で表記してください。\n\n{text}"
            }
        ]
        
        # 翻訳にはTEXT_MODELSを使用（gemma-3-27b-itが最優先）
        return self.chat_completion(messages, TEXT_MODELS, max_tokens=4096, temperature=0.3)
    
    def refine_recipe(self, raw_text: str, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Refine raw recipe text using OpenRouter models.
        
        Args:
            raw_text: Raw recipe text to refine
            model: Specific model to use, or None for automatic fallback
            
        Returns:
            Dict with refined recipe content and metadata
        """
        messages = [
            {
                "role": "user",
                "content": f"""あなたは料理レシピの整理専門家です。与えられたテキストからレシピ情報のみを抽出し、整形してください。

以下の情報は必ず除外してください：
- BGM情報、音楽クレジット（BGM: ○○、Music by、♪、使用音源など）
- チャンネル登録やいいねのお願い
- スポンサー情報、PR、宣伝
- カメラ・編集ソフト情報
- コメント欄への誘導
- SNSリンク、ハッシュタグ
- 動画投稿者の自己紹介

レシピが含まれていない場合は、以下のJSONを返してください：
{{"no_recipe": true}}

レシピが含まれている場合は、以下のJSON形式で返してください：
{{"ingredients": [{{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}}], "steps": ["手順1"], "tips": ["コツ1"]}}

【重要】材料リストのみで作り方/手順が記載されていない場合は、レシピとして成立しないため {{"no_recipe": true}} を返してください。

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

以下のテキストからレシピを抽出してください：

{raw_text}"""
            }
        ]
        
        models = [model] if model else TEXT_MODELS
        return self.chat_completion(messages, models, max_tokens=4096, temperature=0.3)
    
    def analyze_video_url(self, video_url: str, prompt: str, 
                          models: Optional[List[str]] = None,
                          max_tokens: int = 4096,
                          temperature: float = 0.7) -> Dict[str, Any]:
        """
        Analyze a video using OpenRouter's video-capable models.
        Video is sent as a URL (not Base64 encoded).
        
        Args:
            video_url: Direct URL to the video file
            prompt: Text prompt describing what to analyze
            models: List of video-capable models to try. Defaults to VIDEO_CAPABLE_MODELS.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            Dict with 'content', 'model_used', 'tokens_used', 'success', 'needs_translation'
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        
        if models is None:
            models = VIDEO_CAPABLE_MODELS
        
        logging.info(f"Sending video URL to OpenRouter: {video_url[:100]}...")
        
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": video_url
                        }
                    }
                ]
            }
        ]
        
        last_error = None
        
        for model in models:
            try:
                logging.info(f"Trying video analysis with OpenRouter model: {model}")
                
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                
                response = requests.post(
                    self.base_url,
                    headers=self.headers,
                    json=payload,
                    timeout=180
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    
                    return {
                        "success": True,
                        "content": content,
                        "model_used": model,
                        "tokens_used": usage.get("total_tokens", 0),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "needs_translation": False,
                    }
                elif response.status_code == 429:
                    logging.warning(f"Rate limited on {model} for video analysis, trying next model...")
                    last_error = f"Rate limit exceeded for {model}"
                    time.sleep(0.5)
                    continue
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", response.text)
                    except:
                        error_msg = response.text
                    logging.warning(f"Error from {model} for video: {error_msg}")
                    last_error = error_msg
                    continue
                    
            except requests.exceptions.Timeout:
                logging.warning(f"Timeout on {model} for video analysis, trying next model...")
                last_error = f"Timeout for {model}"
                continue
            except Exception as e:
                logging.warning(f"Exception with {model} for video: {e}")
                last_error = str(e)
                continue
        
        return {
            "success": False,
            "content": None,
            "model_used": None,
            "error": last_error or "All video models failed",
            "tokens_used": 0,
            "needs_translation": False,
        }
    
    def extract_recipe_from_video_url(self, video_url: str, 
                                       models: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Extract recipe information from a cooking video using OpenRouter.
        Video is accessed via URL (not downloaded).
        
        Args:
            video_url: Direct URL to the video file
            models: List of video-capable models to try
            
        Returns:
            Dict with recipe content and metadata
        """
        prompt = """この料理動画を見て、レシピを抽出してください。

以下の形式でJSON形式で回答してください：
{
  "ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位"}],
  "steps": ["手順1の説明", "手順2の説明"],
  "tips": ["コツやポイント"]
}

動画に料理レシピが含まれていない場合は：
{"no_recipe": true, "reason": "理由"}

重要：
- 材料は可能な限り分量も含めて記載
- 手順は時系列順に詳細に記載
- 調理のコツやポイントがあれば tips に含める
- 余計な説明は不要、JSON形式のみ返す"""

        result = self.analyze_video_url(video_url, prompt, models, max_tokens=4096, temperature=0.3)
        
        if result["success"] and result.get("needs_translation", False):
            logging.info(f"Video analysis model {result['model_used']} needs translation")
            translation_result = self.translate_to_japanese(result["content"])
            if translation_result["success"]:
                result["content"] = translation_result["content"]
                result["translated"] = True
                result["translation_model"] = translation_result["model_used"]
            else:
                logging.warning(f"Translation failed: {translation_result.get('error')}")
                result["translated"] = False
        
        return result



    def categorize_ingredient(self, ingredient_name: str, categories: List[Dict[str, Any]], 
                              models: Optional[List[str]] = None) -> tuple:
        """
        食材名をカテゴリに分類する
        
        Args:
            ingredient_name: 分類する食材名
            categories: カテゴリ情報のリスト [{'id': 1, 'name': '野菜'}, ...]
            models: 使用するモデルリスト
            
        Returns:
            category_id
        """
        if models is None:
            models = TEXT_MODELS

        # カテゴリ一覧テキストを生成
        categories_text = "\n".join([f"{c['id']}: {c['name']}" for c in categories])
        
        prompt = f"""# Role
あなたは日本の食品流通およびスーパーマーケットの棚割りに精通した専門家です。

# Task
入力された「食材名」が、日本の一般的なスーパーマーケットの棚割りを基準とした場合、以下の「15の分類」のどれに該当するか判定し、そのカテゴリIDを回答してください。

# Categories (Order and ID)
{categories_text}

# Guidelines
- 日本の一般的なスーパーマーケットの「売り場」の感覚で分類してください。
- 以下の判断に迷いやすい項目は、それぞれの基準を優先してください：
  - 加工の度合い: 生肉は「3」、加熱済み惣菜は「6」、冷凍品は「8」を優先。
  - 粉類・乾燥食品: 小麦粉、パスタ、わかめ等は「9」。
  - 食材ではない単語（挨拶や文章など）: 一律で「15」。

# Output Format (Strict JSON)
{{
  "category_id": 数値
}}

# Input
食材名: {ingredient_name}"""

        messages = [{"role": "user", "content": prompt}]
        
        try:
            result = self.chat_completion(messages, models=models, temperature=0.1)
            
            if result['success']:
                try:
                    content = result['content'].strip()
                    # JSONブロックまたは最外の{ }を抽出
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(0)
                        
                    data = json.loads(content)
                    val = data.get('category_id')
                    if val is not None:
                        try:
                            return int(val)
                        except (ValueError, TypeError):
                            return val
                    return None
                except Exception as e:
                    logging.error(f"Failed to parse categorization response: {e}, content: {result['content']}")
                    return None
            else:
                logging.error(f"Categorization failed: {result.get('error')}")
                return None

                
        except Exception as e:
            logging.error(f"Error in categorize_ingredient: {e}")
            return None, str(e)

    def generate_master_name(self, ingredient_name: str, category_id: int, 
                             existing_masters: List[str], models: Optional[List[str]] = None) -> tuple:
        """
        新規食材名から代表名を生成・照合する
        
        Args:
            ingredient_name: 新規食材名
            category_id: カテゴリID
            existing_masters: 既存の代表名リスト
            models: 使用するモデルリスト
            
        Returns:
            (master_name, is_new_master)
        """
        if models is None:
            models = TEXT_MODELS
            
        # 既存リストをテキスト化
        masters_text = "\n".join([f"- {m}" for m in existing_masters])
        # リストが空の場合の表示
        if not masters_text:
            masters_text = "(なし)"

        prompt = f"""# Role
あなたは食品データベースの正規化を行うデータエンジニアです。

# Task
入力された「新規食材名」を、提供された「既存の代表名リスト」と照合してください。
「部位・形態・加工状態」が一致するものがリストにあればその代表名を選択し、なければ新しい代表名を考案してください。

# Rules (厳守)
1. **合算の可否判定**:
   以下の属性が一つでも異なる場合は、既存の代表名に含めず、必ず「新しい代表名」を作成してください。
   - 部位（例: バラ、ロース、もも）
   - 形状（例: ひき肉、薄切り、ブロック、切り落とし）
   - 加工状態（例: 味付け済み、乾燥、冷凍）
2. **名称の統一**:
   「表記ゆれ（人参とにんじん、豚バラと豚ばら等）」は、既存のリストに適切なものがあればそれに合わせ、なければ一般的な漢字・カタカナ表記で作成してください。
3. **新規作成時のルール**:
   新規で代表名を作成する場合、品種名（イベリコ、黒毛和牛等）は除き、部位や形状がわかる名称にしてください。
   例: 「イベリコ豚バラ」→ 代表名: 「豚バラ肉」

# Input
- 新規食材名: {ingredient_name}
- 既存の代表名リスト (カテゴリID: {category_id} 内):
{masters_text}

# Output Format (Strict JSON)
{{
  "master_name": "決定した代表名",
  "is_new_master": true/false
}}"""

        messages = [{"role": "user", "content": prompt}]
        
        try:
            result = self.chat_completion(messages, models=models, temperature=0.1)
            
            if result['success']:
                try:
                    content = result['content'].strip()
                    # JSONブロックまたは最外の{ }を抽出
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(0)
                        
                    data = json.loads(content)
                    is_new = data.get('is_new_master')
                    # booleanへの変換
                    if isinstance(is_new, str):
                        is_new = is_new.lower() == 'true'
                    return data.get('master_name'), bool(is_new)
                except Exception as e:
                    logging.error(f"Failed to parse master name generation response: {e}, content: {result['content']}")
                    return ingredient_name, True
            else:
                logging.error(f"Master name generation failed: {result.get('error')}")
                return ingredient_name, True
                
        except Exception as e:
            logging.error(f"Error in generate_master_name: {e}")
            return ingredient_name, True


openrouter_client = OpenRouterClient()

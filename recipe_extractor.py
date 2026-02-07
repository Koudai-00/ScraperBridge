import os
import logging
import re
import time
import json
import requests
from typing import Optional, Dict, Any, List
import google.generativeai as genai
from bs4 import BeautifulSoup
import pathlib
import yt_dlp
from openrouter_client import openrouter_client, TEXT_MODELS, VIDEO_CAPABLE_MODELS


class RecipeExtractor:
    """動画からレシピを抽出するクラス"""

    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.apify_api_token = os.getenv("APIFY_API_TOKEN")
        self._gemini_initialized = False

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def _ensure_gemini_initialized(self):
        """Gemini APIを遅延初期化"""
        if not self._gemini_initialized:
            if not self.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY is required for AI video analysis. "
                    "Please set GEMINI_API_KEY environment variable.")
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_initialized = True

    def extract_recipe(self, video_url: str) -> Dict[str, Any]:
        """
        動画URLからレシピを抽出

        優先順位:
        1. 説明欄からレシピ抽出
        2. 投稿者コメントからレシピ抽出
        3. Gemini APIで動画解析
        """
        platform = self._detect_platform(video_url)

        if platform == "youtube":
            return self._extract_recipe_from_youtube(video_url)
        elif platform in ["tiktok", "instagram"]:
            # TikTok/InstagramもYouTubeと同様の優先順位で処理するように変更
            return self._extract_recipe_from_other_platform(
                video_url, platform)
        else:
            raise ValueError(f"Unsupported platform for URL: {video_url}")

    def _detect_platform(self, url: str) -> str:
        """URLからプラットフォームを判定"""
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'instagram.com' in url_lower:
            return 'instagram'
        return 'unknown'

    def _extract_recipe_from_youtube(self, video_url: str) -> Dict[str, Any]:
        """YouTubeからレシピを抽出（OpenRouter自動フォールバック対応）"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")

        # OpenRouter自動モードを使用（TEXT_MODELSの優先順位で自動フォールバック）
        default_model = 'openrouter:auto'
        extraction_flow = []
        
        logging.info(f"Checking YouTube description for recipe (using OpenRouter auto mode)...")
        extraction_flow.append("説明欄をチェック")
        description_result = self._get_recipe_from_description(video_id, default_model)
        if description_result:
            if description_result.get('refinement_status') == 'no_recipe':
                logging.info("AI determined no recipe in description")
                extraction_flow.append("レシピなし")
            else:
                logging.info("Recipe found in description")
                extraction_flow.append("キーワード検出 → AI抽出: 成功")
                # 実際に使用されたモデルを報告（Noneの場合は'openrouter:auto'を表示）
                actual_model = description_result.get('model_used') or 'openrouter:auto'
                return {
                    'recipe_text': description_result.get('text', ''),
                    'extraction_method': 'description',
                    'extraction_flow': ' → '.join(extraction_flow),
                    'ai_model': actual_model,
                    'tokens_used': description_result.get('refinement_tokens'),
                    'input_tokens': description_result.get('input_tokens'),
                    'output_tokens': description_result.get('output_tokens'),
                    'refinement_status': description_result.get('refinement_status', 'skipped'),
                    'refinement_error': description_result.get('refinement_error')
                }
        else:
            extraction_flow.append("レシピなし")

        logging.info(f"Checking YouTube comments for recipe (using OpenRouter auto mode)...")
        extraction_flow.append("コメント欄をチェック")
        comment_result = self._get_recipe_from_comments(video_id, default_model)
        if comment_result:
            if comment_result.get('refinement_status') == 'no_recipe':
                logging.info("AI determined no recipe in comment")
                extraction_flow.append("レシピなし")
            else:
                logging.info("Recipe found in author's comment")
                extraction_flow.append("キーワード検出 → AI抽出: 成功")
                # 実際に使用されたモデルを報告（Noneの場合は'openrouter:auto'を表示）
                actual_model = comment_result.get('model_used') or 'openrouter:auto'
                return {
                    'recipe_text': comment_result.get('text', ''),
                    'extraction_method': 'comment',
                    'extraction_flow': ' → '.join(extraction_flow),
                    'ai_model': actual_model,
                    'tokens_used': comment_result.get('refinement_tokens'),
                    'input_tokens': comment_result.get('input_tokens'),
                    'output_tokens': comment_result.get('output_tokens'),
                    'refinement_status': comment_result.get('refinement_status', 'skipped'),
                    'refinement_error': comment_result.get('refinement_error')
                }
        else:
            extraction_flow.append("レシピなし")

        # 動画解析はGemini API直接使用（gemini-2.0-flash-lite）- YouTube URLを直接渡す方式
        video_model = 'gemini-2.0-flash-lite'
        logging.info(f"Extracting recipe from YouTube video using URL-based Gemini API ({video_model})...")
        extraction_flow.append("動画解析")
        result = self._extract_recipe_from_youtube_url(video_url, video_model)
        result['extraction_flow'] = ' → '.join(extraction_flow) + ' → 抽出成功'
        
        # 翻訳が必要な場合は翻訳
        if result.get('recipe_text'):
            result = self._ensure_japanese_response(result)
        
        return result

    def extract_unique_video_id(self, url: str) -> tuple:
        """
        URLからプラットフォームとユニーク動画IDを抽出
        """
        platform = self._detect_platform(url)

        if platform == "youtube":
            video_id = self._extract_youtube_id(url)
            return (platform, video_id)
        elif platform == "tiktok":
            video_id = self._extract_tiktok_id(url)
            return (platform, video_id)
        elif platform == "instagram":
            video_id = self._extract_instagram_id(url)
            return (platform, video_id)
        else:
            return (platform, "")

    def _extract_youtube_id(self, url: str) -> str:
        """YouTube動画IDを抽出"""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu\.be\/([0-9A-Za-z_-]{11}).*'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)
        return ""

    def _extract_recipe_from_youtube_url(self, video_url: str, model_name: str = 'gemini-2.0-flash-lite') -> Dict[str, Any]:
        """
        YouTube動画からレシピを抽出（URL直接方式）
        
        yt-dlpでのダウンロードを行わず、GeminiにYouTube URLを直接渡して解析する。
        これによりCloud Run等のサーバー環境でのボット検出問題を回避できる。
        """
        try:
            self._ensure_gemini_initialized()
            
            video_id = self._extract_youtube_id(video_url)
            if not video_id:
                raise ValueError("Invalid YouTube URL")
            
            youtube_url = f"https://www.youtube.com/watch?v={video_id}"
            logging.info(f"Analyzing YouTube video via URL: {youtube_url} using {model_name}")
            
            model = genai.GenerativeModel(model_name)
            
            prompt = """
この動画からレシピを抽出し、以下のJSON形式「のみ」で出力してください。前置きや説明文は一切不要です。
{"ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}], "steps": ["手順1"], "tips": ["コツ1"]}

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

動画にレシピが含まれていない場合のみ、{"error": "レシピが見つかりませんでした"}と返してください。
"""
            
            video_file_data = {
                "file_data": {
                    "file_uri": youtube_url,
                    "mime_type": "video/mp4"
                }
            }
            
            logging.info(f"Sending YouTube URL to Gemini ({model_name})...")
            response = model.generate_content([video_file_data, prompt])
            
            raw_text = response.text.strip()
            logging.debug(f"Gemini raw response: {raw_text[:200]}...")
            
            recipe_text = None
            try:
                json_text = re.sub(r'^```json\s*|\s*```$', '', raw_text, flags=re.MULTILINE).strip()
                recipe_json = json.loads(json_text)
                if recipe_json.get('error'):
                    raise ValueError("No recipe found in video")
                if not recipe_json.get('ingredients') or not recipe_json.get('steps'):
                    raise json.JSONDecodeError("Missing required fields", json_text, 0)
                recipe_text = self._convert_json_to_text(recipe_json)
                logging.info("Successfully parsed JSON response from Gemini (URL-based)")
            except json.JSONDecodeError:
                logging.warning("Failed to parse JSON, using text fallback")
                recipe_text = self._clean_recipe_text(raw_text)
            
            if "レシピが見つかりませんでした" in recipe_text:
                raise ValueError("No recipe found in video")
            if not self._validate_recipe_structure(recipe_text):
                raise ValueError("Incomplete recipe: missing ingredients or steps")
            
            tokens_info = self._estimate_tokens(response)
            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': model_name,
                'tokens_used': tokens_info.get('total', 0),
                'input_tokens': tokens_info.get('input', 0),
                'output_tokens': tokens_info.get('output', 0),
                'refinement_status': 'not_applicable',
                'refinement_error': None
            }
            
        except Exception as e:
            logging.error(f"Error in _extract_recipe_from_youtube_url: {e}")
            raise

    def _extract_tiktok_id(self, url: str) -> str:
        """TikTok動画IDを抽出"""
        # 通常のURL形式
        patterns = [r'/video/(\d+)', r'/v/(\d+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)

        # 短縮URL形式 (vt.tiktok.com/XXXXXX)
        short_url_pattern = r'vt\.tiktok\.com/([A-Za-z0-9]+)'
        match = re.search(short_url_pattern, url)
        if match:
            return match.group(1)

        # vm.tiktok.com形式も対応
        vm_pattern = r'vm\.tiktok\.com/([A-Za-z0-9]+)'
        match = re.search(vm_pattern, url)
        if match:
            return match.group(1)

        return ""

    def _extract_instagram_id(self, url: str) -> str:
        """Instagram動画IDを抽出"""
        patterns = [
            r'/reel/([A-Za-z0-9_-]+)', r'/p/([A-Za-z0-9_-]+)',
            r'/tv/([A-Za-z0-9_-]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)
        return ""

    def _get_recipe_from_description(self, video_id: str, model_name: str = 'gemini-1.5-flash') -> Optional[Dict[str, Any]]:
        """YouTube説明欄からレシピを取得

        Args:
            video_id: YouTube動画ID
            model_name: 整形に使用するGeminiモデル名

        Returns:
            Dict with recipe text and refinement info, or None if no recipe found
        """
        if not self.youtube_api_key:
            logging.warning(
                "YouTube API key not set, skipping description check")
            return None

        try:
            api_url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                'part': 'snippet',
                'id': video_id,
                'key': self.youtube_api_key
            }
            response = self.session.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get('items'): return None
            description = data['items'][0]['snippet'].get('description', '')

            if self._contains_recipe(description):
                logging.info("Keyword found in description, sending to AI for recipe extraction")
                raw_recipe = self._extract_recipe_text(description)
                if raw_recipe:
                    refinement_result = self._refine_recipe_with_model(raw_recipe, model_name)
                    # AIがレシピなしと判定した場合はNoneを返す（動画解析へ移行）
                    if refinement_result.get('refinement_status') == 'no_recipe':
                        logging.info("AI determined no recipe in description, will try video analysis")
                        return None
                    return refinement_result
                return None
            else:
                logging.info("No recipe keywords found in description")
            return None
        except Exception as e:
            logging.error(f"Error fetching YouTube description: {e}")
            return None

    def _get_recipe_from_comments(self, video_id: str, model_name: str = 'gemini-1.5-flash') -> Optional[Dict[str, Any]]:
        """YouTube投稿者コメントからレシピを取得

        Args:
            video_id: YouTube動画ID
            model_name: 整形に使用するGeminiモデル名

        Returns:
            Dict with recipe text and refinement info, or None if no recipe found
        """
        if not self.youtube_api_key:
            logging.warning("YouTube API key not set, skipping comments check")
            return None

        try:
            api_url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                'part': 'snippet',
                'id': video_id,
                'key': self.youtube_api_key
            }
            response = self.session.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get('items'): return None
            channel_id = data['items'][0]['snippet'].get('channelId')

            comments_url = "https://www.googleapis.com/youtube/v3/commentThreads"
            params = {
                'part': 'snippet',
                'videoId': video_id,
                'maxResults': 100,
                'order': 'relevance',
                'key': self.youtube_api_key
            }
            response = self.session.get(comments_url,
                                        params=params,
                                        timeout=10)
            response.raise_for_status()
            comments_data = response.json()

            for item in comments_data.get('items', []):
                comment = item['snippet']['topLevelComment']['snippet']
                author_channel_id = comment.get('authorChannelId',
                                                {}).get('value')
                if author_channel_id == channel_id:
                    comment_text = comment.get('textDisplay', '')
                    if self._contains_recipe(comment_text):
                        logging.info("Keyword found in author comment, sending to AI for recipe extraction")
                        raw_recipe = self._extract_recipe_text(comment_text)
                        if raw_recipe:
                            refinement_result = self._refine_recipe_with_model(raw_recipe, model_name)
                            # AIがレシピなしと判定した場合はNoneを返す（動画解析へ移行）
                            if refinement_result.get('refinement_status') == 'no_recipe':
                                logging.info("AI determined no recipe in comment, will try video analysis")
                                return None
                            return refinement_result
                        return None
            return None
        except Exception as e:
            logging.error(f"Error fetching YouTube comments: {e}")
            return None

    def _contains_recipe(self, text: str) -> bool:
        """テキストにレシピキーワードが含まれているか判定
        
        キーワードが1つでも含まれていればTrue（AI抽出へ進む）
        """
        recipe_keywords = [
            '材料', '作り方', '手順', '分量', 'ml', 'cc', '大さじ', '小さじ'
        ]
        text_lower = text.lower()
        return any(k.lower() in text_lower for k in recipe_keywords)

    def _extract_recipe_text(self, text: str) -> Optional[str]:
        """テキストからレシピ部分を抽出して整形"""
        text = re.sub(r'<[^>]+>', '', text)
        recipe_start_patterns = [
            r'【?材料.*?】?', r'【?レシピ.*?】?', r'【?作り方.*?】?', r'Ingredients:?',
            r'Recipe:?'
        ]
        start_pos = -1
        for pattern in recipe_start_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_pos = match.start()
                break
        if start_pos >= 0:
            recipe_text = text[start_pos:].strip()
            return recipe_text[:2000] + "..." if len(
                recipe_text) > 2000 else recipe_text
        return text[:2000] + "..." if len(text) > 2000 else text

    def _clean_recipe_text(self, text: str) -> str:
        """AIからの応答をクリーニングして不要な前置きを削除"""
        unwanted_prefixes = [
            r'^はい、.*?。\s*', r'^はい。\s*', r'^動画を拝見しました。?\s*', r'^以下に.*?します。?\s*',
            r'^レシピをテキスト化します。?\s*', r'^こちらがレシピです。?\s*'
        ]
        cleaned = text
        for pattern in unwanted_prefixes:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _convert_json_to_text(self, recipe_json: Dict[str, Any]) -> str:
        """JSON形式のレシピをテキスト形式に変換（料理名は含めない）"""
        parts = []
        if recipe_json.get('ingredients'):
            parts.append("\n【材料】")
            for i in recipe_json['ingredients']:
                if isinstance(i, dict):
                    name = i.get('name', '')
                    amount = i.get('amount', '')
                    unit = i.get('unit', '')
                    sub_amount = i.get('sub_amount', '')
                    sub_unit = i.get('sub_unit', '')
                    main_part = ''
                    if amount and unit:
                        main_part = f"{amount}{unit}"
                    elif amount:
                        main_part = f"{amount}"
                    elif unit:
                        main_part = f"{unit}"
                    sub_part = ''
                    if sub_amount and sub_unit:
                        sub_part = f"({sub_amount}{sub_unit})"
                    if main_part:
                        parts.append(f"- {name} {main_part}{sub_part}")
                    else:
                        parts.append(f"- {name}")
                else:
                    parts.append(f"- {i}")
        if recipe_json.get('steps'):
            parts.append("\n【作り方】")
            for idx, s in enumerate(recipe_json['steps'], 1):
                parts.append(f"{idx}. {s}")
        if recipe_json.get('tips'):
            parts.append("\n【コツ・ポイント】")
            tips = recipe_json['tips']
            if isinstance(tips, list):
                for t in tips:
                    parts.append(f"- {t}")
            else:
                parts.append(f"- {tips}")
        return '\n'.join(parts)

    def _validate_recipe_structure(self, recipe_text: str) -> bool:
        """レシピに必須セクションが含まれているか検証"""
        has_ingredients = any(k in recipe_text
                              for k in ['【材料】', '材料', 'Ingredients'])
        has_steps = any(k in recipe_text
                        for k in ['【作り方】', '作り方', 'Steps', '手順'])
        return has_ingredients and has_steps

    def _refine_recipe_with_gemini(self, raw_recipe_text: str, model_name: str = 'gemini-1.5-flash') -> Dict[str, Any]:
        """
        Geminiを使って説明欄/コメントから抽出したレシピを整形する

        宣伝文や余計なテキストを除去し、レシピ部分のみを構造化して返す

        Args:
            raw_recipe_text: 整形前のレシピテキスト
            model_name: 使用するGeminiモデル名（デフォルト: gemini-1.5-flash）

        Returns:
            Dict with keys:
            - text: 整形後のレシピテキスト（失敗時は元のテキスト）
            - refinement_status: 'success', 'failed', 'skipped'
            - refinement_tokens: トークン使用量（整形時のみ）
            - refinement_error: エラーメッセージ（失敗時のみ）
            - model_used: 実際に使用されたモデル名
        """
        result = {
            'text': raw_recipe_text,
            'refinement_status': 'skipped',
            'refinement_tokens': None,
            'refinement_error': None,
            'model_used': model_name
        }

        try:
            self._ensure_gemini_initialized()

            model = genai.GenerativeModel(model_name)

            prompt = """以下のテキストに料理レシピ（材料リストと作り方/手順）が含まれているか確認し、含まれている場合のみ抽出・整形してください。

【重要な判断基準】
- 実際の料理レシピとは「材料（分量付き）」と「作り方（調理手順）」が両方記載されているものです
- 以下はレシピではありません：
  - アプリやサービスの宣伝文
  - 書籍の紹介リンク
  - SNSアカウントの一覧
  - BGM情報、クレジット

【レシピが含まれていない場合】
以下のJSON形式で返してください：
{"no_recipe": true}

【レシピが含まれている場合】
以下のJSON形式で返してください：
{"ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}], "steps": ["手順1", "手順2"], "tips": ["コツ1"]}

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

※除去する情報：宣伝文、ハッシュタグ、SNSリンク、BGM情報、チャンネル登録のお願い等

【入力テキスト】
""" + raw_recipe_text

            response = model.generate_content(prompt)

            if not response or not response.text:
                logging.warning("Gemini returned empty response for recipe refinement")
                result['refinement_status'] = 'failed'
                result['refinement_error'] = 'Empty response from Gemini'
                return result

            # トークン使用量を取得
            tokens_used = None
            input_tokens = None
            output_tokens = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                tokens_used = getattr(response.usage_metadata, 'total_token_count', None)
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', None)
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', None)
            result['refinement_tokens'] = tokens_used
            result['input_tokens'] = input_tokens
            result['output_tokens'] = output_tokens

            response_text = response.text.strip()

            # JSON形式でパースを試みる
            try:
                # コードブロックを除去
                if response_text.startswith('```'):
                    lines = response_text.split('\n')
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.startswith('```json'):
                            in_json = True
                            continue
                        elif line.startswith('```'):
                            in_json = False
                            continue
                        if in_json or (not line.startswith('```')):
                            json_lines.append(line)
                    response_text = '\n'.join(json_lines).strip()

                recipe_json = json.loads(response_text)

                # レシピが含まれていない場合
                if recipe_json.get('no_recipe'):
                    logging.info("Gemini determined no recipe in text")
                    result['refinement_status'] = 'no_recipe'
                    result['refinement_error'] = 'AI判定: テキストにレシピが含まれていません'
                    return result

                if 'error' in recipe_json:
                    logging.warning(f"Gemini recipe refinement error: {recipe_json['error']}")
                    result['refinement_status'] = 'failed'
                    result['refinement_error'] = recipe_json['error']
                    return result

                # JSONをテキスト形式に変換
                refined_text = self._convert_json_to_text(recipe_json)

                if refined_text and len(refined_text) > 50:
                    logging.info("Recipe successfully refined with Gemini")
                    result['text'] = refined_text
                    result['refinement_status'] = 'success'
                    return result
                else:
                    result['refinement_status'] = 'failed'
                    result['refinement_error'] = 'Refined text too short'
                    return result

            except json.JSONDecodeError:
                # JSONパース失敗時は応答テキストをクリーニングして使用
                cleaned = self._clean_recipe_text(response_text)
                if cleaned and len(cleaned) > 50:
                    result['text'] = cleaned
                    result['refinement_status'] = 'success'
                    return result
                result['refinement_status'] = 'failed'
                result['refinement_error'] = 'JSON parse failed and cleaned text too short'
                return result

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error refining recipe with Gemini: {error_msg}")
            result['refinement_status'] = 'failed'
            result['refinement_error'] = error_msg
            return result

    def _refine_recipe_with_openrouter(self, raw_recipe_text: str, model_name: str = None) -> Dict[str, Any]:
        """
        OpenRouterを使って説明欄/コメントから抽出したレシピを整形する
        429エラー時は自動的に別のモデルにフォールバック

        Args:
            raw_recipe_text: 整形前のレシピテキスト
            model_name: 使用するOpenRouterモデル名（Noneの場合は自動フォールバック）

        Returns:
            Dict with recipe text and refinement info
        """
        result = {
            'text': raw_recipe_text,
            'refinement_status': 'skipped',
            'refinement_tokens': None,
            'refinement_error': None,
            'model_used': model_name or 'openrouter-auto'
        }

        prompt = """以下のテキストに料理レシピ（材料リストと作り方/手順）が含まれているか確認し、含まれている場合のみ抽出・整形してください。

【重要な判断基準】
- 実際の料理レシピとは「材料（分量付き）」と「作り方（調理手順）」が両方記載されているものです
- 以下はレシピではありません：
  - アプリやサービスの宣伝文
  - 書籍の紹介リンク
  - SNSアカウントの一覧
  - BGM情報、クレジット

【レシピが含まれていない場合】
以下のJSON形式で返してください：
{"no_recipe": true}

【レシピが含まれている場合】
以下のJSON形式で返してください：
{"ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}], "steps": ["手順1", "手順2"], "tips": ["コツ1"]}

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

※除去する情報：宣伝文、ハッシュタグ、SNSリンク、BGM情報、チャンネル登録のお願い等

【入力テキスト】
""" + raw_recipe_text

        messages = [
            {"role": "user", "content": "あなたは料理レシピの整理専門家です。与えられたテキストからレシピ情報のみを抽出し、JSON形式で返してください。\n\n" + prompt}
        ]

        try:
            if model_name:
                or_model = self._get_openrouter_model_id(model_name)
                models = [or_model]
            else:
                models = TEXT_MODELS

            response = openrouter_client.chat_completion(messages, models=models)

            if not response.get('success'):
                result['refinement_status'] = 'failed'
                result['refinement_error'] = response.get('error', 'OpenRouter request failed')
                return result

            result['model_used'] = response.get('model_used', model_name)
            result['refinement_tokens'] = response.get('tokens_used', 0)

            response_text = response.get('content', '').strip()
            if not response_text:
                result['refinement_status'] = 'failed'
                result['refinement_error'] = 'Empty response from OpenRouter'
                return result

            try:
                if response_text.startswith('```'):
                    lines = response_text.split('\n')
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.startswith('```json'):
                            in_json = True
                            continue
                        elif line.startswith('```'):
                            in_json = False
                            continue
                        if in_json or (not line.startswith('```')):
                            json_lines.append(line)
                    response_text = '\n'.join(json_lines).strip()

                recipe_json = json.loads(response_text)

                if recipe_json.get('no_recipe'):
                    logging.info("OpenRouter determined no recipe in text")
                    result['refinement_status'] = 'no_recipe'
                    result['refinement_error'] = 'AI判定: テキストにレシピが含まれていません'
                    return result

                if 'error' in recipe_json:
                    result['refinement_status'] = 'failed'
                    result['refinement_error'] = recipe_json['error']
                    return result

                refined_text = self._convert_json_to_text(recipe_json)
                if refined_text and len(refined_text) > 50:
                    logging.info(f"Recipe successfully refined with OpenRouter ({result['model_used']})")
                    result['text'] = refined_text
                    result['refinement_status'] = 'success'
                    return result
                else:
                    result['refinement_status'] = 'failed'
                    result['refinement_error'] = 'Refined text too short'
                    return result

            except json.JSONDecodeError:
                cleaned = self._clean_recipe_text(response_text)
                if cleaned and len(cleaned) > 50:
                    result['text'] = cleaned
                    result['refinement_status'] = 'success'
                    return result
                result['refinement_status'] = 'failed'
                result['refinement_error'] = 'JSON parse failed'
                return result

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error refining recipe with OpenRouter: {error_msg}")
            result['refinement_status'] = 'failed'
            result['refinement_error'] = error_msg
            return result

    def _refine_recipe_with_model(self, raw_recipe_text: str, model_name: str) -> Dict[str, Any]:
        """
        モデル名に応じてGeminiまたはOpenRouterでレシピを整形

        Args:
            raw_recipe_text: 整形前のレシピテキスト
            model_name: モデル名
                - 'openrouter:auto': OpenRouter自動フォールバック（TEXT_MODELSの優先順位で）
                - 'openrouter:xxx'形式: 指定されたOpenRouterモデルを使用
                - それ以外: Geminiモデルを使用
        """
        if model_name == 'openrouter:auto':
            # 自動モード：TEXT_MODELSの優先順位で自動フォールバック
            return self._refine_recipe_with_openrouter_auto(raw_recipe_text)
        elif self._is_openrouter_model(model_name):
            return self._refine_recipe_with_openrouter(raw_recipe_text, model_name)
        else:
            return self._refine_recipe_with_gemini(raw_recipe_text, model_name)
    
    def _refine_recipe_with_openrouter_auto(self, raw_recipe_text: str) -> Dict[str, Any]:
        """
        OpenRouter自動モードでレシピを整形（TEXT_MODELSの優先順位で自動フォールバック）
        """
        try:
            result = openrouter_client.refine_recipe(raw_recipe_text, model=None)
            
            if result.get('success'):
                content = result.get('content', '')
                model_used = result.get('model_used', '')
                tokens_used = result.get('tokens_used', 0)
                input_tokens = result.get('prompt_tokens', 0)
                output_tokens = result.get('completion_tokens', 0)
                
                # JSONレスポンスの解析
                try:
                    import re
                    json_text = re.sub(r'^```json\s*|\s*```$', '', content.strip(), flags=re.MULTILINE).strip()
                    recipe_json = json.loads(json_text)
                    
                    if recipe_json.get('no_recipe'):
                        return {
                            'text': None,
                            'model_used': model_used,
                            'refinement_status': 'no_recipe',
                            'refinement_tokens': tokens_used,
                            'input_tokens': input_tokens,
                            'output_tokens': output_tokens,
                            'refinement_error': None
                        }
                    
                    formatted_text = self._convert_json_to_text(recipe_json)
                    
                    # 翻訳が必要な場合（日本語でない場合のみ）
                    if not self._is_japanese_text(formatted_text):
                        translation_result = openrouter_client.translate_to_japanese(formatted_text)
                        if translation_result.get('success'):
                            formatted_text = translation_result.get('content', formatted_text)
                            tokens_used += translation_result.get('tokens_used', 0)
                            input_tokens += translation_result.get('prompt_tokens', 0)
                            output_tokens += translation_result.get('completion_tokens', 0)
                    
                    return {
                        'text': formatted_text,
                        'model_used': model_used,
                        'refinement_status': 'success',
                        'refinement_tokens': tokens_used,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'refinement_error': None
                    }
                except json.JSONDecodeError:
                    # JSON解析失敗時はテキストクリーニング
                    cleaned_text = self._clean_recipe_text(content)
                    
                    # 翻訳が必要な場合（日本語でない場合のみ）
                    if not self._is_japanese_text(cleaned_text):
                        translation_result = openrouter_client.translate_to_japanese(cleaned_text)
                        if translation_result.get('success'):
                            cleaned_text = translation_result.get('content', cleaned_text)
                            tokens_used += translation_result.get('tokens_used', 0)
                            input_tokens += translation_result.get('prompt_tokens', 0)
                            output_tokens += translation_result.get('completion_tokens', 0)
                    
                    return {
                        'text': cleaned_text,
                        'model_used': model_used,
                        'refinement_status': 'success',
                        'refinement_tokens': tokens_used,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'refinement_error': None
                    }
            else:
                # OpenRouterが全て失敗した場合、Gemini 2.0 Flash Liteにフォールバック
                logging.warning(f"OpenRouter auto refinement failed: {result.get('error')}, falling back to Gemini")
                return self._refine_recipe_with_gemini(raw_recipe_text, 'gemini-2.0-flash-lite')
        except Exception as e:
            logging.error(f"Error in OpenRouter auto refinement: {e}, falling back to Gemini")
            return self._refine_recipe_with_gemini(raw_recipe_text, 'gemini-2.0-flash-lite')

    def _get_video_download_url_from_apify(self, video_url: str, platform: str) -> Optional[str]:
        """
        Apify APIを使ってTikTok/Instagram動画のダウンロードURLを取得

        Args:
            video_url: 動画のURL
            platform: 'tiktok' または 'instagram'

        Returns:
            動画のダウンロードURL、取得失敗時はNone
        """
        if not self.apify_api_token:
            logging.error("APIFY_API_TOKEN is not set")
            return None

        try:
            # プラットフォームに応じたApify Actorとパラメータを設定
            if platform == 'tiktok':
                actor_id = 'clockworks/free-tiktok-scraper'
                payload = {'postURLs': [video_url]}
            elif platform == 'instagram':
                actor_id = 'apify/instagram-scraper'
                payload = {'directUrls': [video_url]}
            else:
                logging.error(f"Unsupported platform for Apify: {platform}")
                return None

            # Apify APIエンドポイント（トークンをクエリパラメータで渡す）
            api_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={self.apify_api_token}"

            headers = {
                'Content-Type': 'application/json'
            }

            logging.info(f"Requesting video download URL from Apify for {platform}...")
            logging.debug(f"Apify request payload: {payload}")

            response = requests.post(api_url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()

            data = response.json()
            logging.debug(f"Apify response data: {data}")

            # レスポンスから動画URLを抽出
            if data and len(data) > 0:
                item = data[0]

                if platform == 'tiktok':
                    # TikTokの場合、複数の可能性のあるフィールドをチェック
                    download_url = (item.get('videoUrl') or 
                                  item.get('video', {}).get('downloadAddr') or
                                  item.get('video', {}).get('playAddr'))
                elif platform == 'instagram':
                    # Instagramの場合
                    download_url = (item.get('videoUrl') or 
                                  item.get('displayUrl') or
                                  item.get('url'))

                if download_url:
                    logging.info(f"Successfully got download URL from Apify: {download_url[:100]}...")
                    return download_url
                else:
                    logging.warning(f"No download URL found in Apify response. Item keys: {list(item.keys())}")

            logging.warning(f"Could not extract download URL from Apify response for {platform}")
            return None

        except Exception as e:
            logging.error(f"Error getting video download URL from Apify: {e}")
            return None

    def _normalize_youtube_url(self, video_url: str) -> str:
        """YouTube URLを標準形式（watch形式）に変換"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id: return video_url
        normalized_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"Normalized URL: {video_url} -> {normalized_url}")
        return normalized_url

    def get_available_models(self) -> list:
        """利用可能なモデルのリストを返す（Gemini + OpenRouter）"""
        models = [
            {'id': 'gemini-3-flash-preview', 'name': 'Gemini 3 Flash Preview', 'default': False, 'provider': 'gemini'},
            {'id': 'gemini-2.5-pro', 'name': 'Gemini 2.5 Pro', 'default': False, 'provider': 'gemini'},
            {'id': 'gemini-2.5-flash', 'name': 'Gemini 2.5 Flash', 'default': False, 'provider': 'gemini'},
            {'id': 'gemini-2.0-flash-exp', 'name': 'Gemini 2.0 Flash Experimental (Free)', 'default': True, 'provider': 'gemini'},
            {'id': 'gemini-1.5-flash', 'name': 'Gemini 1.5 Flash', 'default': False, 'provider': 'gemini'},
            {'id': 'gemini-1.5-pro', 'name': 'Gemini 1.5 Pro', 'default': False, 'provider': 'gemini'},
        ]
        
        openrouter_text_models = [
            {'id': 'openrouter:google/gemini-2.0-flash-exp:free', 'name': 'OpenRouter: Gemini 2.0 Flash (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:google/gemma-3-27b-it:free', 'name': 'OpenRouter: Gemma 3 27B (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:google/gemma-3-12b-it:free', 'name': 'OpenRouter: Gemma 3 12B (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:mistralai/mistral-small-3.1-24b-instruct:free', 'name': 'OpenRouter: Mistral Small 24B (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:deepseek/deepseek-r1-0528:free', 'name': 'OpenRouter: DeepSeek R1 (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:meta-llama/llama-3.3-70b-instruct:free', 'name': 'OpenRouter: Llama 3.3 70B (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:meta-llama/llama-3.1-405b-instruct:free', 'name': 'OpenRouter: Llama 3.1 405B (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:qwen/qwen3-coder:free', 'name': 'OpenRouter: Qwen3 Coder (Free)', 'default': False, 'provider': 'openrouter'},
            {'id': 'openrouter:moonshotai/kimi-k2:free', 'name': 'OpenRouter: Kimi K2 (Free)', 'default': False, 'provider': 'openrouter'},
        ]
        
        openrouter_vision_models = [
            {'id': 'openrouter-vision:google/gemini-2.0-flash-exp:free', 'name': 'OpenRouter Vision: Gemini 2.0 Flash (Free)', 'default': False, 'provider': 'openrouter-vision'},
            {'id': 'openrouter-vision:google/gemma-3-27b-it:free', 'name': 'OpenRouter Vision: Gemma 3 27B (Free)', 'default': False, 'provider': 'openrouter-vision'},
            {'id': 'openrouter-vision:qwen/qwen-2.5-vl-7b-instruct:free', 'name': 'OpenRouter Vision: Qwen 2.5 VL 7B (Free) *要翻訳', 'default': False, 'provider': 'openrouter-vision'},
            {'id': 'openrouter-vision:allenai/molmo-2-8b:free', 'name': 'OpenRouter Vision: Molmo 2 8B (Free) *要翻訳', 'default': False, 'provider': 'openrouter-vision'},
            {'id': 'openrouter-vision:nvidia/nemotron-nano-12b-v2-vl:free', 'name': 'OpenRouter Vision: Nemotron 12B VL (Free) *要翻訳', 'default': False, 'provider': 'openrouter-vision'},
        ]
        
        return models + openrouter_text_models + openrouter_vision_models
    
    def _is_openrouter_model(self, model_name: str) -> bool:
        """OpenRouterモデルかどうかを判定"""
        return model_name.startswith('openrouter:') or model_name.startswith('openrouter-vision:')
    
    def _get_openrouter_model_id(self, model_name: str) -> str:
        """OpenRouterモデルIDを抽出（プレフィックスを除去）"""
        if model_name.startswith('openrouter-vision:'):
            return model_name.replace('openrouter-vision:', '')
        if model_name.startswith('openrouter:'):
            return model_name.replace('openrouter:', '')
        return model_name
    
    def _is_japanese_text(self, text: str) -> bool:
        """テキストが日本語かどうかを判定"""
        if not text:
            return True
        
        japanese_chars = sum(1 for c in text if '\u3040' <= c <= '\u309f' or  # Hiragana
                                                '\u30a0' <= c <= '\u30ff' or  # Katakana
                                                '\u4e00' <= c <= '\u9fff')    # Kanji
        total_chars = len(text.replace(' ', '').replace('\n', ''))
        if total_chars == 0:
            return True
        
        return (japanese_chars / total_chars) > 0.1
    
    def _ensure_japanese_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """レシピテキストが日本語でない場合は翻訳する"""
        recipe_text = result.get('recipe_text', '')
        model_used = result.get('ai_model', '')
        
        # 日本語でない場合は翻訳
        needs_translation = not self._is_japanese_text(recipe_text)
        
        if needs_translation:
            logging.info(f"Non-Japanese response detected from {model_used}, translating...")
            
            translation_result = openrouter_client.translate_to_japanese(recipe_text)
            if translation_result.get('success') and translation_result.get('content'):
                result['recipe_text'] = translation_result['content']
                result['translation_model'] = translation_result.get('model_used')
                result['translation_tokens'] = translation_result.get('tokens_used', 0)
                logging.info(f"Successfully translated recipe to Japanese using {translation_result.get('model_used')}")
            else:
                logging.warning(f"Translation failed: {translation_result.get('error')}")
        
        return result

    def extract_recipe_with_model(self, video_url: str, model_name: str = None) -> Dict[str, Any]:
        """
        テスト用: 指定されたモデルでレシピを抽出

        Args:
            video_url: 動画URL
            model_name: 使用するGeminiモデル名（Noneの場合はデフォルト）
        """
        platform = self._detect_platform(video_url)

        if model_name is None:
            model_name = 'gemini-1.5-flash'

        if platform == "youtube":
            return self._extract_recipe_from_youtube_with_model(video_url, model_name)
        elif platform in ["tiktok", "instagram"]:
            return self._extract_recipe_from_other_platform_with_model(video_url, platform, model_name)
        else:
            raise ValueError(f"Unsupported platform for URL: {video_url}")

    def _extract_recipe_from_youtube_with_model(self, video_url: str, model_name: str) -> Dict[str, Any]:
        """YouTubeからレシピを抽出（モデル指定版）"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")

        extraction_flow = []

        logging.info(f"Checking YouTube description for recipe (using {model_name} for refinement)...")
        extraction_flow.append("説明欄をチェック")
        description_result = self._get_recipe_from_description(video_id, model_name)
        if description_result:
            logging.info("Recipe found in description")
            extraction_flow.append("キーワード検出 → AI抽出: 成功")
            return {
                'recipe_text': description_result.get('text', ''),
                'extraction_method': 'description',
                'extraction_flow': ' → '.join(extraction_flow),
                'ai_model': description_result.get('model_used', model_name),
                'tokens_used': description_result.get('refinement_tokens'),
                'input_tokens': description_result.get('input_tokens'),
                'output_tokens': description_result.get('output_tokens'),
                'refinement_status': description_result.get('refinement_status', 'skipped'),
                'refinement_error': description_result.get('refinement_error')
            }
        else:
            extraction_flow.append("レシピなし")

        logging.info(f"Checking YouTube comments for recipe (using {model_name} for refinement)...")
        extraction_flow.append("コメント欄をチェック")
        comment_result = self._get_recipe_from_comments(video_id, model_name)
        if comment_result:
            logging.info("Recipe found in author's comment")
            extraction_flow.append("キーワード検出 → AI抽出: 成功")
            return {
                'recipe_text': comment_result.get('text', ''),
                'extraction_method': 'comment',
                'extraction_flow': ' → '.join(extraction_flow),
                'ai_model': comment_result.get('model_used', model_name),
                'tokens_used': comment_result.get('refinement_tokens'),
                'input_tokens': comment_result.get('input_tokens'),
                'output_tokens': comment_result.get('output_tokens'),
                'refinement_status': comment_result.get('refinement_status', 'skipped'),
                'refinement_error': comment_result.get('refinement_error')
            }
        else:
            extraction_flow.append("レシピなし")

        # 動画解析はGemini API直接使用（gemini-2.0-flash-lite）
        video_model = 'gemini-2.0-flash-lite'
        logging.info(f"Extracting recipe from video using Gemini API ({video_model})...")
        extraction_flow.append("動画解析")
        
        result = self._extract_recipe_with_gemini_model(video_url, video_model)
        extraction_flow.append("抽出成功")
        result['extraction_flow'] = ' → '.join(extraction_flow)
        
        return result

    def _extract_recipe_from_other_platform_with_model(self, video_url: str, platform: str, model_name: str) -> Dict[str, Any]:
        """TikTok/Instagramからレシピを抽出（モデル指定版）"""
        platform_name = 'TikTok' if platform == 'tiktok' else 'Instagram'
        extraction_flow = []
        
        logging.info(f"Attempting to extract recipe from {platform} description (using {model_name} for refinement)...")
        extraction_flow.append(f"{platform_name}説明欄をチェック")
        try:
            response = self.session.get(video_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            description = None
            meta_description = soup.find('meta', property='og:description')
            if meta_description and hasattr(meta_description, 'get'):
                description = meta_description.get('content', '')

            if description and isinstance(description, str) and self._contains_recipe(description):
                logging.info(f"Keyword found in {platform} description, sending to AI")
                raw_recipe = self._extract_recipe_text(description)
                if raw_recipe:
                    refinement_result = self._refine_recipe_with_model(raw_recipe, model_name)
                    # AIがレシピなしと判定した場合は動画解析へ
                    if refinement_result.get('refinement_status') == 'no_recipe':
                        logging.info(f"AI determined no recipe in {platform} description")
                        extraction_flow.append("キーワード検出 → AI判定: レシピなし")
                    else:
                        logging.info(f"Recipe found in {platform} description")
                        extraction_flow.append("キーワード検出 → AI抽出: 成功")
                        return {
                            'recipe_text': refinement_result.get('text', ''),
                            'extraction_method': 'description',
                            'extraction_flow': ' → '.join(extraction_flow),
                            'ai_model': refinement_result.get('model_used', model_name),
                            'tokens_used': refinement_result.get('refinement_tokens'),
                            'input_tokens': refinement_result.get('input_tokens'),
                            'output_tokens': refinement_result.get('output_tokens'),
                            'refinement_status': refinement_result.get('refinement_status', 'skipped'),
                            'refinement_error': refinement_result.get('refinement_error')
                        }
            else:
                extraction_flow.append("キーワードなし")
        except Exception as e:
            logging.warning(f"Could not fetch {platform} description: {e}. Proceeding with video analysis.")
            extraction_flow.append("取得失敗")

        # 動画解析はGemini API直接使用（gemini-2.0-flash-lite）
        video_model = 'gemini-2.0-flash-lite'
        logging.info(f"No recipe in {platform} description, extracting from video using Gemini API ({video_model})...")
        extraction_flow.append("動画解析")
        
        result = self._extract_recipe_with_gemini_model(video_url, video_model)
        extraction_flow.append("抽出成功")
        result['extraction_flow'] = ' → '.join(extraction_flow)
        
        return result

    def _extract_recipe_with_openrouter_video(self, video_url: str, model_name: str = None) -> Dict[str, Any]:
        """OpenRouter APIを使って動画からレシピを抽出（URLベース）"""
        try:
            platform = self._detect_platform(video_url)
            
            direct_video_url = None
            if platform == 'youtube':
                direct_video_url = self._get_youtube_direct_url(video_url)
            elif platform in ['tiktok', 'instagram']:
                logging.info(f"Detected {platform}, using Apify to get download URL...")
                direct_video_url = self._get_video_download_url_from_apify(video_url, platform)
            
            if not direct_video_url:
                return {
                    'success': False,
                    'recipe_text': None,
                    'extraction_method': 'video_analysis',
                    'error': f'Could not get direct video URL for {platform}',
                }
            
            logging.info(f"Got direct video URL for {platform}")
            
            models_to_try = None
            if model_name and self._is_openrouter_model(model_name):
                model_id = model_name.replace('openrouter:', '')
                if model_id == 'auto':
                    models_to_try = VIDEO_CAPABLE_MODELS
                    logging.info(f"Using VIDEO_CAPABLE_MODELS with auto-fallback for video analysis")
                else:
                    models_to_try = [model_id]
                    logging.info(f"Using specified OpenRouter model: {model_id}")
            else:
                models_to_try = VIDEO_CAPABLE_MODELS
                logging.info(f"Using default VIDEO_CAPABLE_MODELS with fallback")
            
            logging.info(f"Sending video URL to OpenRouter for analysis...")
            result = openrouter_client.extract_recipe_from_video_url(direct_video_url, models_to_try)
            
            if result.get('success'):
                content = result.get('content', '')
                
                recipe_text = None
                try:
                    json_text = re.sub(r'^```json\s*|\s*```$', '', content, flags=re.MULTILINE).strip()
                    recipe_json = json.loads(json_text)
                    
                    if recipe_json.get('no_recipe') or recipe_json.get('error'):
                        raise ValueError("No recipe found in video")
                    
                    if not recipe_json.get('ingredients') or not recipe_json.get('steps'):
                        raise json.JSONDecodeError("Missing required fields", json_text, 0)
                    
                    recipe_text = self._convert_json_to_text(recipe_json)
                    logging.info("Successfully parsed JSON response from OpenRouter")
                except json.JSONDecodeError:
                    logging.warning("Failed to parse JSON, using text fallback")
                    recipe_text = self._clean_recipe_text(content)
                
                if not recipe_text or "レシピが見つかりませんでした" in recipe_text:
                    raise ValueError("No recipe found in video")
                
                return {
                    'success': True,
                    'recipe_text': recipe_text,
                    'extraction_method': 'video_analysis',
                    'ai_model': result.get('model_used', 'openrouter'),
                    'tokens_used': result.get('tokens_used', 0),
                    'translated': result.get('translated', False),
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                logging.error(f"OpenRouter video analysis failed: {error_msg}")
                return {
                    'success': False,
                    'recipe_text': None,
                    'extraction_method': 'video_analysis',
                    'error': error_msg,
                    'ai_model': result.get('model_used'),
                }
                
        except Exception as e:
            logging.error(f"Error in _extract_recipe_with_openrouter_video: {e}")
            return {
                'success': False,
                'recipe_text': None,
                'extraction_method': 'video_analysis',
                'error': str(e),
            }

    def _get_youtube_direct_url(self, video_url: str) -> Optional[str]:
        """YouTubeから直接ダウンロードURLを取得"""
        try:
            ydl_opts = {
                'format': 'best[ext=mp4][height<=480]/best[ext=mp4][height<=720]/best[ext=mp4]/best',
                'quiet': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                },
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                if info_dict and 'url' in info_dict:
                    logging.info(f"Got YouTube direct URL")
                    return info_dict['url']
                elif info_dict and 'formats' in info_dict:
                    for fmt in reversed(info_dict['formats']):
                        if fmt.get('url') and fmt.get('ext') == 'mp4':
                            logging.info(f"Got YouTube direct URL from formats")
                            return fmt['url']
            logging.warning("Could not extract direct URL from YouTube")
            return None
        except Exception as e:
            logging.error(f"Error getting YouTube direct URL: {e}")
            return None

    def _extract_recipe_with_gemini_model(self, video_url: str, model_name: str) -> Dict[str, Any]:
        """Gemini APIを使って動画からレシピを抽出（モデル指定版）- 非推奨、OpenRouterを使用してください"""
        temp_video_path = None
        video_file = None
        try:
            self._ensure_gemini_initialized()

            platform = self._detect_platform(video_url)

            download_url = video_url
            if platform in ['tiktok', 'instagram']:
                logging.info(f"Detected {platform}, using Apify to get download URL...")
                apify_download_url = self._get_video_download_url_from_apify(video_url, platform)
                if apify_download_url:
                    download_url = apify_download_url
                    logging.info(f"Using Apify download URL for {platform}")
                else:
                    logging.warning(f"Failed to get download URL from Apify for {platform}, trying direct download")

            logging.info(f"Downloading video from URL: {download_url}")
            ydl_opts = {
                'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
                'outtmpl': 'temp_video_%(id)s.%(ext)s',
                'quiet': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                },
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(download_url, download=True)
                temp_video_path = ydl.prepare_filename(info_dict)

            if not temp_video_path or not os.path.exists(temp_video_path):
                raise FileNotFoundError("Failed to download the video file.")
            logging.info(f"Video downloaded to: {temp_video_path}")

            logging.info("Uploading video file to Gemini...")
            video_file = genai.upload_file(path=temp_video_path)
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            if video_file.state.name == "FAILED":
                raise ValueError(f"Video processing failed on Google's server: {video_file.uri}")
            logging.info("Video uploaded and processed.")

            model = genai.GenerativeModel(model_name)
            prompt = """
この動画からレシピを抽出し、以下のJSON形式「のみ」で出力してください。前置きや説明文は一切不要です。
{"ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}], "steps": ["手順1"], "tips": ["コツ1"]}

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

動画にレシピが含まれていない場合のみ、{"error": "レシピが見つかりませんでした"}と返してください。
"""
            logging.info(f"Sending video to Gemini ({model_name})...")
            response = model.generate_content([video_file, prompt])

            raw_text = response.text.strip()
            logging.debug(f"Gemini raw response: {raw_text[:200]}...")

            recipe_text = None
            try:
                json_text = re.sub(r'^```json\s*|\s*```$', '', raw_text, flags=re.MULTILINE).strip()
                recipe_json = json.loads(json_text)
                if recipe_json.get('error'):
                    raise ValueError("No recipe found in video")
                if not recipe_json.get('ingredients') or not recipe_json.get('steps'):
                    raise json.JSONDecodeError("Missing required fields", json_text, 0)
                recipe_text = self._convert_json_to_text(recipe_json)
                logging.info("Successfully parsed JSON response from Gemini")
            except json.JSONDecodeError:
                logging.warning("Failed to parse JSON, using text fallback")
                recipe_text = self._clean_recipe_text(raw_text)

            if "レシピが見つかりませんでした" in recipe_text:
                raise ValueError("No recipe found in video")
            if not self._validate_recipe_structure(recipe_text):
                raise ValueError("Incomplete recipe: missing ingredients or steps")

            tokens_info = self._estimate_tokens(response)
            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': model_name,
                'tokens_used': tokens_info.get('total', 0),
                'input_tokens': tokens_info.get('input', 0),
                'output_tokens': tokens_info.get('output', 0),
                'refinement_status': 'not_applicable',
                'refinement_error': None
            }
        except Exception as e:
            logging.error(f"Error in _extract_recipe_with_gemini_model: {e}")
            raise
        finally:
            if video_file:
                try:
                    genai.delete_file(video_file.name)
                    logging.info(f"Deleted uploaded file: {video_file.name}")
                except Exception as e:
                    logging.warning(f"Could not delete uploaded file {video_file.name}: {e}")
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                logging.info(f"Deleted temp local file: {temp_video_path}")

    def _extract_recipe_with_gemini(self, video_url: str) -> Dict[str, Any]:
        """Gemini APIを使って動画からレシピを抽出（動画アップロード対応版）"""
        temp_video_path = None
        video_file = None
        try:
            self._ensure_gemini_initialized()

            platform = self._detect_platform(video_url)

            download_url = video_url
            if platform in ['tiktok', 'instagram']:
                logging.info(f"Detected {platform}, using Apify to get download URL...")
                apify_download_url = self._get_video_download_url_from_apify(video_url, platform)
                if apify_download_url:
                    download_url = apify_download_url
                    logging.info(f"Using Apify download URL for {platform}")
                else:
                    logging.warning(f"Failed to get download URL from Apify for {platform}, trying direct download")

            logging.info(f"Downloading video from URL: {download_url}")
            ydl_opts = {
                'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
                'outtmpl': 'temp_video_%(id)s.%(ext)s',
                'quiet': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                },
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(download_url, download=True)
                temp_video_path = ydl.prepare_filename(info_dict)

            if not temp_video_path or not os.path.exists(temp_video_path):
                raise FileNotFoundError("Failed to download the video file.")
            logging.info(f"Video downloaded to: {temp_video_path}")

            logging.info("Uploading video file to Gemini...")
            video_file = genai.upload_file(path=temp_video_path)
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            if video_file.state.name == "FAILED":
                raise ValueError(
                    f"Video processing failed on Google's server: {video_file.uri}"
                )
            logging.info("Video uploaded and processed.")

            model_name = 'gemini-2.0-flash-exp'
            model = genai.GenerativeModel(model_name)
            prompt = """
この動画からレシピを抽出し、以下のJSON形式「のみ」で出力してください。前置きや説明文は一切不要です。
{"ingredients": [{"name": "材料名", "amount": "数量", "unit": "単位", "sub_amount": "重量換算の数量", "sub_unit": "重量換算の単位"}], "steps": ["手順1"], "tips": ["コツ1"]}

材料のunitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

【重量換算（sub_amount / sub_unit）について】
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

動画にレシピが含まれていない場合のみ、{"error": "レシピが見つかりませんでした"}と返してください。
"""
            logging.info(f"Sending video to Gemini ({model_name})...")
            response = model.generate_content([video_file, prompt])

            raw_text = response.text.strip()
            logging.debug(f"Gemini raw response: {raw_text[:200]}...")

            recipe_text = None
            try:
                json_text = re.sub(r'^```json\s*|\s*```$',
                                   '',
                                   raw_text,
                                   flags=re.MULTILINE).strip()
                recipe_json = json.loads(json_text)
                if recipe_json.get('error'):
                    raise ValueError("No recipe found in video")
                if not recipe_json.get('ingredients') or not recipe_json.get(
                        'steps'):
                    raise json.JSONDecodeError("Missing required fields",
                                               json_text, 0)
                recipe_text = self._convert_json_to_text(recipe_json)
                logging.info("Successfully parsed JSON response from Gemini")
            except json.JSONDecodeError:
                logging.warning("Failed to parse JSON, using text fallback")
                recipe_text = self._clean_recipe_text(raw_text)

            if "レシピが見つかりませんでした" in recipe_text:
                raise ValueError("No recipe found in video")
            if not self._validate_recipe_structure(recipe_text):
                raise ValueError(
                    "Incomplete recipe: missing ingredients or steps")

            tokens_info = self._estimate_tokens(response)
            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': model_name,
                'tokens_used': tokens_info.get('total', 0),
                'input_tokens': tokens_info.get('input', 0),
                'output_tokens': tokens_info.get('output', 0),
                'refinement_status': 'not_applicable',
                'refinement_error': None
            }
        except Exception as e:
            logging.error(f"Error in _extract_recipe_with_gemini: {e}")
            raise
        finally:
            if video_file:
                try:
                    genai.delete_file(video_file.name)
                    logging.info(f"Deleted uploaded file: {video_file.name}")
                except Exception as e:
                    logging.warning(
                        f"Could not delete uploaded file {video_file.name}: {e}"
                    )
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                logging.info(f"Deleted temp local file: {temp_video_path}")

    def _extract_recipe_from_other_platform(self, video_url: str,
                                            platform: str) -> Dict[str, Any]:
        """TikTok/Instagramからレシピを抽出（OpenRouter自動フォールバック対応）"""
        platform_name = 'TikTok' if platform == 'tiktok' else 'Instagram'
        default_model = 'openrouter:auto'
        extraction_flow = []
        
        logging.info(
            f"Attempting to extract recipe from {platform} description (using OpenRouter auto mode)...")
        extraction_flow.append(f"{platform_name}説明欄をチェック")
        
        try:
            response = self.session.get(video_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            description = None
            meta_description = soup.find('meta', property='og:description')
            if meta_description and hasattr(meta_description, 'get'):
                description = meta_description.get('content', '')

            if description and isinstance(
                    description, str) and self._contains_recipe(description):
                raw_recipe = self._extract_recipe_text(description)
                if raw_recipe:
                    refinement_result = self._refine_recipe_with_model(raw_recipe, default_model)
                    
                    if refinement_result.get('refinement_status') == 'no_recipe':
                        logging.info(f"AI determined no recipe in {platform} description")
                        extraction_flow.append("キーワード検出 → AI判定: レシピなし")
                    else:
                        logging.info(f"Recipe found in {platform} description")
                        extraction_flow.append("キーワード検出 → AI抽出: 成功")
                        # 実際に使用されたモデルを報告（Noneの場合は'openrouter:auto'を表示）
                        actual_model = refinement_result.get('model_used') or 'openrouter:auto'
                        return {
                            'recipe_text': refinement_result.get('text', ''),
                            'extraction_method': 'description',
                            'extraction_flow': ' → '.join(extraction_flow),
                            'ai_model': actual_model,
                            'tokens_used': refinement_result.get('refinement_tokens'),
                            'refinement_status': refinement_result.get('refinement_status', 'skipped'),
                            'refinement_error': refinement_result.get('refinement_error')
                        }
            else:
                extraction_flow.append("キーワードなし")
        except Exception as e:
            logging.warning(
                f"Could not fetch {platform} description: {e}. Proceeding with video analysis."
            )
            extraction_flow.append("取得失敗")

        # 動画解析はGeminiを使用（OpenRouterは動画アップロード非対応）
        video_model = 'gemini-2.0-flash-exp'
        logging.info(
            f"No recipe in {platform} description, attempting video analysis with {video_model}..."
        )
        extraction_flow.append("動画解析")
        
        result = self._extract_recipe_with_gemini_model(video_url, video_model)
        result['extraction_flow'] = ' → '.join(extraction_flow) + ' → 抽出成功'
        
        # 翻訳が必要な場合は翻訳
        if result.get('recipe_text'):
            result = self._ensure_japanese_response(result)
        
        return result

    def _estimate_tokens(self, response) -> Dict[str, int]:
        """トークン使用量を推定（入力/出力/合計を返す）"""
        try:
            if hasattr(response, 'usage_metadata'):
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
                return {
                    'total': input_tokens + output_tokens,
                    'input': input_tokens,
                    'output': output_tokens
                }
            text_length = len(response.text)
            estimated = int(text_length / 1.5)
            return {
                'total': estimated,
                'input': 0,
                'output': estimated
            }
        except Exception as e:
            logging.warning(f"Could not estimate tokens: {e}")
            return {'total': 0, 'input': 0, 'output': 0}

    def calculate_cost(self, model: str, tokens_used: int) -> float:
        """AI利用コストを計算（USD）"""
        pricing = {
            'gemini-2.0-flash-exp': {
                'input': 0.0,
                'output': 0.0
            },
            'gemini-1.5-flash': {
                'input': 0.35 / 1000000,
                'output': 1.05 / 1000000
            },
        }
        if model not in pricing:
            logging.warning(f"Unknown model {model}, cannot calculate cost")
            return 0.0

        assumed_input_tokens = tokens_used * 0.5
        assumed_output_tokens = tokens_used * 0.5
        cost = (assumed_input_tokens * pricing[model]['input'] +
                assumed_output_tokens * pricing[model]['output'])
        return round(cost, 8)

    def extract_recipe_from_image(self, image_data: bytes, image_mime_type: str = 'image/jpeg') -> Dict[str, Any]:
        """
        画像からレシピ情報を抽出する
        
        Args:
            image_data: 画像のバイナリデータ
            image_mime_type: 画像のMIMEタイプ (image/jpeg, image/png, image/webp, image/heic)
        
        Returns:
            {
                'success': True,
                'dish_name': '料理名',
                'ingredients': [{'name': '材料名', 'amount': '数量', 'unit': '単位', 'sub_amount': '重量換算数量', 'sub_unit': '重量換算単位'}],
                'steps': ['手順1', '手順2', ...],
                'tips': 'コツや注意点',
                'servings': '2人分',
                'cooking_time': '30分',
                'raw_text': '抽出した生テキスト',
                'tokens_used': 1234,
                'input_tokens': 800,
                'output_tokens': 434
            }
        """
        self._ensure_gemini_initialized()
        
        model_name = 'gemini-2.0-flash-lite'
        
        prompt = """あなたは料理レシピの専門家です。
この画像（レシピ本や料理雑誌の写真）からレシピ情報を抽出してください。

## タスク
画像に写っているレシピの以下の情報を正確に読み取り、構造化してください：
1. 料理名
2. 材料と分量（すべて）
3. 作り方の手順（ステップごと）
4. コツや注意点（あれば）
5. 何人分か（記載があれば）
6. 調理時間（記載があれば）

## 出力形式
必ず以下のJSON形式で出力してください。それ以外のテキストは不要です。

```json
{
    "dish_name": "料理名",
    "servings": "2人分",
    "cooking_time": "30分",
    "ingredients": [
        {"name": "鶏もも肉", "amount": "300", "unit": "g", "sub_amount": "", "sub_unit": ""},
        {"name": "玉ねぎ", "amount": "1", "unit": "個", "sub_amount": "200", "sub_unit": "g"},
        {"name": "醤油", "amount": "2", "unit": "大さじ", "sub_amount": "", "sub_unit": ""}
    ],
    "steps": [
        "鶏肉を一口大に切る",
        "玉ねぎを薄切りにする",
        "フライパンで鶏肉を炒める"
    ],
    "tips": "鶏肉は常温に戻してから調理すると柔らかく仕上がります"
}
```

## 材料のunit（単位）について
unitには以下のような適切な単位を設定してください：
g, kg, ml, L, 個, 本, 枚, 切れ, 片, 束, 袋, パック, 缶, 大さじ, 小さじ, カップ, 合, 適量, 少々, お好みで
amountには数値のみ、unitには単位のみを入れてください。「適量」「少々」「お好みで」等の場合はamountを空文字、unitにその表現を入れてください。

## 重量換算（sub_amount / sub_unit）について
材料に「ズッキーニ1本(200g)」のように主単位と重量換算が併記されている場合：
- amount: "1", unit: "本" （主単位）
- sub_amount: "200", sub_unit: "g" （重量換算値）
重量換算がない場合は sub_amount と sub_unit は空文字にしてください。

## 注意事項
- 画像から読み取れない情報は null にしてください
- 材料は画像に記載されているものをすべて抽出してください
- 手順は番号順に配列で返してください
- 日本語で出力してください
"""

        try:
            import base64
            
            model = genai.GenerativeModel(model_name)
            
            image_part = {
                'mime_type': image_mime_type,
                'data': base64.b64encode(image_data).decode('utf-8')
            }
            
            response = model.generate_content([prompt, image_part])
            
            response_text = response.text.strip()
            logging.info(f"Gemini image analysis response length: {len(response_text)}")
            
            tokens_info = self._estimate_tokens(response)
            
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    
                    return {
                        'success': True,
                        'dish_name': result.get('dish_name'),
                        'servings': result.get('servings'),
                        'cooking_time': result.get('cooking_time'),
                        'ingredients': result.get('ingredients', []),
                        'steps': result.get('steps', []),
                        'tips': result.get('tips'),
                        'raw_text': response_text,
                        'ai_model': model_name,
                        'tokens_used': tokens_info.get('total', 0),
                        'input_tokens': tokens_info.get('input', 0),
                        'output_tokens': tokens_info.get('output', 0)
                    }
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON parse error: {e}")
            
            return {
                'success': True,
                'dish_name': None,
                'servings': None,
                'cooking_time': None,
                'ingredients': [],
                'steps': [],
                'tips': None,
                'raw_text': response_text,
                'ai_model': model_name,
                'tokens_used': tokens_info.get('total', 0),
                'input_tokens': tokens_info.get('input', 0),
                'output_tokens': tokens_info.get('output', 0),
                'parse_error': 'Could not parse structured data from image'
            }
            
        except Exception as e:
            logging.error(f"Error extracting recipe from image: {e}")
            raise ValueError(f"画像からのレシピ抽出に失敗しました: {str(e)}")

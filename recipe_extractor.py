import os
import logging
import re
import time
import json
import requests
from typing import Optional, Dict, Any
import google.generativeai as genai
from bs4 import BeautifulSoup
import pathlib
import yt_dlp


class RecipeExtractor:
    """動画からレシピを抽出するクラス"""

    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
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

        Returns:
            {
                'recipe_text': str,
                'extraction_method': str,  # 'description', 'comment', 'ai_video'
                'ai_model': str or None,
                'tokens_used': int or None
            }
        """
        platform = self._detect_platform(video_url)

        if platform == "youtube":
            return self._extract_recipe_from_youtube(video_url)
        elif platform in ["tiktok", "instagram"]:
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
        """YouTubeからレシピを抽出"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")

        # 1. 説明欄からレシピを探す
        logging.info("Checking YouTube description for recipe...")
        description_recipe = self._get_recipe_from_description(video_id)
        if description_recipe:
            logging.info("Recipe found in description")
            return {
                'recipe_text': description_recipe,
                'extraction_method': 'description',
                'ai_model': None,
                'tokens_used': None
            }

        # 2. 投稿者コメントからレシピを探す
        logging.info("Checking YouTube comments for recipe...")
        comment_recipe = self._get_recipe_from_comments(video_id)
        if comment_recipe:
            logging.info("Recipe found in author's comment")
            return {
                'recipe_text': comment_recipe,
                'extraction_method': 'comment',
                'ai_model': None,
                'tokens_used': None
            }

        # 3. Gemini APIで動画から直接レシピを抽出
        logging.info("Extracting recipe from video using Gemini AI...")
        return self._extract_recipe_with_gemini(video_url)

    def extract_unique_video_id(self, url: str) -> tuple:
        """
        URLからプラットフォームとユニーク動画IDを抽出

        Returns:
            (platform, unique_video_id): タプル
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
            if match:
                return match.group(1)
        return ""

    def _extract_tiktok_id(self, url: str) -> str:
        """TikTok動画IDを抽出"""
        patterns = [r'/video/(\d+)', r'/v/(\d+)']

        for pattern in patterns:
            match = re.search(pattern, url)
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
            if match:
                return match.group(1)
        return ""

    def _refine_recipe_with_gemini(self, raw_text: str) -> Optional[str]:
        """
        Gemini APIを使って説明欄のテキストを整理
        レシピ内容は変えず、余分な文章のみを削除
        """
        try:
            self._ensure_gemini_initialized()
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            
            prompt = """
以下のテキストにはレシピ情報が含まれています。
レシピの内容（材料、分量、手順）は一切変更せず、余分な宣伝文や関係ない情報のみを削除して、
レシピ部分だけを抽出し、以下のJSON形式で出力してください。

{
  "dish_name": "料理の名前",
  "ingredients": ["材料1: 分量", "材料2: 分量"],
  "steps": ["手順1", "手順2"],
  "tips": ["ポイント1"]
}

重要：
- レシピの材料名、分量、手順の内容は絶対に変更しないでください
- 余分な宣伝文、SNSリンク、チャンネル説明などは削除してください
- JSON形式のみを返してください

テキスト：
""" + raw_text
            
            response = model.generate_content(prompt)
            raw_response = response.text.strip()
            
            # JSONパース
            json_text = re.sub(r'^```json\s*', '', raw_response)
            json_text = re.sub(r'\s*```$', '', json_text)
            json_text = json_text.strip()
            
            recipe_json = json.loads(json_text)
            
            # JSON → テキスト形式に変換
            refined_recipe = self._convert_json_to_text(recipe_json)
            logging.info("Successfully refined recipe text with Gemini")
            return refined_recipe
            
        except Exception as e:
            logging.warning(f"Failed to refine recipe with Gemini: {e}, using original")
            return None
    
    def _get_recipe_from_description(self, video_id: str) -> Optional[str]:
        """YouTube説明欄からレシピを取得"""
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

            if not data.get('items'):
                return None

            description = data['items'][0]['snippet'].get('description', '')

            if self._contains_recipe(description):
                # 説明欄全文をGeminiで整理
                logging.info("Recipe found in description, refining with Gemini...")
                refined_recipe = self._refine_recipe_with_gemini(description)
                if refined_recipe:
                    return refined_recipe
                
                # Geminiでの整理に失敗した場合、従来の方法で抽出
                logging.info("Gemini refinement failed, using traditional extraction")
                recipe = self._extract_recipe_text(description)
                return recipe if recipe else None

            return None

        except Exception as e:
            logging.error(f"Error fetching YouTube description: {e}")
            return None

    def _get_recipe_from_comments(self, video_id: str) -> Optional[str]:
        """YouTube投稿者コメントからレシピを取得"""
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

            if not data.get('items'):
                return None

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
                        recipe = self._extract_recipe_text(comment_text)
                        return recipe if recipe else None

            return None

        except Exception as e:
            logging.error(f"Error fetching YouTube comments: {e}")
            return None

    def _contains_recipe(self, text: str) -> bool:
        """テキストにレシピが含まれているか判定"""
        recipe_keywords = [
            '材料', 'レシピ', '作り方', '手順', 'ingredients', 'recipe', '調味料', '分量',
            'g', 'ml', 'cc', '大さじ', '小さじ', '①', '②', '1.', '2.', '・'
        ]

        text_lower = text.lower()
        keyword_count = sum(1 for keyword in recipe_keywords
                            if keyword.lower() in text_lower)
        return keyword_count >= 3

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
        """JSON形式のレシピをテキスト形式に変換"""
        parts = []
        if recipe_json.get('dish_name'):
            parts.append(f"【料理名】\n{recipe_json['dish_name']}")
        if recipe_json.get('ingredients'):
            parts.append("\n【材料】")
            for ingredient in recipe_json['ingredients']:
                parts.append(f"- {ingredient}")
        if recipe_json.get('steps'):
            parts.append("\n【作り方】")
            for i, step in enumerate(recipe_json['steps'], 1):
                parts.append(f"{i}. {step}")
        if recipe_json.get('tips'):
            parts.append("\n【コツ・ポイント】")
            for tip in recipe_json['tips']:
                parts.append(f"- {tip}")
        return '\n'.join(parts)

    def _validate_recipe_structure(self, recipe_text: str) -> bool:
        """レシピに必須セクションが含まれているか検証"""
        has_ingredients = any(k in recipe_text
                              for k in ['【材料】', '材料', 'Ingredients'])
        has_steps = any(k in recipe_text
                        for k in ['【作り方】', '作り方', 'Steps', '手順'])
        return has_ingredients and has_steps

    def _normalize_youtube_url(self, video_url: str) -> str:
        """YouTube URLを標準形式（watch形式）に変換"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id: return video_url
        normalized_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"Normalized URL: {video_url} -> {normalized_url}")
        return normalized_url

    def _extract_recipe_with_gemini(self, video_url: str) -> Dict[str, Any]:
        """Gemini APIを使って動画からレシピを抽出（動画アップロード対応版）"""
        temp_video_path = None
        video_file = None
        try:
            # Gemini APIを初期化
            self._ensure_gemini_initialized()

            # --- 1. 動画をサーバーに一時的にダウンロード ---
            logging.info(f"Downloading video from URL: {video_url}")
            ydl_opts = {
                'format':
                'best[ext=mp4][height<=720]/best[ext=mp4]/best',  # 720p以下のMP4を優先
                'outtmpl': 'temp_video_%(id)s.%(ext)s',
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                temp_video_path = ydl.prepare_filename(info_dict)

            if not temp_video_path or not os.path.exists(temp_video_path):
                raise FileNotFoundError("Failed to download the video file.")
            logging.info(
                f"Video downloaded successfully to: {temp_video_path}")

            # --- 2. ダウンロードした動画ファイルをGeminiにアップロード ---
            logging.info("Uploading video file to Gemini...")
            video_file = genai.upload_file(path=temp_video_path)

            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)

            if video_file.state.name == "FAILED":
                raise ValueError(
                    f"Video processing failed on Google's server: {video_file.uri}"
                )
            logging.info("Video uploaded and processed successfully.")

            # --- 3. アップロードした動画ファイルを使ってAIにリクエスト ---
            model_name = 'gemini-2.0-flash-exp'  # あなたの指定したモデル名
            model = genai.GenerativeModel(model_name)

            prompt = """
この動画からレシピを抽出し、以下のJSON形式「のみ」で出力してください。
前置きや説明文は一切不要です。JSON形式のみを返してください。

{
  "dish_name": "料理の名前",
  "ingredients": [
    "材料1: 分量",
    "材料2: 分量"
  ],
  "steps": [
    "手順1の詳細な説明",
    "手順2の詳細な説明"
  ],
  "tips": [
    "コツやポイント1"
  ]
}

重要な注意事項：
- 必ず上記のJSON形式で出力してください
- 作り方（steps）は必須です
- 動画にレシピが含まれていない場合のみ、{"error": "レシピが見つかりませんでした"}と返してください
"""

            logging.info(
                f"Sending video to Gemini ({model_name}) for analysis...")
            response = model.generate_content([video_file, prompt])

            # --- 4. 以降の処理（レスポンス解析） ---
            raw_text = response.text.strip()
            logging.debug(f"Gemini raw response: {raw_text[:200]}...")

            recipe_text = None
            try:
                json_text = re.sub(r'^```json\s*',
                                   '',
                                   raw_text,
                                   flags=re.MULTILINE)
                json_text = re.sub(r'\s*```$',
                                   '',
                                   json_text,
                                   flags=re.MULTILINE)
                json_text = json_text.strip()
                recipe_json = json.loads(json_text)

                if recipe_json.get('error'):
                    raise ValueError("No recipe found in the video")
                if not recipe_json.get('ingredients') or not recipe_json.get(
                        'steps'):
                    raise json.JSONDecodeError("Missing required fields",
                                               json_text, 0)

                recipe_text = self._convert_json_to_text(recipe_json)
                logging.info("Successfully parsed JSON response from Gemini")

            except json.JSONDecodeError:
                logging.warning(
                    "Failed to parse JSON response, using text fallback")
                recipe_text = self._clean_recipe_text(raw_text)

            if "レシピが見つかりませんでした" in recipe_text:
                raise ValueError("No recipe found in the video")
            if not self._validate_recipe_structure(recipe_text):
                raise ValueError(
                    "Incomplete recipe: missing ingredients or cooking steps")

            tokens_used = self._estimate_tokens(response)

            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': model_name,
                'tokens_used': tokens_used
            }

        except Exception as e:
            logging.error(f"Error extracting recipe with Gemini: {e}")
            raise

        finally:
            # --- 5. 一時ファイルをクリーンアップ ---
            if video_file:
                try:
                    genai.delete_file(video_file.name)
                    logging.info(
                        f"Deleted uploaded file from Google: {video_file.name}"
                    )
                except Exception as e:
                    logging.warning(
                        f"Could not delete uploaded file {video_file.name}: {e}"
                    )
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                logging.info(
                    f"Deleted temporary local file: {temp_video_path}")

    def _extract_recipe_from_other_platform(self, video_url: str,
                                            platform: str) -> Dict[str, Any]:
        """TikTok/Instagramからレシピを抽出（説明欄のみ対応）"""
        logging.info(
            f"Attempting to extract recipe from {platform} description...")
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
                recipe = self._extract_recipe_text(description)
                if recipe:
                    return {
                        'recipe_text': recipe,
                        'extraction_method': 'description',
                        'ai_model': None,
                        'tokens_used': None
                    }

            logging.warning(
                f"{platform} video analysis with Gemini may not be supported")
            raise ValueError(
                f"Recipe extraction from {platform} videos via AI is not fully supported"
            )

        except Exception as e:
            logging.error(f"Error extracting recipe from {platform}: {e}")
            raise

    def _estimate_tokens(self, response) -> int:
        """トークン使用量を推定"""
        try:
            if hasattr(response, 'usage_metadata'):
                return (response.usage_metadata.prompt_token_count +
                        response.usage_metadata.candidates_token_count)
            text_length = len(response.text)
            return int(text_length / 1.5)
        except Exception as e:
            logging.warning(f"Could not estimate tokens: {e}")
            return 0

    def calculate_cost(self, model: str, tokens_used: int) -> float:
        """AI利用コストを計算（USD）"""
        pricing = {
            'gemini-2.0-flash-exp': {
                'input': 0.0,
                'output': 0.0
            },  # 例：無料または特殊価格
            'gemini-1.5-flash': {
                'input': 0.35 / 1000000,
                'output': 1.05 / 1000000
            },
        }

        if model not in pricing:
            logging.warning(f"Unknown model {model}, cannot calculate cost")
            return 0.0

        # 概算のため、トークンの半分が入力、半分が出力と仮定
        assumed_input_tokens = tokens_used * 0.5
        assumed_output_tokens = tokens_used * 0.5

        cost = (assumed_input_tokens * pricing[model]['input'] +
                assumed_output_tokens * pricing[model]['output'])

        return round(cost, 8)

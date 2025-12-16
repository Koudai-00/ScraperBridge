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
        """YouTubeからレシピを抽出"""
        video_id = self._extract_youtube_id(video_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")

        logging.info("Checking YouTube description for recipe...")
        description_recipe = self._get_recipe_from_description(video_id)
        if description_recipe:
            logging.info("Recipe found in description, refining with AI...")
            # AIで整形
            refined_result = self._refine_recipe_text_with_ai(description_recipe)
            
            return {
                'recipe_text': refined_result['recipe_text'],
                'extraction_method': 'description',
                'ai_model': refined_result['ai_model'],
                'tokens_used': refined_result['tokens_used']
            }

        logging.info("Checking YouTube comments for recipe...")
        comment_recipe = self._get_recipe_from_comments(video_id)
        if comment_recipe:
            logging.info("Recipe found in author's comment, refining with AI...")
            # AIで整形
            refined_result = self._refine_recipe_text_with_ai(comment_recipe)
            
            return {
                'recipe_text': refined_result['recipe_text'],
                'extraction_method': 'comment',
                'ai_model': refined_result['ai_model'],
                'tokens_used': refined_result['tokens_used']
            }

        logging.info("Extracting recipe from video using Gemini AI...")
        # YouTubeも動画解析専用関数を呼び出す
        return self._extract_recipe_with_gemini(video_url)

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

            if not data.get('items'): return None
            description = data['items'][0]['snippet'].get('description', '')

            if self._contains_recipe(description):
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
        keyword_count = sum(1 for k in recipe_keywords
                            if k.lower() in text_lower)
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
            r'^レシピをテキスト化します。?\s*', r'^こちらがレシピです。?\s*',
            r'^```json\s*', r'\s*```$'
        ]
        cleaned = text
        for pattern in unwanted_prefixes:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
        return cleaned.strip()

    def _refine_recipe_text_with_ai(self, text: str) -> Dict[str, Any]:
        """抽出されたテキストからAIを使ってレシピ部分のみを綺麗に抽出・整形する"""
        try:
            self._ensure_gemini_initialized()
            
            # テキストが短すぎる場合はそのまま返す（コスト節約）
            if len(text) < 100:
                print(f"Text too short for AI refinement ({len(text)} chars), returning original.")
                return {
                    'recipe_text': text,
                    'ai_model': None,
                    'tokens_used': 0
                }

            model_name = 'gemini-2.0-flash-exp'
            # Fallback to 1.5 flash if 2.0 is not available or desired
            # model_name = 'gemini-1.5-flash' 
            
            model = genai.GenerativeModel(model_name)
            
            prompt = """
以下のテキストから「レシピ情報（料理名、材料、作り方、コツ）」のみを抽出し、JSON形式「のみ」で出力してください。
前置きや、レシピと関係のない挨拶、SNSリンク、ハッシュタグなどは全て削除してください。

入力テキスト:
""" + text + """

出力フォーマット（JSON）:
{"dish_name": "料理名", "ingredients": ["材料1: 分量"], "steps": ["手順1"], "tips": ["コツ1"]}

※必須: JSONのみを出力すること。markdown記法（```json）は不要です。
"""
            logging.info(f"Refining recipe text with Gemini ({model_name})...")
            response = model.generate_content(prompt)
            
            raw_text = response.text.strip()
            tokens_used = self._estimate_tokens(response)
            
            # JSON解析を試みる
            try:
                # markdownコードブロックの削除を試みる
                json_text = re.sub(r'^```json\s*|\s*```$', '', raw_text, flags=re.MULTILINE).strip()
                recipe_json = json.loads(json_text)
                
                # 必須フィールドの確認
                if not recipe_json.get('ingredients') and not recipe_json.get('steps'):
                    logging.warning("AI extracted JSON missing ingredients/steps, falling back to clean text")
                    return {
                        'recipe_text': self._clean_recipe_text(text), # 元のテキストをクリーニングして返す
                        'ai_model': model_name,
                        'tokens_used': tokens_used
                    }
                
                # JSONをテキスト形式に変換
                refined_text = self._convert_json_to_text(recipe_json)
                logging.info("Successfully refined recipe text with AI")
                
                return {
                    'recipe_text': refined_text,
                    'ai_model': model_name,
                    'tokens_used': tokens_used
                }
                
            except json.JSONDecodeError:
                logging.warning("Failed to parse AI response as JSON, using raw cleaned response")
                return {
                    'recipe_text': self._clean_recipe_text(raw_text),
                    'ai_model': model_name,
                    'tokens_used': tokens_used
                }
                
        except Exception as e:
            logging.error(f"Error in _refine_recipe_text_with_ai: {e}")
            # エラー時は元のテキストを返す（フェイルセーフ）
            return {
                'recipe_text': self._clean_recipe_text(text),
                'ai_model': None,
                'tokens_used': 0
            }

    def _convert_json_to_text(self, recipe_json: Dict[str, Any]) -> str:
        """JSON形式のレシピをテキスト形式に変換"""
        parts = []
        if recipe_json.get('dish_name'):
            parts.append(f"【料理名】\n{recipe_json['dish_name']}")
        if recipe_json.get('ingredients'):
            parts.append("\n【材料】")
            for i in recipe_json['ingredients']:
                parts.append(f"- {i}")
        if recipe_json.get('steps'):
            parts.append("\n【作り方】")
            for i, s in enumerate(recipe_json['steps'], 1):
                parts.append(f"{i}. {s}")
        if recipe_json.get('tips'):
            parts.append("\n【コツ・ポイント】")
            for t in recipe_json['tips']:
                parts.append(f"- {t}")
        return '\n'.join(parts)

    def _validate_recipe_structure(self, recipe_text: str) -> bool:
        """レシピに必須セクションが含まれているか検証"""
        has_ingredients = any(k in recipe_text
                              for k in ['【材料】', '材料', 'Ingredients'])
        has_steps = any(k in recipe_text
                        for k in ['【作り方】', '作り方', 'Steps', '手順'])
        return has_ingredients and has_steps
    
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

    def _extract_recipe_with_gemini(self, video_url: str) -> Dict[str, Any]:
        """Gemini APIを使って動画からレシピを抽出（動画アップロード対応版）"""
        temp_video_path = None
        video_file = None
        try:
            self._ensure_gemini_initialized()
            
            # プラットフォームを判定
            platform = self._detect_platform(video_url)
            
            # TikTok/InstagramはApifyでダウンロードURLを取得
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
{"dish_name": "料理名", "ingredients": ["材料1: 分量"], "steps": ["手順1"], "tips": ["コツ1"]}
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

            tokens_used = self._estimate_tokens(response)
            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': model_name,
                'tokens_used': tokens_used
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
        """TikTok/Instagramからレシピを抽出（説明欄チェック後、動画解析へ）"""
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
                    logging.info(f"Recipe found in {platform} description, refining with AI...")
                    # AIで整形
                    refined_result = self._refine_recipe_text_with_ai(recipe)
                    
                    return {
                        'recipe_text': refined_result['recipe_text'],
                        'extraction_method': 'description',
                        'ai_model': refined_result['ai_model'],
                        'tokens_used': refined_result['tokens_used']
                    }
        except Exception as e:
            logging.warning(
                f"Could not fetch {platform} description: {e}. Proceeding with video analysis."
            )

        # 説明欄にレシピがない場合、YouTubeと同様に動画解析を試みる
        logging.info(
            f"No recipe in {platform} description, attempting video analysis with Gemini..."
        )
        return self._extract_recipe_with_gemini(video_url)

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

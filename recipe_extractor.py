import os
import logging
import re
import time
import requests
from typing import Optional, Dict, Any
import google.generativeai as genai
from bs4 import BeautifulSoup

class RecipeExtractor:
    """動画からレシピを抽出するクラス"""
    
    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        
        genai.configure(api_key=self.gemini_api_key)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
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
            return self._extract_recipe_from_other_platform(video_url, platform)
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
    
    def _get_recipe_from_description(self, video_id: str) -> Optional[str]:
        """YouTube説明欄からレシピを取得"""
        if not self.youtube_api_key:
            logging.warning("YouTube API key not set, skipping description check")
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
            
            # 説明欄にレシピが含まれているか判定
            if self._contains_recipe(description):
                # レシピ部分を抽出
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
            # チャンネルIDを取得
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
            
            # コメントを取得
            comments_url = "https://www.googleapis.com/youtube/v3/commentThreads"
            params = {
                'part': 'snippet',
                'videoId': video_id,
                'maxResults': 100,
                'order': 'relevance',
                'key': self.youtube_api_key
            }
            
            response = self.session.get(comments_url, params=params, timeout=10)
            response.raise_for_status()
            comments_data = response.json()
            
            # 投稿者のコメントを探す
            for item in comments_data.get('items', []):
                comment = item['snippet']['topLevelComment']['snippet']
                author_channel_id = comment.get('authorChannelId', {}).get('value')
                
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
            '材料', 'レシピ', '作り方', '手順', 'ingredients', 'recipe',
            '調味料', '分量', 'g', 'ml', 'cc', '大さじ', '小さじ',
            '①', '②', '1.', '2.', '・'
        ]
        
        text_lower = text.lower()
        # 複数のキーワードが含まれているか
        keyword_count = sum(1 for keyword in recipe_keywords if keyword.lower() in text_lower)
        
        # 最低3つのキーワードが含まれていればレシピと判定
        return keyword_count >= 3
    
    def _extract_recipe_text(self, text: str) -> Optional[str]:
        """テキストからレシピ部分を抽出して整形"""
        # HTMLタグを除去
        text = re.sub(r'<[^>]+>', '', text)
        
        # レシピの開始位置を検出
        recipe_start_patterns = [
            r'【?材料.*?】?',
            r'【?レシピ.*?】?',
            r'【?作り方.*?】?',
            r'Ingredients:?',
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
            # 長すぎる場合は最初の2000文字のみ
            if len(recipe_text) > 2000:
                recipe_text = recipe_text[:2000] + "..."
            return recipe_text
        
        # レシピの開始位置が見つからない場合は全文を返す
        if len(text) > 2000:
            text = text[:2000] + "..."
        return text
    
    def _extract_recipe_with_gemini(self, video_url: str) -> Dict[str, Any]:
        """Gemini APIを使って動画からレシピを抽出"""
        try:
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            
            prompt = """
この動画からレシピを抽出してテキスト化してください。

以下の形式で出力してください：

【料理名】
料理の名前

【材料】
- 材料1: 分量
- 材料2: 分量
（すべての材料をリストアップ）

【作り方】
1. 手順1
2. 手順2
（すべての手順を順番に）

【コツ・ポイント】
- ポイント1
- ポイント2
（あれば記載）

レシピが複数ある場合は、それぞれ分けて記載してください。
動画にレシピが含まれていない場合は「レシピが見つかりませんでした」と返してください。
"""
            
            # YouTube URLを直接渡してGeminiに解析させる
            logging.info(f"Sending video to Gemini: {video_url}")
            response = model.generate_content([video_url, prompt])
            
            recipe_text = response.text.strip()
            
            # レシピが見つからなかった場合
            if "レシピが見つかりませんでした" in recipe_text or "レシピが含まれていない" in recipe_text:
                raise ValueError("No recipe found in the video")
            
            # トークン使用量を取得（概算）
            tokens_used = self._estimate_tokens(response)
            
            return {
                'recipe_text': recipe_text,
                'extraction_method': 'ai_video',
                'ai_model': 'gemini-2.0-flash-exp',
                'tokens_used': tokens_used
            }
            
        except Exception as e:
            logging.error(f"Error extracting recipe with Gemini: {e}")
            raise
    
    def _extract_recipe_from_other_platform(self, video_url: str, platform: str) -> Dict[str, Any]:
        """TikTok/Instagramからレシピを抽出（説明欄のみ対応）"""
        logging.info(f"Attempting to extract recipe from {platform} description...")
        
        try:
            # 説明欄を取得（スクレイピング）
            response = self.session.get(video_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # メタタグから説明を取得
            description = None
            meta_description = soup.find('meta', property='og:description')
            if meta_description and hasattr(meta_description, 'get'):
                description = meta_description.get('content', '')
            
            if description and isinstance(description, str) and self._contains_recipe(description):
                recipe = self._extract_recipe_text(description)
                if recipe:
                    return {
                        'recipe_text': recipe,
                        'extraction_method': 'description',
                        'ai_model': None,
                        'tokens_used': None
                    }
            
            # 説明欄にレシピがない場合はGeminiで動画解析
            # ただし、TikTok/InstagramのURLは直接サポートされていない可能性が高い
            logging.warning(f"{platform} video analysis with Gemini may not be supported")
            raise ValueError(f"Recipe extraction from {platform} videos via AI is not fully supported")
            
        except Exception as e:
            logging.error(f"Error extracting recipe from {platform}: {e}")
            raise
    
    def _estimate_tokens(self, response) -> int:
        """トークン使用量を推定"""
        try:
            # Geminiのレスポンスからトークン数を取得
            if hasattr(response, 'usage_metadata'):
                total_tokens = (
                    response.usage_metadata.prompt_token_count +
                    response.usage_metadata.candidates_token_count
                )
                return total_tokens
            
            # メタデータがない場合は文字数から概算
            text_length = len(response.text)
            # 日本語の場合、約1.5文字で1トークン（概算）
            return int(text_length / 1.5)
            
        except Exception as e:
            logging.warning(f"Could not estimate tokens: {e}")
            return 0
    
    def calculate_cost(self, model: str, tokens_used: int) -> float:
        """AI利用コストを計算（USD）"""
        # Gemini 2.0 Flash Experimentalの価格（2025年1月時点）
        # 入力: $0.00 / 1M tokens (無料)
        # 出力: $0.00 / 1M tokens (無料)
        # ただし将来的に有料化される可能性があるため、料金体系を定義
        
        pricing = {
            'gemini-2.0-flash-exp': {
                'input': 0.000,  # per 1K tokens
                'output': 0.000
            },
            'gemini-2.5-flash': {
                'input': 0.075 / 1000,  # $0.075 per 1M tokens
                'output': 0.30 / 1000   # $0.30 per 1M tokens
            },
            'gemini-2.5-pro': {
                'input': 1.25 / 1000,   # $1.25 per 1M tokens
                'output': 5.00 / 1000   # $5.00 per 1M tokens
            }
        }
        
        if model not in pricing:
            logging.warning(f"Unknown model {model}, using default pricing")
            return 0.0
        
        # トークンの半分が入力、半分が出力と仮定（概算）
        input_tokens = tokens_used * 0.6
        output_tokens = tokens_used * 0.4
        
        cost = (
            (input_tokens / 1000) * pricing[model]['input'] +
            (output_tokens / 1000) * pricing[model]['output']
        )
        
        return round(cost, 8)

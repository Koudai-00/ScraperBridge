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
from typing import Dict, Any, List, Optional

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 日本語対応モデル（説明欄・コメント欄からの抽出用）
# 優先順位: 1→2→3、エラー時は次のモデルへフォールバック
# 4番目はGemini APIを直接使用（gemini-2.0-flash-lite）
TEXT_MODELS = [
    "google/gemma-3-27b-it:free",           # 1位
    "google/gemma-3-12b-it:free",           # 2位
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
        self.base_url = OPENROUTER_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://replit.com",
            "X-Title": "Recipe Extractor"
        }
    
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
                    logging.warning(f"Rate limited on {model}, trying next model...")
                    last_error = f"Rate limit exceeded for {model}"
                    time.sleep(0.5)
                    continue
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", response.text)
                        error_code = error_data.get("error", {}).get("code", "unknown")
                        error_metadata = error_data.get("error", {}).get("metadata", {})
                        logging.warning(f"Error from {model} (HTTP {response.status_code}, code={error_code}): {error_msg}")
                        if error_metadata:
                            logging.warning(f"Error metadata from {model}: {error_metadata}")
                        logging.debug(f"Full error response from {model}: {error_data}")
                    except Exception:
                        error_msg = response.text
                        logging.warning(f"Error from {model} (HTTP {response.status_code}): {error_msg}")
                    last_error = error_msg
                    continue
                    
            except requests.exceptions.Timeout:
                logging.warning(f"Timeout on {model}, trying next model...")
                last_error = f"Timeout for {model}"
                continue
            except Exception as e:
                logging.warning(f"Exception with {model}: {e}")
                last_error = str(e)
                continue
        
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
{{"ingredients": ["材料1: 分量"], "steps": ["手順1"], "tips": ["コツ1"]}}

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
  "ingredients": ["材料1: 分量", "材料2: 分量"],
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


openrouter_client = OpenRouterClient()

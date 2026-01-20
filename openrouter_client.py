"""
OpenRouter API Client with automatic fallback support.
Provides access to multiple free AI models with 429 rate limit handling.
"""

import os
import logging
import requests
import time
from typing import Dict, Any, List, Optional

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

TEXT_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "deepseek/deepseek-r1-0528:free",
    "qwen/qwen3-coder:free",
    "moonshotai/kimi-k2:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-405b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-4b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "z-ai/glm-4.5-air:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "tngtech/deepseek-r1t-chimera:free",
    "tngtech/deepseek-r1t2-chimera:free",
    "tngtech/tng-r1t-chimera:free",
    "arcee-ai/trinity-mini:free",
    "mistralai/devstral-2512:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "xiaomi/mimo-v2-flash:free",
    "google/gemma-3n-e4b-it:free",
    "google/gemma-3n-e2b-it:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]

VISION_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-vl-7b-instruct:free",
    "allenai/molmo-2-8b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
]

MODELS_NEEDING_TRANSLATION = [
    "qwen/qwen-2.5-vl-7b-instruct:free",
    "allenai/molmo-2-8b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
]


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
                    error_msg = response.json().get("error", {}).get("message", response.text)
                    logging.warning(f"Error from {model}: {error_msg}")
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
        Uses vision-capable models with automatic fallback.
        
        Args:
            messages: List of message dicts, content can include image_url
            models: List of vision models to try. Defaults to VISION_MODELS.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            Dict with 'content', 'model_used', 'tokens_used', 'success', 'needs_translation'
        """
        if models is None:
            models = VISION_MODELS
        
        result = self.chat_completion(messages, models, max_tokens, temperature)
        
        if result["success"] and result["model_used"] in MODELS_NEEDING_TRANSLATION:
            result["needs_translation"] = True
        else:
            result["needs_translation"] = False
        
        return result
    
    def translate_to_japanese(self, text: str) -> Dict[str, Any]:
        """
        Translate text to Japanese using OpenRouter models.
        
        Args:
            text: Text to translate
            
        Returns:
            Dict with 'content' (translated text), 'model_used', 'success'
        """
        messages = [
            {
                "role": "system",
                "content": "あなたは優秀な翻訳者です。与えられたテキストを自然な日本語に翻訳してください。レシピの場合は、材料名や調理用語を日本語で適切に表現してください。"
            },
            {
                "role": "user",
                "content": f"以下のテキストを日本語に翻訳してください。レシピ形式を維持し、【材料】【作り方】などのセクション見出しは日本語で表記してください。\n\n{text}"
            }
        ]
        
        return self.chat_completion(messages, TEXT_MODELS[:10], max_tokens=4096, temperature=0.3)
    
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
                "role": "system",
                "content": """あなたは料理レシピの整理専門家です。与えられたテキストからレシピ情報のみを抽出し、整形してください。

以下の情報は必ず除外してください：
- BGM情報、音楽クレジット（BGM: ○○、Music by、♪、使用音源など）
- チャンネル登録やいいねのお願い
- スポンサー情報、PR、宣伝
- カメラ・編集ソフト情報
- コメント欄への誘導
- SNSリンク、ハッシュタグ
- 動画投稿者の自己紹介

レシピが含まれていない場合は、以下のJSONを返してください：
{"no_recipe": true}

レシピが含まれている場合は、以下のJSON形式で返してください：
{"dish_name": "料理名", "ingredients": ["材料1: 分量"], "steps": ["手順1"], "tips": ["コツ1"]}"""
            },
            {
                "role": "user",
                "content": raw_text
            }
        ]
        
        models = [model] if model else TEXT_MODELS
        return self.chat_completion(messages, models, max_tokens=4096, temperature=0.3)


openrouter_client = OpenRouterClient()

"""
OpenRouter API Client with automatic fallback support.
Provides access to multiple free AI models with 429 rate limit handling.

Model Priority Order:
1. Japanese-capable models (best for recipe extraction)
2. Video-capable models (for image analysis, but need translation)
3. Other models (weak Japanese support, need translation)
4. Translation reserved: google/gemma-3-27b-it:free (always last for translation fallback)
"""

import os
import logging
import requests
import time
import base64
from typing import Dict, Any, List, Optional

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ① 日本語対応可能モデル（10個）
JAPANESE_CAPABLE_MODELS = [
    "nousresearch/hermes-3-llama-3.1-405b:free",  # 1位
    "meta-llama/llama-3.1-405b-instruct:free",    # 2位
    "google/gemini-2.0-flash-exp:free",            # 3位
    "meta-llama/llama-3.3-70b-instruct:free",     # 4位
    "z-ai/glm-4.5-air:free",                       # 5位
    "deepseek/deepseek-r1-0528:free",              # 6位
    "google/gemma-3-27b-it:free",                  # 7位
    "qwen/qwen3-next-80b-a3b-instruct:free",      # 8位
    "mistralai/mistral-small-3.1-24b-instruct:free",  # 9位
    "meta-llama/llama-3.2-3b-instruct:free",      # 10位
]

# ② 動画解析可能モデル（6個）
VIDEO_CAPABLE_MODELS = [
    "google/gemini-2.0-flash-exp:free",            # ①
    "google/gemma-3-27b-it:free",                  # ②
    "qwen/qwen-2.5-vl-7b-instruct:free",          # ③
    "google/gemma-3-12b-it:free",                  # ④
    "allenai/molmo-2-8b:free",                     # ⑤
    "nvidia/nemotron-nano-12b-v2-vl:free",        # ⑥
]

# ③ その他のモデル（日本語対応が弱い - 上記に該当しなかったモデル）
OTHER_MODELS = [
    "qwen/qwen3-coder:free",
    "moonshotai/kimi-k2:free",
    "qwen/qwen3-4b:free",
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
]

# ④ 翻訳用予約（最後に配置）
TRANSLATION_MODEL = "google/gemma-3-4b-it:free"

# 統合モデルリスト（優先順位順）: ①日本語対応 → ②動画解析 → ③その他 → ④翻訳用
TEXT_MODELS = JAPANESE_CAPABLE_MODELS + VIDEO_CAPABLE_MODELS + OTHER_MODELS + [TRANSLATION_MODEL]

# ビジョンモデル（画像解析用）= 動画解析モデルと同じ
VISION_MODELS = VIDEO_CAPABLE_MODELS.copy()

# 翻訳が必要なモデル（日本語対応モデル以外すべて）
# 動画解析モデルのうち日本語対応に含まれないもの + その他のモデル
MODELS_NEEDING_TRANSLATION = [
    m for m in VIDEO_CAPABLE_MODELS if m not in JAPANESE_CAPABLE_MODELS
] + OTHER_MODELS

# すべてのモデル情報（UI表示用）
ALL_MODELS_INFO = {
    "japanese_capable": [
        {"id": m, "name": m.split("/")[1].replace(":free", ""), "category": "日本語対応"} 
        for m in JAPANESE_CAPABLE_MODELS
    ],
    "video_capable": [
        {"id": m, "name": m.split("/")[1].replace(":free", ""), "category": "動画解析可能（翻訳必要）"} 
        for m in VIDEO_CAPABLE_MODELS
    ],
    "other": [
        {"id": m, "name": m.split("/")[1].replace(":free", ""), "category": "その他（翻訳必要）"} 
        for m in OTHER_MODELS
    ],
    "translation": [
        {"id": TRANSLATION_MODEL, "name": TRANSLATION_MODEL.split("/")[1].replace(":free", ""), "category": "翻訳用予約"}
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
                "role": "system",
                "content": "あなたは優秀な翻訳者です。与えられたテキストを自然な日本語に翻訳してください。レシピの場合は、材料名や調理用語を日本語で適切に表現してください。"
            },
            {
                "role": "user",
                "content": f"以下のテキストを日本語に翻訳してください。レシピ形式を維持し、【材料】【作り方】などのセクション見出しは日本語で表記してください。\n\n{text}"
            }
        ]
        
        # 翻訳には専用の翻訳モデル（gemma-3-27b-it）を使用
        # 他のモデルが429エラーの場合でも翻訳用に予約されている
        return self.chat_completion(messages, [TRANSLATION_MODEL], max_tokens=4096, temperature=0.3)
    
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
{"ingredients": ["材料1: 分量"], "steps": ["手順1"], "tips": ["コツ1"]}"""
            },
            {
                "role": "user",
                "content": raw_text
            }
        ]
        
        models = [model] if model else TEXT_MODELS
        return self.chat_completion(messages, models, max_tokens=4096, temperature=0.3)
    
    def analyze_video(self, video_path: str, prompt: str, 
                      models: Optional[List[str]] = None,
                      max_tokens: int = 4096,
                      temperature: float = 0.7) -> Dict[str, Any]:
        """
        Analyze a video file using OpenRouter's video-capable models.
        Video is sent as Base64 encoded data URL.
        
        Args:
            video_path: Path to the local video file
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
        
        try:
            with open(video_path, 'rb') as f:
                video_data = f.read()
            base64_video = base64.b64encode(video_data).decode('utf-8')
            
            ext = video_path.split('.')[-1].lower()
            mime_types = {
                'mp4': 'video/mp4',
                'mpeg': 'video/mpeg',
                'mov': 'video/mov',
                'webm': 'video/webm',
            }
            mime_type = mime_types.get(ext, 'video/mp4')
            
            video_data_url = f"data:{mime_type};base64,{base64_video}"
            
            logging.info(f"Video file encoded to Base64 (size: {len(base64_video)} chars)")
            
        except Exception as e:
            logging.error(f"Failed to encode video file: {e}")
            return {
                "success": False,
                "content": None,
                "model_used": None,
                "error": f"Failed to encode video: {str(e)}",
                "tokens_used": 0,
            }
        
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
                            "url": video_data_url
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
                    
                    needs_translation = model in MODELS_NEEDING_TRANSLATION
                    
                    return {
                        "success": True,
                        "content": content,
                        "model_used": model,
                        "tokens_used": usage.get("total_tokens", 0),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "needs_translation": needs_translation,
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
    
    def extract_recipe_from_video(self, video_path: str, 
                                   models: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Extract recipe information from a cooking video using OpenRouter.
        
        Args:
            video_path: Path to the local video file
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

        result = self.analyze_video(video_path, prompt, models, max_tokens=4096, temperature=0.3)
        
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

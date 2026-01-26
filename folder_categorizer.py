import logging
import json
import re
from typing import List, Dict, Any, Optional
from openrouter_client import openrouter_client, TEXT_MODELS

class FolderCategorizer:
    """
    動画のメタデータ（タイトル、説明文）に基づいて、
    ユーザーの既存フォルダから最適なものを提案するクラス。
    """

    def __init__(self):
        self.ai_client = openrouter_client

    def suggest_folder(self, 
                       video_title: str, 
                       video_description: str, 
                       current_folders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        動画に最適なフォルダを提案する。

        Args:
            video_title: 動画のタイトル
            video_description: 動画の説明文
            current_folders: ユーザーの現在のフォルダリスト
                             [{"id": "f_001", "name": "和食"}, ...]

        Returns:
            Dict: {
                "success": bool,
                "suggested_folder_id": str or None,
                "reason": str
            }
        """
        if not current_folders:
            return {
                "success": True,
                "suggested_folder_id": None,
                "reason": "フォルダが存在しません。"
            }

        # プロンプトの構築
        folders_text = json.dumps(current_folders, ensure_ascii=False, indent=2)
        
        prompt = f"""
あなたは料理動画の整理アシスタントです。
以下の「動画情報」に基づいて、「既存フォルダリスト」の中からこの動画を保存するのに最も適したフォルダを1つ選んでください。

【動画情報】
タイトル: {video_title}
説明文: {video_description[:1000]}... (以下省略)

【既存フォルダリスト】
{folders_text}

【判断基準】
1. **タイトルを最優先**して判断してください。説明文は補足として扱いますが、プロモーションや宣伝、無関係なキーワードは無視してください。
2. 明確に適したフォルダがある場合のみ、その `id` を返してください。
3. どのフォルダにも当てはまらない、または判断に迷う場合は `null` を選択してください。
4. 既存フォルダにない新しいカテゴリを作る必要はありません。

【回答形式】
以下のJSON形式のみで回答してください。余計な解説は不要です。
{{
  "suggested_folder_id": "フォルダID" または null,
  "reason": "選択理由（簡潔に）"
}}
"""
        
        # AIモデルを使用して推論
        # openrouter_clientのchat_completionを使用して、OpenRouter -> Geminiのフォールバックを利用
        messages = [
            {"role": "system", "content": "あなたはJSON形式で応答するAIアシスタントです。"},
            {"role": "user", "content": prompt}
        ]

        try:
            # TEXT_MODELSの優先順位で実行（自動フォールバック付き）
            result = self.ai_client.chat_completion(
                messages=messages,
                models=TEXT_MODELS,
                temperature=0.3, # 決定論的な結果を好むため低めに設定
                max_tokens=500
            )

            if not result.get("success"):
                logging.error(f"AI folder suggestion failed: {result.get('error')}")
                # AI処理失敗時はGemini APIへ直接フォールバックを試みる（openrouter_clientにはないロジックだが念のため）
                # ただしopenrouter_client側ですでにGemini APIへのフォールバックが含まれている設計であれば不要
                # 今回はopenrouter_clientの実装に依存する
                return {
                    "success": False,
                    "suggested_folder_id": None,
                    "reason": f"AI処理エラー: {result.get('error')}"
                }

            response_content = result.get("content", "").strip()
            
            # JSONパース
            try:
                # コードブロック除去
                json_text = re.sub(r'^```json\s*|\s*```$', '', response_content, flags=re.MULTILINE).strip()
                parsed_json = json.loads(json_text)
                
                return {
                    "success": True,
                    "suggested_folder_id": parsed_json.get("suggested_folder_id"),
                    "reason": parsed_json.get("reason", "AIによる判定")
                }

            except json.JSONDecodeError as e:
                logging.error(f"JSON parse error in folder suggestion: {e}, Content: {response_content}")
                return {
                    "success": False,
                    "suggested_folder_id": None,
                    "reason": "AIの応答形式が不正でした。"
                }

        except Exception as e:
            logging.error(f"Unexpected error in folder suggestion: {e}")
            return {
                "success": False,
                "suggested_folder_id": None,
                "reason": f"システムエラー: {str(e)}"
            }

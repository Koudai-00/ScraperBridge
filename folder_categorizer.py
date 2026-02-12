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

    def suggest_folders_batch(self, 
                              videos: List[Dict[str, Any]], 
                              current_folders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        複数の動画に対して最適なフォルダを一括提案する。
        AIへのリクエストは適切なバッチサイズ（5件）に分割して実行される。

        Args:
            videos: 動画リスト [{"id": "vid1", "title": "...", "description": "..."}, ...]
            current_folders: フォルダリスト [{"id": "f_001", "name": "和食"}, ...]

        Returns:
            Dict: {
                "success": True,
                "results": [
                    { "video_id": "vid1", "suggested_folder_id": "f_001", "reason": "..." },
                    ...
                ]
            }
        """
        if not videos:
            return {"success": False, "error": "動画リストが空です。", "results": []}
            
        if not current_folders:
            # フォルダがない場合は全てnullで返す
            results = []
            for video in videos:
                results.append({
                    "video_id": video.get("id"),
                    "suggested_folder_id": None,
                    "reason": "フォルダが存在しません。"
                })
            return {"success": True, "results": results}

        # 未分類フォルダのIDを探す
        uncategorized_id = None
        for f in current_folders:
            if f.get("name") == "未分類":
                uncategorized_id = f.get("id")
                break

        folders_text = json.dumps(current_folders, ensure_ascii=False, indent=2)
        batch_size = 20
        all_results = []
        
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def process_batch(batch_videos):
            """1つのバッチを処理する内部関数"""
            batch_results_list = []
            
            # 動画リストのテキスト化
            videos_text_list = []
            for v in batch_videos:
                videos_text_list.append(f"""
- ID: {v.get("id")}
  タイトル: {v.get("title")}
""")
            videos_text = "\n".join(videos_text_list)
            
            prompt = f"""
あなたは料理動画の整理アシスタントです。
以下の「動画リスト」の各動画について、「既存フォルダリスト」の中から最も適したフォルダを選んでください。

【既存フォルダリスト】
{folders_text}

【動画リスト】
{videos_text}

【判断基準】
1. **タイトルを最優先**して判断してください。
2. 明確に適したフォルダがある場合のみ、その `id` を返してください。
3. どのフォルダにも当てはまらない、または判断に迷う場合は `null` (PythonのNone) を選択してください。

【回答形式】
以下のJSON配列形式「のみ」で回答してください。
[
  {{
    "video_id": "動画ID",
    "suggested_folder_id": "フォルダID" または null,
    "reason": "選択理由（簡潔に）"
  }},
  ...
]
"""
            try:
                messages = [
                    {"role": "system", "content": "あなたはJSON形式で応答するAIアシスタントです。"},
                    {"role": "user", "content": prompt}
                ]
                
                # 並列実行時はOpenRouterのレートリミットに注意が必要だが、
                # Gemini Flash Liteなどは比較的高速かつリミットが高いため5並列程度なら許容範囲内と想定
                result = self.ai_client.chat_completion(
                    messages=messages,
                    models=TEXT_MODELS,
                    temperature=0.3,
                    max_tokens=4000
                )
                
                if not result.get("success"):
                    logging.error(f"Batch suggestion failed: {result.get('error')}")
                    for v in batch_videos:
                        batch_results_list.append({
                            "video_id": v.get("id"),
                            "suggested_folder_id": None,
                            "reason": f"AI処理エラー: {result.get('error')}"
                        })
                    return batch_results_list

                response_content = result.get("content", "").strip()
                
                # JSONパース
                json_text = re.sub(r'^```json\s*|\s*```$', '', response_content, flags=re.MULTILINE).strip()
                batch_results = json.loads(json_text)
                
                if isinstance(batch_results, list):
                    result_map = {res.get("video_id"): res for res in batch_results}
                    
                    for v in batch_videos:
                        vid = v.get("id")
                        if vid in result_map:
                            res = result_map[vid]
                            s_id = res.get("suggested_folder_id")
                            reason = res.get("reason", "AIによる判定")
                            
                            # 未分類フォールバック
                            if s_id is None and uncategorized_id:
                                s_id = uncategorized_id
                                reason = "適切なフォルダが見つからなかったため、未分類フォルダを選択しました。"
                                
                            batch_results_list.append({
                                "video_id": vid,
                                "suggested_folder_id": s_id,
                                "reason": reason
                            })
                        else:
                            # 欠落時の未分類フォールバック
                            s_id = uncategorized_id if uncategorized_id else None
                            reason = "AIがこの動画の判定をスキップしました。"
                            if s_id:
                                reason = "AI判定がスキップされたため、未分類フォルダを選択しました。"
                                
                            batch_results_list.append({
                                "video_id": vid,
                                "suggested_folder_id": s_id,
                                "reason": reason
                            })
                else:
                    logging.error(f"AI returned invalid JSON format: {response_content}")
                    for v in batch_videos:
                        batch_results_list.append({
                            "video_id": v.get("id"),
                            "suggested_folder_id": None,
                            "reason": "AIの応答形式が不正でした。"
                        })
                        
            except Exception as e:
                logging.error(f"Error in batch processing: {e}")
                for v in batch_videos:
                    batch_results_list.append({
                        "video_id": v.get("id"),
                        "suggested_folder_id": None,
                        "reason": f"システムエラー: {str(e)}"
                    })
            
            return batch_results_list

        # ThreadPoolExecutorによる並列実行
        # max_workers=5: 5バッチ（最大25動画）まで同時並行で処理
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(0, len(videos), batch_size):
                batch_videos = videos[i:i + batch_size]
                futures.append(executor.submit(process_batch, batch_videos))
            
            for future in as_completed(futures):
                try:
                    all_results.extend(future.result())
                except Exception as e:
                    logging.error(f"Batch execution failed: {e}")
        
        return {
            "success": True,
            "results": all_results
        }

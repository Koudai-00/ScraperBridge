import os
import logging
import psycopg2
from typing import List, Dict, Any, Optional
from openrouter_client import openrouter_client

class ShoppingManager:
    """買い物リスト・食材管理機能のビジネスロジック"""

    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        
    def get_db_connection(self):
        return psycopg2.connect(self.db_url)

    def get_all_categories(self) -> List[Dict[str, Any]]:
        """
        データベースから全カテゴリを取得
        Returns:
            List[Dict]: [{'id': 1, 'name': '野菜'}, ...]
        """
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name FROM categories ORDER BY id")
                    results = cur.fetchall()
                    return [{'id': row[0], 'name': row[1]} for row in results]
        except Exception as e:
            logging.error(f"Error fetching categories: {e}")
            return []

    def get_master_names_by_category(self, category_id: int) -> List[str]:
        """
        指定されたカテゴリIDに紐づく全ての代表名を取得
        """
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT master_name FROM ingredient_master WHERE category_id = %s",
                        (category_id,)
                    )
                    results = cur.fetchall()
                    return [row[0] for row in results]
        except Exception as e:
            logging.error(f"Error fetching master names for category {category_id}: {e}")
            return []

    def check_and_resolve_ingredients(self, ingredient_names: List[str]) -> List[Dict[str, Any]]:
        """
        食材名のリストを受け取り、カテゴリ判定と代表名解決を行って結果を返す
        """
        results = []
        
        # 1. カテゴリ一覧を取得（AIプロンプト用）
        categories = self.get_all_categories()
        if not categories:
            logging.error("No categories found in database")
            # カテゴリがない場合は処理できないが、エラーとして空で返すか、適宜ハンドリング
            return []

        for name in ingredient_names:
            try:
                # 2. AIによるカテゴリ判定
                category_id = openrouter_client.categorize_ingredient(name, categories)
                
                if category_id is None:
                    logging.warning(f"Failed to categorize ingredient: {name}")
                    # デフォルト処理（その他など）またはエラーフラグ
                    results.append({
                        "ingredient_name": name,
                        "category_id": None,
                        "category_name": "不明",
                        "master_name": name,
                        "is_new": True,
                        "error": "Categorization failed"
                    })
                    continue

                # カテゴリ名を取得
                category_name = next((c['name'] for c in categories if c['id'] == category_id), "不明")

                # 3. 該当カテゴリの既存代表名リストを取得
                existing_masters = self.get_master_names_by_category(category_id)
                
                # 4. AIによる代表名生成・照合
                master_name, is_new_master = openrouter_client.generate_master_name(
                    name, category_id, existing_masters
                )

                results.append({
                    "ingredient_name": name,
                    "category_id": category_id,
                    "category_name": category_name,
                    "master_name": master_name,
                    "is_new": is_new_master # True: 新規, False: 既存一致
                })


            except Exception as e:
                logging.error(f"Error processing ingredient {name}: {e}")
                results.append({
                    "ingredient_name": name,
                    "error": str(e)
                })

        return results

shopping_manager = ShoppingManager()

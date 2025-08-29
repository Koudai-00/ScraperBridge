import os
import logging
import psycopg2
import requests
from typing import Dict, List, Set
from datetime import datetime, timedelta

class MetadataUpdater:
    """メタデータ更新を管理するクラス"""
    
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.batch_api_url = "http://localhost:5000/api/batch-metadata"
        self.max_age_days = 7  # メタデータの有効期限（日）
        
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")
    
    def get_db_connection(self):
        """データベース接続を取得"""
        return psycopg2.connect(self.database_url)
    
    def get_metadata_from_videos_table(self, video_ids: List[str]) -> Dict[str, dict]:
        """videosテーブルから既存メタデータを取得"""
        if not video_ids:
            return {}
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # IN句用のプレースホルダーを作成
                    placeholders = ','.join(['%s'] * len(video_ids))
                    query = f"""
                    SELECT 
                        unique_video_id,
                        source as platform,
                        video_title as title,
                        video_author_icon_url as thumbnail_url,
                        video_author_name as author_name,
                        created_at as metadata_fetched_at
                    FROM videos 
                    WHERE unique_video_id IN ({placeholders})
                    """
                    
                    cur.execute(query, video_ids)
                    results = cur.fetchall()
                    
                    metadata_dict = {}
                    for row in results:
                        video_id, platform, title, thumbnail_url, author_name, fetched_at = row
                        metadata_dict[video_id] = {
                            'platform': platform,
                            'title': title,
                            'thumbnailUrl': thumbnail_url,
                            'authorName': author_name,
                            'metadata_fetched_at': fetched_at,
                            'unique_video_id': video_id
                        }
                    
                    logging.info(f"Retrieved metadata for {len(metadata_dict)} videos from database")
                    return metadata_dict
                    
        except Exception as e:
            logging.error(f"Error retrieving metadata from database: {e}")
            return {}
    
    def identify_stale_metadata(self, video_metadata: Dict[str, dict]) -> Set[str]:
        """古いメタデータを特定"""
        stale_ids = set()
        cutoff_date = datetime.now()
        
        for video_id, metadata in video_metadata.items():
            fetched_at = metadata.get('metadata_fetched_at')
            # タイムゾーン問題を回避するため、常に新しいものとして扱う
            if not fetched_at:
                stale_ids.add(video_id)
        
        logging.info(f"Identified {len(stale_ids)} stale metadata entries")
        return stale_ids
    
    def construct_urls_from_ids(self, video_ids: Set[str]) -> List[str]:
        """ビデオIDからURL構築（プラットフォーム情報が必要な場合）"""
        urls = []
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    placeholders = ','.join(['%s'] * len(video_ids))
                    query = f"""
                    SELECT unique_video_id, source as platform 
                    FROM videos 
                    WHERE unique_video_id IN ({placeholders})
                    """
                    
                    cur.execute(query, list(video_ids))
                    results = cur.fetchall()
                    
                    for video_id, platform in results:
                        url = self._construct_url(video_id, platform)
                        if url:
                            urls.append(url)
                    
                    logging.info(f"Constructed {len(urls)} URLs from video IDs")
                    return urls
                    
        except Exception as e:
            logging.error(f"Error constructing URLs from IDs: {e}")
            return []
    
    def _construct_url(self, video_id: str, platform: str) -> str:
        """プラットフォーム別URL構築"""
        url_templates = {
            'youtube': f'https://www.youtube.com/watch?v={video_id}',
            'tiktok': f'https://www.tiktok.com/@user/video/{video_id}',
            'instagram': f'https://www.instagram.com/p/{video_id}/'
        }
        
        return url_templates.get(platform, '')
    
    def fetch_fresh_metadata_batch(self, urls: List[str]) -> Dict[str, dict]:
        """バッチAPIで最新メタデータを取得"""
        if not urls:
            return {}
        
        try:
            # バッチサイズで分割（50件ずつ）
            batch_size = 50
            all_metadata = {}
            
            for i in range(0, len(urls), batch_size):
                batch_urls = urls[i:i + batch_size]
                
                payload = {"urls": batch_urls}
                response = requests.post(
                    self.batch_api_url,
                    json=payload,
                    timeout=120  # 2分タイムアウト
                )
                
                if response.status_code == 200:
                    data = response.json()
                    for result in data.get('results', []):
                        if result.get('success'):
                            video_data = result.get('data', {})
                            video_id = video_data.get('unique_video_id')
                            if video_id:
                                all_metadata[video_id] = video_data
                else:
                    logging.warning(f"Batch API returned status {response.status_code}")
            
            logging.info(f"Fetched fresh metadata for {len(all_metadata)} videos")
            return all_metadata
            
        except Exception as e:
            logging.error(f"Error fetching fresh metadata: {e}")
            return {}
    
    def update_videos_cache(self, metadata_batch: Dict[str, dict]):
        """videosテーブルのメタデータキャッシュを更新"""
        if not metadata_batch:
            return
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    for video_id, metadata in metadata_batch.items():
                        cur.execute("""
                            UPDATE videos SET
                                video_title = %s,
                                video_author_name = %s,
                                video_author_icon_url = %s
                            WHERE unique_video_id = %s
                        """, (
                            metadata.get('title'),
                            metadata.get('authorName'),
                            metadata.get('thumbnailUrl'),
                            video_id
                        ))
                    
                    conn.commit()
                    logging.info(f"Updated metadata cache for {len(metadata_batch)} videos")
                    
        except Exception as e:
            logging.error(f"Error updating videos cache: {e}")
    
    def get_complete_metadata_for_rankings(self, ranking_data: Dict[str, List]) -> Dict[str, dict]:
        """ランキング用の完全なメタデータを取得"""
        # 全期間のユニークビデオIDを収集
        all_video_ids = set()
        for period_rankings in ranking_data.values():
            for video_id, count in period_rankings:
                all_video_ids.add(video_id)
        
        all_video_ids_list = list(all_video_ids)
        logging.info(f"Processing metadata for {len(all_video_ids_list)} unique videos")
        
        # 既存メタデータを取得
        existing_metadata = self.get_metadata_from_videos_table(all_video_ids_list)
        
        # 古いまたは不足しているメタデータを特定
        missing_ids = all_video_ids - set(existing_metadata.keys())
        stale_ids = self.identify_stale_metadata(existing_metadata)
        refresh_needed = missing_ids | stale_ids
        
        logging.info(f"Missing: {len(missing_ids)}, Stale: {len(stale_ids)}, Total refresh needed: {len(refresh_needed)}")
        
        # 必要に応じて最新データを取得
        if refresh_needed:
            urls = self.construct_urls_from_ids(refresh_needed)
            fresh_metadata = self.fetch_fresh_metadata_batch(urls)
            
            # キャッシュを更新
            self.update_videos_cache(fresh_metadata)
            
            # 結果をマージ
            existing_metadata.update(fresh_metadata)
        
        return existing_metadata
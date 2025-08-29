import os
import logging
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from urllib.parse import urlparse

class RankingCalculator:
    """ランキング計算を行うクラス"""
    
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")
    
    def get_db_connection(self):
        """データベース接続を取得"""
        return psycopg2.connect(self.database_url)
    
    def calculate_rankings_by_period(self, period_type: str = "daily", limit: int = 100) -> List[Tuple[str, int]]:
        """
        期間別ランキングを計算
        
        Args:
            period_type: 'daily', 'weekly', 'monthly', 'all_time'
            limit: 取得する上位件数
            
        Returns:
            List[(unique_video_id, count), ...] ランキング順
        """
        # 期間の計算
        date_filter = self._get_date_filter(period_type)
        
        query = """
        SELECT 
            unique_video_id,
            COUNT(*) as video_count,
            platform
        FROM videos 
        WHERE 1=1 {}
        GROUP BY unique_video_id, platform
        ORDER BY video_count DESC, unique_video_id
        LIMIT %s
        """.format(date_filter)
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    if period_type == "all_time":
                        cur.execute(query, (limit,))
                    else:
                        days = self._get_period_days(period_type)
                        date_threshold = datetime.now() - timedelta(days=days)
                        cur.execute(query, (date_threshold, limit))
                    
                    results = cur.fetchall()
                    logging.info(f"Calculated {len(results)} rankings for period: {period_type}")
                    
                    return [(row[0], row[1]) for row in results]  # (unique_video_id, count)
                    
        except Exception as e:
            logging.error(f"Error calculating rankings: {e}")
            return []
    
    def _get_date_filter(self, period_type: str) -> str:
        """期間フィルタのSQL条件を生成"""
        if period_type == "all_time":
            return ""
        else:
            return "AND created_at >= %s"
    
    def _get_period_days(self, period_type: str) -> int:
        """期間タイプから日数を取得"""
        period_map = {
            "daily": 1,
            "weekly": 7,
            "monthly": 30
        }
        return period_map.get(period_type, 1)
    
    def get_top_video_ids_by_periods(self, limit: int = 100) -> Dict[str, List[Tuple[str, int]]]:
        """全期間タイプのランキングを一括取得"""
        periods = ["daily", "weekly", "monthly", "all_time"]
        results = {}
        
        for period in periods:
            try:
                rankings = self.calculate_rankings_by_period(period, limit)
                results[period] = rankings
                logging.info(f"Period {period}: {len(rankings)} items")
            except Exception as e:
                logging.error(f"Failed to calculate {period} rankings: {e}")
                results[period] = []
        
        return results
    
    def create_sample_data(self, count: int = 50):
        """テスト用のサンプルデータを作成"""
        sample_videos = [
            ('dQw4w9WgXcQ', 'youtube', 'Rick Astley - Never Gonna Give You Up', 'Rick Astley'),
            ('9bZkp7q19f0', 'youtube', 'PSY - GANGNAM STYLE', 'officialpsy'),
            ('7529453361708518674', 'tiktok', 'MV Dance Video', 'GINTA OFFICIAL'),
            ('7528376512286854408', 'tiktok', 'Japanese Food Video', 'Food Channel'),
            ('DM8vWoFTYSZ', 'instagram', 'Cooking Video Recipe', 'Mizuki'),
        ]
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # 既存のサンプルデータをクリア
                    cur.execute("DELETE FROM videos WHERE author_name IN ('Rick Astley', 'officialpsy', 'GINTA OFFICIAL', '千葉うまグルメ', 'Mizuki')")
                    
                    # サンプルデータを複数回挿入してランキングを作成
                    for i in range(count):
                        for video_id, platform, title, author in sample_videos:
                            # 各動画を異なる回数挿入してランキングを作成
                            insert_count = hash(video_id + str(i)) % 10 + 1  # 1-10回のランダム挿入
                            for _ in range(insert_count):
                                cur.execute("""
                                    INSERT INTO videos (unique_video_id, platform, title, author_name, created_at)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON CONFLICT (unique_video_id) DO NOTHING
                                """, (
                                    f"{video_id}_{i}_{_}", 
                                    platform, 
                                    f"{title} #{i+1}", 
                                    author,
                                    datetime.now() - timedelta(days=i % 30)  # 過去30日間に分散
                                ))
                    
                    conn.commit()
                    logging.info(f"Created sample data: {count} video variations")
                    
        except Exception as e:
            logging.error(f"Error creating sample data: {e}")
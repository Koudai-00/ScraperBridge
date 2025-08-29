import os
import logging
import psycopg2
from datetime import datetime
from typing import Dict, List
from ranking_calculator import RankingCalculator
from metadata_updater import MetadataUpdater

class BatchProcessor:
    """メインのバッチ処理を管理するクラス"""
    
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.ranking_calculator = RankingCalculator()
        self.metadata_updater = MetadataUpdater()
        
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        # ログ設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def get_db_connection(self):
        """データベース接続を取得"""
        return psycopg2.connect(self.database_url)
    
    def run_daily_ranking_batch(self):
        """毎日実行されるメインバッチ処理"""
        start_time = datetime.now()
        logging.info("Starting daily ranking batch process")
        
        try:
            # Step 1: 全期間のランキングを計算
            logging.info("Step 1: Calculating rankings for all periods")
            ranking_data = self.ranking_calculator.get_top_video_ids_by_periods(limit=100)
            
            if not any(ranking_data.values()):
                logging.warning("No ranking data calculated - skipping batch process")
                return False
            
            # Step 2: 必要なメタデータを取得・更新
            logging.info("Step 2: Fetching and updating metadata")
            complete_metadata = self.metadata_updater.get_complete_metadata_for_rankings(ranking_data)
            
            # Step 3: ランキングテーブルを更新（ゼロダウンタイムで）
            logging.info("Step 3: Updating rankings table")
            success = self.update_rankings_table_atomic(ranking_data, complete_metadata)
            
            if success:
                elapsed_time = (datetime.now() - start_time).total_seconds()
                logging.info(f"Daily ranking batch completed successfully in {elapsed_time:.2f} seconds")
                return True
            else:
                logging.error("Failed to update rankings table")
                return False
                
        except Exception as e:
            logging.error(f"Error in daily ranking batch: {e}")
            return False
    
    def update_rankings_table_atomic(self, ranking_data: Dict[str, List], metadata: Dict[str, dict]) -> bool:
        """ランキングテーブルをアトミックに更新（ゼロダウンタイム）"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # トランザクション開始
                    conn.autocommit = False
                    
                    # 新しいランキングデータをテンポラリテーブルに作成
                    cur.execute("DROP TABLE IF EXISTS rankings_temp")
                    
                    cur.execute("""
                        CREATE TABLE rankings_temp (
                            id SERIAL PRIMARY KEY,
                            unique_video_id VARCHAR(50) NOT NULL,
                            platform VARCHAR(20) NOT NULL,
                            rank_position INTEGER NOT NULL,
                            period_type VARCHAR(10) NOT NULL,
                            count INTEGER NOT NULL,
                            title TEXT,
                            thumbnail_url TEXT,
                            author_name TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            
                            UNIQUE(unique_video_id, period_type)
                        )
                    """)
                    
                    # インデックス作成（IF NOT EXISTSで重複エラー回避）
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_rankings_temp_period_rank ON rankings_temp(period_type, rank_position)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_rankings_temp_video_id ON rankings_temp(unique_video_id)")
                    
                    # 新しいランキングデータを挿入
                    total_inserted = 0
                    for period_type, rankings in ranking_data.items():
                        for rank_position, (video_id, count) in enumerate(rankings, 1):
                            video_metadata = metadata.get(video_id, {})
                            
                            cur.execute("""
                                INSERT INTO rankings_temp (
                                    unique_video_id,
                                    platform,
                                    rank_position,
                                    period_type,
                                    count,
                                    title,
                                    thumbnail_url,
                                    author_name
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                video_id,
                                video_metadata.get('platform', 'unknown'),
                                rank_position,
                                period_type,
                                count,
                                video_metadata.get('title'),
                                video_metadata.get('thumbnailUrl'),
                                video_metadata.get('authorName')
                            ))
                            total_inserted += 1
                    
                    logging.info(f"Inserted {total_inserted} ranking entries into temp table")
                    
                    # 古いテーブルをバックアップに移動し、新しいテーブルを本テーブルに昇格
                    cur.execute("DROP TABLE IF EXISTS rankings_old")
                    
                    # rankingsテーブルが存在する場合はrankings_oldにリネーム
                    cur.execute("""
                        DO $$
                        BEGIN
                            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'rankings') THEN
                                ALTER TABLE rankings RENAME TO rankings_old;
                            END IF;
                        END
                        $$
                    """)
                    
                    # テンポラリテーブルを本テーブルに昇格
                    cur.execute("ALTER TABLE rankings_temp RENAME TO rankings")
                    
                    # コミット
                    conn.commit()
                    logging.info("Successfully updated rankings table with zero downtime")
                    
                    return True
                    
        except Exception as e:
            logging.error(f"Error updating rankings table atomically: {e}")
            try:
                conn.rollback()
                logging.info("Transaction rolled back")
            except:
                pass
            return False
    
    def get_ranking_stats(self) -> Dict:
        """ランキングの統計情報を取得"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # 期間別の件数
                    cur.execute("""
                        SELECT 
                            period_type,
                            COUNT(*) as count,
                            MAX(updated_at) as last_updated
                        FROM rankings 
                        GROUP BY period_type
                        ORDER BY period_type
                    """)
                    
                    period_stats = {}
                    for period_type, count, last_updated in cur.fetchall():
                        period_stats[period_type] = {
                            'count': count,
                            'last_updated': last_updated.isoformat() if last_updated else None
                        }
                    
                    # プラットフォーム別の件数
                    cur.execute("""
                        SELECT 
                            platform,
                            COUNT(*) as count
                        FROM rankings 
                        GROUP BY platform
                        ORDER BY count DESC
                    """)
                    
                    platform_stats = {}
                    for platform, count in cur.fetchall():
                        platform_stats[platform] = count
                    
                    return {
                        'periods': period_stats,
                        'platforms': platform_stats,
                        'total_rankings': sum(period_stats[p]['count'] for p in period_stats)
                    }
                    
        except Exception as e:
            logging.error(f"Error getting ranking stats: {e}")
            return {}
    
    def create_test_data_and_run_sample(self):
        """テスト用データを作成してサンプル実行"""
        try:
            # サンプルデータ作成
            logging.info("Creating sample data for testing...")
            self.ranking_calculator.create_sample_data(count=20)
            
            # サンプルバッチ実行
            logging.info("Running sample ranking batch...")
            success = self.run_daily_ranking_batch()
            
            if success:
                # 統計表示
                stats = self.get_ranking_stats()
                logging.info(f"Ranking stats: {stats}")
                return True
            else:
                logging.error("Sample batch run failed")
                return False
                
        except Exception as e:
            logging.error(f"Error in test data creation and sample run: {e}")
            return False
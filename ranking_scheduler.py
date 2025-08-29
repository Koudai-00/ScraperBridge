import os
import logging
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from batch_processor import BatchProcessor

class RankingScheduler:
    """ランキング更新の定時実行を管理するクラス"""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.batch_processor = BatchProcessor()
        
        # ログ設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
    def setup_daily_job(self, hour: int = 2, minute: int = 0):
        """毎日定時実行のジョブを設定"""
        try:
            # 既存のジョブがある場合は削除
            if self.scheduler.get_job('daily_ranking_job'):
                self.scheduler.remove_job('daily_ranking_job')
            
            # 毎日指定時刻に実行するジョブを追加
            self.scheduler.add_job(
                func=self.run_daily_ranking_job,
                trigger=CronTrigger(hour=hour, minute=minute),
                id='daily_ranking_job',
                name='Daily Ranking Update Job',
                replace_existing=True,
                max_instances=1,  # 同時実行を防ぐ
                misfire_grace_time=3600  # 1時間の猶予時間
            )
            
            logging.info(f"Scheduled daily ranking job at {hour:02d}:{minute:02d}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to setup daily job: {e}")
            return False
    
    def setup_test_job(self, interval_minutes: int = 5):
        """テスト用の定期実行ジョブを設定"""
        try:
            # 既存のテストジョブがある場合は削除
            if self.scheduler.get_job('test_ranking_job'):
                self.scheduler.remove_job('test_ranking_job')
            
            # テスト用の定期実行ジョブを追加
            self.scheduler.add_job(
                func=self.run_test_ranking_job,
                trigger='interval',
                minutes=interval_minutes,
                id='test_ranking_job',
                name='Test Ranking Update Job',
                replace_existing=True,
                max_instances=1
            )
            
            logging.info(f"Scheduled test ranking job every {interval_minutes} minutes")
            return True
            
        except Exception as e:
            logging.error(f"Failed to setup test job: {e}")
            return False
    
    def run_daily_ranking_job(self):
        """毎日のランキング更新ジョブ実行"""
        job_name = "Daily Ranking Update"
        logging.info(f"Starting {job_name}")
        
        try:
            success = self.batch_processor.run_daily_ranking_batch()
            
            if success:
                logging.info(f"{job_name} completed successfully")
                
                # 統計情報をログに出力
                stats = self.batch_processor.get_ranking_stats()
                logging.info(f"Ranking statistics: {stats}")
            else:
                logging.error(f"{job_name} failed")
                
        except Exception as e:
            logging.error(f"Error in {job_name}: {e}")
    
    def run_test_ranking_job(self):
        """テスト用のランキング更新ジョブ実行"""
        job_name = "Test Ranking Update"
        logging.info(f"Starting {job_name}")
        
        try:
            # テスト用のデータ作成も含めて実行
            success = self.batch_processor.create_test_data_and_run_sample()
            
            if success:
                logging.info(f"{job_name} completed successfully")
            else:
                logging.error(f"{job_name} failed")
                
        except Exception as e:
            logging.error(f"Error in {job_name}: {e}")
    
    def start_scheduler(self):
        """スケジューラを開始"""
        try:
            if not self.scheduler.running:
                self.scheduler.start()
                logging.info("Ranking scheduler started")
                
                # アプリケーション終了時にスケジューラも停止
                atexit.register(lambda: self.shutdown_scheduler())
                return True
            else:
                logging.warning("Scheduler is already running")
                return True
                
        except Exception as e:
            logging.error(f"Failed to start scheduler: {e}")
            return False
    
    def shutdown_scheduler(self):
        """スケジューラを停止"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
                logging.info("Ranking scheduler shut down")
        except Exception as e:
            logging.error(f"Error shutting down scheduler: {e}")
    
    def get_job_status(self) -> dict:
        """実行中のジョブ状態を取得"""
        jobs_info = {}
        
        try:
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                jobs_info[job.id] = {
                    'name': job.name,
                    'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger),
                    'max_instances': job.max_instances
                }
                
        except Exception as e:
            logging.error(f"Error getting job status: {e}")
        
        return {
            'scheduler_running': self.scheduler.running,
            'jobs': jobs_info
        }
    
    def run_manual_update(self):
        """手動でランキング更新を実行"""
        logging.info("Manual ranking update requested")
        
        try:
            success = self.batch_processor.run_daily_ranking_batch()
            
            if success:
                stats = self.batch_processor.get_ranking_stats()
                logging.info("Manual ranking update completed successfully")
                return {
                    'success': True,
                    'message': 'Ranking update completed successfully',
                    'stats': stats
                }
            else:
                return {
                    'success': False,
                    'message': 'Ranking update failed'
                }
                
        except Exception as e:
            logging.error(f"Error in manual ranking update: {e}")
            return {
                'success': False,
                'message': f'Error: {str(e)}'
            }
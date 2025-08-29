import os
import logging
from flask import Flask
from flask_cors import CORS

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Enable CORS for API endpoints
CORS(app, origins="*", allow_headers=["*"], methods=["*"])

# Initialize and start ranking scheduler
try:
    from ranking_scheduler import RankingScheduler
    
    ranking_scheduler = RankingScheduler()
    
    # 本番環境では毎日午前2時に実行、開発環境では5分間隔のテストモードで実行
    if os.getenv('FLASK_ENV') == 'production':
        ranking_scheduler.setup_daily_job(hour=2, minute=0)
        logging.info("Ranking scheduler set up for production (daily at 2:00 AM)")
    else:
        ranking_scheduler.setup_test_job(interval_minutes=5)
        logging.info("Ranking scheduler set up for development (every 5 minutes)")
    
    ranking_scheduler.start_scheduler()
    
    # スケジューラーをアプリのコンテキストで利用可能にする
    app.ranking_scheduler = ranking_scheduler
    
except Exception as e:
    logging.error(f"Failed to initialize ranking scheduler: {e}")
    app.ranking_scheduler = None

# Import and register routes
from api_routes import api_bp
app.register_blueprint(api_bp)

# Import main routes
import main

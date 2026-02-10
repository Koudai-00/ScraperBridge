
import os
import psycopg2
import logging
from urllib.parse import urlparse

# 設定
LOG_DB_URL = os.getenv("LOG_DATABASE_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    if not LOG_DB_URL:
        logger.error("LOG_DATABASE_URL environment variable is not set.")
        print("Please set LOG_DATABASE_URL in your .env file.")
        return

    try:
        # Connect to the database
        logger.info(f"Connecting to database...")
        conn = psycopg2.connect(LOG_DB_URL)
        cur = conn.cursor()

        # Create table SQL
        create_table_query = """
        CREATE TABLE IF NOT EXISTS ai_usage_logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            model_name VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL,  -- 'success' or 'error'
            tokens_used INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            prompt_tokens INTEGER DEFAULT 0,
            error_message TEXT,
            latency_ms INTEGER
        );
        """

        # Create index on timestamp for faster queries
        create_index_query = """
        CREATE INDEX IF NOT EXISTS idx_ai_logs_timestamp ON ai_usage_logs(timestamp DESC);
        """

        logger.info("Creating table 'ai_usage_logs'...")
        cur.execute(create_table_query)
        
        logger.info("Creating index on timestamp...")
        cur.execute(create_index_query)

        conn.commit()
        cur.close()
        conn.close()

        logger.info("Database initialization completed successfully!")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        print(f"Failed to initialize database: {e}")

if __name__ == "__main__":
    init_db()

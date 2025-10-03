import os
import logging
import psycopg2
from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from metadata_extractor import MetadataExtractor
from recipe_extractor import RecipeExtractor

# Create blueprint for API routes
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Initialize metadata extractor
extractor = MetadataExtractor()

# Initialize recipe extractor
recipe_extractor = RecipeExtractor()

# Get API keys from environment
APP_API_KEY = os.getenv('APP_API_KEY')
INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')


def require_api_key(key_type='app'):
    """APIキー認証デコレーター"""

    def decorator(f):

        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_key = request.headers.get('X-API-Key')

            if key_type == 'app':
                expected_key = APP_API_KEY
                key_name = 'APP_API_KEY'
            elif key_type == 'internal':
                expected_key = INTERNAL_API_KEY
                key_name = 'INTERNAL_API_KEY'
            else:
                return jsonify({'error': 'Invalid key type'}), 500

            if not expected_key:
                logging.error(f"{key_name} is not set in environment")
                return jsonify({'error': 'Server configuration error'}), 500

            if not api_key:
                return jsonify({'error': 'API key is required'}), 401

            if api_key != expected_key:
                return jsonify({'error': 'Invalid API key'}), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def get_db_connection():
    """データベース接続を取得"""
    return psycopg2.connect(DATABASE_URL)


@api_bp.route('/v2/get-metadata', methods=['POST'])
def get_metadata_v2():
    """
    Extract metadata from SNS URLs (YouTube, TikTok, Instagram)
    
    Request body:
    {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
    
    Response:
    {
        "platform": "youtube",
        "unique_video_id": "dQw4w9WgXcQ",
        "title": "Video Title",
        "thumbnailUrl": "https://...",
        "authorName": "Channel Name"
    }
    """
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({"error":
                            "Missing 'url' field in request body"}), 400

        url = data['url']
        logging.info(f"Processing URL: {url}")

        # Extract metadata using the extractor
        metadata = extractor.extract_metadata(url)

        logging.info(f"Extracted metadata: {metadata}")
        return jsonify(metadata), 200

    except ValueError as e:
        logging.error(f"ValueError: {str(e)}")
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/get-metadata', methods=['POST'])
def get_metadata_v1():
    """Legacy v1 endpoint for backward compatibility"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({"error":
                            "Missing 'url' field in request body"}), 400

        url = data['url']
        metadata = extractor.extract_metadata(url)

        # Convert v2 format to v1 format (without unique_video_id)
        v1_metadata = {
            "platform": metadata["platform"],
            "title": metadata.get("title"),
            "thumbnailUrl": metadata.get("thumbnailUrl"),
            "authorName": metadata.get("authorName")
        }

        return jsonify(v1_metadata), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/get-videos-from-playlist', methods=['POST'])
def get_videos_from_playlist():
    """
    Get video URLs from YouTube playlist
    
    Request body:
    {
        "url": "https://www.youtube.com/playlist?list=PLrGjL4i5rXIvKOPyneAz_Paf0Rqv6ZsEK"
    }
    
    Response:
    {
        "videos": [
            {
                "title": "Video Title",
                "videoUrl": "https://www.youtube.com/watch?v=...",
                "thumbnailUrl": "https://..."
            }
        ]
    }
    """
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({"error":
                            "Missing 'url' field in request body"}), 400

        playlist_url = data['url']

        # Check if it's a YouTube playlist URL
        if 'youtube.com/playlist' not in playlist_url and 'youtu.be/playlist' not in playlist_url:
            return jsonify({"error": "Invalid YouTube playlist URL"}), 400

        logging.info(f"Processing YouTube playlist: {playlist_url}")

        # Extract playlist videos using the extractor
        videos = extractor.extract_playlist_videos(playlist_url)

        return jsonify({"videos": videos}), 200

    except ValueError as e:
        logging.error(f"ValueError in playlist extraction: {str(e)}")
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logging.error(f"Unexpected error in playlist extraction: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/batch-metadata', methods=['POST'])
def batch_get_metadata():
    """
    Get metadata for multiple URLs in a single request
    
    Request body:
    {
        "urls": [
            "https://www.youtube.com/watch?v=...",
            "https://www.tiktok.com/@user/video/...",
            "https://www.instagram.com/p/..."
        ]
    }
    
    Response:
    {
        "results": [
            {
                "url": "https://www.youtube.com/watch?v=...",
                "success": true,
                "data": {
                    "platform": "youtube",
                    "title": "Video Title",
                    "authorName": "Channel Name",
                    "thumbnailUrl": "...",
                    "unique_video_id": "..."
                }
            },
            {
                "url": "https://www.tiktok.com/@user/video/...",
                "success": false,
                "error": "Failed to extract metadata"
            }
        ],
        "summary": {
            "total": 3,
            "successful": 2,
            "failed": 1
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'urls' not in data:
            return jsonify({"error":
                            "Missing 'urls' field in request body"}), 400

        urls = data['urls']
        if not isinstance(urls, list):
            return jsonify({"error": "'urls' must be an array"}), 400

        if len(urls) == 0:
            return jsonify({"error": "URLs array cannot be empty"}), 400

        # Limit to prevent abuse
        max_urls = 50
        if len(urls) > max_urls:
            return jsonify(
                {"error": f"Maximum {max_urls} URLs allowed per request"}), 400

        logging.info(f"Processing batch metadata request for {len(urls)} URLs")

        results = []
        successful_count = 0
        failed_count = 0

        for url in urls:
            try:
                if not isinstance(url, str) or not url.strip():
                    results.append({
                        "url": url,
                        "success": False,
                        "error": "Invalid URL format"
                    })
                    failed_count += 1
                    continue

                # Process each URL individually
                metadata = extractor.extract_metadata(url.strip())

                results.append({"url": url, "success": True, "data": metadata})
                successful_count += 1

            except Exception as e:
                logging.warning(f"Failed to process URL {url}: {str(e)}")
                results.append({"url": url, "success": False, "error": str(e)})
                failed_count += 1

        return jsonify({
            "results": results,
            "summary": {
                "total": len(urls),
                "successful": successful_count,
                "failed": failed_count
            }
        }), 200

    except Exception as e:
        logging.error(
            f"Unexpected error in batch metadata processing: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/rankings', methods=['GET'])
def get_rankings():
    """
    Get current rankings for different periods
    
    Query parameters:
    - period: daily, weekly, monthly, all_time (default: daily)
    - limit: number of results to return (default: 10, max: 100)
    
    Response:
    {
        "period_type": "daily",
        "rankings": [
            {
                "rank": 1,
                "unique_video_id": "dQw4w9WgXcQ",
                "platform": "youtube",
                "title": "Video Title",
                "thumbnail_url": "...",
                "author_name": "Author",
                "count": 42
            }
        ],
        "last_updated": "2024-01-01T12:00:00"
    }
    """
    try:
        from flask import current_app
        import psycopg2

        # Get query parameters
        period_type = request.args.get('period', 'daily')
        limit = min(int(request.args.get('limit', 10)), 100)

        # Validate period type
        valid_periods = ['daily', 'weekly', 'monthly', 'all_time']
        if period_type not in valid_periods:
            return jsonify({
                "error":
                f"Invalid period. Must be one of: {', '.join(valid_periods)}"
            }), 400

        # Connect to database and get rankings
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return jsonify({"error": "Database connection not available"}), 500

        with psycopg2.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        unique_video_id,
                        platform,
                        rank_position,
                        count,
                        title,
                        thumbnail_url,
                        author_name,
                        updated_at
                    FROM rankings
                    WHERE period_type = %s
                    ORDER BY rank_position
                    LIMIT %s
                """, (period_type, limit))

                results = cur.fetchall()

                rankings = []
                last_updated = None

                for row in results:
                    video_id, platform, rank_pos, count, title, thumbnail_url, author_name, updated_at = row

                    rankings.append({
                        "rank": rank_pos,
                        "unique_video_id": video_id,
                        "platform": platform,
                        "title": title,
                        "thumbnail_url": thumbnail_url,
                        "author_name": author_name,
                        "count": count
                    })

                    if not last_updated and updated_at:
                        last_updated = updated_at.isoformat()

        return jsonify({
            "period_type": period_type,
            "rankings": rankings,
            "last_updated": last_updated,
            "total_results": len(rankings)
        }), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logging.error(f"Error getting rankings: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/rankings/stats', methods=['GET'])
def get_ranking_stats():
    """
    Get ranking system statistics
    
    Response:
    {
        "periods": {
            "daily": {"count": 100, "last_updated": "2024-01-01T12:00:00"},
            "weekly": {"count": 100, "last_updated": "2024-01-01T12:00:00"},
            ...
        },
        "platforms": {
            "youtube": 250,
            "tiktok": 150,
            "instagram": 100
        },
        "total_rankings": 500,
        "scheduler_status": {
            "running": true,
            "next_job": "2024-01-01T14:00:00"
        }
    }
    """
    try:
        from flask import current_app
        from batch_processor import BatchProcessor

        # Get ranking statistics
        batch_processor = BatchProcessor()
        stats = batch_processor.get_ranking_stats()

        # Get scheduler status if available
        scheduler_status = {"running": False, "next_job": None}
        try:
            from app import app as main_app
            if hasattr(main_app,
                       'ranking_scheduler') and main_app.ranking_scheduler:
                job_status = main_app.ranking_scheduler.get_job_status()
        except:
            job_status = {}
            scheduler_status = {
                "running": job_status.get('scheduler_running', False),
                "jobs": job_status.get('jobs', {})
            }

        return jsonify({
            "periods": stats.get('periods', {}),
            "platforms": stats.get('platforms', {}),
            "total_rankings": stats.get('total_rankings', 0),
            "scheduler_status": scheduler_status
        }), 200

    except Exception as e:
        logging.error(f"Error getting ranking stats: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/rankings/update', methods=['POST'])
def manual_ranking_update():
    """
    Manually trigger ranking update
    
    Response:
    {
        "success": true,
        "message": "Ranking update completed successfully",
        "stats": {...}
    }
    """
    try:
        from flask import current_app

        import time
        start_time = time.time()

        try:
            from app import app as main_app
            if hasattr(main_app,
                       'ranking_scheduler') and main_app.ranking_scheduler:
                result = main_app.ranking_scheduler.run_manual_update()

                end_time = time.time()
                execution_time = round(end_time - start_time, 2)

                if isinstance(result, dict) and result.get('success'):
                    # 統計情報を取得
                    stats = main_app.ranking_scheduler.batch_processor.get_ranking_stats(
                    )
                    logging.info(
                        f"Manual ranking update completed successfully")
                    return jsonify({
                        'success':
                        True,
                        'message':
                        result.get('message', 'ランキング更新が正常に完了しました'),
                        'execution_time':
                        result.get('execution_time', execution_time),
                        'stats':
                        stats
                    }), 200
                elif isinstance(result, dict):
                    # 辞書形式のエラーレスポンス
                    logging.error(
                        f"Manual ranking update failed: {result.get('error')}")
                    return jsonify({
                        'success':
                        False,
                        'error':
                        result.get('error', 'ランキング更新処理が失敗しました'),
                        'execution_time':
                        result.get('execution_time', execution_time)
                    }), 500
                else:
                    # 従来のbool型レスポンス
                    logging.error(
                        f"Manual ranking update failed after {execution_time}s"
                    )
                    return jsonify({
                        'success': False,
                        'error': 'ランキング更新処理が失敗しました',
                        'execution_time': execution_time
                    }), 500
            else:
                return jsonify({
                    "success": False,
                    "error": "ランキングスケジューラが利用できません"
                }), 503

        except Exception as scheduler_error:
            end_time = time.time()
            execution_time = round(end_time - start_time, 2)
            error_msg = str(scheduler_error)
            logging.error(
                f"Scheduler access error after {execution_time}s: {error_msg}")

            # エラーの種類に応じて詳細メッセージを作成
            if "timeout" in error_msg.lower():
                detailed_error = "処理がタイムアウトしました。大量のデータ処理中の可能性があります。"
            elif "database" in error_msg.lower(
            ) or "connection" in error_msg.lower():
                detailed_error = "データベース接続エラーが発生しました。"
            elif "memory" in error_msg.lower():
                detailed_error = "メモリ不足エラーが発生しました。"
            else:
                detailed_error = f"予期しないエラーが発生しました: {error_msg}"

            return jsonify({
                'success': False,
                'error': detailed_error,
                'technical_error': error_msg,
                'execution_time': execution_time
            }), 500

    except Exception as e:
        logging.error(f"Error in manual ranking update: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "SNS Metadata Extractor API is running"
    }), 200


@api_bp.route('/extract-recipe', methods=['POST'])
@require_api_key('app')
def extract_recipe():
    """
    動画URLからレシピを抽出
    
    Request headers:
    {
        "X-API-Key": "your-app-api-key"
    }
    
    Request body:
    {
        "video_url": "https://www.youtube.com/watch?v=...",
        "user_id": "uuid-string"
    }
    
    Response:
    {
        "success": true,
        "recipe_text": "レシピテキスト...",
        "extraction_method": "description|comment|ai_video",
        "cached": false,
        "cost_usd": 0.00123
    }
    """
    try:
        data = request.get_json()

        # バリデーション
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        if 'video_url' not in data:
            return jsonify({'error': 'Missing video_url field'}), 400

        if 'user_id' not in data:
            return jsonify({'error': 'Missing user_id field'}), 400

        video_url = data['video_url'].strip()
        user_id = data['user_id'].strip()

        if not video_url:
            return jsonify({'error': 'video_url cannot be empty'}), 400

        if not user_id:
            return jsonify({'error': 'user_id cannot be empty'}), 400

        logging.info(
            f"Recipe extraction request - URL: {video_url}, User: {user_id}")

        # キャッシュチェック
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT recipe_id, extracted_text, extraction_method FROM extracted_recipes WHERE video_url = %s",
                    (video_url, ))
                cached_result = cur.fetchone()

                if cached_result:
                    recipe_id, recipe_text, extraction_method = cached_result
                    logging.info(f"Cache hit for URL: {video_url}")

                    # キャッシュヒットをログに記録
                    cur.execute(
                        """
                        INSERT INTO recipe_extraction_logs 
                        (user_id, video_url, status, recipe_id, calculated_cost_usd)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, video_url, 'CACHE_HIT', recipe_id, 0))
                    conn.commit()

                    return jsonify({
                        'success': True,
                        'recipe_text': recipe_text,
                        'extraction_method': extraction_method,
                        'cached': True,
                        'cost_usd': 0.0
                    }), 200

        # キャッシュなし - 新規抽出
        logging.info("No cache found, extracting recipe...")

        try:
            result = recipe_extractor.extract_recipe(video_url)

            recipe_text = result['recipe_text']
            extraction_method = result['extraction_method']
            ai_model = result.get('ai_model')
            tokens_used = result.get('tokens_used', 0)

            # コスト計算
            cost_usd = 0.0
            if ai_model and tokens_used > 0:
                cost_usd = recipe_extractor.calculate_cost(
                    ai_model, tokens_used)

            logging.info(
                f"Recipe extracted successfully - Method: {extraction_method}, Cost: ${cost_usd}"
            )

            # データベースに保存
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # extracted_recipesに保存
                    cur.execute(
                        """
                        INSERT INTO extracted_recipes (video_url, extracted_text, extraction_method)
                        VALUES (%s, %s, %s)
                        RETURNING recipe_id
                    """, (video_url, recipe_text, extraction_method))

                    recipe_id = cur.fetchone()[0]

                    # recipe_extraction_logsに保存
                    cur.execute(
                        """
                        INSERT INTO recipe_extraction_logs 
                        (user_id, video_url, status, ai_model, calculated_cost_usd, recipe_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (user_id, video_url, 'SUCCESS', ai_model, cost_usd,
                          recipe_id))

                    conn.commit()

            return jsonify({
                'success': True,
                'recipe_text': recipe_text,
                'extraction_method': extraction_method,
                'cached': False,
                'cost_usd': cost_usd
            }), 200

        except ValueError as ve:
            # レシピが見つからない、またはサポートされていないプラットフォーム
            logging.warning(f"Recipe extraction failed: {ve}")

            # エラーログを記録
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO recipe_extraction_logs 
                        (user_id, video_url, status, error_message, calculated_cost_usd)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, video_url, 'ERROR', str(ve), 0))
                    conn.commit()

            return jsonify({'success': False, 'error': str(ve)}), 400

    except Exception as e:
        logging.error(f"Unexpected error in recipe extraction: {e}")

        # エラーログを記録（可能なら）
        try:
            if 'user_id' in locals() and 'video_url' in locals():
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO recipe_extraction_logs 
                            (user_id, video_url, status, error_message, calculated_cost_usd)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (user_id, video_url, 'ERROR', str(e), 0))
                        conn.commit()
        except:
            pass

        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


@api_bp.route('/internal/metrics', methods=['GET'])
@require_api_key('internal')
def get_metrics():
    """
    AI利用コストのメトリクスを取得（Appsmith用）
    
    Request headers:
    {
        "X-API-Key": "your-internal-api-key"
    }
    
    Response:
    [
        { "date": "2025-10-01", "total_cost": 15.72 },
        { "date": "2025-10-02", "total_cost": 18.05 }
    ]
    """
    try:
        # 過去30日間のデータを取得
        thirty_days_ago = datetime.now() - timedelta(days=30)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        DATE(created_at) as date,
                        SUM(calculated_cost_usd) as total_cost
                    FROM recipe_extraction_logs
                    WHERE created_at >= %s
                    GROUP BY DATE(created_at)
                    ORDER BY date ASC
                """, (thirty_days_ago, ))

                results = cur.fetchall()

                metrics = []
                for row in results:
                    date, total_cost = row
                    metrics.append({
                        'date':
                        date.strftime('%Y-%m-%d'),
                        'total_cost':
                        float(total_cost) if total_cost else 0.0
                    })

                logging.info(f"Returned {len(metrics)} days of metrics data")
                return jsonify(metrics), 200

    except Exception as e:
        logging.error(f"Error fetching metrics: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

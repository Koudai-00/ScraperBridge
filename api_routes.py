import os
import re
import logging
import psycopg2
from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from metadata_extractor import MetadataExtractor
from recipe_extractor import RecipeExtractor
from folder_categorizer import FolderCategorizer
from layout_analyzer import LayoutAnalyzer
from shopping_manager import shopping_manager

# Create blueprint for API routes
api_bp = Blueprint('api', __name__, url_prefix='/api')


def _split_amount_unit(amount_raw: str) -> tuple:
    """
    分量文字列を数量と単位に分割する
    例: '300g' -> ('300', 'g'), '大さじ2' -> ('2', '大さじ'), '適量' -> ('', '適量')
    """
    if not amount_raw:
        return ('', '')
    
    has_digits = any(c.isdigit() for c in amount_raw)
    
    unit_keywords = ['適量', '少々', 'お好みで', '少量', 'ひとつまみ', 'ひとかけ']
    for kw in unit_keywords:
        if kw in amount_raw:
            if has_digits:
                num = re.sub(r'[^\d０-９./／]', '', amount_raw).strip()
                return (num, kw) if num else ('', kw)
            return ('', kw)
    
    prefix_units = ['大さじ', '小さじ', 'カップ']
    for pu in prefix_units:
        if pu in amount_raw:
            num = amount_raw.replace(pu, '').strip()
            return (num, pu)
    
    match = re.match(r'^([\d０-９./／＋+½¼¾⅓⅔]+(?:\s*[-～〜]\s*[\d０-９./／]+)?)\s*(.+)$', amount_raw)
    if match:
        return (match.group(1).strip(), match.group(2).strip())
    
    match2 = re.match(r'^(.+?)([\d０-９./／]+)$', amount_raw)
    if match2:
        return (match2.group(2).strip(), match2.group(1).strip())
    
    if has_digits:
        return (amount_raw, '')
    
    return ('', amount_raw)


def _normalize_ingredient(ing):
    """
    材料データを正規化して {name, amount, unit, sub_amount, sub_unit} 形式にする
    文字列形式（旧フォーマット）やunit無しのdictにも対応
    """
    if isinstance(ing, str):
        sub_amount, sub_unit = '', ''
        paren_match = re.search(r'[（(]([\d０-９./／]+)\s*([a-zA-Zぁ-んァ-ヶㅤ㎖㎗㎘㎎㎏]+)[）)]', ing)
        if paren_match:
            sub_amount = paren_match.group(1)
            sub_unit = paren_match.group(2)
            ing = ing[:paren_match.start()].strip()
        match = re.match(r'^(.+?)[\s:：]+(.+)$', ing)
        if match:
            name = match.group(1).strip()
            amount_raw = match.group(2).strip()
            amount, unit = _split_amount_unit(amount_raw)
            return {'name': name, 'amount': amount, 'unit': unit, 'sub_amount': sub_amount, 'sub_unit': sub_unit}
        return {'name': ing, 'amount': '', 'unit': '', 'sub_amount': sub_amount, 'sub_unit': sub_unit}
    if isinstance(ing, dict):
        return {
            'name': ing.get('name', ''),
            'amount': str(ing.get('amount', '')),
            'unit': ing.get('unit', ''),
            'sub_amount': str(ing.get('sub_amount', '')),
            'sub_unit': ing.get('sub_unit', '')
        }
    return {'name': str(ing), 'amount': '', 'unit': '', 'sub_amount': '', 'sub_unit': ''}


def parse_recipe_text(recipe_text: str) -> dict:
    """
    レシピテキストを構造化データに変換
    
    入力例:
    【材料】
    ・玉ねぎ 1個
    ・豚肉 200g
    
    【作り方】
    1. 玉ねぎを切る
    2. 炒める
    
    【コツ・ポイント】
    弱火でじっくり炒める
    
    出力:
    {
        'ingredients': [{'name': '玉ねぎ', 'amount': '1', 'unit': '個', 'sub_amount': '', 'sub_unit': ''}, ...],
        'steps': ['玉ねぎを切る', '炒める'],
        'tips': '弱火でじっくり炒める'
    }
    """
    if not recipe_text:
        return {'ingredients': [], 'steps': [], 'tips': None}
    
    ingredients = []
    steps = []
    tips = None
    
    lines = recipe_text.strip().split('\n')
    current_section = None
    tips_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if '【材料】' in line or '材料' in line and len(line) < 10:
            current_section = 'ingredients'
            continue
        elif '【作り方】' in line or '【手順】' in line or ('作り方' in line and len(line) < 10):
            current_section = 'steps'
            continue
        elif '【コツ】' in line or '【ポイント】' in line or '【コツ・ポイント】' in line or ('コツ' in line and len(line) < 15):
            current_section = 'tips'
            continue
        
        if current_section == 'ingredients':
            line = re.sub(r'^[・\-\*•]\s*', '', line)
            
            sub_amount, sub_unit = '', ''
            paren_match = re.search(r'[（(]([\d０-９./／]+)\s*([a-zA-Zぁ-んァ-ヶㅤ㎖㎗㎘㎎㎏]+)[）)]', line)
            if paren_match:
                sub_amount = paren_match.group(1)
                sub_unit = paren_match.group(2)
                line = line[:paren_match.start()].strip() + line[paren_match.end():].strip()
                line = line.strip()
            
            match = re.match(r'^(.+?)[\s:：]+(.+)$', line)
            if match:
                name = match.group(1).strip()
                amount_raw = match.group(2).strip()
            else:
                parts = line.rsplit(' ', 1)
                if len(parts) == 2 and (
                    any(c.isdigit() for c in parts[1]) or
                    any(u in parts[1] for u in ['個', 'g', 'ml', '本', '枚', '切れ', '大さじ', '小さじ', '適量', '少々'])
                ):
                    name = parts[0].strip()
                    amount_raw = parts[1].strip()
                else:
                    name = line
                    amount_raw = ''
            
            if name:
                amount, unit = _split_amount_unit(amount_raw)
                ingredients.append({'name': name, 'amount': amount, 'unit': unit, 'sub_amount': sub_amount, 'sub_unit': sub_unit})
        
        elif current_section == 'steps':
            step_text = re.sub(r'^[\d０-９]+[\.．\.\)）]\s*', '', line)
            if step_text:
                steps.append(step_text)
        
        elif current_section == 'tips':
            tips_lines.append(line)
    
    if tips_lines:
        tips = '\n'.join(tips_lines)
    
    return {
        'ingredients': ingredients,
        'steps': steps,
        'tips': tips
    }

# Initialize metadata extractor
extractor = MetadataExtractor()

# Initialize recipe extractor
recipe_extractor = RecipeExtractor()

# Initialize folder categorizer
folder_categorizer = FolderCategorizer()

# Initialize layout analyzer
layout_analyzer = LayoutAnalyzer()

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

        # URLからプラットフォームとユニークIDを抽出
        platform, unique_video_id = recipe_extractor.extract_unique_video_id(video_url)
        if not unique_video_id:
            return jsonify({'error': 'Could not extract video ID from URL'}), 400
        
        logging.info(f"Extracted - Platform: {platform}, Video ID: {unique_video_id}")

        # キャッシュチェック（platform + unique_video_idで）
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT recipe_id, extracted_text, extraction_method FROM extracted_recipes WHERE platform = %s AND unique_video_id = %s",
                    (platform, unique_video_id))
                cached_result = cur.fetchone()

                if cached_result:
                    recipe_id, recipe_text, extraction_method = cached_result
                    logging.info(f"Cache hit for {platform}:{unique_video_id}")

                    parsed = parse_recipe_text(recipe_text)

                    if not parsed['steps']:
                        logging.info(f"Cached recipe has no steps, invalidating cache for {platform}:{unique_video_id}")
                        cur.execute(
                            "DELETE FROM extracted_recipes WHERE recipe_id = %s",
                            (recipe_id,))
                        conn.commit()
                    else:
                        cur.execute(
                            """
                            INSERT INTO recipe_extraction_logs 
                            (user_id, platform, unique_video_id, status, recipe_id, calculated_cost_usd)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (user_id, platform, unique_video_id, 'CACHE_HIT', recipe_id, 0))
                        conn.commit()

                        return jsonify({
                            'success': True,
                            'recipe_text': recipe_text,
                            'ingredients': parsed['ingredients'],
                            'steps': parsed['steps'],
                            'tips': parsed['tips'],
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

            parsed = parse_recipe_text(recipe_text)

            if not parsed['steps']:
                logging.warning("Extracted recipe has no steps, not caching")

            # データベースに保存（stepsがある場合のみキャッシュ）
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    recipe_id = None
                    if parsed['steps']:
                        cur.execute(
                            """
                            INSERT INTO extracted_recipes (platform, unique_video_id, extracted_text, extraction_method)
                            VALUES (%s, %s, %s, %s)
                            RETURNING recipe_id
                        """, (platform, unique_video_id, recipe_text, extraction_method))

                        result_row = cur.fetchone()
                        if not result_row:
                            raise ValueError("Failed to save recipe to database")
                        recipe_id = result_row[0]

                    # recipe_extraction_logsに保存
                    cur.execute(
                        """
                        INSERT INTO recipe_extraction_logs 
                        (user_id, platform, unique_video_id, status, ai_model, calculated_cost_usd, recipe_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (user_id, platform, unique_video_id, 'SUCCESS', ai_model, cost_usd,
                          recipe_id))

                    conn.commit()

            return jsonify({
                'success': True,
                'recipe_text': recipe_text,
                'ingredients': parsed['ingredients'],
                'steps': parsed['steps'],
                'tips': parsed['tips'],
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
                        (user_id, platform, unique_video_id, status, error_message, calculated_cost_usd)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (user_id, platform, unique_video_id, 'ERROR', str(ve), 0))
                    conn.commit()

            return jsonify({'success': False, 'error': str(ve)}), 400

    except Exception as e:
        logging.error(f"Unexpected error in recipe extraction: {e}")

        # エラーログを記録（可能なら）
        try:
            if 'user_id' in locals() and 'platform' in locals() and 'unique_video_id' in locals():
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO recipe_extraction_logs 
                            (user_id, platform, unique_video_id, status, error_message, calculated_cost_usd)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (user_id, platform, unique_video_id, 'ERROR', str(e), 0))
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


@api_bp.route('/suggest-folder', methods=['POST'])
@require_api_key('app')
def suggest_folder():
    """
    動画のタイトルと説明文から最適なフォルダを提案する
    
    Request body:
    {
        "user_id": "user_12345...",
        "video_title": "肉じゃがの作り方",
        "video_description": "...",
        "current_folders": [
            { "id": "f_001", "name": "和食" },
            ...
        ]
    }
    
    Response:
    {
        "success": true,
        "suggested_folder_id": "f_001",
        "reason": "..."
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
            
        # 必須パラメータのチェック
        required_fields = ['user_id', 'video_title', 'current_folders']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing {field} field'}), 400
        
        user_id = data['user_id']
        video_title = data['video_title']
        # 説明文は任意（なければ空文字）
        video_description = data.get('video_description', '')
        current_folders = data['current_folders']
        
        if not isinstance(current_folders, list):
            return jsonify({'error': 'current_folders must be a list'}), 400
            
        logging.info(f"Folder suggestion request - User: {user_id}, Title: {video_title}")
        
        # フォルダ提案の実行
        result = folder_categorizer.suggest_folder(
            video_title=video_title,
            video_description=video_description,
            current_folders=current_folders
        )
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            # 失敗しても200で返し、success: falseとする（クライアント側のハンドリングのため）
            # ただしシステムエラーの場合は500にするなど調整可能だが、
            # 今回は要件定義にあるレスポンス形式に従い、successフラグで制御
            return jsonify(result), 200
            
    except Exception as e:
        logging.error(f"Error in suggest_folder endpoint: {e}")
        return jsonify({
            'success': False,
            'suggested_folder_id': None,
            'reason': f"Internal server error: {str(e)}"
        }), 500


@api_bp.route('/extract-collection-metadata', methods=['POST'])
@require_api_key('app')
def extract_collection_metadata():
    """
    InstagramコレクションファイルからURLを抽出し、各投稿のメタデータを取得
    
    Request headers:
    {
        "X-API-Key": "your-app-api-key"
    }
    
    Request:
    - Content-Type: multipart/form-data
    - file: JSONファイル または ZIPファイル
    
    Response (成功時):
    {
        "success": true,
        "collection_name": "コレクション名",
        "total_urls": 4,
        "successful": 3,
        "failed": 1,
        "results": [
            {
                "url": "https://www.instagram.com/reel/...",
                "success": true,
                "data": {
                    "platform": "instagram",
                    "unique_video_id": "...",
                    "title": "...",
                    "thumbnailUrl": "...",
                    "authorName": "...",
                    "embedCode": "..."
                }
            },
            {
                "url": "https://www.instagram.com/reel/...",
                "success": false,
                "error": "エラーメッセージ"
            }
        ]
    }
    
    Response (エラー時):
    {
        "success": false,
        "error": "エラーメッセージ"
    }
    """
    import zipfile
    import io
    import json
    import tempfile
    import os as os_module
    
    try:
        # ファイルが送信されているか確認
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'ファイルが送信されていません。fileフィールドにJSONまたはZIPファイルを添付してください。'
            }), 400
        
        uploaded_file = request.files['file']
        
        if uploaded_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'ファイルが選択されていません。'
            }), 400
        
        filename = uploaded_file.filename.lower()
        file_content = uploaded_file.read()
        
        logging.info(f"Received file: {uploaded_file.filename}, size: {len(file_content)} bytes")
        
        # コレクションJSONを探す
        collection_json_data = None
        collection_filename = None
        
        if filename.endswith('.json'):
            # JSONファイルの場合は直接解析
            try:
                collection_json_data = json.loads(file_content.decode('utf-8'))
                collection_filename = uploaded_file.filename
                logging.info(f"Parsed JSON file: {collection_filename}")
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return jsonify({
                    'success': False,
                    'error': f'JSONファイルの解析に失敗しました: {str(e)}'
                }), 400
                
        elif filename.endswith('.zip'):
            # ZIPファイルの場合は展開してJSONファイルを探す
            try:
                with zipfile.ZipFile(io.BytesIO(file_content), 'r') as zip_ref:
                    # ZIPファイル内のファイル一覧を取得
                    file_list = zip_ref.namelist()
                    logging.info(f"ZIP file contains: {file_list}")
                    
                    # コレクションJSONファイルを探す（saved_collectionsを含むファイルを優先）
                    json_files = [f for f in file_list if f.endswith('.json')]
                    
                    if not json_files:
                        return jsonify({
                            'success': False,
                            'error': 'ZIPファイル内にJSONファイルが見つかりませんでした。'
                        }), 400
                    
                    # saved_collectionsを含むファイルを優先的に探す
                    collection_file = None
                    for jf in json_files:
                        if 'saved_collections' in jf.lower() or 'collection' in jf.lower():
                            collection_file = jf
                            break
                    
                    # 見つからない場合は最初のJSONファイルを使用
                    if not collection_file:
                        collection_file = json_files[0]
                    
                    logging.info(f"Using collection file from ZIP: {collection_file}")
                    
                    # JSONファイルを読み込んで解析
                    with zip_ref.open(collection_file) as json_file:
                        json_content = json_file.read()
                        collection_json_data = json.loads(json_content.decode('utf-8'))
                        collection_filename = collection_file
                        
            except zipfile.BadZipFile:
                return jsonify({
                    'success': False,
                    'error': 'ZIPファイルの形式が正しくありません。'
                }), 400
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return jsonify({
                    'success': False,
                    'error': f'ZIP内のJSONファイルの解析に失敗しました: {str(e)}'
                }), 400
        else:
            return jsonify({
                'success': False,
                'error': 'サポートされていないファイル形式です。JSONまたはZIPファイルを送信してください。'
            }), 400
        
        # コレクションJSONからURLを抽出
        urls = []
        collection_name = None
        
        # saved_saved_collections形式を解析
        if 'saved_saved_collections' in collection_json_data:
            collections = collection_json_data['saved_saved_collections']
            
            for item in collections:
                # コレクション名を取得（titleフィールドがある場合）
                if 'title' in item and not collection_name:
                    raw_title = item['title']
                    try:
                        collection_name = raw_title.encode('latin1').decode('utf-8')
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        collection_name = raw_title
                
                # string_map_dataからURLを抽出
                if 'string_map_data' in item:
                    string_map = item['string_map_data']
                    
                    # Nameフィールドからコレクション名またはURLを取得
                    if 'Name' in string_map:
                        name_data = string_map['Name']
                        
                        # コレクション名を取得（valueがあってhrefがない場合）
                        if 'value' in name_data and 'href' not in name_data and not collection_name:
                            # UTF-8エンコードされた文字列をデコード
                            raw_value = name_data['value']
                            try:
                                collection_name = raw_value.encode('latin1').decode('utf-8')
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                collection_name = raw_value
                        
                        # URLを取得（hrefがある場合）
                        if 'href' in name_data:
                            url = name_data['href']
                            if url and 'instagram.com' in url:
                                urls.append(url)
                                logging.info(f"Found Instagram URL: {url}")
        else:
            return jsonify({
                'success': False,
                'error': 'コレクションデータが見つかりませんでした。Instagramからダウンロードしたコレクションファイルを使用してください。'
            }), 400
        
        if not urls:
            return jsonify({
                'success': False,
                'error': 'コレクション内にInstagramの投稿URLが見つかりませんでした。'
            }), 400
        
        logging.info(f"Found {len(urls)} Instagram URLs in collection '{collection_name}'")
        
        # 各URLに対してメタデータを取得
        results = []
        successful_count = 0
        failed_count = 0
        
        for url in urls:
            try:
                # 既存のメタデータ取得機能を使用
                metadata = extractor.extract_metadata(url.strip())
                
                results.append({
                    'url': url,
                    'success': True,
                    'data': metadata
                })
                successful_count += 1
                logging.info(f"Successfully extracted metadata for: {url}")
                
            except Exception as e:
                error_msg = str(e)
                logging.warning(f"Failed to extract metadata for {url}: {error_msg}")
                
                results.append({
                    'url': url,
                    'success': False,
                    'error': error_msg
                })
                failed_count += 1
        
        return jsonify({
            'success': True,
            'collection_name': collection_name,
            'source_file': collection_filename,
            'total_urls': len(urls),
            'successful': successful_count,
            'failed': failed_count,
            'results': results
        }), 200
        
    except Exception as e:
        logging.error(f"Error in extract_collection_metadata: {e}")
        return jsonify({
            'success': False,
            'error': f'サーバーエラーが発生しました: {str(e)}'
        }), 500


@api_bp.route('/v1/analyze-layout', methods=['POST'])
@require_api_key('app')
def analyze_layout():
    """
    レシピサイトのレイアウトを解析し、調理モード用のCSSルールを返す
    
    Request headers:
    {
        "X-API-Key": "your-app-api-key"
    }
    
    Request body:
    {
        "url": "https://cookpad.com/recipe/12345",
        "user_id": "user_12345..."  // optional
    }
    
    Response (成功時):
    {
        "success": true,
        "site_domain": "cookpad.com",
        "hide_selectors": [".ad-container", "#sidebar", ".social-buttons"],
        "main_content_selector": ".recipe-main",
        "cached": true/false
    }
    
    Response (エラー時):
    {
        "success": false,
        "error": "エラーメッセージ"
    }
    
    Notes:
    - 同一ドメインのルールは1ヶ月間キャッシュされます
    - キャッシュがある場合はAI処理をスキップして即座に返却します
    - user_idを指定すると利用履歴がDBに記録されます
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400
        
        if 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing url field'
            }), 400
        
        url = data['url'].strip()
        user_id = data.get('user_id')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'url cannot be empty'
            }), 400
        
        logging.info(f"Layout analysis request - URL: {url}, User: {user_id}")
        
        try:
            result = layout_analyzer.analyze_layout(url, user_id)
            
            return jsonify({
                'success': True,
                'site_domain': result.get('site_domain'),
                'hide_selectors': result.get('hide_selectors', []),
                'main_content_selector': result.get('main_content_selector', 'body'),
                'cached': result.get('cached', False),
                'created_at': result.get('created_at'),
                'updated_at': result.get('updated_at')
            }), 200
            
        except ValueError as e:
            logging.warning(f"Layout analysis failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400
            
        except Exception as e:
            logging.error(f"Layout analysis error: {e}")
            return jsonify({
                'success': False,
                'error': f'レイアウト解析に失敗しました: {str(e)}'
            }), 500
    
    except Exception as e:
        logging.error(f"Error in analyze_layout: {e}")
        return jsonify({
            'success': False,
            'error': f'サーバーエラーが発生しました: {str(e)}'
        }), 500


@api_bp.route('/v1/extract-recipe-from-image', methods=['POST'])
@require_api_key('app')
def extract_recipe_from_image():
    """
    画像からレシピ情報を抽出する
    
    Request headers:
    {
        "X-API-Key": "your-app-api-key"
    }
    
    Request:
    - Content-Type: multipart/form-data
    - image: 画像ファイル (JPEG, PNG, WebP, HEIC)
    - user_id: ユーザーID (optional)
    
    Response (成功時):
    {
        "success": true,
        "dish_name": "肉じゃが",
        "servings": "4人分",
        "cooking_time": "30分",
        "ingredients": [
            {"name": "じゃがいも", "amount": "4", "unit": "個", "sub_amount": "", "sub_unit": ""},
            {"name": "牛肉", "amount": "200", "unit": "g", "sub_amount": "", "sub_unit": ""}
        ],
        "steps": [
            "じゃがいもを一口大に切る",
            "牛肉を炒める"
        ],
        "tips": "煮込む時は落し蓋をすると味が染みやすい",
        "ai_model": "gemini-2.0-flash-lite",
        "tokens_used": 1234,
        "input_tokens": 800,
        "output_tokens": 434
    }
    
    Response (エラー時):
    {
        "success": false,
        "error": "エラーメッセージ"
    }
    """
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': '画像ファイルが送信されていません。imageフィールドに画像を添付してください。'
            }), 400
        
        uploaded_file = request.files['image']
        
        if uploaded_file.filename == '':
            return jsonify({
                'success': False,
                'error': '画像ファイルが選択されていません。'
            }), 400
        
        filename = uploaded_file.filename.lower()
        
        mime_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.heic': 'image/heic',
            '.heif': 'image/heif'
        }
        
        file_ext = None
        for ext in mime_type_map.keys():
            if filename.endswith(ext):
                file_ext = ext
                break
        
        if not file_ext:
            return jsonify({
                'success': False,
                'error': 'サポートされていない画像形式です。JPEG, PNG, WebP, HEICのいずれかを使用してください。'
            }), 400
        
        mime_type = mime_type_map[file_ext]
        image_data = uploaded_file.read()
        
        logging.info(f"Received image: {uploaded_file.filename}, size: {len(image_data)} bytes, type: {mime_type}")
        
        max_size = 20 * 1024 * 1024
        if len(image_data) > max_size:
            return jsonify({
                'success': False,
                'error': f'画像サイズが大きすぎます。20MB以下の画像を使用してください。'
            }), 400
        
        user_id = request.form.get('user_id')
        
        try:
            result = recipe_extractor.extract_recipe_from_image(image_data, mime_type)
            
            return jsonify({
                'success': True,
                'dish_name': result.get('dish_name'),
                'servings': result.get('servings'),
                'cooking_time': result.get('cooking_time'),
                'ingredients': [_normalize_ingredient(i) for i in result.get('ingredients', [])],
                'steps': result.get('steps', []),
                'tips': result.get('tips'),
                'ai_model': result.get('ai_model'),
                'tokens_used': result.get('tokens_used', 0),
                'input_tokens': result.get('input_tokens', 0),
                'output_tokens': result.get('output_tokens', 0)
            }), 200
            
        except ValueError as e:
            logging.warning(f"Image recipe extraction failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400
            
        except Exception as e:
            logging.error(f"Image recipe extraction error: {e}")
            return jsonify({
                'success': False,
                'error': f'画像からのレシピ抽出に失敗しました: {str(e)}'
            }), 500
    
    except Exception as e:
        logging.error(f"Error in extract_recipe_from_image: {e}")
        return jsonify({
            'success': False,
            'error': f'サーバーエラーが発生しました: {str(e)}'
        }), 500


@api_bp.route('/test/extract-recipe', methods=['POST'])
def test_extract_recipe():
    """
    Browser test: Recipe extraction (model selectable)
    
    Note: App endpoint /api/extract-recipe is unchanged
    
    Request body:
    {
        "video_url": "https://www.youtube.com/watch?v=...",
        "model": "gemini-1.5-flash"  // optional, default: gemini-1.5-flash
    }
    
    Response:
    {
        "success": true,
        "recipe_text": "レシピテキスト...",
        "extraction_method": "description|comment|ai_video",
        "ai_model": "gemini-1.5-flash",
        "tokens_used": 1234
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        if 'video_url' not in data:
            return jsonify({'error': 'Missing video_url field'}), 400

        video_url = data['video_url'].strip()
        model_name = data.get('model', 'gemini-1.5-flash')

        if not video_url:
            return jsonify({'error': 'video_url cannot be empty'}), 400

        logging.info(f"Test recipe extraction - URL: {video_url}, Model: {model_name}")

        try:
            result = recipe_extractor.extract_recipe_with_model(video_url, model_name)

            recipe_text = result['recipe_text']
            parsed = parse_recipe_text(recipe_text)
            
            return jsonify({
                'success': True,
                'recipe_text': recipe_text,
                'ingredients': parsed['ingredients'],
                'steps': parsed['steps'],
                'tips': parsed['tips'],
                'extraction_method': result['extraction_method'],
                'extraction_flow': result.get('extraction_flow', ''),
                'ai_model': result.get('ai_model'),
                'tokens_used': result.get('tokens_used', 0),
                'input_tokens': result.get('input_tokens', 0),
                'output_tokens': result.get('output_tokens', 0),
                'refinement_status': result.get('refinement_status'),
                'refinement_error': result.get('refinement_error')
            }), 200

        except ValueError as e:
            logging.warning(f"Test recipe extraction failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        except Exception as e:
            logging.error(f"Test recipe extraction error: {e}")
            return jsonify({
                'success': False,
                'error': f'レシピ抽出に失敗しました: {str(e)}'
            }), 500

    except Exception as e:
        logging.error(f"Error in test_extract_recipe: {e}")
        return jsonify({
            'success': False,
            'error': f'サーバーエラーが発生しました: {str(e)}'
        }), 500


@api_bp.route('/test/available-models', methods=['GET'])
def get_available_models():
    """
    利用可能なGeminiモデルのリストを取得
    
    Response:
    {
        "models": [
            {"id": "gemini-2.0-flash-exp", "name": "Gemini 2.0 Flash Experimental (Free)", "default": true},
            ...
        ]
    }
    """
    try:
        models = recipe_extractor.get_available_models()
        return jsonify({'models': models}), 200
    except Exception as e:
        logging.error(f"Error getting available models: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/test/supabase-connection', methods=['GET'])
def test_supabase_connection():
    import requests as http_requests

    supabase_url = os.getenv('SUPABASE_URL', '')
    service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

    if not supabase_url:
        return jsonify({
            'success': False,
            'error': 'SUPABASE_URL が設定されていません'
        }), 500

    if not service_key:
        return jsonify({
            'success': False,
            'error': 'SUPABASE_SERVICE_ROLE_KEY が設定されていません'
        }), 500

    try:
        url = f'{supabase_url}/rest/v1/categories?select=*&order=id.asc'
        headers = {
            'apikey': service_key,
            'Authorization': f'Bearer {service_key}',
            'Content-Type': 'application/json'
        }

        response = http_requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'success': True,
                'message': 'Supabase接続成功',
                'record_count': len(data),
                'table': 'categories',
                'data': data
            }), 200
        elif response.status_code == 401:
            return jsonify({
                'success': False,
                'error': '認証エラー: APIキーが無効です',
                'status_code': response.status_code
            }), 401
        elif response.status_code == 404:
            return jsonify({
                'success': False,
                'error': 'テーブルが見つかりません',
                'status_code': response.status_code
            }), 404
        else:
            return jsonify({
                'success': False,
                'error': f'Supabaseからエラーレスポンス',
                'status_code': response.status_code,
                'details': response.text[:500]
            }), response.status_code

    except http_requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'error': 'Supabaseに接続できません。URLを確認してください。'
        }), 503
    except http_requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'error': '接続がタイムアウトしました'
        }), 504
    except Exception as e:
        logging.error(f"Supabase connection test error: {e}")
        return jsonify({
            'success': False,
            'error': f'予期しないエラーが発生しました',
            'details': str(e)
        }), 500


@api_bp.route('/shopping-list/check-master', methods=['POST'])

def check_shopping_master():
    """
    買い物リストのマスターデータ照合
    
    Request body:
    {
        "ingredients": ["人参", "豚バラ肉", ...]
    }
    
    Response:
    {
        "results": [
            {
                "ingredient_name": "人参",
                "master_name": "人参",
                "category_id": 1,
                "category_name": "野菜・果物",
                "is_new": false  # 既存代表名あり
            },
            {
                "ingredient_name": "未知の食材",
                "master_name": "未知の食材",
                "category_id": 15,
                "category_name": "日用品・その他",
                "is_new": true   # 新規作成
            }
        ]
    }
    """
    try:
        data = request.get_json()
        if not data or 'ingredients' not in data:
            return jsonify({"error": "Missing 'ingredients' field"}), 400
            
        ingredients = data['ingredients']
        if not isinstance(ingredients, list):
            return jsonify({"error": "'ingredients' must be a list"}), 400
            
        # 買い物リストマネージャーで処理
        results = shopping_manager.check_and_resolve_ingredients(ingredients)
        
        return jsonify({"results": results}), 200
        
    except Exception as e:
        logging.error(f"Error in check_shopping_master: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api_bp.route('/service-status', methods=['GET'])
def service_status():
    """
    OpenRouterモデルの使用状況を表示するダッシュボード (HTML)
    """
    try:
        from openrouter_client import openrouter_client
        stats = openrouter_client.get_model_status()
        
        # DB接続状態の確認
        db_status_text = '<span style="color:red">未設定</span>'
        if openrouter_client.log_db_url:
            db_status_text = '<span style="color:green">接続済み (Neon)</span>'
        
        # シンプルなHTML生成
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AIモデル稼働状況</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; background-color: #f5f5f5; }}
                h1 {{ color: #333; }}
                .card {{ background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); padding: 20px; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f8f9fa; font-weight: bold; }}
                .status-success {{ color: green; font-weight: bold; }}
                .status-error {{ color: red; font-weight: bold; }}
                .status-unused {{ color: gray; }}
                .refresh-btn {{ 
                    padding: 10px 20px; background-color: #007bff; color: white; 
                    border: none; border-radius: 4px; cursor: pointer; text-decoration: none; 
                    display: inline-block; margin-bottom: 10px;
                }}
                .refresh-btn:hover {{ background-color: #0056b3; }}
                .last-error {{ font-size: 0.85em; color: #d9534f; max-width: 300px; overflow-wrap: break-word; }}
                .db-status {{ margin-bottom: 15px; font-weight: bold; color: #555; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>AIモデル稼働状況</h1>
                <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 15px;">
                    <a href="/api/service-status" class="refresh-btn">ステータス更新</a>
                    <button id="runChecksBtn" class="refresh-btn" style="background-color: #28a745;">全モデル動作確認</button>
                    <span id="checkStatus" style="display:none; color: #666;">動作確認を実行中... (10〜20秒かかります)</span>
                </div>
                <div class="db-status">
                    ログデータベース: {db_status_text}
                </div>
                <p>現在のOpenRouterおよびGemini APIモデルの使用状況（再起動でリセットされます）</p>
                
                <table>
                    <thead>
                        <tr>
                            <th>モデル名</th>
                            <th>状態</th>
                            <th>最終使用日時</th>
                            <th>成功 / 失敗</th>
                            <th>現在のエラー</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        
        
        # 統計データを最終使用日時順（降順）にソート
        # last_usedがNoneの場合は空文字列として扱い、末尾にする
        sorted_stats = sorted(
            stats.items(), 
            key=lambda x: x[1]['last_used'] or "", 
            reverse=True
        )

        # 統計データを行として追加
        for model, data in sorted_stats:
            status_class = f"status-{data['status']}"
            
            # ステータスがsuccessの場合はエラーメッセージを表示しない
            last_error = "-"
            if data['status'] == 'error':
                last_error = data['last_error'] if data['last_error'] else "Unknown Error"
            elif data['status'] == 'unused':
                last_error = "-"
            
            row = f"""
                        <tr>
                            <td>{model}</td>
                            <td class="{status_class}">{data['status'].upper()}</td>
                            <td>{data['last_used'] or '-'}</td>
                            <td>
                                <span style="color:green">✓ {data['success_count']}</span> / 
                                <span style="color:red">✗ {data['error_count']}</span>
                            </td>
                            <td class="last-error">{last_error}</td>
                        </tr>
            """
            html_content += row
            
        html_content += """
                    </tbody>
                </table>
            </div>
            <div style="text-align: center; color: #666; font-size: 0.8em;">
                ScraperBridge API Service
            </div>
            
            <script>
                document.getElementById('runChecksBtn').addEventListener('click', function() {
                    const btn = this;
                    const statusSpan = document.getElementById('checkStatus');
                    
                    if (confirm('全モデルの動作確認を実行しますか？（数秒〜20秒程度かかります）')) {
                        btn.disabled = true;
                        btn.style.opacity = "0.7";
                        statusSpan.style.display = "inline";
                        
                        fetch('/api/check-models', { method: 'POST' })
                            .then(response => response.json())
                            .then(data => {
                                alert('確認完了！ページをリロードします。');
                                window.location.reload();
                            })
                            .catch(error => {
                                alert('エラーが発生しました: ' + error);
                                btn.disabled = false;
                                btn.style.opacity = "1";
                                statusSpan.style.display = "none";
                            });
                    }
                });
            </script>
        </body>
        </html>
        """
        
        return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        
    except Exception as e:
        logging.error(f"Error rendering status dashboard: {e}")
        return jsonify({"error": str(e)}), 500

@api_bp.route('/check-models', methods=['POST'])
def check_models_endpoint():
    """全モデルの動作確認を実行（非同期ではないが並列処理）"""
    try:
        from openrouter_client import openrouter_client
        results = openrouter_client.check_all_models() # 内部でcleanupも実行
        return jsonify({"status": "completed", "results": results})
    except Exception as e:
        logging.error(f"Error checking models: {e}")
        return jsonify({"error": str(e)}), 500

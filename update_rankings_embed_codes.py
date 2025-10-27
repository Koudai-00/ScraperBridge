"""
既存のランキングデータに埋め込みコードとURLを追加するスクリプト
videosテーブルから最新の埋め込みコード情報を取得してrankingsテーブルを更新します
"""
import os
import logging
import psycopg2
from metadata_extractor import MetadataExtractor

logging.basicConfig(level=logging.INFO)

def update_rankings_with_embed_codes():
    """rankingsテーブルのデータにurl/embed_codeを追加"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.error("DATABASE_URL not set")
        return False
    
    extractor = MetadataExtractor()
    
    try:
        with psycopg2.connect(database_url) as conn:
            with conn.cursor() as cur:
                # rankingsテーブルから全てのunique_video_idを取得
                cur.execute("""
                    SELECT DISTINCT unique_video_id, platform
                    FROM rankings
                    WHERE url IS NULL OR embed_code IS NULL
                """)
                
                videos_to_update = cur.fetchall()
                logging.info(f"Found {len(videos_to_update)} videos to update")
                
                if not videos_to_update:
                    logging.info("No videos need updating")
                    return True
                
                updated_count = 0
                for video_id, platform in videos_to_update:
                    # URLを構築
                    url = construct_url(video_id, platform)
                    if not url:
                        logging.warning(f"Could not construct URL for {video_id} ({platform})")
                        continue
                    
                    # メタデータAPIを使って埋め込みコードを取得
                    try:
                        metadata = extractor.extract_metadata(url)
                        if metadata and metadata.get('embedCode'):
                            # rankingsテーブルを更新
                            cur.execute("""
                                UPDATE rankings
                                SET url = %s, embed_code = %s
                                WHERE unique_video_id = %s
                            """, (url, metadata['embedCode'], video_id))
                            
                            updated_count += 1
                            if updated_count % 10 == 0:
                                conn.commit()
                                logging.info(f"Updated {updated_count} videos so far...")
                        else:
                            logging.warning(f"No embed code found for {url}")
                    except Exception as e:
                        logging.error(f"Error processing {url}: {e}")
                        continue
                
                conn.commit()
                logging.info(f"Successfully updated {updated_count} videos with embed codes")
                return True
                
    except Exception as e:
        logging.error(f"Error updating rankings: {e}")
        return False

def construct_url(video_id: str, platform: str) -> str:
    """プラットフォーム別URL構築"""
    url_templates = {
        'youtube': f'https://www.youtube.com/watch?v={video_id}',
        'tiktok': f'https://www.tiktok.com/@user/video/{video_id}',
        'instagram': f'https://www.instagram.com/p/{video_id}/'
    }
    return url_templates.get(platform, '')

if __name__ == '__main__':
    logging.info("Starting rankings embed code update...")
    success = update_rankings_with_embed_codes()
    if success:
        logging.info("Update completed successfully!")
    else:
        logging.error("Update failed")

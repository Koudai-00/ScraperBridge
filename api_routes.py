import os
import logging
from flask import Blueprint, request, jsonify
from metadata_extractor import MetadataExtractor

# Create blueprint for API routes
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Initialize metadata extractor
extractor = MetadataExtractor()

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
            return jsonify({
                "error": "Missing 'url' field in request body"
            }), 400
        
        url = data['url']
        logging.info(f"Processing URL: {url}")
        
        # Extract metadata using the extractor
        metadata = extractor.extract_metadata(url)
        
        logging.info(f"Extracted metadata: {metadata}")
        return jsonify(metadata), 200
        
    except ValueError as e:
        logging.error(f"ValueError: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 400
        
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}"
        }), 500

@api_bp.route('/get-metadata', methods=['POST'])
def get_metadata_v1():
    """Legacy v1 endpoint for backward compatibility"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                "error": "Missing 'url' field in request body"
            }), 400
        
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
            return jsonify({
                "error": "Missing 'url' field in request body"
            }), 400
        
        playlist_url = data['url']
        
        # Check if it's a YouTube playlist URL
        if 'youtube.com/playlist' not in playlist_url and 'youtu.be/playlist' not in playlist_url:
            return jsonify({
                "error": "Invalid YouTube playlist URL"
            }), 400
        
        logging.info(f"Processing YouTube playlist: {playlist_url}")
        
        # Extract playlist videos using the extractor
        videos = extractor.extract_playlist_videos(playlist_url)
        
        return jsonify({
            "videos": videos
        }), 200
        
    except ValueError as e:
        logging.error(f"ValueError in playlist extraction: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 400
        
    except Exception as e:
        logging.error(f"Unexpected error in playlist extraction: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}"
        }), 500

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
            return jsonify({
                "error": "Missing 'urls' field in request body"
            }), 400
        
        urls = data['urls']
        if not isinstance(urls, list):
            return jsonify({
                "error": "'urls' must be an array"
            }), 400
        
        if len(urls) == 0:
            return jsonify({
                "error": "URLs array cannot be empty"
            }), 400
        
        # Limit to prevent abuse
        max_urls = 50
        if len(urls) > max_urls:
            return jsonify({
                "error": f"Maximum {max_urls} URLs allowed per request"
            }), 400
        
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
                
                results.append({
                    "url": url,
                    "success": True,
                    "data": metadata
                })
                successful_count += 1
                
            except Exception as e:
                logging.warning(f"Failed to process URL {url}: {str(e)}")
                results.append({
                    "url": url,
                    "success": False,
                    "error": str(e)
                })
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
        logging.error(f"Unexpected error in batch metadata processing: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}"
        }), 500

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "SNS Metadata Extractor API is running"
    }), 200

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

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "SNS Metadata Extractor API is running"
    }), 200

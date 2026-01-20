# SNS Metadata Extractor & Recipe Extraction System

## Overview

This is a Flask-based web application that extracts metadata from social media URLs (YouTube, TikTok, Instagram) and provides AI-powered recipe extraction from cooking videos. The system provides REST API endpoints for both metadata extraction and recipe extraction, with intelligent caching and cost tracking for AI usage.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Framework**: Flask with Blueprint organization for modular routing
- **API Design**: RESTful API with multiple endpoints for metadata and recipe extraction
  - `/api/v2/get-metadata`: Metadata extraction from social media URLs
  - `/api/extract-recipe`: AI-powered recipe extraction from cooking videos
  - `/api/internal/metrics`: Cost tracking and analytics for Appsmith dashboard
- **Request/Response Format**: JSON-based communication with structured error handling
- **Metadata Extraction**: Centralized `MetadataExtractor` class that handles platform detection and data extraction
- **Recipe Extraction**: `RecipeExtractor` class with multi-tier extraction strategy (description → comments → AI video analysis)
- **Platform Support**: YouTube, TikTok, and Instagram URL processing with platform-specific extraction logic

### Frontend Architecture
- **Template Engine**: Flask's Jinja2 templating for server-side rendering
- **UI Framework**: Bootstrap with dark theme and Font Awesome icons
- **JavaScript Architecture**: Class-based frontend with `MetadataExtractor` class for API interaction
- **Responsive Design**: Mobile-friendly interface with example URL testing capabilities

### Data Processing
- **URL Parsing**: Regular expression-based platform detection and ID extraction
- **Web Scraping**: BeautifulSoup for HTML parsing when direct APIs aren't available
- **Session Management**: Persistent HTTP session with proper user-agent headers for web scraping

### Error Handling
- **Validation**: Input validation for required URL parameters
- **Exception Management**: Structured error responses with appropriate HTTP status codes
- **Logging**: Debug-level logging for request tracking and troubleshooting

### Security and CORS
- **Cross-Origin Requests**: CORS enabled for all origins to support API access
- **API Key Authentication**: Two-tier authentication system
  - `APP_API_KEY`: Mobile app authentication for recipe extraction
  - `INTERNAL_API_KEY`: Appsmith dashboard authentication for metrics access
- **Environment Variables**: Sensitive configuration stored in environment variables
- **Session Security**: Flask session management with configurable secret keys

### Recipe Extraction System
- **Multi-Tier Extraction Strategy**:
  1. YouTube description analysis (fastest, no AI cost)
  2. Creator comment extraction (fast, no AI cost)
  3. Google Gemini AI video analysis (fallback, AI cost incurred)
- **Intelligent Caching**: Video URL-based cache to avoid redundant AI processing
- **Cost Tracking**: Comprehensive logging of AI usage and costs per user
- **Database Tables**:
  - `extracted_recipes`: Recipe cache with extraction method tracking
  - `recipe_extraction_logs`: Detailed logs for AI cost analysis and user activity

## External Dependencies

### APIs and Services
- **YouTube Data API**: For extracting YouTube video metadata, descriptions, and comments using `YOUTUBE_API_KEY`
- **Google Gemini API**: AI-powered video analysis for recipe extraction using `GEMINI_API_KEY`
- **OpenRouter API**: Free AI model access for text refinement using `OPENROUTER_API_KEY`
  - Text models: DeepSeek Chat V3, Llama 4, Qwen3, Microsoft Phi-4, etc.
  - Vision models (image only): Qwen 2.5 VL, Molmo, Nemotron VL
  - Automatic fallback on 429 rate limit errors
- **Apify API**: Video download URL extraction for TikTok and Instagram using `APIFY_API_TOKEN`
  - TikTok: Uses `clockworks/free-tiktok-scraper` actor
  - Instagram: Uses `apify/instagram-scraper` actor
- **ScrapingBee API**: Web scraping service for platforms without direct API access using `SCRAPINGBEE_API_KEY`
- **Supabase**: Database service integration with `SUPABASE_URL` and `SUPABASE_ANON_KEY` for potential data storage

### Python Libraries
- **Flask**: Web framework for API and web interface
- **Flask-CORS**: Cross-origin resource sharing support
- **Requests**: HTTP client for external API calls and web scraping
- **BeautifulSoup4**: HTML parsing for metadata extraction
- **urllib.parse**: URL parsing and manipulation utilities
- **google-generativeai**: Google Gemini API client for AI-powered video analysis
- **psycopg2-binary**: PostgreSQL database adapter for recipe caching and logging

### Frontend Dependencies
- **Bootstrap**: CSS framework with dark theme from Replit CDN
- **Font Awesome**: Icon library for UI enhancement
- **Vanilla JavaScript**: Native JavaScript for API interaction without additional frameworks

### Development Tools
- **Python Logging**: Built-in logging for debugging and monitoring
- **Environment Configuration**: Support for development and production environment variables

## Recent Changes (October 2025)

### Recipe Extraction Feature
- **New Module**: `recipe_extractor.py` - Handles intelligent recipe extraction from cooking videos
- **New Endpoints**: 
  - `POST /api/extract-recipe` - Extract recipes from video URLs with caching
  - `GET /api/internal/metrics` - Retrieve AI usage costs for analytics
- **Database Schema**: 
  - `extracted_recipes`: Changed from URL-based to `(platform, unique_video_id)` caching
  - `recipe_extraction_logs`: Updated to track platform and unique_video_id
  - Unique index on `(platform, unique_video_id)` prevents duplicate entries
- **AI Integration**: Google Gemini 2.0 Flash Experimental for video analysis
- **Cost Optimization**: Multi-tier extraction strategy minimizes AI costs by checking descriptions and comments first

### Recipe Quality Improvements (October 3, 2025)
- **JSON-based Gemini Responses**: Prompts Gemini to return structured JSON format for reliable parsing
- **Post-processing Cleaning**: Removes unwanted prefix text ("はい、動画を拝見しました" etc.)
- **Required Section Validation**: Verifies recipes contain both ingredients and cooking steps
- **Fallback Handling**: If JSON parsing fails, falls back to text cleaning for maximum reliability
- **Platform-agnostic Caching**: Uses unique video IDs instead of full URLs to handle URL variations

### Apify Integration for TikTok/Instagram (October 5, 2025)
- **Apify API Integration**: TikTok and Instagram video downloads now use Apify API instead of direct yt-dlp
- **Improved Reliability**: Apify provides stable video download URLs where direct downloads were failing
- **Processing Flow**: 
  1. Detect platform (TikTok/Instagram)
  2. Call Apify API to get video download URL
  3. Download video using yt-dlp from Apify URL
  4. Upload to Gemini for recipe extraction (same as YouTube)
- **Actor Configuration**:
  - TikTok: `clockworks/free-tiktok-scraper`
  - Instagram: `apify/instagram-scraper`

### Recipe Refinement with Gemini (January 2026)
- **Method**: `_refine_recipe_with_gemini` - Uses Gemini 2.0 Flash to refine extracted recipes
- **Applied To**: Both description-based and comment-based recipe extraction
- **Processing Strategy**: 
  1. When recipe detected in description or author comment, extract raw text
  2. Send to Gemini 2.0 Flash with structured prompt
  3. Gemini removes promotional content, hashtags, SNS links
  4. Returns structured JSON format (dish_name, ingredients, steps, tips)
  5. Convert JSON to formatted text with【材料】【作り方】sections
- **Fallback**: If Gemini fails or quota exceeded, returns original text unchanged
- **Model**: `gemini-2.0-flash-exp` (free tier)

### Recipe Refinement Status Tracking (January 2026)
- **Refinement Status**: API now returns explicit refinement status (`success`, `failed`, `skipped`, `not_applicable`)
- **Token Tracking**: Gemini API token usage is tracked and returned for description/comment extractions
- **Improved Prompt**: Enhanced prompt to explicitly exclude:
  - BGM info, music credits (BGM: ○○, Music by, ♪, 使用音源)
  - Channel subscription requests, like requests
  - Sponsor info, PR tags
  - Camera/editing software info
  - Comment section invitations
- **UI Updates**: Test interface now displays:
  - AI refinement status (成功/失敗/スキップ)
  - Token usage count
  - Error message if refinement failed
- **Response Fields**:
  - `refinement_status`: success | failed | skipped | not_applicable
  - `refinement_tokens`: Token count used for refinement (null if not applicable)
  - `refinement_error`: Error message if refinement failed

### Security Improvements (October 23, 2025)
- **API Key Protection**: All API keys stored in environment variables only (never hardcoded)
- **Git Ignore Configuration**: Added comprehensive `.gitignore` file to prevent accidental exposure of:
  - Environment variables and secrets (.env files)
  - Log files and debug output (Pasted-*.txt, *.log)
  - Uploaded videos and temporary files
  - Database files and IDE configurations
- **Log File Cleanup**: Removed debug log files from `attached_assets/` that contained API keys in request URLs
- **Environment Variable Usage**: All sensitive configuration uses `os.getenv()` pattern:
  - `YOUTUBE_API_KEY`: YouTube Data API authentication
  - `GEMINI_API_KEY`: Google Gemini AI authentication
  - `APIFY_API_TOKEN`: Apify API authentication
  - `SCRAPINGBEE_API_KEY`: ScrapingBee API authentication
  - `SESSION_SECRET`: Flask session encryption key

### Improved Recipe Detection Logic (January 2026)
- **Keyword Detection Refinement**: `_contains_recipe` now uses 8 specific keywords only:
  - 材料, 作り方, 手順, 分量, ml, cc, 大さじ, 小さじ
  - Returns true if ANY ONE keyword is found (previously required 3+)
- **AI Validation for Recipe Content**: When keywords are detected, AI validates if actual recipe exists
  - Prompt instructs AI to return `{"no_recipe": true}` if no actual ingredients/steps present
  - Prevents false positives from promotional content containing recipe-related words
- **Automatic Fallback**: If AI determines no recipe in description/comments, automatically proceeds to video analysis
- **Extraction Flow Tracking**: New `extraction_flow` field tracks the entire extraction path
  - Example: "説明欄をチェック → レシピなし → コメント欄をチェック → レシピなし → 動画解析 → 抽出成功"
- **UI Enhancement**: Browser test interface now displays extraction flow for debugging
- **Default Model Change**: Changed default Gemini model from `gemini-2.0-flash-exp` to `gemini-1.5-flash`

### Instagram Collection Import Feature (December 2025)
- **New Endpoint**: `POST /api/extract-collection-metadata` - Extract metadata from Instagram collection files
- **File Support**: 
  - JSON files (direct upload of `saved_collections_*.json`)
  - ZIP files (auto-extracts and finds collection JSON inside)
- **Processing Flow**:
  1. Receive JSON or ZIP file via multipart/form-data
  2. Parse `saved_saved_collections` structure from Instagram export
  3. Extract collection name (UTF-8 decoded from latin1)
  4. Extract all Instagram URLs from collection items
  5. Fetch metadata for each URL using existing Instagram extraction
  6. Return aggregated results with success/failure counts
- **Authentication**: Requires `APP_API_KEY` header (`X-API-Key`)
- **Response Format**: Same as existing batch metadata endpoint with additional collection info
- **Error Handling**: 
  - Invalid file format errors
  - Missing collection data errors
  - Per-URL extraction error tracking

### OpenRouter Integration (January 2026)
- **New Module**: `openrouter_client.py` - Handles OpenRouter API calls with automatic fallback
- **Model Support**:
  - Text models: Use 'openrouter:' prefix (e.g., `openrouter:deepseek/deepseek-chat-v3-0324:free`)
  - Vision models: Use 'openrouter-vision:' prefix (e.g., `openrouter-vision:qwen/qwen-2.5-vl-7b-instruct:free`)
- **Automatic Fallback**: On 429 rate limit errors, automatically tries next model in priority list
- **Model Priority (Text)**:
  1. deepseek/deepseek-chat-v3-0324:free
  2. deepseek/deepseek-r1-0528:free
  3. google/gemini-2.0-flash-exp:free
  4. meta-llama/llama-4-maverick:free
  5. qwen/qwen3-235b-a22b:free
  6. microsoft/phi-4:free
  7. (30+ more models)
- **Japanese Translation**: Models that return English responses are automatically translated using OpenRouter's translation models
- **Video Analysis Limitation**: OpenRouter doesn't support video upload - automatically falls back to Gemini 2.0 Flash for video analysis
- **UI Updates**: Model selector now shows Gemini and OpenRouter models in separate groups
- **Environment Variable**: `OPENROUTER_API_KEY` required for OpenRouter functionality
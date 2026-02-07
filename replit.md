# SNS Metadata Extractor & Recipe Extraction System

## Overview
This project is a Flask-based web application designed to extract metadata from social media URLs (YouTube, TikTok, Instagram) and offer AI-powered recipe extraction from cooking videos. It provides REST API endpoints for both functionalities, incorporating intelligent caching and cost tracking for AI usage. The system aims to streamline content analysis and recipe discovery from various social media platforms.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Framework**: Flask with Blueprint organization for modular routing.
- **API Design**: RESTful API for metadata and recipe extraction, including an internal metrics endpoint for analytics.
- **Data Extraction**: Uses a `MetadataExtractor` for platform-specific social media metadata and a `RecipeExtractor` with a multi-tier strategy (description → comments → AI video analysis).
- **Security**: Implements API key authentication (`APP_API_KEY`, `INTERNAL_API_KEY`), CORS for all origins, and utilizes environment variables for sensitive configurations.

### Frontend Architecture
- **Template Engine**: Flask's Jinja2 for server-side rendering.
- **UI/UX**: Bootstrap with a dark theme and Font Awesome icons, designed to be responsive and mobile-friendly.
- **JavaScript**: Class-based architecture for API interaction.

### Data Processing
- **URL Handling**: Regular expression-based URL parsing for platform detection and ID extraction.
- **Web Scraping**: BeautifulSoup for HTML parsing and ScrapingBee for platforms without direct API access.

### Recipe Extraction System
- **Multi-Tier Strategy**: Prioritizes YouTube description and creator comment analysis before falling back to Google Gemini AI video analysis to optimize costs.
- **Caching**: Intelligent video URL-based caching prevents redundant AI processing.
- **Cost Tracking**: Logs AI usage and costs per user.
- **Recipe Refinement**: Uses Gemini to refine extracted recipes from descriptions/comments, removing promotional content and structuring output into JSON.
- **Ingredient Structure**: Extracts ingredients with separate `name`, `amount`, `unit`, `sub_amount`, and `sub_unit` fields. The `sub_amount`/`sub_unit` pair holds weight conversion data (e.g., "ズッキーニ1本(200g)" → amount="1", unit="本", sub_amount="200", sub_unit="g").

### System Design Choices
- **Error Handling**: Structured error responses with appropriate HTTP status codes and input validation.
- **Logging**: Debug-level logging for request tracking and troubleshooting.
- **Model Integration**: Utilizes OpenRouter for text extraction with automatic model fallback, while video analysis exclusively uses the Gemini API.
- **Instagram Collection Import**: Supports extracting metadata from Instagram collection JSON/ZIP files.

## External Dependencies

### APIs and Services
- **YouTube Data API**: For YouTube video metadata, descriptions, and comments.
- **Google Gemini API**: AI-powered video analysis for recipe extraction and refinement.
- **OpenRouter API**: Provides access to various AI models for text refinement with automatic fallback mechanisms.
- **Apify API**: For extracting video download URLs from TikTok and Instagram.
- **ScrapingBee API**: Web scraping service for platforms without direct API access.
- **Supabase**: Potentially used as a database service for recipe caching and logging.

### Python Libraries
- **Flask**: Web framework.
- **Flask-CORS**: Cross-origin resource sharing.
- **Requests**: HTTP client.
- **BeautifulSoup4**: HTML parsing.
- **google-generativeai**: Google Gemini API client.
- **psycopg2-binary**: PostgreSQL adapter.

### Frontend Dependencies
- **Bootstrap**: CSS framework.
- **Font Awesome**: Icon library.
- **Vanilla JavaScript**: For client-side interactivity.
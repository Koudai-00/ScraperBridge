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
- **Database Schema**: Added `extracted_recipes` and `recipe_extraction_logs` tables
- **AI Integration**: Google Gemini 2.0 Flash Experimental for video analysis
- **Cost Optimization**: Multi-tier extraction strategy minimizes AI costs by checking descriptions and comments first
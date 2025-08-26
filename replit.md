# SNS Metadata Extractor

## Overview

This is a Flask-based web application that extracts metadata from social media URLs (YouTube, TikTok, Instagram). The system provides both a REST API endpoint and a web interface for testing. It fetches video titles, thumbnails, author names, and unique video IDs from supported platforms using various extraction methods including web scraping and API integrations.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Framework**: Flask with Blueprint organization for modular routing
- **API Design**: RESTful API with `/api/v2/get-metadata` endpoint accepting POST requests
- **Request/Response Format**: JSON-based communication with structured error handling
- **Metadata Extraction**: Centralized `MetadataExtractor` class that handles platform detection and data extraction
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
- **Environment Variables**: Sensitive configuration stored in environment variables
- **Session Security**: Flask session management with configurable secret keys

## External Dependencies

### APIs and Services
- **YouTube Data API**: For extracting YouTube video metadata using `YOUTUBE_API_KEY`
- **ScrapingBee API**: Web scraping service for platforms without direct API access using `SCRAPINGBEE_API_KEY`
- **Supabase**: Database service integration with `SUPABASE_URL` and `SUPABASE_ANON_KEY` for potential data storage

### Python Libraries
- **Flask**: Web framework for API and web interface
- **Flask-CORS**: Cross-origin resource sharing support
- **Requests**: HTTP client for external API calls and web scraping
- **BeautifulSoup4**: HTML parsing for metadata extraction
- **urllib.parse**: URL parsing and manipulation utilities

### Frontend Dependencies
- **Bootstrap**: CSS framework with dark theme from Replit CDN
- **Font Awesome**: Icon library for UI enhancement
- **Vanilla JavaScript**: Native JavaScript for API interaction without additional frameworks

### Development Tools
- **Python Logging**: Built-in logging for debugging and monitoring
- **Environment Configuration**: Support for development and production environment variables
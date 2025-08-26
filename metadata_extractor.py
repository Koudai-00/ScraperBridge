import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import json

class MetadataExtractor:
    """Extract metadata from various social media platforms"""
    
    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self.scrapingbee_api_key = os.getenv("SCRAPINGBEE_API_KEY")
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")
        
        # Set up session for HTTP requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def extract_metadata(self, url: str) -> dict:
        """
        Extract metadata from a given URL
        
        Args:
            url (str): The URL to extract metadata from
            
        Returns:
            dict: Metadata containing platform, unique_video_id, title, thumbnailUrl, authorName
        """
        if not url:
            raise ValueError("URL cannot be empty")
        
        # Determine platform
        platform = self._detect_platform(url)
        
        if platform == "youtube":
            return self._extract_youtube_metadata(url)
        elif platform == "tiktok":
            return self._extract_tiktok_metadata(url)
        elif platform == "instagram":
            return self._extract_instagram_metadata(url)
        else:
            raise ValueError(f"Unsupported platform for URL: {url}")
    
    def _detect_platform(self, url: str) -> str:
        """Detect which platform the URL belongs to"""
        url_lower = url.lower()
        
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        elif "tiktok.com" in url_lower:
            return "tiktok"
        elif "instagram.com" in url_lower:
            return "instagram"
        else:
            return "unknown"
    
    def _extract_youtube_metadata(self, url: str) -> dict:
        """Extract metadata from YouTube URLs"""
        logging.info(f"Extracting YouTube metadata from: {url}")
        
        # Extract video ID
        video_id = self._extract_youtube_id(url)
        if not video_id:
            raise ValueError("Could not extract YouTube video ID from URL")
        
        # Try YouTube API first if API key is available
        if self.youtube_api_key:
            try:
                return self._get_youtube_api_metadata(video_id)
            except Exception as e:
                logging.warning(f"YouTube API failed, falling back to scraping: {e}")
        
        # Fallback to web scraping
        return self._scrape_youtube_metadata(url, video_id)
    
    def _extract_youtube_id(self, url: str) -> str:
        """Extract YouTube video ID from URL"""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu\.be\/([0-9A-Za-z_-]{11}).*'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return ""
    
    def _get_youtube_api_metadata(self, video_id: str) -> dict:
        """Get YouTube metadata using YouTube Data API"""
        api_url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            'part': 'snippet',
            'id': video_id,
            'key': self.youtube_api_key
        }
        
        response = self.session.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('items'):
            raise ValueError("Video not found or is private")
        
        snippet = data['items'][0]['snippet']
        
        return {
            "platform": "youtube",
            "unique_video_id": video_id,
            "title": snippet.get('title'),
            "thumbnailUrl": snippet.get('thumbnails', {}).get('high', {}).get('url'),
            "authorName": snippet.get('channelTitle')
        }
    
    def _scrape_youtube_metadata(self, url: str, video_id: str) -> dict:
        """Scrape YouTube metadata from web page"""
        response = self.session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract title
        title = None
        title_tag = soup.find('meta', property='og:title')
        if title_tag and hasattr(title_tag, 'get'):
            title = title_tag.get('content')
        
        # Extract thumbnail
        thumbnail_url = None
        thumbnail_tag = soup.find('meta', property='og:image')
        if thumbnail_tag and hasattr(thumbnail_tag, 'get'):
            thumbnail_url = thumbnail_tag.get('content')
        
        # Extract author name from page title or meta tags
        author_name = None
        # Try to find channel name in various places
        for script in soup.find_all('script'):
            if hasattr(script, 'string') and script.string and '"channelName"' in script.string:
                try:
                    # This is a simplified extraction - in production you'd want more robust parsing
                    import json
                    text = script.string
                    start = text.find('"channelName":"') + 15
                    end = text.find('"', start)
                    if start > 14 and end > start:
                        author_name = text[start:end]
                        break
                except:
                    pass
        
        return {
            "platform": "youtube",
            "unique_video_id": video_id,
            "title": title,
            "thumbnailUrl": thumbnail_url,
            "authorName": author_name
        }
    
    def _extract_tiktok_metadata(self, url: str) -> dict:
        """Extract metadata from TikTok URLs"""
        logging.info(f"Extracting TikTok metadata from: {url}")
        
        # Resolve short URLs
        final_url = self._resolve_tiktok_url(url)
        
        # Extract video ID
        video_id = self._extract_tiktok_id(final_url)
        if not video_id:
            raise ValueError("Could not extract TikTok video ID from URL")
        
        # Try Supabase function if available
        if self.supabase_url and self.supabase_anon_key:
            try:
                return self._get_tiktok_supabase_metadata(final_url, video_id)
            except Exception as e:
                logging.warning(f"Supabase function failed, falling back to scraping: {e}")
        
        # Fallback to web scraping
        return self._scrape_tiktok_metadata(final_url, video_id)
    
    def _resolve_tiktok_url(self, url: str) -> str:
        """Resolve TikTok short URLs to full URLs"""
        if "vt.tiktok.com" in url or "vm.tiktok.com" in url:
            response = self.session.head(url, allow_redirects=True, timeout=10)
            return response.url
        return url
    
    def _extract_tiktok_id(self, url: str) -> str:
        """Extract TikTok video ID from URL"""
        clean_url = url.split('?')[0]
        match = re.search(r'\/video\/(\d+)', clean_url)
        return match.group(1) if match else ""
    
    def _get_tiktok_supabase_metadata(self, url: str, video_id: str) -> dict:
        """Get TikTok metadata using Supabase function"""
        supabase_function_url = f"{self.supabase_url}/functions/v1/video-metadata"
        headers = {"Authorization": f"Bearer {self.supabase_anon_key}"}
        body = {"url": url}
        
        response = self.session.post(supabase_function_url, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        
        data = response.json()
        
        return {
            "platform": "tiktok",
            "unique_video_id": video_id,
            "title": data.get("title"),
            "thumbnailUrl": data.get("thumbnailUrl"),
            "authorName": data.get("authorName")
        }
    
    def _scrape_tiktok_metadata(self, url: str, video_id: str) -> dict:
        """Scrape TikTok metadata from web page"""
        response = self.session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract metadata from meta tags
        title = None
        thumbnail_url = None
        author_name = None
        
        # Extract title
        title_tag = soup.find('meta', property='og:title')
        if title_tag and hasattr(title_tag, 'get'):
            title = title_tag.get('content')
        
        # Extract thumbnail
        thumbnail_tag = soup.find('meta', property='og:image')
        if thumbnail_tag and hasattr(thumbnail_tag, 'get'):
            thumbnail_url = thumbnail_tag.get('content')
        
        # Extract author name (usually in the title or description)
        description_tag = soup.find('meta', property='og:description')
        if description_tag and hasattr(description_tag, 'get'):
            description = description_tag.get('content', '')
            # TikTok descriptions often contain author info
            if description and '@' in description:
                author_match = re.search(r'@([^\s]+)', description)
                if author_match:
                    author_name = f"@{author_match.group(1)}"
        
        return {
            "platform": "tiktok",
            "unique_video_id": video_id,
            "title": title,
            "thumbnailUrl": thumbnail_url,
            "authorName": author_name
        }
    
    def _extract_instagram_metadata(self, url: str) -> dict:
        """Extract metadata from Instagram URLs"""
        logging.info(f"Extracting Instagram metadata from: {url}")
        
        # Extract post ID (shortcode)
        post_id = self._extract_instagram_id(url)
        if not post_id:
            raise ValueError("Could not extract Instagram post ID from URL")
        
        # Scrape metadata
        return self._scrape_instagram_metadata(url, post_id)
    
    def _extract_instagram_id(self, url: str) -> str:
        """Extract Instagram post ID (shortcode) from URL"""
        clean_url = url.split('?')[0]
        match = re.search(r'\/(p|reel)\/([A-Za-z0-9-_]+)', clean_url)
        return match.group(2) if match else ""
    
    def _scrape_instagram_metadata(self, url: str, post_id: str) -> dict:
        """Scrape Instagram metadata from web page"""
        # Instagram requires special handling due to their anti-bot measures
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = self.session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract metadata from meta tags
        title = None
        thumbnail_url = None
        author_name = None
        
        # Extract title/caption
        title_tag = soup.find('meta', property='og:title')
        if title_tag and hasattr(title_tag, 'get'):
            title_content = title_tag.get('content')
            if title_content:
                title = title_content
                # Instagram titles often contain author info
                if ' on Instagram:' in title:
                    author_name = title.split(' on Instagram:')[0]
                    title = title.split(': "')[1].rstrip('"') if ': "' in title else title
        
        # Extract thumbnail
        thumbnail_tag = soup.find('meta', property='og:image')
        if thumbnail_tag and hasattr(thumbnail_tag, 'get'):
            thumbnail_url = thumbnail_tag.get('content')
        
        return {
            "platform": "instagram",
            "unique_video_id": post_id,
            "title": title,
            "thumbnailUrl": thumbnail_url,
            "authorName": author_name
        }

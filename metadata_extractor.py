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
        
        # Check if it's a YouTube playlist
        if self._is_youtube_playlist(url):
            return self._extract_youtube_playlist_metadata(url)
        
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
        # TikTok requires special handling due to their anti-bot measures
        approaches = [
            # Approach 1: Mobile user agent
            {
                'url': url,
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Referer': 'https://www.tiktok.com/',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            },
            # Approach 2: Facebook external crawler
            {
                'url': url,
                'headers': {
                    'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
            },
            # Approach 3: Desktop Chrome user agent
            {
                'url': url,
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9,ja;q=0.8',
                    'Referer': 'https://www.tiktok.com/',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                }
            },
            # Approach 4: Try without query parameters
            {
                'url': url.split('?')[0],  # Remove query parameters
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.tiktok.com/',
                }
            },
            # Approach 5: Try TikTok embed URL (similar to Instagram approach)
            {
                'url': f"https://www.tiktok.com/oembed?url={url}",
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'application/json,text/plain,*/*',
                    'Referer': 'https://www.tiktok.com/',
                }
            }
        ]
        
        # Try each approach until one works
        for i, approach in enumerate(approaches):
            try:
                logging.debug(f"Trying TikTok approach {i+1}: {approach['url']}")
                response = self.session.get(approach['url'], headers=approach['headers'], timeout=15)
                response.raise_for_status()
                
                # Handle encoding issues
                content = response.content
                html_text = ""
                
                # Try different encoding methods
                encodings_to_try = ['utf-8', 'iso-8859-1', 'cp1252', 'latin1']
                for encoding in encodings_to_try:
                    try:
                        html_text = content.decode(encoding, errors='ignore')
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                
                if not html_text:
                    html_text = content.decode('utf-8', errors='replace')
                
                # Special handling for oEmbed JSON response
                if approach['url'].startswith('https://www.tiktok.com/oembed'):
                    try:
                        import json
                        json_data = json.loads(html_text)
                        if json_data.get('title'):
                            title = json_data['title'].strip()
                            thumbnail_url = json_data.get('thumbnail_url')
                            author_name = json_data.get('author_name')
                            if not author_name:
                                # Extract username from URL if not provided
                                username_match = re.search(r'tiktok\.com/@([^/]+)', url)
                                if username_match:
                                    author_name = f"@{username_match.group(1)}"
                            
                            logging.debug(f"TikTok oEmbed extraction results: title='{title}', thumbnail='{thumbnail_url}', author='{author_name}'")
                            return {
                                "platform": "tiktok",
                                "unique_video_id": video_id,
                                "title": title,
                                "thumbnailUrl": thumbnail_url,
                                "authorName": author_name
                            }
                    except (json.JSONDecodeError, TypeError, AttributeError, KeyError) as e:
                        logging.debug(f"Failed to parse oEmbed response: {e}")
                        continue
                
                soup = BeautifulSoup(html_text, 'html.parser')
                
                # Debug: Log HTML structure for analysis
                title_tag = soup.find('title')
                meta_count = len(soup.find_all('meta'))
                script_count = len(soup.find_all('script'))
                
                logging.debug(f"TikTok Approach {i+1} - Title: {title_tag}, Meta: {meta_count}, Scripts: {script_count}")
                
                # Skip if no useful content found
                if meta_count < 3 and script_count < 3 and not title_tag:
                    logging.debug(f"TikTok Approach {i+1} returned minimal content, trying next...")
                    continue
                
                # Log some meta tags for debugging
                meta_tags = soup.find_all('meta')
                for j, tag in enumerate(meta_tags[:5]):  # Log first 5 meta tags
                    if tag.get('property') or tag.get('name'):
                        logging.debug(f"TikTok Approach {i+1} Meta tag {j}: {tag}")
                
                # Extract metadata from meta tags
                title = None
                thumbnail_url = None
                author_name = None
                
                # Method 1: Extract title from various sources
                title_sources = [
                    # First try TikTok-specific meta tags
                    soup.find('meta', property='og:title'),
                    soup.find('meta', property='og:description'),
                    soup.find('meta', attrs={'name': 'description'}),
                    soup.find('meta', attrs={'name': 'twitter:title'}),
                    soup.find('meta', attrs={'name': 'twitter:description'}),
                    # Also try the title tag as fallback
                    soup.find('title')
                ]
                
                for source in title_sources:
                    if source:
                        content = None
                        if hasattr(source, 'get') and source.get('content'):
                            content = source.get('content').strip()
                        elif hasattr(source, 'get_text') and source.get_text():
                            content = source.get_text().strip()
                        
                        if content:
                            # Clean up TikTok title format
                            if content.startswith('TikTok ·'):
                                # Skip generic TikTok titles like "TikTok · 名無し"
                                if '名無し' not in content and 'Untitled' not in content:
                                    title = content.replace('TikTok ·', '').strip()
                                    break
                            elif content != 'TikTok' and len(content) > 6:
                                # Use content if it's not just "TikTok" and has meaningful length
                                title = content
                                break
                
                # Method 2: Extract thumbnail from various sources
                thumbnail_sources = [
                    soup.find('meta', property='og:image'),
                    soup.find('meta', property='og:image:secure_url'),
                    soup.find('meta', attrs={'name': 'twitter:image'}),
                    soup.find('meta', attrs={'name': 'thumbnail'})
                ]
                
                for source in thumbnail_sources:
                    if source and hasattr(source, 'get') and source.get('content'):
                        thumbnail_url = source.get('content').strip()
                        break
                
                # Method 3: Extract author name from multiple sources
                author_sources = [
                    soup.find('meta', property='og:description'),
                    soup.find('meta', attrs={'name': 'description'}),
                    soup.find('meta', property='twitter:description')
                ]
                
                for source in author_sources:
                    if source and hasattr(source, 'get') and source.get('content'):
                        description = source.get('content', '').strip()
                        if description and '@' in description:
                            author_match = re.search(r'@([^\s,\.\!\?]+)', description)
                            if author_match:
                                author_name = f"@{author_match.group(1)}"
                                break
                
                # Method 4: Try to extract username from URL if not found
                if not author_name and url:
                    username_match = re.search(r'tiktok\.com/@([^/]+)', url)
                    if username_match:
                        author_name = f"@{username_match.group(1)}"
                
                # Method 5: Look for JSON-LD or script data
                if not title or not thumbnail_url:
                    scripts = soup.find_all('script')
                    for script in scripts:
                        if script.string and len(script.string) > 100:
                            script_text = script.string
                            # Look for TikTok specific data patterns
                            if '"title"' in script_text or '"desc"' in script_text or '"video"' in script_text:
                                try:
                                    # Try multiple approaches to extract from script data
                                    import json
                                    
                                    # Approach 1: Look for title in JSON data
                                    title_patterns = [
                                        r'"title":\s*"([^"]+)"',
                                        r'"desc":\s*"([^"]+)"',
                                        r'"description":\s*"([^"]+)"',
                                    ]
                                    
                                    for pattern in title_patterns:
                                        match = re.search(pattern, script_text)
                                        if match and not title:
                                            potential_title = match.group(1).strip()
                                            # Filter out generic or empty titles
                                            if (potential_title and 
                                                len(potential_title) > 3 and 
                                                potential_title not in ['TikTok', '名無し', 'Untitled', ''] and
                                                not potential_title.startswith('TikTok ·')):
                                                title = potential_title
                                                logging.debug(f"Found title in script data: {title}")
                                                break
                                    
                                    # Approach 2: Look for JSON objects with title
                                    json_matches = re.finditer(r'\{[^{}]*"title"[^{}]*\}', script_text)
                                    for json_match in json_matches:
                                        try:
                                            json_data = json.loads(json_match.group())
                                            if not title and 'title' in json_data:
                                                potential_title = json_data['title'].strip()
                                                if (potential_title and 
                                                    len(potential_title) > 3 and
                                                    potential_title not in ['TikTok', '名無し', 'Untitled'] and
                                                    not potential_title.startswith('TikTok ·')):
                                                    title = potential_title
                                                    break
                                        except (json.JSONDecodeError, TypeError, AttributeError):
                                            continue
                                            
                                    if title:
                                        break
                                        
                                except (json.JSONDecodeError, TypeError, AttributeError):
                                    continue
                
                # Log extracted data for debugging
                logging.debug(f"TikTok Approach {i+1} extraction results: title='{title}', thumbnail='{thumbnail_url}', author='{author_name}'")
                
                # If we found some meaningful metadata, return it
                if title or thumbnail_url or (author_name and len(author_name) > 1):
                    logging.debug(f"Successfully extracted TikTok metadata using approach {i+1}")
                    return {
                        "platform": "tiktok",
                        "unique_video_id": video_id,
                        "title": title,
                        "thumbnailUrl": thumbnail_url,
                        "authorName": author_name
                    }
                
            except Exception as e:
                logging.debug(f"TikTok Approach {i+1} failed: {e}")
                continue
        
        # If all approaches failed, return minimal data
        logging.warning("All TikTok extraction approaches failed")
        
        # Extract username from URL as fallback
        author_name = None
        if url:
            username_match = re.search(r'tiktok\.com/@([^/]+)', url)
            if username_match:
                author_name = f"@{username_match.group(1)}"
        
        return {
            "platform": "tiktok",
            "unique_video_id": video_id,
            "title": None,
            "thumbnailUrl": None,
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
        # Try different Instagram URL formats and approaches
        approaches = [
            # Approach 1: Try embed URL (often has more accessible metadata)
            {
                'url': f"https://www.instagram.com/p/{post_id}/embed/",
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.instagram.com/',
                }
            },
            # Approach 2: Original URL with different headers
            {
                'url': url.replace('?hl=ja', ''),  # Remove language parameter
                'headers': {
                    'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
            },
            # Approach 3: Mobile user agent
            {
                'url': url,
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Cache-Control': 'max-age=0',
                }
            }
        ]
        
        # Try each approach until one works
        for i, approach in enumerate(approaches):
            try:
                logging.debug(f"Trying Instagram approach {i+1}: {approach['url']}")
                response = self.session.get(approach['url'], headers=approach['headers'], timeout=20)
                response.raise_for_status()
                
                # Handle encoding issues by trying different encodings
                content = response.content
                html_text = ""
                
                # Try different encoding methods
                encodings_to_try = ['utf-8', 'iso-8859-1', 'cp1252', 'latin1']
                for encoding in encodings_to_try:
                    try:
                        html_text = content.decode(encoding, errors='ignore')
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                
                if not html_text:
                    html_text = content.decode('utf-8', errors='replace')
                
                soup = BeautifulSoup(html_text, 'html.parser')
                
                # Debug: Log HTML structure for analysis
                title_tag = soup.find('title')
                meta_count = len(soup.find_all('meta'))
                script_count = len(soup.find_all('script'))
                
                logging.debug(f"Approach {i+1} - Title: {title_tag}, Meta: {meta_count}, Scripts: {script_count}")
                
                # Skip if no useful content found
                if meta_count == 0 and script_count == 0 and not title_tag:
                    logging.debug(f"Approach {i+1} returned empty content, trying next...")
                    continue
                
                # Log some meta tags for debugging
                meta_tags = soup.find_all('meta')
                for j, tag in enumerate(meta_tags[:5]):  # Log first 5 meta tags
                    if tag.get('property') or tag.get('name'):
                        logging.debug(f"Approach {i+1} Meta tag {j}: {tag}")
                
                # Extract metadata from meta tags and JSON-LD
                title = None
                thumbnail_url = None
                author_name = None
                
                # Method 1: Try to find JSON-LD structured data
                json_scripts = soup.find_all('script', type='application/ld+json')
                for script in json_scripts:
                    try:
                        if script.string:
                            json_data = json.loads(script.string)
                            if isinstance(json_data, dict):
                                # Extract from structured data
                                if 'name' in json_data:
                                    title = json_data.get('name')
                                if 'image' in json_data:
                                    image_data = json_data.get('image')
                                    if isinstance(image_data, list) and image_data:
                                        thumbnail_url = image_data[0]
                                    elif isinstance(image_data, str):
                                        thumbnail_url = image_data
                                if 'author' in json_data:
                                    author_data = json_data.get('author')
                                    if isinstance(author_data, dict) and 'name' in author_data:
                                        author_name = author_data['name']
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        continue
                
                # Method 2: Extract from meta tags
                if not title:
                    title_tag = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'title'})
                    if title_tag:
                        title_content = title_tag.get('content')
                        if title_content:
                            title = title_content.strip()
                            # Instagram titles often contain author info
                            if ' • Instagram' in title:
                                parts = title.split(' • Instagram')
                                title = parts[0].strip()
                            if ' on Instagram:' in title:
                                author_name = title.split(' on Instagram:')[0].strip()
                                if ': "' in title:
                                    title = title.split(': "')[1].rstrip('"').strip()
                
                # Method 3: Try description meta tag
                if not title:
                    description_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', property='og:description')
                    if description_tag:
                        description = description_tag.get('content')
                        if description and description.strip():
                            title = description.strip()
                
                # Method 4: Extract thumbnail from various meta tags
                if not thumbnail_url:
                    image_tags = [
                        soup.find('meta', property='og:image'),
                        soup.find('meta', attrs={'name': 'twitter:image'}),
                        soup.find('meta', property='og:image:secure_url'),
                        soup.find('meta', attrs={'name': 'thumbnail'})
                    ]
                    for tag in image_tags:
                        if tag and tag.get('content'):
                            thumbnail_url = tag.get('content').strip()
                            break
                
                # Method 5: Extract author name from URL if not found elsewhere
                if not author_name:
                    username_match = re.search(r'instagram\.com/([^/]+)/', url)
                    if username_match:
                        author_name = username_match.group(1)
                
                # Log extracted data for debugging
                logging.debug(f"Approach {i+1} extraction results: title='{title}', thumbnail='{thumbnail_url}', author='{author_name}'")
                
                # If we found some metadata, return it
                if title or thumbnail_url or (author_name and author_name != username_match.group(1) if username_match else True):
                    logging.debug(f"Successfully extracted metadata using approach {i+1}")
                    return {
                        "platform": "instagram",
                        "unique_video_id": post_id,
                        "title": title,
                        "thumbnailUrl": thumbnail_url,
                        "authorName": author_name
                    }
                
            except Exception as e:
                logging.debug(f"Approach {i+1} failed: {e}")
                continue
        
        # If all approaches failed, return minimal data
        logging.warning("All Instagram extraction approaches failed")
        author_name = None
        if url:
            username_match = re.search(r'instagram\.com/([^/]+)/', url)
            if username_match:
                author_name = username_match.group(1)
        
        return {
            "platform": "instagram",
            "unique_video_id": post_id,
            "title": None,
            "thumbnailUrl": None,
            "authorName": author_name
        }
    
    def _is_youtube_playlist(self, url: str) -> bool:
        """Check if the URL is a YouTube playlist"""
        return "list=" in url.lower() and ("youtube.com" in url.lower() or "youtu.be" in url.lower())
    
    def _extract_youtube_playlist_metadata(self, url: str) -> dict:
        """Extract metadata from YouTube playlist URLs"""
        logging.info(f"Extracting YouTube playlist metadata from: {url}")
        
        # Extract playlist ID
        playlist_id = self._extract_playlist_id(url)
        if not playlist_id:
            raise ValueError("Could not extract YouTube playlist ID from URL")
        
        # Check if YouTube API key is available
        if not self.youtube_api_key:
            raise ValueError("YouTube API key is required for playlist processing")
        
        # Get playlist videos using YouTube Data API
        return self._get_youtube_playlist_videos(playlist_id)
    
    def _extract_playlist_id(self, url: str) -> str:
        """Extract YouTube playlist ID from URL"""
        if "list=" in url:
            # Extract everything after 'list='
            parts = url.split('list=')
            if len(parts) > 1:
                # Get the playlist ID (everything up to the next & or end of string)
                playlist_id = parts[1].split('&')[0]
                return playlist_id
        return ""
    
    def _get_youtube_playlist_videos(self, playlist_id: str) -> dict:
        """Get videos from YouTube playlist using YouTube Data API"""
        api_url = "https://www.googleapis.com/youtube/v3/playlistItems"
        params = {
            'part': 'snippet',
            'playlistId': playlist_id,
            'key': self.youtube_api_key,
            'maxResults': 50  # Maximum 50 videos as specified in the requirements
        }
        
        response = self.session.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('items'):
            raise ValueError("Playlist not found or is empty")
        
        # Extract video IDs for batch API call
        video_ids = []
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            video_id = snippet.get('resourceId', {}).get('videoId')
            if video_id:
                video_ids.append(video_id)
        
        # Get detailed video information including author names
        video_details = self._get_videos_details_batch(video_ids)
        
        # Extract video list with author information
        video_list = []
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            video_id = snippet.get('resourceId', {}).get('videoId')
            if video_id:
                # Get author name from detailed video info
                video_detail = video_details.get(video_id, {})
                
                video_info = {
                    'title': snippet.get('title'),
                    'videoUrl': f"https://www.youtube.com/watch?v={video_id}",
                    'thumbnailUrl': snippet.get('thumbnails', {}).get('high', {}).get('url'),
                    'unique_video_id': video_id,
                    'authorName': video_detail.get('authorName')
                }
                video_list.append(video_info)
        
        # Get playlist info from the first item
        first_item = data['items'][0]['snippet'] if data['items'] else {}
        playlist_title = first_item.get('channelTitle', 'YouTube Playlist')
        
        return {
            "platform": "youtube_playlist",
            "unique_video_id": playlist_id,
            "title": f"プレイリスト: {playlist_title}",
            "thumbnailUrl": video_list[0].get('thumbnailUrl') if video_list else None,
            "authorName": first_item.get('channelTitle'),
            "playlist_videos": video_list,
            "video_count": len(video_list)
        }
    
    def _get_videos_details_batch(self, video_ids: list) -> dict:
        """Get detailed information for multiple videos in a batch request"""
        if not video_ids:
            return {}
        
        # YouTube API allows up to 50 video IDs per request
        api_url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            'part': 'snippet',
            'id': ','.join(video_ids),
            'key': self.youtube_api_key
        }
        
        response = self.session.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # Create a dictionary mapping video_id to video details
        video_details = {}
        for item in data.get('items', []):
            video_id = item.get('id')
            snippet = item.get('snippet', {})
            if video_id:
                video_details[video_id] = {
                    'authorName': snippet.get('channelTitle'),
                    'title': snippet.get('title'),
                    'thumbnailUrl': snippet.get('thumbnails', {}).get('high', {}).get('url')
                }
        
        return video_details

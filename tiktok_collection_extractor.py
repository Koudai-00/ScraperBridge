import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

class TikTokCollectionExtractor:
    def __init__(self):
        # Increased timeouts for loading and scrolling heavy collections
        self.navigation_timeout = 30000  # 30 seconds
        self.scroll_timeout = 60000      # 60 seconds total for scrolling
        
    def extract_collection(self, url):
        """
        Extracts all video URLs from a TikTok shared collection.
        Uses Playwright to render the page and infinite scroll to load all videos.
        """
        if not url or "tiktok.com" not in url or "/collection/" not in url:
            return {
                "success": False,
                "error": "Invalid TikTok collection URL provided."
            }

        videos = []
        try:
            with sync_playwright() as p:
                # Launch a headful or headless browser (headless often works, but some bot protection prefers headful)
                # We start with headless=True as requested for Cloud Run.
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--window-size=1920,1080'
                    ]
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = context.new_page()
                
                # Apply stealth plugin to avoid detection
                Stealth().apply_stealth_sync(page)

                logger.info(f"Navigating to TikTok collection: {url}")
                page.goto(url, wait_until="networkidle", timeout=self.navigation_timeout)
                
                # Wait briefly to ensure UI components are loaded
                page.wait_for_timeout(2000)
                
                # Infinite scroll implementation to load all videos
                logger.info("Starting infinite scroll to load all videos in the collection...")
                previous_height = page.evaluate("document.body.scrollHeight")
                
                scroll_count = 0
                max_scrolls = 20 # Guardrails to prevent infinite loop
                
                while scroll_count < max_scrolls:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    # Wait for network idle or a specific time for new items to load
                    page.wait_for_timeout(2000)
                    
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == previous_height:
                        logger.info("Reached the bottom of the collection or no new items loaded.")
                        break
                        
                    previous_height = new_height
                    scroll_count += 1
                
                logger.info(f"Completed {scroll_count} scrolls. Extracting video links...")
                
                # Extract all 'a' tags with href containing '/video/'
                # Using a generic CSS selector as TikTok classes change frequently
                link_elements = page.query_selector_all('a[href*="/video/"]')
                
                for el in link_elements:
                    href = el.get_attribute('href')
                    if href:
                        # Extract the clean URL, stripping any query parameters
                        clean_url = href.split('?')[0]
                        # Ensure it's absolute
                        if clean_url.startswith('/'):
                            clean_url = 'https://www.tiktok.com' + clean_url
                        
                        if clean_url not in videos:
                            videos.append(clean_url)

                browser.close()
                
            logger.info(f"Successfully extracted {len(videos)} videos from collection.")
            
            return {
                "success": True,
                "collection_url": url,
                "total_videos": len(videos),
                "videos": videos
            }
            
        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout extracting TikTok collection: {str(e)}")
            return {
                "success": False,
                "error": "The request timed out. This may happen if the collection is very large or TikTok is blocking access."
            }
        except Exception as e:
            logger.error(f"Error extracting TikTok collection: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to extract videos from the collection. Error: {str(e)}"
            }

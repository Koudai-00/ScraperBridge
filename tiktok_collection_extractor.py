import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

class TikTokCollectionExtractor:
    def __init__(self):
        # Timeouts adjusted for robustness and Cloud Run limits
        self.navigation_timeout = 20000  # 20 seconds
        self.scroll_wait = 2000          # 2 seconds between scrolls
        self.max_scrolls = 15            # Enough for most collections
        self.total_timeout = 120         # 2 minutes total guardrail
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

                logger.info(f"Navigating to TikTok collection (wait_until=domcontentloaded): {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout)
                
                # Check for captcha or blocking page
                page.wait_for_timeout(3000)
                page_content = page.content().lower()
                if "verify" in page_content and ("human" in page_content or "captcha" in page_content):
                    logger.error("TikTok block detected: Captcha/Verification required.")
                    return {
                        "success": False,
                        "error": "Access was blocked by TikTok (Captcha required). Please try again later or use a proxy."
                    }
                
                # Infinite scroll implementation to load all videos
                logger.info("Starting infinite scroll extraction...")
                previous_video_count = 0
                
                scroll_count = 0
                start_time = time.time()
                
                while scroll_count < self.max_scrolls:
                    # Check for total timeout
                    if time.time() - start_time > self.total_timeout:
                        logger.warning("Extraction reached total timeout guardrail.")
                        break

                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(self.scroll_wait)
                    
                    # Instead of just height, check if we found more videos
                    current_videos = page.query_selector_all('a[href*="/video/"]')
                    current_count = len(current_videos)
                    
                    logger.info(f"Scroll {scroll_count + 1}: Found {current_count} videos.")
                    
                    if current_count == previous_video_count and current_count > 0:
                        # We might have reached the end if count didn't increase
                        # Wait one more time just to be sure
                        page.wait_for_timeout(1000)
                        current_videos = page.query_selector_all('a[href*="/video/"]')
                        if len(current_videos) == current_count:
                            logger.info("No more videos loading. Stopping scroll.")
                            break
                        
                    previous_video_count = current_count
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

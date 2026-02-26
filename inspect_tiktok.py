from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

def inspect_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        
        url = "https://www.tiktok.com/@recipe.pocket/collection/料理-7223156686599572226?is_from_webapp=1&sender_device=pc"
        print(f"Opening {url}...")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        # Look for JSON data in script tags
        scripts = page.query_selector_all('script')
        for i, script in enumerate(scripts):
            content = script.inner_text()
            if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in content or "SIGI_STATE" in content:
                print(f"Found potential JSON data in script tag {i}")
                with open(f"tiktok_script_{i}.json", "w", encoding="utf-8") as f:
                    f.write(content)
        
        # Save HTML for analysis
        with open("tiktok_debug.html", "w", encoding="utf-8") as f:
            f.write(page.content())
            
        browser.close()

if __name__ == "__main__":
    inspect_html()

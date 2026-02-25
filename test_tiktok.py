import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from tiktok_collection_extractor import TikTokCollectionExtractor

def test():
    extractor = TikTokCollectionExtractor()
    url = "https://www.tiktok.com/@recipe.pocket/collection/料理-7223156686599572226?is_from_webapp=1&sender_device=pc"
    print(f"Testing url: {url}")
    result = extractor.extract_collection(url)
    print("Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test()

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from fastapi.middleware.cors import CORSMiddleware
import urllib.parse
import re
import json
import traceback # エラーの詳細を表示するためにインポート

app = FastAPI()
# (CORS設定などは変更なし)
origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# (データモデル定義は変更なし)
class URLRequest(BaseModel): url: str
class MetaDataResponse(BaseModel): platform: str; title: str | None = None; thumbnailUrl: str | None = None; authorName: str | None = None
class PlaylistItem(BaseModel): title: str; videoUrl: str; thumbnailUrl: str | None = None
class PlaylistResponse(BaseModel): videos: list[PlaylistItem]
class MetaDataResponseV2(BaseModel): platform: str; unique_video_id: str | None = None; title: str | None = None; thumbnailUrl: str | None = None; authorName: str | None = None

# (ヘルパー関数は変更なし)
def extract_youtube_id(url: str):
    patterns = [r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', r'youtu\.be\/([0-9A-Za-z_-]{11}).*']
    for p in patterns:
        if m := re.search(p, url): return m.group(1)
    return None
def extract_instagram_id(url: str):
    clean_url = url.split('?')[0]
    if m := re.search(r'\/(p|reel)\/([A-Za-z0-9-_]+)', clean_url): return m.group(2)
    return None
def extract_tiktok_id(url: str):
    clean_url = url.split('?')[0]
    if m := re.search(r'\/video\/(\d+)', clean_url): return m.group(1)
    return None

@app.post("/api/v2/get-metadata", response_model=MetaDataResponseV2)
def get_metadata_v2(request: URLRequest):
    url = request.url

    # --- TikTok (超詳細デバッグモード) ---
    if "tiktok.com" in url:
        print("\n--- TIKTOK DEBUG START ---")
        try:
            print(f"[1] Received URL from App: '{url}'")

            final_url = url
            if "vt.tiktok.com" in url or "vm.tiktok.com" in url:
                print("[1.1] Short URL detected. Resolving...")
                head_response = requests.head(url, allow_redirects=True, timeout=10)
                head_response.raise_for_status()
                final_url = head_response.url

            print(f"[2] Resolved Final URL: '{final_url}'")

            video_id = extract_tiktok_id(final_url)
            if not video_id:
                print(f"[!!!] FAILED at step 3: Could not extract video ID from '{final_url}'.")
                raise HTTPException(status_code=400, detail="Could not extract TikTok video ID.")

            print(f"[3] Extracted Video ID: '{video_id}'")

            if not SUPABASE_URL or not SUPABASE_ANON_KEY:
                print("[!!!] FAILED at step 4: Supabase secrets not found.")
                raise HTTPException(status_code=500, detail="Supabase env vars not configured.")

            supabase_function_url = f"{SUPABASE_URL}/functions/v1/video-metadata"
            headers = {"Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
            body = {"url": final_url} # Bodyをdictとして作成

            print(f"[4] Calling Supabase Function URL: '{supabase_function_url}'")
            print(f"[5] Sending JSON to Supabase: {body}")

            response = requests.post(supabase_function_url, headers=headers, json=body, timeout=20)

            print(f"[6] Received from Supabase - Status: {response.status_code}, Raw Body: '{response.text}'")
            response.raise_for_status()

            data = response.json()
            print(f"[7] Parsed Supabase Response Data: {data}")

            print("--- TIKTOK DEBUG END (Success) ---")
            return MetaDataResponseV2(
                platform="tiktok", unique_video_id=video_id,
                title=data.get("title"), thumbnailUrl=data.get("thumbnailUrl"), authorName=data.get("authorName"),
            )
        except Exception as e:
            print(f"[!!!] AN ERROR OCCURRED: {e}")
            traceback.print_exc() # Pythonの生々しいエラーを全て表示
            print("--- TIKTOK DEBUG END (Failure) ---")
            raise HTTPException(status_code=500, detail=f"Internal Server Error while processing TikTok URL: {str(e)}")

    # (YouTubeとInstagramの処理は、調査のため一時的に簡略化します)
    elif "youtube.com" in url or "youtu.be" in url:
        return MetaDataResponseV2(platform="youtube", unique_video_id="test_yt_id", title="YT Test", thumbnailUrl="", authorName="YT Author")
    elif "instagram.com" in url:
        return MetaDataResponseV2(platform="instagram", unique_video_id="test_ig_id", title="IG Test", thumbnailUrl="", authorName="IG Author")
    else:
        return MetaDataResponseV2(platform="other", unique_video_id=url, title="Other", thumbnailUrl="", authorName="")

# (v1のコードはデバッグ中は不要ですが、安全のため残します)
@app.post("/api/get-metadata", response_model=MetaDataResponse)
def get_metadata_v1(request: URLRequest): return {}
@app.post("/api/get-videos-from-playlist", response_model=PlaylistResponse)
def get_playlist_v1(request: URLRequest): return {}
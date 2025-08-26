import { createClient } from 'npm:@supabase/supabase-js@2.39.7';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

// --- あなたの既存のコード (変更なし) ---
interface VideoMetadata { /* ... */ }
async function getYouTubeMetadata(url: string): Promise<VideoMetadata> { /* ... */ }
async function getInstagramMetadata(url: string): Promise<VideoMetadata> { /* ... */ }
// --- あなたの既存のコード (ここまで) ---

// ★★★ ここからが修正箇所です ★★★
async function getTikTokMetadata(url: string): Promise<VideoMetadata> {
  try {
    // 1. URLから不要なパラメータを完全に削除する
    const cleanUrl = url.split('?')[0];
    const oembedUrl = `https://www.tiktok.com/oembed?url=${encodeURIComponent(cleanUrl)}`;

    // 2.【決定的な修正】成功した時と全く同じ「本物の名刺」
    const response = await fetch(oembedUrl, {
      headers: {
        'User-Agent': 'Expo/1017721 CFNetwork/3826.600.41 Darwin/24.6.0'
      }
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[DEBUG] TikTok oEmbed API Error for URL (${cleanUrl}). Status: ${response.status}. Body: ${errorText}`);
      throw new Error('Failed to fetch TikTok metadata');
    }
    
    const data = await response.json();
    
    return {
      platform: 'tiktok',
      title: data.title || '',
      thumbnailUrl: data.thumbnail_url || '',
      authorName: data.author_name || '',
      authorIconUrl: null,
    };
  } catch (error) {
    console.error('TikTok metadata error:', error);
    throw new Error('TikTok動画の情報取得に失敗しました');
  }
}
// ★★★ ここまでが修正箇所です ★★★

function getVideoSource(url: string): string {
  // (あなたの元のコードのまま)
  const hostname = new URL(url).hostname.toLowerCase();
  if (hostname.includes('youtube.com') || hostname.includes('youtu.be')) { return 'youtube'; }
  else if (hostname.includes('instagram.com')) { return 'instagram'; }
  else if (hostname.includes('tiktok.com')) { return 'tiktok'; }
  throw new Error('サポートされていないプラットフォームです');
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  // --- 調査ログ (リクエスト受付) ---
  console.log("\n--- NEW REQUEST RECEIVED ---");
  const headersObject = Object.fromEntries(req.headers);
  console.log("INCOMING HEADERS:", JSON.stringify(headersObject, null, 2));

  try {
    const body = await req.json();
    console.log("INCOMING BODY:", body);
    
    const { url } = body;
    if (!url) { throw new Error('URLが必要です'); }
    
    console.log("--- STARTING METADATA FETCH ---");
    const platform = getVideoSource(url);
    let metadata: VideoMetadata;
    
    switch (platform) {
      case 'youtube': metadata = await getYouTubeMetadata(url); break;
      case 'instagram': metadata = await getInstagramMetadata(url); break;
      case 'tiktok': metadata = await getTikTokMetadata(url); break;
      default: throw new Error('サポートされていないプラットフォームです');
    }
    
    console.log("--- METADATA FETCH SUCCESSFUL ---");
    return new Response(JSON.stringify(metadata), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
  } catch (error) {
    console.error("--- FUNCTION FAILED ---");
    console.error("ERROR DETAILS:", error);
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  } finally {
    console.log("--- REQUEST PROCESSING FINISHED ---\n");
  }
});
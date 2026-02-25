# TikTok共有コレクション一括保存機能 実装計画（サーバーサイド編）

本ドキュメントは、TikTokのShared Collection（共有コレクション）のURLを受け取り、それに含まれる全ての動画URLを一括で抽出してアプリに返す新機能（Scraperbridgeサーバー側の実装）の方針をまとめたものです。

## 1. 処理のフロー（全体像）

アプリとサーバー間の連携を含めた、ユーザー操作から保存完了までの全体フローは以下の通りです。

1. **[アプリ]** ユーザーが共有コレクションのURL（例: `https://www.tiktok.com/@.../collection/...`）を入力し、ボタンを押す。
2. **[アプリ]** 新規エンドポイント `POST /api/extract-tiktok-collection` へURLを送信する。
3. **[サーバー]** Node.jsのヘッドレスブラウザ（Puppeteer Stealth）を内部で起動する。
4. **[サーバー]** TikTokの対象URLへアクセスする。人間のように見せかけるため、画面最下部まで自動スクロールを行う。
5. **[サーバー]** 読み込まれたHTML要素の中から、特定の要素クラスに依存せず、すべての `a` タグのうち `href` に `/video/` が含まれるリンクを収集・重複を除去する。
6. **[サーバー]** 抽出した動画URLのリスト（配列）をJSONとしてアプリに返却する。（ヘッドレスブラウザ終了）
7. **[アプリ]** サーバーから受け取ったURLリストを元に、既存の動画情報取得用エンドポイント（`POST /api/v2/get-metadata`）を1件ずつ順番に呼び出し、タイトルやサムネイルを取得する。
8. **[アプリ]** 取得した動画情報をユーザー確認画面へ表示し、OKが出たらデータベース（Supabase等）へ一括保存する。

---

## 2. 各処理に使用する技術と詳細内容

サーバー（Scraperbridge）上で安全かつ確実にURLを抽出するための技術スタックとアルゴリズムです。

### 2.1 技術スタック
*   **稼働環境:** Google Cloud Run (Node.js環境)
    *   ※ Cloud Runコンテナ内でChromeブラウザを起動するため、Dockerfileへの関連パッケージ（フォントや依存ライブラリ）の追加が必要です。
*   **ブラウザ自動化:** `puppeteer-core` (または `puppeteer`)
*   **Bot検知回避:** `puppeteer-extra`, `puppeteer-extra-plugin-stealth`
    *   TikTokのキャプチャ（スライダー認証など）やデータ隠蔽システムを回避するための必須プラグインです。

### 2.2 抽出アルゴリズムの工夫点
今回、TikTokのHTML構造変化に負けないように以下の単純な手法を取ります。
*   **ターゲット要素:** `div[data-e2e="..."]` のような名前はコロコロ変わるため無視します。
*   **抽出ルール:** `document.querySelectorAll('a[href*="/video/"]')` を使い、動画のリンクURLだけを無差別に拾い集めます。
*   **自動スクロール処理:** 画面下部に到達するごとに自動で次の動画がロードされる「無限スクロール」に対応するため、`window.scrollBy` を使って最下部まで数回スクロールするスクリプトをブラウザ内で走らせます。

---

## 3. リクエスト形式とレスポンス形式

アプリと Scraperbridge サーバー間の API 仕様です。

### 3.1 エンドポイント
`POST /api/extract-tiktok-collection`

### 3.2 リクエスト (Request)
```json
{
  "url": "https://www.tiktok.com/@recipe.pocket/collection/料理-7223156686599572226?is_from_webapp=1&sender_device=pc"
}
```

### 3.3 レスポンス (Response)

**成功時 (200 OK)**
```json
{
  "success": true,
  "collection_url": "https://www.tiktok.com/@recipe.pocket/collection/料理-...",
  "total_videos": 29,
  "videos": [
    "https://www.tiktok.com/@recipe.pocket/video/7223156686599572226",
    "https://www.tiktok.com/@recipe.pocket/video/1234567890123456789",
    // ... 29件分のURL
  ]
}
```

**失敗時 (400 Bad Request / 500 Internal Server Error など)**
```json
{
  "success": false,
  "error": "Failed to extract videos from the collection. The page might have been blocked by a captcha."
}
```

---

## 4. その他実装に必要な情報（注意点・懸念点）

### 4.1 Cloud Run (Scraperbridge) 環境設定について
Puppeteerを起動するためには、現在のCloud Runコンテナ（Dockerfile）にChromeを実行するための依存ライブラリ群を含める必要があります。現在軽量なAlpine Linuxなどを使っている場合は、Puppeteer用の設定調整が発生します。

### 4.2 APIのタイムアウト設定
一括取得処理では、Puppeteerの起動、ページロード、さらに画面最下部への自動スクロールが走るため、通常のAPI（1〜2秒）よりもはるかに時間がかかります。
*   **処理時間の目安:** 10件なら数秒ですが、50〜100件のコレクションになると**10秒〜20秒**かかる場合があります。
*   **対策:** アプリ側の `fetch` のタイムアウト設定（現状 `10000` = 10秒等）を長く取るか、Cloud Run側の設定でリクエストタイムアウト時間を長めに設定しておく必要があります。

### 4.3 「アクセスブロック」への対策と段階的導入
テスト報告でも挙げた通り、同じGoogle CloudのIPから短期間に何度もPuppeteerでアクセスすると、TikTok側に「これはボットだ」と見破られ、アクセスが完全にブロックされるリスクがあります。
*   **初期フェーズ:** まずは現在のサーバー（Cloud Run）から**普通のIP（プロキシなし）**で実装してリリースし、ユーザー数（アクセス頻度）に耐えられるか様子を見ることをお勧めします。
*   **将来の拡張:** 万が一ブロックが多発する（真っ白な画面になってURLが1件も取れない状態が続く）ようになった場合は、**「BrightData等のプロキシサービス」**を利用して毎回IPアドレスを散らす処理をコードに追加するフェーズへ移行します。

/**
 * GAS単体でX（Twitter）へ画像付き自動投稿
 * - Google Sheets でキュー管理
 * - Google Drive に画像を保存
 * - GASのトリガーでスケジュール実行（PCオフでも動作）
 *
 * 【Sheets の列構成】
 * A: 投稿テキスト
 * B: Google Drive ファイルID（画像。不要なら空欄）
 * C: ステータス（空欄 or "投稿済み"）
 * D: 投稿日時（自動記入）
 * E: 投稿URL（自動記入）
 * F: 投稿希望スロット（例: "21時（夜）"）
 */

// 現在時刻に対応するスロットラベルを返す
function getCurrentSlotLabel() {
  const now  = new Date();
  const hour = parseInt(Utilities.formatDate(now, "Asia/Tokyo", "H"), 10);
  // GASトリガーは±1時間の誤差があるため、前後1時間を含む範囲で判定
  const slots = [
    { hours: [5, 6, 7],   label: "06時（朝）" },
    { hours: [11, 12, 13], label: "12時（昼）" },
    { hours: [14, 15, 16], label: "15時（放課後）" },
    { hours: [17, 18, 19], label: "18時（夕方）" },
    { hours: [20, 21, 22], label: "21時（夜）" },
    { hours: [23, 0, 1],   label: "00時（深夜）" },
  ];
  for (const s of slots) {
    if (s.hours.includes(hour)) return s.label;
  }
  return null; // 対応スロットなし
}

// ── 認証情報（スクリプトプロパティに設定）─────────────────────────────
function getCredentials() {
  const props = PropertiesService.getScriptProperties();
  return {
    apiKey:            props.getProperty("X_API_KEY"),
    apiSecret:         props.getProperty("X_API_SECRET"),
    accessToken:       props.getProperty("X_ACCESS_TOKEN"),
    accessTokenSecret: props.getProperty("X_ACCESS_TOKEN_SECRET"),
  };
}


// ── メイン投稿関数 ────────────────────────────────────────────────────
function postToX() {
  const sheet      = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Queue");
  const data       = sheet.getDataRange().getValues();
  const slotLabel  = getCurrentSlotLabel();

  Logger.log(`現在のスロット: ${slotLabel || "（対象外）"}`);

  // 同じ時間帯の未投稿行をすべて収集してランダムに1件選ぶ
  const candidates = [];
  for (let i = 1; i < data.length; i++) {
    const text    = data[i][0];
    const status  = data[i][2];
    const rowSlot = data[i][5];
    if (!text || status === "投稿済み") continue;
    if (rowSlot && slotLabel && rowSlot !== slotLabel) continue;
    candidates.push(i);
  }

  if (candidates.length === 0) {
    Logger.log("投稿対象なし（未投稿 & スロット一致の行がありません）");
    return;
  }

  // ランダムに1件選択
  const i = candidates[Math.floor(Math.random() * candidates.length)];
  const text    = data[i][0];
  const driveId = data[i][1];

  {
    try {
      // 画像アップロード（Drive IDがある場合）
      let mediaId = null;
      if (driveId) {
        mediaId = uploadImageFromDrive(driveId);
      }

      // ツイート投稿
      const tweetId = createTweet(text, mediaId);

      // Sheets を更新
      const now = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy/MM/dd HH:mm");
      sheet.getRange(i + 1, 3).setValue("投稿済み");
      sheet.getRange(i + 1, 4).setValue(now);
      sheet.getRange(i + 1, 5).setValue(`https://x.com/i/web/status/${tweetId}`);

      Logger.log(`投稿完了[${data[i][5] || "スロット未指定"}]: ${text.substring(0, 30)}...`);

      // 投稿成功後にGoogle Driveから画像を削除
      if (driveId) {
        try {
          DriveApp.getFileById(driveId).setTrashed(true);
          Logger.log(`Drive画像削除完了: ${driveId}`);
        } catch (delErr) {
          Logger.log(`Drive削除スキップ（投稿は成功）: ${delErr.message}`);
        }
      }

    } catch (e) {
      Logger.log(`エラー: ${e.message}`);
      sheet.getRange(i + 1, 3).setValue(`エラー: ${e.message}`);
    }
  }
}


// ── Google Drive から画像をアップロード ──────────────────────────────
function uploadImageFromDrive(fileId) {
  const file   = DriveApp.getFileById(fileId);
  const blob   = file.getBlob();
  const base64 = Utilities.base64Encode(blob.getBytes());

  const url    = "https://upload.twitter.com/1.1/media/upload.json";
  const params = { media_data: base64 };
  const creds  = getCredentials();

  const auth = buildOAuthHeader("POST", url, params, creds);

  const response = UrlFetchApp.fetch(url, {
    method:            "POST",
    headers:           { Authorization: auth },
    payload:           params,
    muteHttpExceptions: true,
  });

  const result = JSON.parse(response.getContentText());
  if (!result.media_id_string) {
    throw new Error(`画像アップロード失敗: ${response.getContentText()}`);
  }
  return result.media_id_string;
}


// ── ツイート投稿（v2 API）────────────────────────────────────────────
function createTweet(text, mediaId) {
  const url   = "https://api.x.com/2/tweets";
  const creds = getCredentials();
  const auth  = buildOAuthHeader("POST", url, {}, creds);

  const body = { text };
  if (mediaId) body.media = { media_ids: [mediaId] };

  const response = UrlFetchApp.fetch(url, {
    method:  "POST",
    headers: {
      Authorization:  auth,
      "Content-Type": "application/json",
    },
    payload:           JSON.stringify(body),
    muteHttpExceptions: true,
  });

  const result = JSON.parse(response.getContentText());
  if (!result.data?.id) {
    throw new Error(`ツイート失敗: ${response.getContentText()}`);
  }
  return result.data.id;
}


// ── OAuth 1.0a ヘッダー生成 ──────────────────────────────────────────
function buildOAuthHeader(method, url, extraParams, creds) {
  const oauthParams = {
    oauth_consumer_key:     creds.apiKey,
    oauth_nonce:            Utilities.getUuid().replace(/-/g, ""),
    oauth_signature_method: "HMAC-SHA1",
    oauth_timestamp:        Math.floor(Date.now() / 1000).toString(),
    oauth_token:            creds.accessToken,
    oauth_version:          "1.0",
  };

  // 署名対象パラメータをマージ・ソート
  const allParams = Object.assign({}, extraParams, oauthParams);
  const paramString = Object.keys(allParams)
    .sort()
    .map(k => `${pEnc(k)}=${pEnc(allParams[k])}`)
    .join("&");

  const signatureBase = [method, pEnc(url), pEnc(paramString)].join("&");
  const signingKey    = `${pEnc(creds.apiSecret)}&${pEnc(creds.accessTokenSecret)}`;

  const signature = Utilities.base64Encode(
    Utilities.computeHmacSignature(
      Utilities.MacAlgorithm.HMAC_SHA_1,
      signatureBase,
      signingKey
    )
  );

  oauthParams.oauth_signature = signature;

  return "OAuth " + Object.keys(oauthParams)
    .sort()
    .map(k => `${pEnc(k)}="${pEnc(oauthParams[k])}"`)
    .join(", ");
}

// RFC 3986 エンコード
function pEnc(str) {
  return encodeURIComponent(String(str))
    .replace(/!/g, "%21").replace(/'/g, "%27")
    .replace(/\(/g, "%28").replace(/\)/g, "%29")
    .replace(/\*/g, "%2A");
}


// ── トリガー設定（初回1回だけ実行）─────────────────────────────────
function setupTriggers() {
  // 既存のpostToXトリガーを削除
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "postToX") ScriptApp.deleteTrigger(t);
  });

  // 時刻をずらして設定（毎日同じ時刻にならないよう nearMinute でオフセット）
  // nearMinute は指定分の ±15分 以内に実行される
  const schedule = [
    { hour: 6,  minute: 20 },  // 06:05〜06:35 の間
    { hour: 12, minute: 10 },  // 11:55〜12:25 の間
    { hour: 15, minute: 40 },  // 15:25〜15:55 の間
    { hour: 18, minute: 15 },  // 18:00〜18:30 の間
    { hour: 21, minute: 50 },  // 21:35〜22:05 の間
    { hour: 0,  minute: 25 },  // 00:10〜00:40 の間
  ];

  schedule.forEach(({ hour, minute }) => {
    ScriptApp.newTrigger("postToX")
      .timeBased()
      .everyDays(1)
      .atHour(hour)
      .nearMinute(minute)
      .inTimezone("Asia/Tokyo")
      .create();
  });

  Logger.log("postToXトリガー設定完了（6件・時刻オフセット済み）");
}


// ── テスト用：手動で1件投稿 ──────────────────────────────────────────
function testPost() {
  const creds = getCredentials();
  const tweetId = createTweet("テスト投稿です。自動投稿システムの動作確認中📸", null);
  Logger.log(`テスト投稿完了: https://x.com/i/web/status/${tweetId}`);
}


// =============================================================
// ===== Threads 自動投稿 =======================================
// =============================================================

// 初期トークン（初回のみ使用。以降はScript Propertiesに保存した値を使う）
const THREADS_TOKEN_INITIAL = "THAAVoZAI8IN3JBUVM4NEc4aUJNOHktV0NJSFFQRVphQzh5bUZALTUJlUnVidDczaFc5d3JxOHFpOEU1SlZAhelZACV0l4bnRTVExCY0ZAwMEgwbWtNZA1lCUEpuZAy04ZA2VDUk56TFR1NV9sZA0hNWVh6WXk2Y2FEb1NVNkJudGhrX3BFWUFBa21yb0RqbUZAlWWZAjaWsZD";
const DISCORD_WEBHOOK       = "https://discordapp.com/api/webhooks/1482643050126774442/yxwb31MOFBbkkO1oerwLLOlYksRH6yt3OlaY0uIBrsgSXXRt7it34HMB_5CrbFhY_Zhr";

/** 現在有効なThreadsトークンを返す（Script Properties優先） */
function getThreadsToken() {
  const saved = PropertiesService.getScriptProperties().getProperty("THREADS_ACCESS_TOKEN");
  return saved || THREADS_TOKEN_INITIAL;
}

/** Discordへ通知を送る */
function notifyDiscord(message) {
  try {
    UrlFetchApp.fetch(DISCORD_WEBHOOK, {
      method:      "post",
      contentType: "application/json",
      payload:     JSON.stringify({ content: message }),
      muteHttpExceptions: true,
    });
  } catch (e) {
    Logger.log("Discord通知失敗: " + e.message);
  }
}

/**
 * Threadsアクセストークンを自動更新する
 * - 30日ごとのトリガーで呼び出す
 * - 更新後はScript Propertiesに保存 → GAS再デプロイ不要
 * - 成功/失敗をDiscordに通知
 */
function refreshThreadsToken() {
  const currentToken = getThreadsToken();
  const url = "https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=" + currentToken;

  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  const json = JSON.parse(resp.getContentText());

  if (json.access_token) {
    PropertiesService.getScriptProperties().setProperty("THREADS_ACCESS_TOKEN", json.access_token);
    // キャッシュをクリア（次回取得時に新トークンを使わせる）
    CacheService.getScriptCache().remove("THREADS_USER_ID");
    const days = Math.floor((json.expires_in || 5184000) / 86400);
    Logger.log("Threadsトークン更新成功。有効期限: " + days + "日後");
    notifyDiscord("✅ Threadsアクセストークンを自動更新しました（有効期限: " + days + "日）");
  } else {
    Logger.log("Threadsトークン更新失敗: " + resp.getContentText());
    notifyDiscord("⚠️ **Threadsトークン自動更新に失敗しました！**\nMeta Developerで手動更新が必要です。\nhttps://developers.facebook.com/apps/1522155989251954/");
  }
}

/** Threadsトークン自動更新トリガーを設定（初回1回だけ実行） */
function setupThreadsTokenRefreshTrigger() {
  // 既存の更新トリガーを削除
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "refreshThreadsToken") ScriptApp.deleteTrigger(t);
  });

  // 30日ごとに自動更新
  ScriptApp.newTrigger("refreshThreadsToken")
    .timeBased()
    .everyDays(30)
    .atHour(9)
    .inTimezone("Asia/Tokyo")
    .create();

  Logger.log("Threadsトークン自動更新トリガー設定完了（30日ごと）");
  notifyDiscord("🔧 Threadsトークン自動更新トリガーを設定しました（30日ごと 9時）");
}

/** Threads用ユーザーIDを取得（1時間キャッシュ） */
function getThreadsUserId() {
  const cache = CacheService.getScriptCache();
  let userId = cache.get("THREADS_USER_ID");
  if (userId) return userId;

  const url = "https://graph.threads.net/v1.0/me?fields=id&access_token=" + getThreadsToken();
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  const json = JSON.parse(resp.getContentText());
  if (!json.id) throw new Error("ThreadsユーザーID取得失敗: " + resp.getContentText());

  cache.put("THREADS_USER_ID", json.id, 3600);
  return json.id;
}

/** Threads メディアコンテナ作成（Step1） */
function createThreadsMediaContainer(imageUrl, text) {
  const userId = getThreadsUserId();
  const url    = "https://graph.threads.net/v1.0/" + userId + "/threads";

  const resp = UrlFetchApp.fetch(url, {
    method:             "post",
    contentType:        "application/x-www-form-urlencoded",
    payload:            { media_type: "IMAGE", image_url: imageUrl, text: text, access_token: getThreadsToken() },
    muteHttpExceptions: true,
  });

  const json = JSON.parse(resp.getContentText());
  if (!json.id) throw new Error("Threadsコンテナ作成失敗: " + resp.getContentText());
  return json.id;
}

/** Threads 投稿公開（Step2） */
function publishThreadsMedia(containerId) {
  const userId = getThreadsUserId();
  const url    = "https://graph.threads.net/v1.0/" + userId + "/threads_publish";

  const resp = UrlFetchApp.fetch(url, {
    method:             "post",
    contentType:        "application/x-www-form-urlencoded",
    payload:            { creation_id: containerId, access_token: getThreadsToken() },
    muteHttpExceptions: true,
  });

  const json = JSON.parse(resp.getContentText());
  if (!json.id) throw new Error("Threads公開失敗: " + resp.getContentText());
  return json.id;
}

/** Threads へ画像付き投稿（外部から呼ぶメイン関数） */
function postToThreads(imageUrl, text) {
  const containerId = createThreadsMediaContainer(imageUrl, text);
  const postId      = publishThreadsMedia(containerId);
  Logger.log("Threads投稿成功: " + postId);
  return postId;
}

/** テスト用：手動でThreads投稿確認 */
function testThreadsPost() {
  const testImageUrl = "https://raw.githubusercontent.com/mochipro888-auto-poster/x-auto-poster/main/images/test.png";
  const testCaption  = "テスト投稿 #mochipro";
  try {
    postToThreads(testImageUrl, testCaption);
    Logger.log("Threadsテスト投稿完了");
  } catch (e) {
    Logger.log("Threadsテストエラー: " + e.message);
  }
}

// =============================================================
// ===== Instagram 自動投稿 =====================================
// =============================================================

const IG_USER_ID        = "17841475056727881";
const IG_TOKEN_INITIAL  = "IGAAShyrMr8rxBZAFplRHBGVHhjWEN6dXJqVkRacHg0dHUyeDhiOEN3UDkxaHZApV2VIbmdOTmxBWmlWb2c0UEh0VlNLUklhUjN3OU5ZAdFhyM2R4d1BWelVGUXdZANlB2anZATaXRVemJYNExHV2FXaXR6Q2FmdjBoY0FOV3RrWHNzWQZDZD";
const IG_SPREADSHEET_ID = "1OwKCkIzBF0nOCLLP8Bo0ntaRzaVMgeYxlVQewdIhzpM";
const IG_SHEET_NAME     = "Instagram";

/** 現在有効なInstagramトークンを返す（Script Properties優先） */
function getIgToken() {
  const saved = PropertiesService.getScriptProperties().getProperty("IG_ACCESS_TOKEN");
  return saved || IG_TOKEN_INITIAL;
}

/**
 * InstagramアクセストークンをGraph APIで自動更新する
 * - 30日ごとのトリガーで呼び出す
 * - 更新後はScript Propertiesに保存 → GAS再デプロイ不要
 * - 成功/失敗をDiscordに通知
 */
function refreshIgToken() {
  const currentToken = getIgToken();
  const url = "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=" + currentToken;

  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  const json = JSON.parse(resp.getContentText());

  if (json.access_token) {
    PropertiesService.getScriptProperties().setProperty("IG_ACCESS_TOKEN", json.access_token);
    const days = Math.floor((json.expires_in || 5184000) / 86400);
    Logger.log("IGトークン更新成功。有効期限: " + days + "日後");
    notifyDiscord("✅ Instagramアクセストークンを自動更新しました（有効期限: " + days + "日）");
  } else {
    Logger.log("IGトークン更新失敗: " + resp.getContentText());
    notifyDiscord("⚠️ **Instagramトークン自動更新に失敗しました！**\nMeta Developerで手動更新が必要です。\nhttps://developers.facebook.com/apps/");
  }
}

/** Instagramトークン自動更新トリガーを設定（初回1回だけ実行） */
function setupIgTokenRefreshTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "refreshIgToken") ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger("refreshIgToken")
    .timeBased()
    .everyDays(30)
    .atHour(9)
    .inTimezone("Asia/Tokyo")
    .create();

  Logger.log("IGトークン自動更新トリガー設定完了（30日ごと）");
  notifyDiscord("🔧 Instagramトークン自動更新トリガーを設定しました（30日ごと 9時）");
}

/**
 * Instagram 自動投稿メイン関数
 *
 * 【Instagram シートの列構成】
 * A: キャプション（投稿テキスト）
 * B: 画像の公開URL（直接アクセス可能なURL）
 * C: ステータス（空欄 or "投稿済み" or "エラー"）
 * D: 投稿日時（自動記入）
 * E: 投稿URL（自動記入）
 * F: 投稿希望スロット（例: "21時（夜）"）
 */
function postToInstagram() {
  const sheet = SpreadsheetApp.openById(IG_SPREADSHEET_ID).getSheetByName(IG_SHEET_NAME);
  if (!sheet) {
    Logger.log("Instagramシートが見つかりません");
    return;
  }

  const data = sheet.getDataRange().getValues();
  const currentSlot = getCurrentSlotLabel();

  Logger.log(`Instagram投稿開始 スロット: ${currentSlot || "（対象外）"}`);

  // 同じ時間帯の未投稿行をすべて収集してランダムに1件選ぶ
  const candidates = [];
  for (let i = 1; i < data.length; i++) {
    const status   = data[i][2];
    const slot     = data[i][5];
    const imageUrl = data[i][1];
    if (status === "投稿済み" || status === "エラー") continue;
    if (slot && currentSlot && slot !== currentSlot) continue;
    if (!imageUrl) continue;
    candidates.push(i);
  }

  if (candidates.length === 0) {
    Logger.log("Instagram投稿対象なし（未投稿 & スロット一致の行がありません）");
    return;
  }

  const i = candidates[Math.floor(Math.random() * candidates.length)];
  {
    const text     = data[i][0];
    const imageUrl = data[i][1];

    try {
      // Step1: メディアコンテナ作成
      const containerId = createIgMediaContainer(imageUrl, text);

      // Step1.5: コンテナ処理完了待機
      waitForIgContainer(containerId);

      // Step2: 投稿公開
      const postId = publishIgMedia(containerId);

      // シート更新
      const now = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy/MM/dd HH:mm");
      sheet.getRange(i + 1, 3).setValue("投稿済み");
      sheet.getRange(i + 1, 4).setValue(now);
      sheet.getRange(i + 1, 5).setValue("https://www.instagram.com/p/" + postId);

      Logger.log("Instagram投稿成功: " + postId);

      // Threads同時投稿
      try {
        postToThreads(imageUrl, text);
      } catch (thrErr) {
        Logger.log("Threads投稿スキップ（Instagram投稿は成功）: " + thrErr.message);
      }

      // 投稿成功後にGitHubから画像を削除
      try {
        deleteGithubImage(imageUrl);
      } catch (delErr) {
        Logger.log("GitHub削除スキップ（投稿は成功）: " + delErr.message);
      }

    } catch (e) {
      sheet.getRange(i + 1, 3).setValue("エラー: " + e.message);
      Logger.log("Instagram投稿エラー: " + e.message);
    }
  }
}

// ── GitHub から画像を削除 ─────────────────────────────────────────────
function deleteGithubImage(rawUrl) {
  // Raw URL例: https://raw.githubusercontent.com/mochipro888-auto-poster/x-auto-poster/main/images/filename.png
  const match = rawUrl.match(/raw\.githubusercontent\.com\/(.+?)\/(.+?)\/(.+?)\/(images\/.+)$/);
  if (!match) {
    Logger.log("GitHub URL のパース失敗: " + rawUrl);
    return;
  }
  const owner    = match[1];
  const repo     = match[2];
  const filePath = match[4];
  const token    = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");

  if (!token) {
    Logger.log("GITHUB_TOKEN がスクリプトプロパティに未設定のためスキップ");
    return;
  }

  const apiUrl  = `https://api.github.com/repos/${owner}/${repo}/contents/${filePath}`;
  const headers = { "Authorization": "token " + token, "Accept": "application/vnd.github.v3+json" };

  // ファイルのSHAを取得（削除に必要）
  const getResp = UrlFetchApp.fetch(apiUrl, { headers, muteHttpExceptions: true });
  if (getResp.getResponseCode() !== 200) {
    Logger.log("GitHub ファイル取得失敗（すでに削除済み？）: " + getResp.getContentText());
    return;
  }
  const sha = JSON.parse(getResp.getContentText()).sha;

  // 削除リクエスト
  const delResp = UrlFetchApp.fetch(apiUrl, {
    method:             "delete",
    headers,
    payload:            JSON.stringify({ message: "Remove posted image: " + filePath, sha }),
    muteHttpExceptions: true,
  });

  if (delResp.getResponseCode() === 200) {
    Logger.log("GitHub画像削除完了: " + filePath);
  } else {
    throw new Error("削除失敗: " + delResp.getContentText());
  }
}

// メディアコンテナ作成（Step1）
function createIgMediaContainer(imageUrl, caption) {
  const url = `https://graph.instagram.com/v21.0/${IG_USER_ID}/media`;
  const payload = {
    image_url:    imageUrl,
    caption:      caption,
    access_token: getIgToken()
  };

  const response = UrlFetchApp.fetch(url, {
    method:             "post",
    contentType:        "application/x-www-form-urlencoded",
    payload:            payload,
    muteHttpExceptions: true
  });

  const json = JSON.parse(response.getContentText());
  if (!json.id) throw new Error("コンテナ作成失敗: " + response.getContentText());
  return json.id;
}

// コンテナのステータスが FINISHED になるまで待機（最大30秒）
function waitForIgContainer(containerId) {
  const token = getIgToken();
  const statusUrl = `https://graph.instagram.com/v21.0/${containerId}?fields=status_code&access_token=${token}`;

  for (let i = 0; i < 10; i++) {
    Utilities.sleep(3000); // 3秒待機
    const resp = UrlFetchApp.fetch(statusUrl, { muteHttpExceptions: true });
    const json = JSON.parse(resp.getContentText());
    Logger.log(`IGコンテナ状態確認 [${i + 1}/10]: ${json.status_code}`);
    if (json.status_code === "FINISHED") return;
    if (json.status_code === "ERROR") throw new Error("IGコンテナ処理エラー: " + resp.getContentText());
  }
  throw new Error("IGコンテナのタイムアウト（30秒以内に完了せず）");
}

// メディア公開（Step2）
function publishIgMedia(containerId) {
  const url = `https://graph.instagram.com/v21.0/${IG_USER_ID}/media_publish`;
  const payload = {
    creation_id:  containerId,
    access_token: getIgToken()
  };

  const response = UrlFetchApp.fetch(url, {
    method:             "post",
    contentType:        "application/x-www-form-urlencoded",
    payload:            payload,
    muteHttpExceptions: true
  });

  const json = JSON.parse(response.getContentText());
  if (!json.id) throw new Error("公開失敗: " + response.getContentText());
  return json.id;
}

// Instagram トリガー設定（初回1回だけ実行）
function setupIgTriggers() {
  // 既存のInstagramトリガー削除
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "postToInstagram") ScriptApp.deleteTrigger(t);
  });

  // X と同じスケジュールで統一（nearMinute でオフセット）
  const schedule = [
    { hour: 6,  minute: 20 },
    { hour: 12, minute: 10 },
    { hour: 15, minute: 40 },
    { hour: 18, minute: 15 },
    { hour: 21, minute: 50 },
    { hour: 0,  minute: 25 },
  ];

  schedule.forEach(({ hour, minute }) => {
    ScriptApp.newTrigger("postToInstagram")
      .timeBased()
      .everyDays(1)
      .atHour(hour)
      .nearMinute(minute)
      .inTimezone("Asia/Tokyo")
      .create();
  });

  Logger.log("Instagramトリガー設定完了（6件・時刻オフセット済み）");
}

// テスト用：手動で1件投稿確認
function testIgPost() {
  const testImageUrl = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png";
  const testCaption  = "テスト投稿 #mochipro";

  try {
    const containerId = createIgMediaContainer(testImageUrl, testCaption);
    Logger.log("コンテナID: " + containerId);
    const postId = publishIgMedia(containerId);
    Logger.log("投稿成功！ Post ID: " + postId);
    Logger.log("URL: https://www.instagram.com/p/" + postId);
  } catch (e) {
    Logger.log("エラー: " + e.message);
  }
}

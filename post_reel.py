"""
X リール動画自動投稿スクリプト（GitHub Actions用）

posts/reel_queue.json から pending エントリを取得し、
Google Drive から mp4 をダウンロードして X に投稿する。
投稿成功後は Drive から mp4 を削除し、キューを posted に更新する。
Drive にファイルが存在しない場合は drive_not_found としてスキップし次のエントリを試みる。

必要な GitHub Secrets:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
  GOOGLE_SERVICE_ACCOUNT_JSON（→ service_account.json に書き出してから使用）

前提条件（一回だけの手動設定）:
  Drive フォルダ（DRIVE_FOLDER_ID）を service account にエディタ権限で共有すること。
  service account: x-auto-poster@x-auto-poster-490306.iam.gserviceaccount.com
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import tweepy
from requests_oauthlib import OAuth1Session
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

QUEUE_PATH = Path("posts/reel_queue.json")
SERVICE_ACCOUNT_FILE = "service_account.json"


# ── Google Drive クライアント ───────────────────────────────────────────────
def build_drive_service():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


# ── X（Twitter）クライアント ────────────────────────────────────────────────
def build_x_clients():
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    api = tweepy.API(auth)
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return api, client


# ── Drive からダウンロード（ファイル未存在時は HttpError 404 を送出）──────
def download_from_drive(service, file_id: str, dest_path: str):
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"  Drive DL: {int(status.progress() * 100)}%")
    print(f"  Drive: [OK] ダウンロード完了 → {dest_path}")


# ── Drive から削除 ─────────────────────────────────────────────────────────
def delete_from_drive(service, file_id: str):
    service.files().delete(fileId=file_id).execute()
    print(f"  Drive: [OK] 削除完了 (file_id={file_id})")


# ── X に動画投稿 ────────────────────────────────────────────────────────────
def post_video_to_x(api, client, video_path: str, caption: str) -> str:
    import time
    print("  X: 動画アップロード中（チャンク分割）...")
    media = api.media_upload(
        filename=video_path,
        media_category="tweet_video",
        chunked=True,
    )
    # アップロード処理完了を待機
    for _ in range(30):
        info = api.get_media_upload_status(media.media_id)
        state = info.processing_info.get("state") if hasattr(info, "processing_info") else "succeeded"
        if state in ("succeeded", None):
            break
        if state == "failed":
            raise RuntimeError("X 動画処理失敗")
        print(f"  X: 処理中... state={state}")
        time.sleep(info.processing_info.get("check_after_secs", 3))

    print(f"  X: アップロード完了 media_id={media.media_id}")

    # OAuth1Session で直接 v2 tweets エンドポイントを呼ぶ（tweepy迂回・詳細ログ取得用）
    oauth = OAuth1Session(
        client_key=os.environ["X_API_KEY"],
        client_secret=os.environ["X_API_SECRET"],
        resource_owner_key=os.environ["X_ACCESS_TOKEN"],
        resource_owner_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    payload = {
        "text": caption,
        "media": {"media_ids": [str(media.media_id)]},
    }
    r = oauth.post("https://api.twitter.com/2/tweets", json=payload)
    print(f"  X: HTTP status={r.status_code}")
    print(f"  X: response body={r.text}")
    if not r.ok:
        raise RuntimeError(f"X tweet failed: {r.status_code} {r.text}")
    tweet_id = r.json()["data"]["id"]
    print(f"  X: 投稿完了 → https://x.com/i/web/status/{tweet_id}")
    return tweet_id


# ── キュー更新して保存 ────────────────────────────────────────────────────
def update_queue(queue: list, file_id: str, status: str, **extra):
    for e in queue:
        if e["file_id"] == file_id:
            e["status"] = status
            e.update(extra)
            break
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  reel_queue.json: {status} に更新")


# ── メイン ──────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] リール X 投稿開始")

    if not QUEUE_PATH.exists():
        print("  reel_queue.json が見つかりません。スキップ。")
        return

    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    pending = [e for e in queue if e.get("status") == "pending"]

    if not pending:
        print("  投稿待ちエントリなし。スキップ。")
        return

    drive = build_drive_service()
    api, client = build_x_clients()

    for entry in pending:
        file_id    = entry["file_id"]
        caption    = entry["caption"]
        story_name = entry["story_name"]
        print(f"  ストーリー: {story_name}")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Drive からダウンロード（404 の場合はスキップ）
            try:
                download_from_drive(drive, file_id, tmp_path)
            except HttpError as he:
                if he.resp.status == 404:
                    print(f"  Drive: ファイルが見つかりません (file_id={file_id})。スキップ。")
                    update_queue(queue, file_id, "drive_not_found",
                                 skipped_at=datetime.now().isoformat())
                    continue
                raise

            # X に投稿
            post_video_to_x(api, client, tmp_path, caption)

            # Drive から削除
            delete_from_drive(drive, file_id)

            # キューを posted に更新して終了（1日1件）
            update_queue(queue, file_id, "posted",
                         posted_at=datetime.now().isoformat())
            return

        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
            sys.exit(1)

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    print("  投稿可能なエントリが見つかりませんでした（全件 drive_not_found）。")


if __name__ == "__main__":
    main()

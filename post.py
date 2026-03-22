"""
X（Twitter）自動投稿スクリプト
- Google Sheets をキュー管理に使用（オプション）
- ローカルの queue.json でも動作
- GitHub Actions 上で実行（PCオフでも動作）
"""

import os
import json
import random
import sys
import tweepy
from pathlib import Path
from datetime import datetime


# ── 設定 ────────────────────────────────────────────────────────────────
USE_SHEETS = os.environ.get("USE_SHEETS", "false").lower() == "true"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1OwKCkIzBF0nOCLLP8Bo0ntaRzaVMgeYxlVQewdIhzpM")


# ── X API 認証 ──────────────────────────────────────────────────────────
def build_clients():
    creds = {
        "api_key":             os.environ["X_API_KEY"],
        "api_secret":          os.environ["X_API_SECRET"],
        "access_token":        os.environ["X_ACCESS_TOKEN"],
        "access_token_secret": os.environ["X_ACCESS_TOKEN_SECRET"],
    }
    client = tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
    )
    auth = tweepy.OAuth1UserHandler(
        creds["api_key"], creds["api_secret"],
        creds["access_token"], creds["access_token_secret"],
    )
    return client, tweepy.API(auth)


# ── Google Sheets からキュー取得 ─────────────────────────────────────────
def get_next_from_sheets():
    """
    Sheets のキューから未投稿の最初の行を取得し、投稿済みにマーク。
    列構成: A=テキスト, B=画像パス, C=ステータス, D=投稿日時
    """
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    gc = gspread.authorize(creds)

    sheet = gc.open_by_key(SPREADSHEET_ID).sheet1
    records = sheet.get_all_values()

    # 未投稿行をすべて収集してランダムに1件選択
    pending = []
    for i, row in enumerate(records[1:], start=2):  # 1行目はヘッダー
        text = row[0] if len(row) > 0 else ""
        image = row[1] if len(row) > 1 else ""
        status = row[2] if len(row) > 2 else ""
        if text and status != "投稿済み":
            pending.append((i, text, image))

    if not pending:
        return None, None

    # ランダムに1件選択
    i, text, image = random.choice(pending)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    sheet.update(f"C{i}:D{i}", [["投稿済み", now]])
    return text, image or None


# ── ローカル queue.json からキュー取得（ランダム選択・重複回避） ───────────
def get_next_from_local():
    queue_path = Path("posts/queue.json")
    state_path = Path("posts/state.json")

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    if not queue:
        return None, None

    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    posted_indices = set(state.get("posted_indices", []))

    # 全て投稿済みならリセット（一巡したらシャッフルして再スタート）
    all_indices = set(range(len(queue)))
    remaining = list(all_indices - posted_indices)
    if not remaining:
        posted_indices = set()
        remaining = list(all_indices)

    # 未投稿からランダムに1件選択
    idx = random.choice(remaining)
    entry = queue[idx]

    posted_indices.add(idx)
    state["posted_indices"] = list(posted_indices)
    state["last_posted_at"] = datetime.now().isoformat()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    return entry["text"], entry.get("image")


# ── X へ投稿 ─────────────────────────────────────────────────────────────
def post_to_x(client, api, text: str, image_path: str | None):
    media_ids = []

    if image_path:
        img = Path(image_path)
        if img.exists():
            media = api.media_upload(str(img))
            media_ids.append(media.media_id)
            print(f"  画像アップロード: {img.name}")
        else:
            print(f"  [警告] 画像なし: {image_path}", file=sys.stderr)

    response = client.create_tweet(
        text=text,
        media_ids=media_ids if media_ids else None,
    )
    return response.data["id"]


# ── メイン ───────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 投稿開始")

    if USE_SHEETS:
        print("  モード: Google Sheets")
        text, image = get_next_from_sheets()
    else:
        print("  モード: ローカル queue.json")
        text, image = get_next_from_local()

    if not text:
        print("  投稿できるコンテンツがありません。終了します。")
        return

    print(f"  テキスト: {text[:60]}{'...' if len(text) > 60 else ''}")

    client, api = build_clients()
    tweet_id = post_to_x(client, api, text, image)
    print(f"  投稿完了 → https://x.com/i/web/status/{tweet_id}")


if __name__ == "__main__":
    main()

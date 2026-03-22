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
from datetime import datetime, timezone, timedelta


# ── 設定 ────────────────────────────────────────────────────────────────
USE_SHEETS = os.environ.get("USE_SHEETS", "false").lower() == "true"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1OwKCkIzBF0nOCLLP8Bo0ntaRzaVMgeYxlVQewdIhzpM")

# 時間帯スロット定義（GAS post_to_x.gs の slotLabel と完全一致させる）
SLOT_NAMES = {6: "06時（朝）", 12: "12時（昼）", 15: "15時（放課後）", 18: "18時（夕方）", 21: "21時（夜）", 0: "00時（深夜）"}


def get_current_slot_label() -> str:
    """現在のJST時刻から時間帯ラベルを返す（GitHub Actions はUTCで動作するため+9h変換）"""
    jst = timezone(timedelta(hours=9))
    h = datetime.now(tz=jst).hour
    for slot in [21, 18, 15, 12, 6, 0]:
        if slot == 0 or h >= slot:
            return SLOT_NAMES[slot]
    return SLOT_NAMES[0]


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
    Sheets の Queue シートから現在の時間帯に合う未投稿行をランダムに1件取得。
    列構成: A=テキスト, B=DriveID, C=ステータス, D=投稿日時, E=(空), F=時間帯ラベル
    """
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    gc = gspread.authorize(creds)

    sheet = gc.open_by_key(SPREADSHEET_ID).worksheet("Queue")
    records = sheet.get_all_values()

    current_slot = get_current_slot_label()
    print(f"  現在の時間帯: {current_slot}")

    # 現在の時間帯に合う未投稿行を収集
    pending = []
    for i, row in enumerate(records[1:], start=2):  # 1行目はヘッダー
        text   = row[0] if len(row) > 0 else ""
        image  = row[1] if len(row) > 1 else ""
        status = row[2] if len(row) > 2 else ""
        slot   = row[5] if len(row) > 5 else ""
        if text and status != "投稿済み" and slot == current_slot:
            pending.append((i, text, image))

    # 同じ時間帯に未投稿がなければ全時間帯の未投稿からランダム選択（フォールバック）
    if not pending:
        print(f"  [{current_slot}]の未投稿なし → 全時間帯からランダム選択")
        for i, row in enumerate(records[1:], start=2):
            text   = row[0] if len(row) > 0 else ""
            image  = row[1] if len(row) > 1 else ""
            status = row[2] if len(row) > 2 else ""
            if text and status != "投稿済み":
                pending.append((i, text, image))

    if not pending:
        return None, None

    # ランダムに1件選択
    i, text, image = random.choice(pending)
    now = datetime.now(tz=timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M")
    sheet.update(f"C{i}:D{i}", [["投稿済み", now]])
    return text, image or None


# ── ローカル queue.json からキュー取得（時間帯フィルタ + ランダム選択） ───
def get_next_from_local():
    queue_path = Path("posts/queue.json")
    state_path = Path("posts/state.json")

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    if not queue:
        return None, None

    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    posted_indices = set(state.get("posted_indices", []))

    current_slot = get_current_slot_label()
    print(f"  現在の時間帯: {current_slot}")

    def pick_from(indices):
        """指定インデックス群から未投稿をランダム選択。全投稿済みならリセット後に再選択。"""
        remaining = [i for i in indices if i not in posted_indices]
        if not remaining:
            # この範囲を一巡したのでリセット
            for i in indices:
                posted_indices.discard(i)
            remaining = list(indices)
        return random.choice(remaining) if remaining else None

    # 同じ時間帯のエントリのみ対象
    slot_indices = [i for i, e in enumerate(queue) if e.get("slot") == current_slot]

    if slot_indices:
        idx = pick_from(slot_indices)
    else:
        # slot フィールドなし（旧形式）→ 全件からランダム
        print(f"  slot情報なし → 全件からランダム選択")
        all_indices = list(range(len(queue)))
        idx = pick_from(all_indices)

    if idx is None:
        return None, None

    entry = queue[idx]
    posted_indices.add(idx)
    state["posted_indices"] = list(posted_indices)
    state["last_posted_at"] = datetime.now(tz=timezone(timedelta(hours=9))).isoformat()
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

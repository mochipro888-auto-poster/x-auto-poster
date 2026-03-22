"""
X リール動画投稿スクリプト（無効化済み）

X API Free tier では動画ツイートが禁止（403）のため、自動投稿を停止。
動画は Google Drive からダウンロードして手動で X に投稿してください。

手動投稿フロー:
  1. reel_queue.json で status="manual_post" のエントリを確認
  2. file_id を使って Google Drive から mp4 をダウンロード
  3. caption の内容をコピーして X に手動で投稿
  4. 投稿後に status を "posted" に手動更新
"""

import json
from pathlib import Path

QUEUE_PATH = Path("posts/reel_queue.json")


def main():
    print("X リール自動投稿は無効化されています（X API Free tier制限）。")
    print("動画はDriveから手動でダウンロードしてXに投稿してください。")

    if not QUEUE_PATH.exists():
        return

    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    manual = [e for e in queue if e.get("status") == "manual_post"]

    if manual:
        print(f"\n手動投稿待ち: {len(manual)}件")
        for e in manual:
            print(f"  - {e['story_name']}")
            print(f"    Drive file_id: {e['file_id']}")
            print(f"    caption: {e['caption'][:40]}...")
    else:
        print("手動投稿待ちなし。")


if __name__ == "__main__":
    main()

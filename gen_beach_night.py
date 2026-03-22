#!/usr/bin/env python3
"""
夏ビーチ・プールシーン 追加4枚（夜・深夜）生成スクリプト
キャラ：yura / mio / tsumugi / iroha
"""

import base64
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ("cp932", "shift_jis", "shift-jis"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

from discord_auto_gen import (
    CHARACTERS, API_URL, WEBHOOK_URL, SLOT_NAMES,
    build_payload, post_to_discord,
    save_image, register_to_x_queue, ENABLE_X_POST,
)

SCENES = [
    # ---- 21時帯 ----
    {
        "chara": "yura",
        "hour_slot": 21,
        "scene": "屋上ナイトプール・浮き輪に座って夜空を見上げる",
        "prompt": (
            "1girl, sitting on float ring in rooftop pool, "
            "both arms spread wide open to sides, looking up at night sky, "
            "silver black gradient bikini, "
            "dreamy gentle eyes, gazing slightly upward, "
            "rooftop night pool, city night view background, "
            "neon lights reflecting on water surface, "
            "dark night sky, stars, romantic atmosphere, upper body"
        ),
        "dialogue": "夜のプール……夜空がこんなに近いなんて……🌸 夢みたい……♡",
    },
    # ---- 0時帯 ----
    {
        "chara": "mio",
        "hour_slot": 0,
        "scene": "スイートルーム・ベッドに座って肩紐をずらした仕草",
        "prompt": (
            "1girl, sitting on edge of bed, knees together, "
            "one hand near shoulder strap with subtle gesture, "
            "black lace sheer bandeau bikini, "
            "seductive inviting gaze, looking at camera, "
            "dim hotel suite room, warm indirect lighting, "
            "large window with city night view, "
            "luxury interior, soft shadow atmosphere, upper body"
        ),
        "dialogue": "ねえ……もう夜中だよ？ ふふ、まだ起きてるの……？💫",
    },
    {
        "chara": "tsumugi",
        "hour_slot": 0,
        "scene": "深夜の露天風呂・湯船の縁に座って足を浸す",
        "prompt": (
            "1girl, sitting on edge of outdoor hot spring bath, "
            "legs submerged in hot water, leaning back with hands behind supporting body, "
            "white towel wrapped around body, pale pink simple bikini underneath, "
            "blushing flushed cheeks, shy embarrassed smile, looking slightly down, "
            "moonlit outdoor onsen, steam rising, rock bath, "
            "moonlight, quiet night atmosphere, upper body"
        ),
        "dialogue": "お、お湯が気持ちよすぎて……！えへへ、顔あかいかな……♡🌙",
    },
    {
        "chara": "iroha",
        "hour_slot": 0,
        "scene": "薄暗いナイトプール・プールサイドに横たわり片手で髪を弄る",
        "prompt": (
            "1girl, lying on pool side, one hand playing with hair, "
            "dark navy glossy one-piece swimsuit, wet shiny fabric, "
            "sleepy yet alluring eyes, looking gently at camera, "
            "dimly lit night pool, weak lights, calm still water surface, "
            "quiet night atmosphere, soft dark lighting, "
            "water reflections, serene, upper body and torso"
        ),
        "dialogue": "んー……なんか眠くなってきた……でも、まだいたいな💙",
    },
]


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 夏ビーチ・プール 追加4シーン（夜・深夜）生成開始\n")

    for i, scene in enumerate(SCENES, 1):
        chara_key = scene["chara"]
        hour_slot = scene["hour_slot"]
        chara_name = CHARACTERS[chara_key]["name"]

        print(f"[{datetime.now().strftime('%H:%M:%S')}] シーン{i:02d}/04 [{chara_name} / {hour_slot}時] {scene['scene']}")

        payload = build_payload(chara_key, scene["prompt"])
        try:
            resp = requests.post(f"{API_URL}/txt2img", json=payload, timeout=600)
            resp.raise_for_status()
            result = resp.json()
            image_bytes = base64.b64decode(result["images"][0])
        except requests.exceptions.ConnectionError:
            print(f"  ❌ SD WebUIに接続できません。スキップします。")
            continue
        except Exception as e:
            print(f"  ❌ 生成エラー: {e}")
            continue

        saved_path = save_image(image_bytes, chara_key, hour_slot)
        filename = saved_path.name
        print(f"  保存: {saved_path}")
        print(f"  ✅ 保存: {filename}")

        discord_text = f"[{chara_name} / {hour_slot}時] {scene['scene']}\n{chara_name}：{scene['dialogue']}"
        post_to_discord(saved_path, discord_text, chara_name)

        print(f"\n登録中: {filename}")
        register_to_x_queue(saved_path, scene["dialogue"], SLOT_NAMES.get(hour_slot, f"{hour_slot}時"))

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✅ 追加4シーン生成完了")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
夏ビーチ・プールシーン 14枚一括生成スクリプト
キャラはランダム割り当て（6キャラを均等分配）
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

# キャラ割り当て（14シーン / 6キャラ = 均等分配）
# nagi×3, tsumugi×2, mio×2, iroha×2, shizuku×3, yura×2
SCENES = [
    # ---- 6時帯 ----
    {
        "chara": "nagi",
        "hour_slot": 6,
        "scene": "朝焼けビーチ・砂浜に座って膝を抱える",
        "prompt": (
            "1girl, sitting on sandy beach, knees pulled to chest, "
            "hair blowing in breeze, looking into distance, "
            "white and light blue striped triangle bikini, "
            "thin hoodie draped over shoulders, "
            "sleepy gentle smile, gazing at horizon, upper body, "
            "sunrise beach, orange pink sky, early morning golden hour, "
            "soft warm light, ocean waves"
        ),
        "dialogue": "朝焼けのビーチ……✨ ひとりでぼーっとするの、すきなんだよね🌅",
    },
    {
        "chara": "tsumugi",
        "hour_slot": 6,
        "scene": "ホテルバルコニー・手すりに肘をついて上半身を乗り出す",
        "prompt": (
            "1girl, hotel balcony, leaning forward on railing with elbows, "
            "upper body leaning over balcony railing, "
            "lavender one-shoulder bandeau bikini top, "
            "fresh morning smile, looking at camera, "
            "morning sunlight streaming in, soft golden light, "
            "ocean view from balcony, tropical resort atmosphere"
        ),
        "dialogue": "バルコニーから見る朝の海、最っっ高すぎる〜！♡🌊",
    },
    {
        "chara": "shizuku",
        "hour_slot": 6,
        "scene": "プライベートプール・足を浸して水面を指でなぞる",
        "prompt": (
            "1girl, sitting at private pool edge, feet dangling in pool water, "
            "one hand reaching down tracing water surface with finger, "
            "mint green high-neck sporty one-piece swimsuit, "
            "innocent cute smile, looking slightly downward at water, "
            "resort hotel private pool, sparkling pool water, "
            "morning calm atmosphere, soft light"
        ),
        "dialogue": "プールのお水、ひんやりして気持ちいい〜…！🌿あわわ、癒される♡",
    },
    # ---- 12時帯 ----
    {
        "chara": "mio",
        "hour_slot": 12,
        "scene": "ナイトプール（日中）・プールサイドで腰に手を当てて立つ",
        "prompt": (
            "1girl, standing at poolside, one hand on hip, confident pose, "
            "glossy silver micro bikini, metallic sheen, "
            "confident proud expression, slight smirk, looking at camera, "
            "resort pool daytime, bright sunlight, "
            "clear blue pool water, tropical atmosphere"
        ),
        "dialogue": "ふふ、どうかな…？✨ このビキニ、選んだかいあったかも🌿",
    },
    {
        "chara": "iroha",
        "hour_slot": 12,
        "scene": "海の家テラス・テーブルに座ってアイスを舐める",
        "prompt": (
            "1girl, sitting at outdoor terrace table, licking ice cream cone, "
            "light blue and pink checkered bikini, "
            "happy blissful expression eating ice cream, slight sideways glance, "
            "beachside cafe terrace, bright afternoon, "
            "summer atmosphere, ocean visible in background"
        ),
        "dialogue": "んんっ〜！うますぎる！💙 海の家のアイス、やっぱり最高じゃん！",
    },
    {
        "chara": "yura",
        "hour_slot": 12,
        "scene": "リゾートプール・浮き輪にうつ伏せで乗って足ぷらぷら",
        "prompt": (
            "1girl, lying face down on pool float ring, legs swinging in air behind, "
            "orange string bikini, "
            "happy carefree smile, looking at camera, "
            "resort pool, bright midday sun, "
            "colorful pool float, clear blue water, tropical"
        ),
        "dialogue": "ぷかぷか〜……🌸 なんか、このままずっと浮いてたいな……♡",
    },
    # ---- 15時帯 ----
    {
        "chara": "nagi",
        "hour_slot": 15,
        "scene": "インフィニティプール・ラウンジチェアに横たわる",
        "prompt": (
            "1girl, lying on lounge chair, one hand tucking hair behind ear, "
            "pale mint green off-shoulder bandeau bikini top, thin pareo wrapped at waist, "
            "relaxed gentle smile, looking softly at camera, "
            "infinity pool resort, afternoon soft golden light, "
            "ocean and palm trees in distance, "
            "calm peaceful atmosphere"
        ),
        "dialogue": "午後のプールサイドって、なんでこんなに心地いいんだろ…🌿✨",
    },
    {
        "chara": "tsumugi",
        "hour_slot": 15,
        "scene": "プライベートビーチ・ハンモックで膝を寄せ抱きしめる",
        "prompt": (
            "1girl, sitting in hammock, knees drawn up hugged with both arms, "
            "pastel pink frilly halterneck bikini, "
            "slightly shy upward glance, looking at camera, "
            "private beach hammock area, dappled sunlight through trees, "
            "tropical trees, ocean glimpse"
        ),
        "dialogue": "ねえ、ここ気持ちよすぎない…？♡ えへへ、ずっといたい🎀",
    },
    {
        "chara": "shizuku",
        "hour_slot": 15,
        "scene": "プールサイドデッキ・足を浸して後ろ手で上体を反らす",
        "prompt": (
            "1girl, sitting on poolside deck, feet in pool, "
            "both hands behind supporting body, arching upper body back, "
            "gold and white metallic striped bikini, "
            "pleasured sigh-like smile, looking slightly upward, "
            "pool deck with sparkling water reflection, afternoon light"
        ),
        "dialogue": "うわあ……キラキラしてる〜…！✨ お水の反射、きれい……♡",
    },
    # ---- 18時帯 ----
    {
        "chara": "mio",
        "hour_slot": 18,
        "scene": "夕陽ビーチ・両手を広げ髪を夕風になびかせる",
        "prompt": (
            "1girl, standing on beach, both arms spread wide open, "
            "hair flowing in evening breeze, "
            "orange gradient fringe bikini, tassel details, "
            "radiant smile lit by sunset, looking at camera, "
            "sunset beach, orange pink sky, gentle waves, "
            "warm golden sunset light"
        ),
        "dialogue": "夕陽に染まるの、すき……💫 今日も最高な一日だったなぁ🌿",
    },
    {
        "chara": "iroha",
        "hour_slot": 18,
        "scene": "夕暮れプール・プールエッジに座って後ろ手に支える",
        "prompt": (
            "1girl, sitting on pool edge, feet in water, "
            "both hands behind supporting body, "
            "deep wine red high-leg bikini, "
            "slightly sexy exhale-like smile, inviting look at camera, "
            "pool at dusk, pool lights starting to turn on, "
            "warm evening atmosphere"
        ),
        "dialogue": "夕方のプール、なんかドキドキするじゃん…？💙 ねえ、もっと遊ぼ？",
    },
    {
        "chara": "yura",
        "hour_slot": 18,
        "scene": "夕陽の桟橋・膝を抱えて横顔で夕陽を見る",
        "prompt": (
            "1girl, sitting at end of pier jetty, knees drawn up, "
            "side profile looking at sunset, "
            "gold and pink metallic triangle bikini, "
            "romantic gentle expression, profile view, "
            "sunset over ocean, pier stretching into sea, "
            "warm orange golden light, romantic atmosphere"
        ),
        "dialogue": "夕陽が……きれい……🌸 こういう時間って、なんか特別だよね……♡",
    },
    # ---- 21時帯 ----
    {
        "chara": "nagi",
        "hour_slot": 21,
        "scene": "ナイトプール・プールエッジに腰掛けて上体を反らす",
        "prompt": (
            "1girl, sitting on pool edge, one leg in water, "
            "upper body leaning slightly back, "
            "black and neon pink glossy high-leg bikini, thin string sides, "
            "lip slightly between teeth, alluring gaze at camera, "
            "night pool, blue and pink neon lighting, "
            "water surface reflecting neon lights, night atmosphere"
        ),
        "dialogue": "ナイトプール、はじめてきた……！🌙 雰囲気すごすぎてドキドキするよ♡",
    },
    {
        "chara": "shizuku",
        "hour_slot": 21,
        "scene": "夜のビーチ・後ろから振り返り片手で髪をかき上げる",
        "prompt": (
            "1girl, standing on night beach, turning back to look over shoulder, "
            "one hand running through hair, hair flowing, "
            "dark purple metallic bandeau bikini top, "
            "thin sheer cover-up wrap over shoulders, "
            "mysterious moonlit smile, looking at camera, "
            "night beach, moonlight, distant fireworks in sky, "
            "dark romantic atmosphere"
        ),
        "dialogue": "花火……みえた！🌸 あわ、すごい……きれい……！💕",
    },
]


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 夏ビーチ・プールシーン 14枚生成開始\n")

    for i, scene_data in enumerate(SCENES, 1):
        chara_key = scene_data["chara"]
        hour_slot = scene_data["hour_slot"]
        chara_name = CHARACTERS[chara_key]["name"]

        print(f"[{datetime.now().strftime('%H:%M:%S')}] シーン{i:02d}/14 [{chara_name} / {hour_slot}時] {scene_data['scene']}")

        payload = build_payload(chara_key, scene_data["prompt"])
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

        image_path = save_image(image_bytes, chara_key, hour_slot)
        print(f"  ✅ 保存: {image_path.name}")

        post_to_discord(image_path, scene_data["dialogue"], chara_name)

        if ENABLE_X_POST:
            register_to_x_queue(image_path, scene_data["dialogue"], SLOT_NAMES.get(hour_slot, f"{hour_slot}時"))

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✅ 全14シーン生成完了")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Discord/X 自動画像生成・投稿スクリプト（時間帯対応・全年齢SFW版 v3）

スケジュール: 5:50 / 11:50 / 14:50 / 17:50 / 20:50 / 23:50
  → GASのX投稿（6/12/15/18/21/0時）の10分前に生成・登録

機能:
  - シーンコンセプトをClaude APIで動的生成（場所・衣装・ポーズ・雰囲気を毎回新鮮に）
  - 約20%の確率で「読者に直接語りかける」コンテンツ（reader_talk）を生成
  - 季節・時間帯・特別シーンをすべてClaude APIが柔軟に考案
  - 固定シーンプールはClaude API失敗時のフォールバックとして保持
  - 全年齢SFW基本 / 微エロ（示唆のみ）を約1/3の確率で混入
  - NSFW検出時は自動スキップ
  - シーンコンセプトとセリフを1回のClaude APIコールで同時生成
  - Discord Webhook投稿 ＋ Google Sheets（X自動投稿キュー）登録

初期設定:
  1. pip install requests schedule anthropic gspread google-auth google-api-python-client
  2. 環境変数に ANTHROPIC_API_KEY を設定
     例: set ANTHROPIC_API_KEY=sk-ant-...
  3. C:\\EasyReforge\\Reforge_API.bat を起動しておく

実行方法:
  python discord_auto_gen.py              # 定期スケジュール実行
  python discord_auto_gen.py --now        # 現在時刻シーンで即時実行（テスト用）
  python discord_auto_gen.py --time 21    # 時刻指定テスト
  python discord_auto_gen.py --time 21 --chara tsumugi  # キャラ＋時刻指定テスト
"""

import argparse
import base64
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import schedule

# ── upload_to_drive.py（同フォルダ）をインポート ─────────────────────────────
ENABLE_X_POST = True
THIS_DIR = Path(__file__).parent

if ENABLE_X_POST:
    sys.path.insert(0, str(THIS_DIR))
    os.chdir(THIS_DIR)
    try:
        from upload_to_drive import register_one, validate_config
    except ImportError:
        print("[警告] upload_to_drive.py が見つかりません。X投稿連携をスキップします。")
        ENABLE_X_POST = False

# ── Claude API（セリフ動的生成） ──────────────────────────────────────────────
try:
    import anthropic
    CLAUDE_CLIENT = anthropic.Anthropic()
    ENABLE_CLAUDE = True
except Exception:
    CLAUDE_CLIENT = None
    ENABLE_CLAUDE = False

# ============================================================
# 設定
# ============================================================

API_URL     = "http://127.0.0.1:7860/sdapi/v1"
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1482643050126774442/yxwb31MOFBbkkO1oerwLLOlYksRH6yt3OlaY0uIBrsgSXXRt7it34HMB_5CrbFhY_Zhr"

OUTPUT_DIR = Path(r"C:\Users\ikeda\Desktop\EseClaw v1.0\EseClaw v1.0\data\images\x_insta_auto_post")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 微エロ混入確率（N = 1/N の確率）: 3 → 約33%
SUGGESTIVE_RATIO = 3

# 特別シーン（アイドル・行事等）の出現確率（N = 1/N の確率）: 3 → 約33%
SPECIAL_SCENE_RATIO = 3

# 読者に語りかけるreader_talkの出現確率（N = 1/N の確率）: 5 → 約20%
READER_TALK_RATIO = 5

# ============================================================
# 共通ネガティブプロンプト
# ============================================================

NEGATIVE_PROMPT = (
    "NEGATIVE_HANDS,negativeXL_D,lowres,(bad),(bad quality, worst quality:1.2),"
    "worst quality,low quality,displeasing,normal quality,bad quality,bad details,"
    "chromatic aberration,sketch,jpeg artifacts,ugly,poorly drawn,blurry,watermark,"
    "signature,artist name,frame,transparent background,censored,(bad anatomy:1.3),"
    "limb asymmetry,three fingers,((four fingers:1.2)),((six fingers:1.3)),"
    "(seven fingers:1.2),((extra fingers:1.2)),missing fingers,(fused fingers:1.1),"
    "(deformed fingers:1.1),((ugly fingers:1.1)),(deformed hands:1.2),"
    "((bad hands:1.3)),worst time,(worst hands:1.1),wrong hands,(twisted hands:1.1),"
    "(ugly hands:1.1),deformed toes,fused toes,missing toes,wrong feet,deformed feet,"
    "ugly feet,deformed limbs,(extra digit:1.2),interlocked fingers,fewer digits,"
    "bad feet,oldest,blush stickers,(shiny_skin:1.2),(skin gloss:1.2),freckles,"
    "cum on face,cum on mouth,(sweat:1.3),animal ears,(gradient hair:1.3),"
    "double navel:1.1,(multiple boy:1.2),(multiple girl:1.2),(emblem:1.2),"
    "(printed design:1.1),(hair accessory:1.2),(bad eyes:1.2),(diamond-shaped pupils:1.4),"
    "nsfw,nude,naked,topless,nipples,genitalia,explicit,"
)

# ============================================================
# ADetailer設定（共通）
# ============================================================

ADETAILER_ARGS = {
    "ADetailer": {
        "args": [
            True, False,
            {
                "ad_model": "99coins_anime_girl_face_m_seg.pt",
                "ad_confidence": 0.3,
                "ad_dilate_erode": 4,
                "ad_mask_blur": 4,
                "ad_denoising_strength": 0.4,
                "ad_inpaint_only_masked": True,
                "ad_inpaint_only_masked_padding": 32,
                "ad_mask_k_largest": 1,
            },
            {
                "ad_model": "AnzhcEyes-seg.pt",
                "ad_confidence": 0.3,
                "ad_dilate_erode": 4,
                "ad_mask_blur": 4,
                "ad_denoising_strength": 0.3,
                "ad_inpaint_only_masked": True,
                "ad_inpaint_only_masked_padding": 32,
            },
        ]
    }
}

# ============================================================
# キャラクター定義
# ============================================================

CHARACTERS = {
    "tsumugi": {
        "name": "柊つむぎ",
        "personality": (
            "明るく元気な女の子。一人称は「わたし」。感情豊かで、喜怒哀楽がはっきりしている。"
            "少し天然でかわいらしい口調。前向きな言葉が多い。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:hiiragi_tsumugi_face_v2-000004:0.4>,hiiragi_tsumugi_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "(blonde hair), twin braids, sidelocks, (hair accessory:-2), round eyes, sky blue eyes, "
            "petite:1.1, medium breasts, loli:1.1, cute face:1.1, (smooth skin:1.1)"
        ),
    },
    "mio": {
        "name": "月見山美桜",
        "personality": (
            "物静かで思慮深い女の子。一人称は「わたし」。詩的・内省的な表現を好む。"
            "落ち着いた語調で、感情をじっくり言葉にする。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:yamanashi_mio_face_v1-000004:0.4>,yamanashi_mio_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "(white hair), long hair, disheveled hair, (hair accessory:-2), round eyes, purple eyes, "
            "petite:1.1, medium breasts, loli:1.1, cute face:1.1, (smooth skin:1.1)"
        ),
    },
    "shizuku": {
        "name": "薬袋しずく",
        "personality": (
            "好奇心旺盛で自由奔放、思いついたらすぐ動くタイプ。一人称は「わたし」。"
            "普段は緊張しやすくあわあわしてしまうが、ライブや本番になると別人のように堂々と輝く。"
            "「みんなのことを思うと怖くなくなる」。よく噛む＆照れるギャップがファンを掴む。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:minai_mio_face_v1-000001:0.4>,minai_mio_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "(hair translucent aqua hair:1.25),(double bun),(long hair),(hair accessory:-2),"
            "round eyes,(eyes blue eyes:1.1),small breasts,loli:1.2,cute face:1.1,(smooth skin:1.1)"
        ),
    },
    "nagi": {
        "name": "九十九凪",
        "personality": (
            "しっかり者で気配り上手、面倒見がよくグループのサポート役。一人称は「わたし」。"
            "困っている人を放っておけない。信頼する人には甘えたがる妹気質。"
            "ツッコミ役になることも多く、たまに抜けてる可愛らしい一面も。少しジト目になる瞬間がある。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:tsukumo_nagi_face_v1-000001:0.2>,tsukumo_nagi_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "(black hair:1.1),(long low twintails:1.3),(hair accessory:-2),"
            "eyes light green eyes,petite:1.1,small breasts,cute face:1.1,(smooth skin:1.1)"
        ),
    },
    "iroha": {
        "name": "朱鷺いろは",
        "personality": (
            "ボーイッシュで元気いっぱいな女の子。一人称は「あたし」。さばさばした口調で、ちょっとツンデレ気味。"
            "でも本当は仲間想いで優しい。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:tsukumo_nagi_face_v1-000001:0.2>,tsukumo_nagi_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "Person_A,1girl,(amber brown hair),short hair,(long sidelocks:1.1),"
            "(wolf cut:0.7),(hair accessory:-2),red eyes,(single fang:0.8),"
            "small breasts,(tomboy:0.8),cute face:1.1,(smooth skin:1.1)"
        ),
    },
    "yura": {
        "name": "紫乃瀬ゆら",
        "personality": (
            "やさしくて穏やか、少し天然でマイペース。一人称は「わたし」。"
            "人の気持ちにすぐ気づくけど、自分のことはちょっと鈍感。ふわふわしているようで芯はしっかりしている癒し系アイドル。"
            "話していると少しズレた天然発言をすることも。声はやわらかくて落ち着いていて、聞いていると安心するタイプ。"
        ),
        "lora_block": (
            "masterpiece,best quality,very aesthetic,amazing quality,high quality,absurdres,newest,"
            "<lora:tsukumo_nagi_face_v1-000001:0.2>,tsukumo_nagi_face,"
            "<lora:dilanshengxue-waiNSFWIllustriousv12-v3-000008:0.2>,dilanshengxue,"
            "<lora:Eyes_for_Illustrious_Lora_Perfect_anime_eyes:0.2>,perfect eyes,"
            "<lora:outline-slider:-1>,no outline,"
            "<lora:slider-flatberry:0.3>,(plump:-0.1),"
            "<lora:ppw_v8_Illuv1_128:0.1>,"
            "<lora:illustrious_masterpieces_v3:0.2>,"
            "<lora:add-detail-xl:0.4>,"
            "<lora:good_background-ILSTR-came:0.2>,"
        ),
        "appearance": (
            "(hair dark purple hair:1.1),(long side ponytail),blunt bangs,(hair accessory:-2),"
            "round eyes,(eyes purple eyes),large breasts,petite:1.1,loli,cute face:1.1,(smooth skin:1.1)"
        ),
    },
}

# ============================================================
# 時間帯別シーン定義
# ============================================================

TIME_SCENES = {
    6: [
        {"prompt": "1girl, bedroom, morning, pajamas, just woke up, stretching, yawning, soft morning sunlight through window, warm cozy atmosphere,", "description": "朝、パジャマで目覚め・ストレッチ", "suggestive": False},
        {"prompt": "1girl, school uniform, morning, walking to school, quiet residential street, cherry blossoms, morning mist, fresh start,", "description": "登校中、桜並木の朝", "suggestive": False},
        {"prompt": "1girl, kitchen, morning, pajamas, eating breakfast, toast, warm orange juice, sunny window, peaceful home,", "description": "朝食、キッチンでパジャマ姿", "suggestive": False},
        {"prompt": "1girl, school uniform, front door, morning sunlight, ready for school, fresh morning, gentle smile, backpack,", "description": "登校前、玄関で制服姿", "suggestive": False},
        {"prompt": "1girl, bedroom, morning, pajamas, off shoulder, stretching, soft morning backlight, sleepy expression, collarbone visible, warm gentle light,", "description": "朝、パジャマが肩からずれた目覚め", "suggestive": True},
    ],
    12: [
        {"prompt": "1girl, school uniform, school rooftop, noon, sitting on bench, blue sky, white clouds, eating bento, wind in hair,", "description": "屋上でお弁当、青空と風", "suggestive": False},
        {"prompt": "1girl, school uniform, school courtyard, under tree, noon light, gentle breeze, eating lunch, dappled light,", "description": "中庭の木陰でランチ", "suggestive": False},
        {"prompt": "1girl, school uniform, school window, leaning on windowsill, noon, reading book, warm sunlight, peaceful,", "description": "窓際で読書、昼休み", "suggestive": False},
        {"prompt": "1girl, school uniform, school cafeteria, noon, tray of food, cheerful, chatting, bright interior,", "description": "学食でランチ、賑やか", "suggestive": False},
        {"prompt": "1girl, school uniform, after PE class, corridor, slightly disheveled uniform, collar open, light blush, afternoon light,", "description": "体育後の廊下、制服が少し乱れ", "suggestive": True},
    ],
    15: [
        {"prompt": "1girl, school uniform, school gate, golden hour, waving goodbye, cherry blossom petals, gentle smile,", "description": "放課後、校門でさよなら", "suggestive": False},
        {"prompt": "1girl, school uniform, walking home, residential street, warm afternoon sunlight, hands in pockets, peaceful,", "description": "下校中、住宅街の夕暮れ前", "suggestive": False},
        {"prompt": "1girl, school uniform, school garden, afternoon, flowers, sitting on bench, resting, soft light, tired but happy,", "description": "放課後、学校の庭でひと休み", "suggestive": False},
        {"prompt": "1girl, school uniform, library, afternoon, books, quiet, reading, warm interior light, concentrated,", "description": "図書室で読書、放課後の静けさ", "suggestive": False},
        {"prompt": "1girl, school uniform, outdoor, afternoon wind, pleated skirt fluttering, holding skirt down, light blush, thighs visible, candid natural,", "description": "放課後、風でスカートがなびく瞬間", "suggestive": True},
    ],
    18: [
        {"prompt": "1girl, casual clothes, street, golden hour sunset, warm orange sky, walking, beautiful evening light,", "description": "夕焼けの帰り道、私服", "suggestive": False},
        {"prompt": "1girl, casual clothes, cafe, window seat, evening, coffee cup, warm interior, relaxed expression, outside view,", "description": "カフェで夕方のひととき", "suggestive": False},
        {"prompt": "1girl, casual clothes, park bench, sunset, golden light, peaceful, end of day, autumn leaves,", "description": "公園のベンチ、夕暮れ", "suggestive": False},
        {"prompt": "1girl, casual clothes, home kitchen, evening, cooking, warm home lighting, comfortable domestic scene,", "description": "夕飯の準備、自宅キッチン", "suggestive": False},
        {"prompt": "1girl, casual off-shoulder top, street, evening breeze, collarbone visible, hair swaying, golden sunset light, natural,", "description": "夕方の私服、オフショルダーで風に揺れる", "suggestive": True},
    ],
    21: [
        {"prompt": "1girl, loungewear, bedroom, night, studying at desk, lamp light, concentrated, cozy night scene, textbooks,", "description": "夜の勉強、デスクランプ", "suggestive": False},
        {"prompt": "1girl, casual wear, bedroom, night, sitting on bed, looking at phone, soft lamp light, relaxing, pillows,", "description": "ベッドでスマホ、夜のリラックス", "suggestive": False},
        {"prompt": "1girl, casual wear, living room, night, couch, reading book, warm indoor light, peaceful evening, cup of tea,", "description": "リビングのソファでお茶と読書", "suggestive": False},
        {"prompt": "1girl, casual wear, bedroom, night, window, city lights background, thoughtful expression, quiet night,", "description": "夜の窓際、街の灯りを眺める", "suggestive": False},
        {"prompt": "1girl, loose oversized shirt, bedroom, late night, sitting on bed, shoulders peeking out, soft lamp light, hair down, natural and relaxed,", "description": "夜、大きめのシャツで肩がのぞく", "suggestive": True},
    ],
    0: [
        {"prompt": "1girl, pajamas, bedroom, midnight, moonlight through window, sitting on bed, serene, soft moonlight, quiet night,", "description": "深夜、月明かりの中パジャマ姿", "suggestive": False},
        {"prompt": "1girl, pajamas, bedroom, midnight, lying on bed, starry night through window, soft pillow, peaceful,", "description": "深夜、ベッドで星空を眺める", "suggestive": False},
        {"prompt": "1girl, pajamas, dim hallway, midnight, getting glass of water, quiet house, soft nightlight, sleepy,", "description": "深夜、薄暗い廊下で水を取りに", "suggestive": False},
        {"prompt": "1girl, pajamas, bedroom window, midnight, looking at moon, serene, quiet contemplation, moonlit room,", "description": "深夜、窓から月を見上げる", "suggestive": False},
        {"prompt": "1girl, pajama top, bedroom, midnight, moonlight illuminating figure, off shoulder, hair loose, sitting on bed, sleepy and soft,", "description": "深夜、パジャマが肩からずれて月明かりの中", "suggestive": True},
    ],
}

# ============================================================
# 特別シーン定義（アイドル/ライブ/学校行事/季節イベント）
# ============================================================

SPECIAL_SCENES = [
    # ── アイドル活動 ────────────────────────────────────────
    {"prompt": "1girl, idol stage outfit, spotlight, microphone, stage, colorful stage lights, performing, crowd silhouette, energetic pose,", "description": "アイドルライブのステージ上、スポットライト", "suggestive": False, "category": "アイドル"},
    {"prompt": "1girl, idol costume, backstage, mirror, stage makeup, getting ready, nervous and excited expression, dressing room,", "description": "バックステージ、ステージ前の準備", "suggestive": False, "category": "アイドル"},
    {"prompt": "1girl, idol outfit, fan meeting, smiling, waving, indoor venue, pastel decorations, happy,", "description": "ファンミーティング、笑顔で手を振る", "suggestive": False, "category": "アイドル"},
    {"prompt": "1girl, idol costume, after performance, catching breath, slightly disheveled, backstage, real and natural moment,", "description": "ライブ終了後、バックステージで息を整える", "suggestive": True, "category": "アイドル"},

    # ── ライブ・音楽 ─────────────────────────────────────────
    {"prompt": "1girl, concert stage, live performance, dramatic lighting, microphone stand, crowd cheering, powerful stance, night concert,", "description": "夜のライブ会場、ドラマチックな照明", "suggestive": False, "category": "ライブ"},
    {"prompt": "1girl, outdoor music festival, summer stage, singing, crowd with glowsticks, summer night sky, energetic,", "description": "夏の野外フェスのステージ", "suggestive": False, "category": "ライブ"},
    {"prompt": "1girl, casual clothes, music room, practicing guitar, afternoon light, music notes, focused expression,", "description": "音楽室でギター練習", "suggestive": False, "category": "ライブ"},

    # ── 学校行事 ─────────────────────────────────────────────
    {"prompt": "1girl, school uniform, apron, school cultural festival, classroom stall, welcoming pose, excited, festival atmosphere,", "description": "文化祭、クラスの出店でお出迎え", "suggestive": False, "category": "文化祭"},
    {"prompt": "1girl, school uniform, sports day, athletic track, running, cheering, energetic, sports festival, sunny day,", "description": "体育祭、競技に全力", "suggestive": False, "category": "体育祭"},
    {"prompt": "1girl, school uniform, graduation ceremony, cherry blossoms, holding diploma, happy tears, spring,", "description": "卒業式、桜と証書を手に", "suggestive": False, "category": "卒業式"},
    {"prompt": "1girl, school uniform, school trip, tourist spot, sightseeing, group photo pose, excited, clear sky,", "description": "修学旅行、観光地でひとり", "suggestive": False, "category": "修学旅行"},
    {"prompt": "1girl, school uniform, school pool, summer, poolside, watching pool lesson, summer heat, blue sky,", "description": "学校のプールサイド、夏の授業", "suggestive": False, "category": "学校行事"},

    # ── 季節・イベント（月別対応） ─────────────────────────────
    {"prompt": "1girl, casual spring clothes, cherry blossom park, hanami, bento, pink petals falling, happy, spring afternoon,", "description": "お花見、桜の下でお弁当", "suggestive": False, "category": "花見", "months": [3, 4]},
    {"prompt": "1girl, yukata, summer festival, fireworks in sky, night market, excited, summer night, lanterns,", "description": "夏祭り、浴衣で花火を見上げる", "suggestive": False, "category": "夏祭り", "months": [7, 8]},
    {"prompt": "1girl, casual summer clothes, beach, ocean, blue sky, summer sunlight, waves, happy and energetic,", "description": "海水浴、夏の砂浜", "suggestive": False, "category": "海・夏", "months": [7, 8]},
    {"prompt": "1girl, swimsuit, beach, ocean, sunny, summer waves, natural candid pose, blue sky, clear water,", "description": "海でのスイムスーツ、夏の太陽", "suggestive": True, "category": "海・夏", "months": [7, 8]},
    {"prompt": "1girl, autumn casual clothes, autumn park, fallen leaves, warm orange colors, peaceful walk, cool breeze,", "description": "紅葉の公園を散歩", "suggestive": False, "category": "秋", "months": [10, 11]},
    {"prompt": "1girl, winter clothes, scarf, first snow, outdoor, snowflakes, wonder expression, white breath, cold but happy,", "description": "初雪、マフラー姿で空を見上げる", "suggestive": False, "category": "冬・雪", "months": [12, 1, 2]},
    {"prompt": "1girl, casual clothes, Christmas, Christmas tree, warm indoor, string lights, happy, presents, festive atmosphere,", "description": "クリスマス、ツリーの前でプレゼントと", "suggestive": False, "category": "クリスマス", "months": [12]},
    {"prompt": "1girl, casual clothes, Valentine's Day, chocolate, kitchen, apron, cooking, excited, heart shape,", "description": "バレンタイン、チョコ作り", "suggestive": False, "category": "バレンタイン", "months": [2]},
    {"prompt": "1girl, casual spring clothes, school entrance ceremony, cherry blossoms, new school bag, excited and nervous, fresh start,", "description": "入学式、桜の前で新生活のスタート", "suggestive": False, "category": "入学・春", "months": [4]},
    {"prompt": "1girl, casual clothes, new year, shrine, hatsumode, coming of age outfit, furisode, serene new year morning,", "description": "初詣、振袖姿で新年参拝", "suggestive": False, "category": "お正月", "months": [1]},

    # ── 日常・バリエーション ───────────────────────────────────
    {"prompt": "1girl, gym uniform, school gym, indoor sports, energetic, volleyball, dynamic pose, afternoon light,", "description": "体育の授業、体育館でスポーツ", "suggestive": False, "category": "体育"},
    {"prompt": "1girl, apron over casual clothes, kitchen, home cooking, dinner preparation, warm home, domestic,", "description": "料理中、エプロン姿", "suggestive": False, "category": "日常"},
    {"prompt": "1girl, casual clothes, shopping mall, looking at clothes, happy, bags, afternoon, modern interior,", "description": "ショッピングモールでお買い物", "suggestive": False, "category": "日常"},
    {"prompt": "1girl, casual clothes, amusement park, roller coaster, excited, screaming happily, bright day,", "description": "遊園地でアトラクション", "suggestive": False, "category": "日常"},
    {"prompt": "1girl, raincoat, rainy day, umbrella, puddles, street, rain, peaceful rainy mood,", "description": "雨の日、カラフルなレインコート", "suggestive": False, "category": "雨の日"},
]


def get_seasonal_special_scenes() -> list:
    """現在の月に合ったシーンを優先リストとして返す（フォールバック用）"""
    month = datetime.now().month
    seasonal = [s for s in SPECIAL_SCENES if month in s.get("months", [month])]
    if len(seasonal) < 3:
        seasonal += [s for s in SPECIAL_SCENES if "months" not in s]
    return seasonal


# ============================================================
# 時間帯ラベル（動的生成関数より前に定義）
# ============================================================

SLOT_NAMES = {6: "朝", 12: "昼", 15: "放課後", 18: "夕方", 21: "夜", 0: "深夜"}

# ============================================================
# フォールバック用固定セリフ（Claude API失敗時）
# ============================================================

FALLBACK_DIALOGUES = {
    "tsumugi": [
        "今日もいい一日だった！✨",
        "ちょっとだけ、頑張りすぎたかも……🌸",
        "こういう時間、好きだな💕",
        "明日もよろしくお願いします！🌟",
        "なんかわくわくしてきた……！🎀",
    ],
    "mio": [
        "今日も、ちゃんと生きられた🌿",
        "この景色、少し覚えておきたい✨",
        "……静かでいい🍃",
        "何も考えない時間も、必要だと思う🌙",
        "いつの間にか、こんな時間になっていた💫",
    ],
    "iroha": [
        "まあ、悪くない一日だったかな🎵",
        "あたしが言うのもなんだけど、頑張ったじゃん✨",
        "別に、心配してたわけじゃないから…💦",
        "次はもっとうまくやれるし！🔥",
        "……ちょっとだけ、楽しかった🌸",
    ],
    "shizuku": [
        "あわわ……！で、でも、やってみます！🌸",
        "みんなのことを思うと、怖くなくなるんです……！💕",
        "え、え、えっと……あ、ありがとうございます！(*´ω`*)✨",
        "わたし、ここぞって時はちゃんとできるんです。たぶん！🌷",
        "今日も全力でいきます……！あわわ、緊張してきた🥺💦",
    ],
    "nagi": [
        "……ちゃんと見てるから、安心して？🌙",
        "もう、しょうがないな。わたしがついてるし✨",
        "疲れたら、言ってね。放っておけないので💫",
        "……べつに、寂しかったわけじゃないけど。いた方がよかったな、とは思って🌿",
        "ちゃんとできてたから、よかった。ほっとした🍃",
    ],
    "yura": [
        "あの……今日も、みんなが笑顔でいてくれてよかったです🌸",
        "なんか、ぽかぽかするね……。わたし、こういう時間がすきです💕",
        "えっと……それって、もしかしてわたしのこと、心配してくれてた……？🥺",
        "うん……なんとなくそんな気がしてたんです。ちゃんとわかりますよ✨",
        "あ、これ……おいしいかも。なんか、ほっとする感じ🍀",
    ],
}


# ============================================================
# シーン＋セリフ 動的生成（Claude API）
# ============================================================

def generate_scene_and_dialogue(
    chara_key: str,
    hour_slot: int,
    use_special: bool,
    use_suggestive: bool,
) -> dict | None:
    """
    Claude APIでシーンコンセプトとセリフを1コールで動的生成。
    失敗時はNoneを返す（呼び出し側が固定プールにフォールバック）。

    Returns dict with keys:
        content_type, prompt, description, dialogue, suggestive, category
    """
    if not (ENABLE_CLAUDE and CLAUDE_CLIENT):
        return None

    chara = CHARACTERS[chara_key]
    time_label = SLOT_NAMES.get(hour_slot, f"{hour_slot}時")
    month = datetime.now().month

    # content_type 決定（reader_talk: 約20%）
    is_reader_talk = (random.randint(1, READER_TALK_RATIO) == 1)
    content_type = "reader_talk" if is_reader_talk else "scene"

    # 各種指示の構築
    suggestive_note = (
        "微エロ要素（肌のちらり見え、オフショルダー、太ももが少し見える等のSFW示唆のみ。"
        "Nude/nipples/explicit は絶対禁止）を含めてよい。"
        if use_suggestive else
        "全年齢・完全SFWのシーンにする。肌の露出を示唆するタグは含めない。"
    )

    if content_type == "reader_talk":
        scene_note = (
            "キャラクターが視聴者・読者に向けて直接語りかけるシーン。"
            "キャラクターが正面を向き、視聴者とまっすぐ目を合わせている構図にする。"
            "上半身またはポートレート寄りの構図。"
        )
        composition_tags = "upper body, portrait, looking at viewer, facing forward, direct gaze,"
        dialogue_note = (
            "視聴者・読者に直接語りかけるセリフ（「あなた」への呼びかけ、"
            "質問、温かい言葉、日常の何気ない共感など）。"
        )
    else:
        if use_special:
            scene_note = (
                f"アイドル活動・ライブ・学校行事・季節イベント（現在{month}月）・"
                "スポーツ・旅行・お祭り・日常の特別な瞬間など、"
                "バリエーション豊かな特別シーンを自由に考案する。"
            )
        else:
            scene_note = (
                f"{time_label}の時間帯らしい日常的なシーン。"
                "毎回異なる場所・状況・衣装・ポーズを新鮮に考案する。"
            )
        composition_tags = ""
        dialogue_note = (
            "そのシーン・時間帯にいる人物が思わず口にしたくなる自然な言葉。"
            "X（Twitter）投稿として読者を引きつける言葉にする。"
        )

    system_prompt = (
        "あなたはアニメキャラクターのビジュアルSNS投稿コンテンツを設計するクリエイターです。\n"
        "Stable Diffusionの英語プロンプトタグと日本語セリフをJSONで出力します。\n"
        "出力はJSON形式のみ。説明文・マークダウン記号は一切含めない。"
    )

    composition_line = (
        f"- scene_promptに必ず含めるタグ: {composition_tags}\n"
        if composition_tags else ""
    )

    user_prompt = (
        f"キャラクター: {chara['name']}\n"
        f"キャラクター外見: {chara['appearance']}\n"
        f"キャラクター性格: {chara['personality']}\n"
        f"時間帯: {time_label}\n\n"
        f"シーン指示: {scene_note}\n"
        f"エロ指示: {suggestive_note}\n\n"
        "以下のJSON形式で出力してください（他のテキストは一切不要）:\n"
        "{\n"
        '  "content_type": "scene" または "reader_talk",\n'
        '  "scene_prompt": "SD英語タグ（カンマ区切り、必ず1girlで始める、場所・衣装・ポーズ・雰囲気・光源を含む）",\n'
        '  "description": "シーンの日本語説明（25文字以内）",\n'
        '  "dialogue": "キャラのセリフ（15〜50文字、性格の口調で、ハッシュタグなし、絵文字を1〜2個自然に入れて可愛らしく）",\n'
        '  "category": "シーンカテゴリ（日本語1語、例: アイドル/文化祭/日常/reader_talk等）"\n'
        "}\n\n"
        "scene_promptの追加要件:\n"
        "- 必ず「1girl,」で始める\n"
        f"{composition_line}"
        "- NSFWタグ（nude, nipples, genitalia等）は絶対に含めない\n"
        "- 具体的で視覚的に鮮明なタグを50〜80語程度で\n"
    )

    try:
        message = CLAUDE_CLIENT.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=320,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()

        # コードブロックがあれば除去
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else parts[0]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        # 必須フィールド確認
        for key in ("content_type", "scene_prompt", "description", "dialogue"):
            if key not in data:
                raise ValueError(f"必須フィールド不足: {key}")

        # NSFWタグ安全チェック
        unsafe_tags = ["nude", "nipple", "genitalia", "explicit", "pussy", "penis", "nsfw"]
        sp_lower = data["scene_prompt"].lower()
        if any(t in sp_lower for t in unsafe_tags):
            raise ValueError("NSFWタグ検出、破棄")

        return {
            "content_type": data["content_type"],
            "prompt": data["scene_prompt"],
            "description": data["description"],
            "dialogue": data["dialogue"].strip().strip("「」''\""),
            "suggestive": use_suggestive,
            "category": data.get("category"),
            "is_dynamic": True,
        }

    except Exception as e:
        print(f"  Claude APIシーン生成失敗: {e}")
        return None


# ============================================================
# シーン選択ロジック（動的優先、フォールバック付き）
# ============================================================

def get_current_hour_slot() -> int:
    h = datetime.now().hour
    for slot in reversed([6, 12, 15, 18, 21, 0]):
        if slot == 0 or h >= slot:
            return slot
    return 6


def select_scene_and_dialogue(chara_key: str, hour_slot: int) -> dict:
    """
    シーンコンセプトとセリフを取得。
    1. Claude APIで動的生成を試みる
    2. 失敗時は固定プール + 固定セリフにフォールバック
    """
    use_special = (random.randint(1, SPECIAL_SCENE_RATIO) == 1)
    use_suggestive = (random.randint(1, SUGGESTIVE_RATIO) == 1)

    # 動的生成を試みる
    result = generate_scene_and_dialogue(chara_key, hour_slot, use_special, use_suggestive)
    if result:
        return result

    # ── フォールバック: 固定シーンプール ──────────────────────
    print("  → 固定シーンプールにフォールバック")
    if use_special:
        candidates = get_seasonal_special_scenes()
    else:
        candidates = TIME_SCENES[hour_slot]

    safe = [s for s in candidates if not s["suggestive"]]
    suggestive_list = [s for s in candidates if s["suggestive"]]

    if use_suggestive and suggestive_list:
        scene = random.choice(suggestive_list)
    else:
        scene = random.choice(safe)

    time_label = SLOT_NAMES.get(hour_slot, f"{hour_slot}時")
    dialogue = random.choice(FALLBACK_DIALOGUES[chara_key])

    return {
        "content_type": "scene",
        "prompt": scene["prompt"],
        "description": scene["description"],
        "dialogue": dialogue,
        "suggestive": scene["suggestive"],
        "category": scene.get("category"),
        "is_dynamic": False,
    }


# ============================================================
# 生成・投稿関数
# ============================================================

def check_nsfw(response_json: dict) -> bool:
    is_nsfw_list = response_json.get("is_nsfw", [])
    if isinstance(is_nsfw_list, list) and any(is_nsfw_list):
        return True
    return False


def build_payload(chara_key: str, scene_prompt: str) -> dict:
    chara = CHARACTERS[chara_key]
    prompt = f"{scene_prompt}\nBREAK\n{chara['lora_block']}{chara['appearance']}"
    return {
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "override_settings": {"sd_model_checkpoint": "bubbleHentai_v20"},
        "sampler_name": "Euler a",
        "scheduler": "Karras",
        "steps": 40,
        "cfg_scale": 6,
        "width": 832,
        "height": 1216,
        "seed": -1,
        "clip_skip": 2,
        "enable_hr": True,
        "hr_upscaler": "R-ESRGAN 4x+ Anime6B",
        "hr_second_pass_steps": 30,
        "denoising_strength": 0.3,
        "hr_scale": 1.5,
        "hr_cfg": 6,
        "alwayson_scripts": ADETAILER_ARGS,
    }


def generate_image(payload: dict) -> tuple:
    resp = requests.post(f"{API_URL}/txt2img", json=payload, timeout=600)
    resp.raise_for_status()
    result = resp.json()
    return base64.b64decode(result["images"][0]), result


def save_image(image_bytes: bytes, chara_key: str, hour_slot: int) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"discord_{chara_key}_{hour_slot}h_{ts}.png"
    path.write_bytes(image_bytes)
    print(f"  保存: {path}")
    return path


def post_to_discord(image_path: Path, dialogue: str, chara_name: str) -> bool:
    content = f"**{chara_name}**「{dialogue}」"
    with open(image_path, "rb") as f:
        resp = requests.post(
            WEBHOOK_URL,
            data={"content": content},
            files={"file": (image_path.name, f, "image/png")},
        )
    ok = resp.status_code in (200, 204)
    print(f"  Discord: {'[OK] 投稿完了' if ok else f'[NG] 失敗 {resp.status_code}'}")
    return ok


def register_to_x_queue(image_path: Path, dialogue: str, slot_label: str = ""):
    try:
        register_one(str(image_path), dialogue, slot_label)
        print(f"  X Queue: [OK] 登録完了")
    except Exception as e:
        print(f"  X Queue: [NG] 失敗（{e}）")


# ============================================================
# メイン生成サイクル
# ============================================================


def run_cycle(hour_slot: int = None, force_chara: str = None):
    if hour_slot is None:
        hour_slot = get_current_hour_slot()

    chara_key = force_chara if force_chara in CHARACTERS else random.choice(list(CHARACTERS.keys()))
    chara_name = CHARACTERS[chara_key]["name"]
    time_label = SLOT_NAMES.get(hour_slot, f"{hour_slot}時")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ── 生成開始 ──")
    print(f"  キャラ: {chara_name}  /  時間帯: {time_label}")

    # シーン＋セリフ生成（動的 or フォールバック）
    scene = select_scene_and_dialogue(chara_key, hour_slot)

    content_label = {
        "reader_talk": "[reader_talk] 読者へ語りかけ",
        "scene":       "[scene] シーン",
    }.get(scene["content_type"], "シーン")
    category_label = f"  特別: {scene['category']}" if scene.get("category") else "  通常"
    dynamic_label  = "動的生成" if scene.get("is_dynamic") else "固定プール"

    print(f"  コンテンツ: {content_label}  /  {category_label}  /  [{dynamic_label}]")
    print(f"  シーン: {scene['description']}")
    print(f"  タイプ: {'微エロ（示唆）' if scene['suggestive'] else '全年齢SFW'}")
    print(f"  セリフ: {scene['dialogue']}")

    # 画像生成
    try:
        image_bytes, api_response = generate_image(build_payload(chara_key, scene["prompt"]))
    except requests.exceptions.ConnectionError:
        print("  [NG] SD WebUIに接続できません。Reforge_API.bat で起動しているか確認してください。")
        return
    except Exception as e:
        print(f"  [NG] 生成エラー: {e}")
        return

    # NSFW検出
    if check_nsfw(api_response):
        print("  [SKIP] NSFW検出: スキップします")
        return

    image_path = save_image(image_bytes, chara_key, hour_slot)
    post_to_discord(image_path, scene["dialogue"], chara_name)
    if ENABLE_X_POST:
        register_to_x_queue(image_path, scene["dialogue"], time_label)

    print(f"  [OK] サイクル完了")


# ============================================================
# スケジュール設定（GASの10分前に生成）
# ============================================================

SCHEDULE = {"05:50": 6, "11:50": 12, "14:50": 15, "17:50": 18, "20:50": 21, "23:50": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now",   action="store_true", help="現在時刻シーンで即時実行")
    parser.add_argument("--time",  type=int, choices=[6, 12, 15, 18, 21, 0], help="時刻指定テスト")
    parser.add_argument("--chara", choices=list(CHARACTERS.keys()), help="キャラ指定")
    args = parser.parse_args()

    if ENABLE_X_POST:
        try:
            validate_config()
        except SystemExit:
            print("[警告] X投稿連携の設定に問題があります。Discordのみ投稿します。")

    # テスト実行
    if args.now or args.time is not None:
        slot = args.time if args.time is not None else get_current_hour_slot()
        print(f"テスト実行: {SLOT_NAMES.get(slot, str(slot)+'時')} / キャラ: {args.chara or 'ランダム'}")
        run_cycle(hour_slot=slot, force_chara=args.chara)
        return

    # 定期スケジュール実行
    print("=" * 55)
    print("Discord/X 自動投稿スクリプト 起動 v3")
    print(f"Claude API動的シーン生成: {'有効' if ENABLE_CLAUDE else '無効（固定プール使用）'}")
    print(f"X投稿連携: {'有効' if ENABLE_X_POST else '無効'}")
    print(f"微エロ確率: 約{100 // SUGGESTIVE_RATIO}%  /  特別シーン確率: 約{100 // SPECIAL_SCENE_RATIO}%")
    print(f"読者語りかけ(reader_talk)確率: 約{100 // READER_TALK_RATIO}%")
    print("スケジュール:")
    for t, slot in SCHEDULE.items():
        s = slot
        schedule.every().day.at(t).do(run_cycle, hour_slot=s)
        print(f"  {t} → {SLOT_NAMES[slot]}シーン生成")
    print("Ctrl+C で停止")
    print("=" * 55)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
リール動画生成スクリプト

gen_manual.py --reel で生成した連続画像をスライドショー動画（mp4）に変換する。

使い方:
  python make_reel.py --story-dir "reels/20260320_朝の準備"
  python make_reel.py --story-dir "reels/20260320_朝の準備" --duration 3.5 --bgm bgm.mp3
  python make_reel.py --list   # reelsフォルダ内のストーリー一覧を表示

オプション:
  --story-dir   画像フォルダのパス（reels/ からの相対パスでも可）
  --duration    1枚あたりの表示秒数（デフォルト: 3.0秒）
  --bgm         BGM音声ファイルのパス（省略可）
  --output      出力mp4ファイル名（省略時: フォルダ名.mp4 として同フォルダに保存）
  --no-discord  Discordへの動画送信をスキップ
  --no-drive    Google Driveへのアップロードをスキップ
  --list        reelsフォルダ内のストーリー一覧を表示して終了

必要ライブラリ:
  pip install moviepy
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Windows cp932環境でUnicode文字を扱えるようにする
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("cp932", "shift_jis", "shift-jis"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

from discord_auto_gen import OUTPUT_DIR, WEBHOOK_URL, CHARACTERS

REEL_BASE_DIR = OUTPUT_DIR.parent / "reels"

# Claude APIクライアント（make_reel.py独自に初期化）
def _get_api_key() -> str:
    """ANTHROPIC_API_KEY を環境変数 → auto_upload.py → Windowsレジストリの順で取得"""
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # auto_upload.py に直接記載されているキーを参照
    try:
        from auto_upload import ANTHROPIC_KEY
        if ANTHROPIC_KEY:
            return ANTHROPIC_KEY
    except Exception:
        pass
    # Windowsレジストリ（ユーザー→システム）
    try:
        import winreg
        for hive, path in [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, path) as reg:
                    val, _ = winreg.QueryValueEx(reg, "ANTHROPIC_API_KEY")
                    return val
            except Exception:
                pass
    except Exception:
        pass
    return ""

try:
    import anthropic as _anthropic
    _api_key = _get_api_key()
    _CLAUDE = _anthropic.Anthropic(api_key=_api_key) if _api_key else _anthropic.Anthropic()
    _CLAUDE_OK = bool(_api_key)
except Exception:
    _CLAUDE = None
    _CLAUDE_OK = False


def _extract_chara_fullname(story_dir: Path) -> str:
    """画像ファイル名からキャラ名（フルネーム）を取得する"""
    images = sorted(story_dir.glob("*.png"))
    for img in images:
        # ファイル名形式: NNN_charakey_timestamp.png
        parts = img.stem.split("_")
        if len(parts) >= 2:
            chara_key = parts[1]
            if chara_key in CHARACTERS:
                return CHARACTERS[chara_key]["name"]
    return ""


def _extract_story_name(folder_name: str) -> str:
    """フォルダ名からストーリー名を取得する（YYYYMMDD_ プレフィックスを除去）"""
    import re
    return re.sub(r"^\d{8}_", "", folder_name)


def generate_caption(story_name: str, captions: list[str], story_dir: Path | None = None) -> str:
    """Claude APIでリール用キャプションを生成する"""
    # ハッシュタグ用にキャラ名・ストーリー名を取得
    chara_fullname = _extract_chara_fullname(story_dir) if story_dir else ""
    story_name_clean = _extract_story_name(story_dir.name) if story_dir else story_name
    fixed_tags = "#もちプロ🍡"
    if chara_fullname:
        fixed_tags += f" #{chara_fullname}"
    fixed_tags += f" #{story_name_clean}"

    if not _CLAUDE_OK or not _CLAUDE:
        # フォールバック：セリフをそのまま並べる
        caption = "\n".join(captions)
        return f"{caption}\n\n{fixed_tags} #AIキャラクター #イラスト"

    scenes_text = "\n".join([f"・{c}" for c in captions])
    prompt = f"""以下のセリフをもとに、Instagramリール動画の投稿キャプション文を日本語で生成してください。

ストーリー名: {story_name_clean}
各シーンのセリフ:
{scenes_text}

条件:
- タイトルや見出し（#で始まる行）は絶対に含めない
- キャラクター本人が話しているような一人称の自然な会話文にする
- セリフの内容・感情・雰囲気を反映し、ストーリーの流れに沿った内容にする
- 絵文字を2〜4個使い、感情を豊かに表現する
- 3〜5文程度で、読みやすいコンパクトな文章
- ハッシュタグは一切含めない
- 「です・ます」より話し言葉に近いナチュラルなトーンで
- 本文のみ出力（説明文・前置きなし）"""

    try:
        message = _CLAUDE.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        # タイトル行（#で始まる行）や余分な前置きを除去
        lines = message.content[0].text.strip().splitlines()
        lines = [l for l in lines if not l.startswith("#")]
        body = "\n".join(lines).strip()

        # 推奨ハッシュタグ2つを別途生成（固定タグとの重複を除外）
        fixed_tag_words = {t.lstrip("#").lower() for t in fixed_tags.split()}
        exclude_note = "、".join(f"#{w}" for w in fixed_tag_words if w)
        tag_prompt = f"""「{story_name_clean}」というテーマのInstagramリール動画に合うハッシュタグを2つだけ提案してください。
日本語または英語で、#記号付きで、スペース区切りで返してください。
例: #アイドル #ライブ
以下のハッシュタグは既に使用済みなので絶対に含めないでください: {exclude_note}
ハッシュタグのみ返答してください。"""

        tag_message = _CLAUDE.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": tag_prompt}],
        )
        # 重複チェック：fixed_tagsと被っているタグを除去
        raw_tags = tag_message.content[0].text.strip().split()
        unique_tags = [t for t in raw_tags if t.lstrip("#").lower() not in fixed_tag_words]
        recommended_tags = " ".join(unique_tags[:2])  # 最大2つ
        return f"{body}\n\n{fixed_tags} {recommended_tags}"

    except Exception as e:
        print(f"  ⚠️ Claude API失敗（{e}）→ フォールバック使用")
        caption = "\n".join(captions)
        return f"{caption}\n\n{fixed_tags} #AIキャラクター #イラスト"


def upload_video_to_drive(video_path: Path) -> tuple[str, str] | None:
    """mp4をGoogle Driveにアップロードして (link, file_id) を返す"""
    try:
        from upload_to_drive import upload_image  # 画像・動画共用
        file_id = upload_image(str(video_path))
        link = f"https://drive.google.com/file/d/{file_id}/view"
        print(f"  Drive リンク   : {link}")
        return link, file_id
    except ImportError:
        print("  Drive: [スキップ] upload_to_drive.py が見つかりません")
        return None
    except Exception as e:
        print(f"  Drive: [NG] アップロード失敗（{e}）")
        return None


def save_reel_queue(file_id: str, caption: str, story_name: str):
    """reel_queue.json に投稿待ちエントリを追加し GitHub に push する"""
    import json
    import subprocess

    queue_path = THIS_DIR / "posts" / "reel_queue.json"

    if queue_path.exists():
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    else:
        queue = []

    queue.append({
        "file_id": file_id,
        "caption": caption,
        "story_name": story_name,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
    })

    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  reel_queue.json: [{story_name}] を登録")

    try:
        subprocess.run(["git", "add", "posts/reel_queue.json"], cwd=THIS_DIR, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: add reel queue {story_name}"],
            cwd=THIS_DIR, check=True,
        )
        subprocess.run(["git", "push"], cwd=THIS_DIR, check=True)
        print("  GitHub: [OK] reel_queue.json をpush完了")
    except subprocess.CalledProcessError as e:
        print(f"  GitHub: [NG] push失敗（{e}）")


def list_stories():
    """reelsフォルダ内のストーリー一覧を表示"""
    if not REEL_BASE_DIR.exists():
        print("reelsフォルダがまだありません。gen_manual.py --reel で画像を生成してください。")
        return
    dirs = sorted([d for d in REEL_BASE_DIR.iterdir() if d.is_dir()])
    if not dirs:
        print("ストーリーフォルダが見つかりません。")
        return
    print(f"\n{'─'*50}")
    print(f"  リール用ストーリー一覧（{REEL_BASE_DIR}）")
    print(f"{'─'*50}")
    for d in dirs:
        images = sorted(d.glob("*.png"))
        mp4s = list(d.glob("*.mp4"))
        status = "✅ 動画あり" if mp4s else "🖼  画像のみ"
        print(f"  {status}  {d.name}  （{len(images)}枚）")
    print(f"{'─'*50}\n")


SUBTITLE_FONT     = r"C:/Windows/Fonts/UDDigiKyokashoN-B.ttc"
SUBTITLE_FONTSIZE = 100
SUBTITLE_COLOR    = "white"
SUBTITLE_STROKE   = "#fbacff"
SUBTITLE_STROKE_W = 6
SUBTITLE_PADDING  = 30   # 下端からのマージン（px）
SUBTITLE_Y_RATIO  = 0.72  # 画面の上から何割の位置に表示（0.5=中央, 0.72=中央やや下）
SUBTITLE_MAX_CHARS = 9    # 1行あたりの最大文字数


SUBTITLE_SYMBOL_FONT = r"C:/Windows/Fonts/seguisym.ttf"  # ♡♪等の記号フォント


def _wrap_text(text: str, max_width: int) -> str:
    """フォント実寸を測りながら、max_width を超えたら改行する。
    句読点・感嘆符等の後は優先的に改行し、それでも収まらない場合は文字単位で折り返す。"""
    import re
    from PIL import ImageFont

    main_font   = ImageFont.truetype(SUBTITLE_FONT,        SUBTITLE_FONTSIZE)
    symbol_font = ImageFont.truetype(SUBTITLE_SYMBOL_FONT, SUBTITLE_FONTSIZE)
    symbol_chars = set('♡♥❤♪♫♬★☆◎●')

    def ch_width(ch):
        f = symbol_font if ch in symbol_chars else main_font
        return f.getlength(ch)

    # Step1: まず句読点後で候補分割
    import re
    segments = re.split(r'(?<=[。！？…♡♥❤♪♫])', text)
    segments = [s for s in segments if s]  # 空文字除去

    lines = []
    current = ''
    current_w = 0

    for seg in segments:
        seg_w = sum(ch_width(c) for c in seg)
        if current_w + seg_w <= max_width and len(current) + len(seg) <= SUBTITLE_MAX_CHARS:
            current += seg
            current_w += seg_w
        else:
            # セグメントが収まらない → まず現在行を確定
            if current:
                lines.append(current)
                current = ''
                current_w = 0
            # セグメント自体が長い場合は文字単位で折り返し
            for ch in seg:
                w = ch_width(ch)
                if (current_w + w > max_width or len(current) >= SUBTITLE_MAX_CHARS) and current:
                    lines.append(current)
                    current = ''
                    current_w = 0
                current += ch
                current_w += w

    if current:
        lines.append(current)

    return '\n'.join(lines)


def _hex_to_rgb(hex_color: str) -> tuple:
    """HEXカラーコードをRGBタプルに変換"""
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _make_subtitle_image(text: str, video_w: int) -> "Image":
    """Pillowで字幕画像（RGBA）を生成する。♡等の記号はSegoe UI Symbolで描画。"""
    from PIL import Image, ImageDraw, ImageFont
    import re

    main_font   = ImageFont.truetype(SUBTITLE_FONT,        SUBTITLE_FONTSIZE)
    symbol_font = ImageFont.truetype(SUBTITLE_SYMBOL_FONT, SUBTITLE_FONTSIZE)

    # 記号かどうかを判定
    symbol_chars = set('♡♥❤♪♫♬★☆◎●')
    def get_font(ch):
        return symbol_font if ch in symbol_chars else main_font

    # 各行のサイズを計算して全体高さを決定
    lines = text.split('\n')
    line_height = SUBTITLE_FONTSIZE + 10
    pad = SUBTITLE_STROKE_W + 4
    img_h = line_height * len(lines) + pad * 2
    img_w = video_w

    img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    text_color  = _hex_to_rgb(SUBTITLE_COLOR)  if SUBTITLE_COLOR.startswith('#')  else SUBTITLE_COLOR
    stroke_color = _hex_to_rgb(SUBTITLE_STROKE) if SUBTITLE_STROKE.startswith('#') else SUBTITLE_STROKE
    sw = SUBTITLE_STROKE_W

    for line_idx, line in enumerate(lines):
        # 行全体の幅を計算（文字ごとに適切なフォントで）
        total_w = sum(get_font(ch).getlength(ch) for ch in line)
        x = (img_w - total_w) / 2
        y = pad + line_idx * line_height

        for ch in line:
            font = get_font(ch)
            ch_w = font.getlength(ch)
            # 縁取り（8方向）
            for dx in range(-sw, sw + 1):
                for dy in range(-sw, sw + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((x + dx, y + dy), ch, font=font, fill=stroke_color)
            # 本文
            draw.text((x, y), ch, font=font, fill=text_color)
            x += ch_w

    return img


def _make_subtitle_clip(text: str, duration: float, video_w: int, video_h: int):
    """1シーン分の字幕クリップをPillow描画で生成する"""
    try:
        from moviepy import ImageClip

        # 幅に合わせて折り返し（句読点優先・文字単位フォールバック）
        margin = 40
        text = _wrap_text(text, max_width=video_w - margin)

        sub_img = _make_subtitle_image(text, video_w)
        import numpy as np
        arr = np.array(sub_img)

        clip = ImageClip(arr, duration=duration)
        # 中央やや下に配置
        y_pos = int(video_h * SUBTITLE_Y_RATIO - sub_img.size[1] / 2)
        return clip.with_position(("center", y_pos))
    except Exception as e:
        print(f"  ⚠️ 字幕生成スキップ（{e}）")
        return None


def make_reel(story_dir: Path, duration: float, bgm_path: Path | None,
              output_path: Path, post_discord: bool, post_drive: bool = True,
              with_subtitle: bool = True):

    # moviepy インポート（v1/v2 両対応）
    try:
        try:
            from moviepy import ImageClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip
        except ImportError:
            from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip
    except ImportError:
        print("❌ moviepy がインストールされていません。")
        print("   pip install moviepy  を実行してください。")
        return

    # 画像ファイルを番号順に取得
    images = sorted(story_dir.glob("*.png"))
    if not images:
        print(f"❌ 画像ファイルが見つかりません: {story_dir}")
        return

    # captions.txt からセリフを読み込む（字幕用）
    captions_path = story_dir / "captions.txt"
    captions = []
    if with_subtitle and captions_path.exists():
        captions = [l.strip() for l in captions_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ── リール動画生成開始 ──")
    print(f"  フォルダ   : {story_dir}")
    print(f"  画像枚数   : {len(images)}枚")
    print(f"  1枚の秒数  : {duration}秒")
    print(f"  合計時間   : {len(images) * duration:.1f}秒")
    print(f"  BGM        : {bgm_path or '（なし）'}")
    print(f"  字幕       : {'あり（' + str(len(captions)) + '件）' if captions else 'なし'}")
    print(f"  出力先     : {output_path}")

    # スライドショー作成（字幕合成あり）
    print("  動画を生成中...")
    clips = []
    for i, img in enumerate(images):
        base = ImageClip(str(img), duration=duration)
        caption_text = captions[i] if i < len(captions) else ""
        if caption_text:
            sub = _make_subtitle_clip(caption_text, duration, base.size[0], base.size[1])
            if sub:
                clips.append(CompositeVideoClip([base, sub]))
                continue
        clips.append(base)
    video = concatenate_videoclips(clips, method="compose")

    # BGM合成
    if bgm_path and bgm_path.exists():
        audio = AudioFileClip(str(bgm_path))
        # 動画より長い場合はカット、短い場合はループ
        if audio.duration < video.duration:
            loops = int(video.duration / audio.duration) + 1
            try:
                from moviepy import concatenate_audioclips
            except ImportError:
                from moviepy.editor import concatenate_audioclips
            audio = concatenate_audioclips([audio] * loops)
        audio = audio.subclip(0, video.duration)
        video = video.set_audio(audio)
    elif bgm_path:
        print(f"  ⚠️ BGMファイルが見つかりません（スキップ）: {bgm_path}")

    # 書き出し（Instagram Reels推奨: 1080×1920、ただし元画像比率を維持）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        logger=None,  # moviepyのログを抑制
    )
    print(f"  ✅ 動画保存完了: {output_path}")

    # キャプション生成
    captions_path = story_dir / "captions.txt"
    if captions_path.exists():
        captions = [l.strip() for l in captions_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        captions = []
    print("  キャプション生成中...")
    caption = generate_caption(story_dir.name, captions, story_dir=story_dir)
    caption_out = story_dir / "caption.txt"
    caption_out.write_text(caption, encoding="utf-8")
    print(f"\n{'─'*50}")
    print("  📝 生成キャプション:")
    print(f"{caption}")
    print(f"{'─'*50}\n")

    # Google Driveアップロード → reel_queue.json に登録
    if post_drive:
        drive_result = upload_video_to_drive(output_path)
        if drive_result:
            _, file_id = drive_result
            save_reel_queue(file_id, caption, story_dir.name)

    # Discord送信（動画＋キャプション）
    if post_discord:
        _post_video_to_discord(output_path, story_dir.name, caption)


def _post_video_to_discord(video_path: Path, story_name: str, caption: str = ""):
    """Discord Webhookに動画＋キャプションを送信"""
    print("  Discord送信中...")
    content = f"🎬【リール動画】{story_name}"
    if caption:
        content += f"\n\n📝 キャプション（コピー用）:\n```\n{caption}\n```"
    try:
        with open(video_path, "rb") as f:
            resp = requests.post(
                WEBHOOK_URL,
                data={"content": content},
                files={"file": (video_path.name, f, "video/mp4")},
                timeout=120,
            )
        if resp.status_code in (200, 204):
            print("  Discord: [OK] 送信完了")
        else:
            print(f"  Discord: [NG] ステータス {resp.status_code}")
    except Exception as e:
        print(f"  Discord: [NG] エラー（{e}）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--story-dir", help="画像フォルダのパス（reels/フォルダ名 でも可）")
    parser.add_argument("--duration",  type=float, default=3.0, help="1枚あたりの表示秒数（デフォルト: 3.0）")
    parser.add_argument("--bgm",       default="", help="BGM音声ファイルのパス（省略可）")
    parser.add_argument("--output",    default="", help="出力mp4ファイル名（省略時: フォルダ名.mp4）")
    parser.add_argument("--no-discord",  action="store_true", help="Discord送信をスキップ")
    parser.add_argument("--no-drive",    action="store_true", help="Google Driveアップロードをスキップ")
    parser.add_argument("--no-subtitle", action="store_true", help="字幕テキストを入れない")
    parser.add_argument("--list",        action="store_true", help="ストーリー一覧を表示して終了")
    args = parser.parse_args()

    if args.list:
        list_stories()
        return

    if not args.story_dir:
        parser.error("--story-dir を指定してください（または --list でフォルダ一覧を確認）")

    # フォルダパスの解決（reels/フォルダ名 or フルパス）
    story_dir = Path(args.story_dir)
    if not story_dir.is_absolute():
        # 相対パスの場合: スクリプトのフォルダ基準 → なければ REEL_BASE_DIR 基準
        candidate = THIS_DIR / story_dir
        if not candidate.exists():
            candidate = REEL_BASE_DIR / story_dir.name
        story_dir = candidate

    if not story_dir.exists():
        print(f"❌ フォルダが見つかりません: {story_dir}")
        print("   python make_reel.py --list  で一覧を確認してください。")
        return

    # 出力パス
    output_name = args.output or f"{story_dir.name}.mp4"
    output_path = story_dir / output_name

    # BGMパス
    bgm_path = Path(args.bgm) if args.bgm else None

    make_reel(
        story_dir=story_dir,
        duration=args.duration,
        bgm_path=bgm_path,
        output_path=output_path,
        post_discord=not args.no_discord,
        post_drive=not args.no_drive,
        with_subtitle=not args.no_subtitle,
    )


if __name__ == "__main__":
    main()

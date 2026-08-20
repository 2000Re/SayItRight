"""
video_builder.py

単語 + IPA発音記号 + 音声(スロー/通常) から、YouTube通常動画用の
横型動画(1920x1080, 16:9)を生成する。

[Design] 縦型(9:16)かつ3分以内の動画はYouTubeに自動的にShorts判定され、
Shortsフィード上ではカスタムサムネイルが表示されない。このチャンネルは
サムネイル(単語をどんと表示)を主要な導線にしたいため、あえて横型(16:9)で
作成し、時間の長さに関わらず「通常動画」として扱われるようにしている。

sheriff-shorts-bot(everysheriff/video_generator.py)の以下の資産を流用:
  - Playwrightでのスクリーンショット撮影パターン(ブラウザは1回だけ起動)
  - create_zoomed_clips によるKen Burns風のズーム効果
  - moviepyでの結合・書き出し
"""
import os
import random
import uuid

from moviepy import ImageClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips
from PIL import Image

from config import AUDIO_PAD_MS

# ------------------------------------------------------------------
# 動画キャンバスサイズ(横型 16:9)
# ------------------------------------------------------------------
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

# サムネイルサイズ(YouTube推奨: 1280x720, 16:9)
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# 背景色バリエーション(sheriff-shorts-botと同系統の落ち着いた配色)
BG_COLORS = [
    "#171310", "#221C18", "#1C211B", "#2B1E18", "#181C24",
]

# サムネイル配色: 黄色地に黒文字(高視認性の定番配色)
THUMBNAIL_BG_COLOR = "#FFD400"
THUMBNAIL_TEXT_COLOR = "#111111"

FONT_STACK = '"DejaVu Sans", "Liberation Sans", "Segoe UI", Roboto, sans-serif'

# 前後の無音パディング秒数。generate_audio.py が付与する無音(config.AUDIO_PAD_MS)
# から算出することで、値がずれることを防ぐ。
AUDIO_PAD_SECONDS = AUDIO_PAD_MS / 1000

ENDING_CTAS = [
    "Follow for more tricky words!",
    "Could you say it right?",
    "Comment your score!",
    "Tap follow for daily challenges!",
]


def _html_escape(text):
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _screenshot_html(browser, html_content, output_path, width=VIDEO_WIDTH, height=VIDEO_HEIGHT):
    """起動済みのPlaywright browserでHTMLをスクリーンショットする。"""
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        page.set_content(html_content)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(300)
        page.screenshot(path=output_path)
    finally:
        page.close()


def create_zoomed_clips(base_image_path, duration, start_zoom, end_zoom, steps=15):
    """静止画に対してKen Burns風のゆっくりズームをかけた連続クリップを作る。
    (sheriff-shorts-botのvideo_generator.pyと同一のロジック)"""
    base_image = Image.open(base_image_path)
    width, height = base_image.size
    step_duration = duration / steps
    clips = []
    temp_paths = []

    try:
        for i in range(steps):
            t = i / (steps - 1) if steps > 1 else 0.0
            zoom_factor = start_zoom + (end_zoom - start_zoom) * t

            new_w = int(width * zoom_factor)
            new_h = int(height * zoom_factor)

            resized_img = base_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = (new_w - width) // 2
            top = (new_h - height) // 2
            cropped_img = resized_img.crop((left, top, left + width, top + height))

            temp_path = "temp_zoom_" + uuid.uuid4().hex + ".png"
            cropped_img.save(temp_path)
            temp_paths.append(temp_path)

            clip = ImageClip(temp_path).with_duration(step_duration)
            clips.append(clip)
    except Exception:
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        for p in temp_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        raise
    finally:
        base_image.close()

    return clips, temp_paths


def _cleanup_temp_files(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception as e:
            print(f"[Warning] Failed to remove temp file {p}: {e}")


# ------------------------------------------------------------------
# HTML組み立て(動画本編。16:9キャンバス)
# ------------------------------------------------------------------
def _build_intro_html(bg_hex):
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        f"body {{margin:0; padding:0; width:{VIDEO_WIDTH}px; height:{VIDEO_HEIGHT}px; background-color:{bg_hex}; "
        "color:#F2EDE4; display:flex; flex-direction:column; justify-content:center; "
        f"align-items:center; box-sizing:border-box; font-family:{FONT_STACK};}}"
        ".prompt {font-size:88px; font-weight:800; text-align:center; width:1300px; line-height:1.3;}"
        ".sub {font-size:44px; margin-top:36px; opacity:0.75;}"
        "</style></head><body>"
        "<div class='prompt'>Can you pronounce this word?</div>"
        "<div class='sub'>🔊 listen carefully</div>"
        "</body></html>"
    )


def _build_main_html(word, ipa, bg_hex, label):
    safe_word = _html_escape(word)
    safe_ipa = _html_escape(ipa) if ipa else ""
    ipa_html = f"<div class='ipa'>/{safe_ipa}/</div>" if safe_ipa else ""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        f"body {{margin:0; padding:0; width:{VIDEO_WIDTH}px; height:{VIDEO_HEIGHT}px; background-color:{bg_hex}; "
        "color:#F2EDE4; display:flex; flex-direction:column; justify-content:center; "
        f"align-items:center; box-sizing:border-box; font-family:{FONT_STACK};}}"
        ".word {font-size:170px; font-weight:800; text-align:center; word-break:break-word; padding:0 100px;}"
        ".ipa {font-size:70px; margin-top:40px; opacity:0.8; letter-spacing:0.02em;}"
        ".label {font-size:44px; margin-top:56px; padding:16px 40px; border-radius:100px; "
        "background-color:rgba(242,237,228,0.12); font-weight:600;}"
        "</style></head><body>"
        f"<div class='word'>{safe_word}</div>"
        f"{ipa_html}"
        f"<div class='label'>{_html_escape(label)}</div>"
        "</body></html>"
    )


def _build_ending_html(word, ipa, bg_hex):
    safe_word = _html_escape(word)
    safe_ipa = _html_escape(ipa) if ipa else ""
    cta = random.choice(ENDING_CTAS)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        f"body {{margin:0; padding:0; width:{VIDEO_WIDTH}px; height:{VIDEO_HEIGHT}px; background-color:{bg_hex}; "
        "color:#F2EDE4; display:flex; flex-direction:column; justify-content:center; "
        f"align-items:center; box-sizing:border-box; font-family:{FONT_STACK};}}"
        ".check {font-size:80px;}"
        ".word {font-size:120px; font-weight:800; text-align:center; margin-top:16px; padding:0 100px; word-break:break-word;}"
        ".ipa {font-size:54px; margin-top:20px; opacity:0.8;}"
        ".cta {font-size:46px; margin-top:60px; font-weight:700; text-align:center; padding:0 120px;}"
        "</style></head><body>"
        "<div class='check'>✅</div>"
        f"<div class='word'>{safe_word}</div>"
        f"<div class='ipa'>/{safe_ipa}/</div>"
        f"<div class='cta'>{_html_escape(cta)}</div>"
        "</body></html>"
    )


# ------------------------------------------------------------------
# サムネイル(黄色地に黒文字。単語のみをどんと表示)
# ------------------------------------------------------------------
def _build_thumbnail_html(word):
    safe_word = _html_escape(word)
    # 単語の長さに応じてフォントサイズを自動調整(長い単語がはみ出さないように)
    length = len(word)
    if length <= 6:
        font_size = 220
    elif length <= 10:
        font_size = 170
    elif length <= 14:
        font_size = 130
    else:
        font_size = 100

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        f"body {{margin:0; padding:0; width:{THUMBNAIL_WIDTH}px; height:{THUMBNAIL_HEIGHT}px; "
        f"background-color:{THUMBNAIL_BG_COLOR}; color:{THUMBNAIL_TEXT_COLOR}; "
        "display:flex; justify-content:center; align-items:center; "
        f"box-sizing:border-box; font-family:{FONT_STACK};}}"
        f".word {{font-size:{font_size}px; font-weight:900; text-align:center; "
        "word-break:break-word; padding:0 60px; letter-spacing:-0.01em;}}"
        "</style></head><body>"
        f"<div class='word'>{safe_word}</div>"
        "</body></html>"
    )


def generate_thumbnail(word, output_path):
    """
    単語をどんと表示するだけのサムネイル(1280x720、黄色地に黒文字)を生成する。
    動画本体の生成とは独立した、専用のPlaywrightセッションで完結させる。
    """
    from playwright.sync_api import sync_playwright

    html_content = _build_thumbnail_html(word)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            _screenshot_html(browser, html_content, output_path,
                              width=THUMBNAIL_WIDTH, height=THUMBNAIL_HEIGHT)
        finally:
            browser.close()

    print(f"[Thumbnail] 生成しました: {output_path}")
    return output_path


def build_word_video(word, ipa, audio_slow_path, audio_normal_path, output_filename):
    """
    単語1つ分の動画(mp4, 16:9横型)を生成する。

    audio_slow_path / audio_normal_path は generate_audio.py が出力した
    (前後 AUDIO_PAD_SECONDS 秒の無音つき)mp3を想定。ここで無音部分は
    subclippedで取り除いてから動画に配置する。
    """
    from playwright.sync_api import sync_playwright

    bg_hex = random.choice(BG_COLORS)
    unique_id = uuid.uuid4().hex

    intro_img = f"temp_intro_{unique_id}.png"
    main_slow_img = f"temp_main_slow_{unique_id}.png"
    main_normal_img = f"temp_main_normal_{unique_id}.png"
    ending_img = f"temp_ending_{unique_id}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            _screenshot_html(browser, _build_intro_html(bg_hex), intro_img)
            _screenshot_html(browser, _build_main_html(word, ipa, bg_hex, "🐢 slow"), main_slow_img)
            _screenshot_html(browser, _build_main_html(word, ipa, bg_hex, "🐇 normal speed"), main_normal_img)
            _screenshot_html(browser, _build_ending_html(word, ipa, bg_hex), ending_img)
        finally:
            browser.close()

    all_clips_to_close = []
    zoom_temp_paths = []
    slow_audio = normal_audio = mixed_audio = video_clip = None

    try:
        # --- 音声の準備(無音パディングを取り除く) ---
        slow_audio_full = AudioFileClip(audio_slow_path)
        all_clips_to_close.append(slow_audio_full)
        slow_core_duration = max(0.3, slow_audio_full.duration - AUDIO_PAD_SECONDS * 2)
        slow_audio = slow_audio_full.subclipped(AUDIO_PAD_SECONDS, AUDIO_PAD_SECONDS + slow_core_duration)

        normal_audio_full = AudioFileClip(audio_normal_path)
        all_clips_to_close.append(normal_audio_full)
        normal_core_duration = max(0.3, normal_audio_full.duration - AUDIO_PAD_SECONDS * 2)
        normal_audio = normal_audio_full.subclipped(AUDIO_PAD_SECONDS, AUDIO_PAD_SECONDS + normal_core_duration)

        # --- 各セクションの長さ ---
        intro_duration = 1.2
        gap = 0.4
        slow_section = slow_core_duration + gap
        normal_section = normal_core_duration + gap
        ending_duration = 2.2

        # --- 画像クリップ(ズーム付き) ---
        intro_clips, intro_paths = create_zoomed_clips(intro_img, intro_duration, 1.0, 1.03, steps=6)
        zoom_temp_paths.extend(intro_paths)
        all_clips_to_close.extend(intro_clips)

        slow_clips, slow_paths = create_zoomed_clips(main_slow_img, slow_section, 1.0, 1.05, steps=10)
        zoom_temp_paths.extend(slow_paths)
        all_clips_to_close.extend(slow_clips)

        normal_clips, normal_paths = create_zoomed_clips(main_normal_img, normal_section, 1.05, 1.10, steps=10)
        zoom_temp_paths.extend(normal_paths)
        all_clips_to_close.extend(normal_clips)

        ending_clips, ending_paths = create_zoomed_clips(ending_img, ending_duration, 1.0, 1.04, steps=8)
        zoom_temp_paths.extend(ending_paths)
        all_clips_to_close.extend(ending_clips)

        video_clip = concatenate_videoclips(
            intro_clips + slow_clips + normal_clips + ending_clips
        )

        # --- 音声の配置 ---
        audio_sources = [
            slow_audio.with_start(intro_duration),
            normal_audio.with_start(intro_duration + slow_section),
        ]

        mixed_audio = CompositeAudioClip(audio_sources)
        previous_video_clip = video_clip
        video_clip = video_clip.with_audio(mixed_audio)
        try:
            previous_video_clip.close()
        except Exception:
            pass

        video_clip.write_videofile(
            output_filename, fps=30, codec="libx264", audio_codec="aac", logger=None
        )

    finally:
        if mixed_audio:
            try:
                mixed_audio.close()
            except Exception:
                pass
        if video_clip:
            try:
                video_clip.close()
            except Exception:
                pass
        for clip in all_clips_to_close:
            try:
                clip.close()
            except Exception:
                pass
        _cleanup_temp_files(
            intro_img, main_slow_img, main_normal_img, ending_img, *zoom_temp_paths
        )

    print(f"[Video Gen] 動画を生成しました: {output_filename}")
    return output_filename
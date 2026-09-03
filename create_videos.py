"""
create_videos.py

candidates.json の各単語について、
  audio_output/{word}_slow.mp3 / {word}_normal.mp3
を使って動画(mp4, 9:16縦型、Shorts用)を生成し、video_output/ に出力する。

前提:
  - generate_audio.py が事前に実行済みで、audio_output/ に音声があること
  - pip install moviepy playwright pillow
  - playwright install --with-deps chromium (ブラウザ本体のインストールが別途必要)
"""
import json
import os

from playwright.sync_api import sync_playwright

from arpabet_to_ipa import arpabet_to_ipa
from video_builder import build_word_video
from config import (
    CANDIDATES_PATH,
    AUDIO_DIR,
    VIDEO_DIR as VIDEO_OUTPUT_DIR,
)


def main():
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)

    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("candidates.json が空です。動画生成をスキップします。")
        return

    # 単語ごとにPlaywrightブラウザを起動し直すと無駄が大きいため、
    # バッチ全体で1つのブラウザを使い回す。
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for c in candidates:
                word = c["word"]
                arpabet = c["arpabet"]
                ipa = arpabet_to_ipa(arpabet)

                slow_path = os.path.join(AUDIO_DIR, f"{word.lower()}_slow.mp3")
                normal_path = os.path.join(AUDIO_DIR, f"{word.lower()}_normal.mp3")

                if not (os.path.exists(slow_path) and os.path.exists(normal_path)):
                    print(f"[Skip] {word}: 音声ファイルが見つかりません "
                          f"({slow_path} / {normal_path})。generate_audio.pyを先に実行してください。")
                    continue

                video_path = os.path.join(VIDEO_OUTPUT_DIR, f"{word.lower()}.mp4")

                print(f"動画生成中: {word} (IPA: {ipa})")
                try:
                    build_word_video(
                        word=word,
                        ipa=ipa,
                        audio_slow_path=slow_path,
                        audio_normal_path=normal_path,
                        output_filename=video_path,
                        browser=browser,
                    )
                except Exception as e:
                    print(f"::error::{word} の動画生成に失敗しました: {e}")
                    # write_videofileはffmpegへ直接書き込むため、エンコード
                    # 途中(ディスク容量不足・ワークフローのタイムアウト等)で
                    # 失敗すると不完全なmp4がそのまま残ることがある。
                    # upload_videos.pyはファイルの存在チェックしかしないため、
                    # ここで削除しておかないと壊れた動画がアップロードされうる。
                    if os.path.exists(video_path):
                        try:
                            os.remove(video_path)
                        except OSError as remove_error:
                            print(f"[Warning] 不完全な動画ファイルの削除に失敗しました: {remove_error}")
                    continue
        finally:
            browser.close()

    print("全単語の動画生成処理が完了しました。")


if __name__ == "__main__":
    main()
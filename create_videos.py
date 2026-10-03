"""
create_videos.py

candidates.json の各単語について、
  audio_output/{word}_slow.mp3 / {word}_normal.mp3
を使って動画を生成する。1単語につき以下の3つを出力する:
  - Shorts用動画(mp4, 9:16縦型) -> video_output/
  - 通常動画(mp4, 16:9横型、Shorts用動画をピラーボックスしたもの)
    -> regular_video_output/
  - サムネイル(jpg, 単語をどんと表示。Shorts・通常動画で共用)
    -> thumbnail_output/

前提:
  - generate_audio.py が事前に実行済みで、audio_output/ に音声があること
  - pip install moviepy playwright pillow
  - playwright install --with-deps chromium (ブラウザ本体のインストールが別途必要)
"""
import json
import os

from playwright.sync_api import sync_playwright

from arpabet_to_ipa import arpabet_to_ipa
from video_builder import build_word_video, build_regular_video, generate_thumbnail
from config import (
    CANDIDATES_PATH,
    AUDIO_DIR,
    VIDEO_DIR as VIDEO_OUTPUT_DIR,
    REGULAR_VIDEO_DIR as REGULAR_VIDEO_OUTPUT_DIR,
    THUMBNAIL_DIR as THUMBNAIL_OUTPUT_DIR,
)


def main():
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    os.makedirs(REGULAR_VIDEO_OUTPUT_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_OUTPUT_DIR, exist_ok=True)

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

                regular_video_path = os.path.join(REGULAR_VIDEO_OUTPUT_DIR, f"{word.lower()}.mp4")
                print(f"通常動画生成中: {word}")
                try:
                    build_regular_video(video_path, regular_video_path)
                except Exception as e:
                    print(f"::error::{word} の通常動画生成に失敗しました: {e}")
                    if os.path.exists(regular_video_path):
                        try:
                            os.remove(regular_video_path)
                        except OSError as remove_error:
                            print(f"[Warning] 不完全な動画ファイルの削除に失敗しました: {remove_error}")
                    # 通常動画の生成に失敗しても、Shorts用動画は生成済みなので
                    # アップロード自体は継続させる(upload_videos.py側で
                    # 通常動画ファイルが無ければそちらのアップロードだけスキップする)。

                thumbnail_path = os.path.join(THUMBNAIL_OUTPUT_DIR, f"{word.lower()}.jpg")
                print(f"サムネイル生成中: {word}")
                try:
                    generate_thumbnail(word, thumbnail_path, browser=browser)
                except Exception as e:
                    print(f"::error::{word} のサムネイル生成に失敗しました: {e}")
        finally:
            browser.close()

    print("全単語の動画生成処理が完了しました。")


if __name__ == "__main__":
    main()

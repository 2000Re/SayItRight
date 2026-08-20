"""
create_videos.py

candidates.json の各単語について、
  audio_output/{word}_slow.mp3 / {word}_normal.mp3
を使って動画(mp4, 16:9横型)とサムネイル(jpg)を生成し、
video_output/ / thumbnail_output/ に出力する。

前提:
  - generate_audio.py が事前に実行済みで、audio_output/ に音声があること
  - pip install moviepy playwright pillow
  - playwright install --with-deps chromium (ブラウザ本体のインストールが別途必要)
"""
import json
import os

from arpabet_to_ipa import arpabet_to_ipa
from video_builder import build_word_video, generate_thumbnail

CANDIDATES_PATH = "candidates.json"
AUDIO_DIR = "audio_output"
VIDEO_OUTPUT_DIR = "video_output"
THUMBNAIL_OUTPUT_DIR = "thumbnail_output"


def main():
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_OUTPUT_DIR, exist_ok=True)

    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("candidates.json が空です。動画生成をスキップします。")
        return

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
        thumbnail_path = os.path.join(THUMBNAIL_OUTPUT_DIR, f"{word.lower()}.jpg")

        print(f"動画生成中: {word} (IPA: {ipa})")
        try:
            build_word_video(
                word=word,
                ipa=ipa,
                audio_slow_path=slow_path,
                audio_normal_path=normal_path,
                output_filename=video_path,
            )
        except Exception as e:
            print(f"[Error] {word} の動画生成に失敗しました: {e}")
            continue

        print(f"サムネイル生成中: {word}")
        try:
            generate_thumbnail(word, thumbnail_path)
        except Exception as e:
            print(f"[Error] {word} のサムネイル生成に失敗しました: {e}")

    print("全単語の動画・サムネイル生成処理が完了しました。")


if __name__ == "__main__":
    main()
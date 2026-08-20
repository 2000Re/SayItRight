"""
upload_videos.py

candidates.json の各単語について、
  video_output/{word}.mp4
  thumbnail_output/{word}.jpg
をYouTubeにアップロードする。

認証方式はsheriff-shorts-bot(movie.py)と同じパターン:
  環境変数 YT_REFRESH_TOKEN / YT_CLIENT_ID / YT_CLIENT_SECRET から
  google.oauth2.credentials.Credentials を組み立てる。
  ただしhard2sayは別チャンネル用なので、これらは
  sheriff-shorts-bot側とは別の値(hard2say専用のOAuthクライアント/
  リフレッシュトークン)を使うこと。
"""
import json
import os
import time

import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from arpabet_to_ipa import arpabet_to_ipa

CANDIDATES_PATH = "candidates.json"
VIDEO_DIR = "video_output"
THUMBNAIL_DIR = "thumbnail_output"
USED_WORDS_PATH = "used_words.json"

# 初回運用時は "unlisted" にして、実際の見え方を確認してから
# "public" に変更するのがおすすめ。
PRIVACY_STATUS = os.environ.get("YT_PRIVACY_STATUS", "public")
CATEGORY_ID = "27"  # Education

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def load_used_words() -> list:
    """使用済み単語履歴を古い→新しい順で読み込む。

    各要素は {"word": str, "patterns": list[str]}。旧形式(単語の文字列だけの
    リスト)のファイルも読み込めるよう、文字列の要素は patterns 不明(空リスト)
    として扱う。fetch_and_score.py の同名関数と同じ形式。"""
    if not os.path.exists(USED_WORDS_PATH):
        return []
    with open(USED_WORDS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    history = []
    for entry in raw:
        if isinstance(entry, str):
            history.append({"word": entry, "patterns": []})
        else:
            history.append({"word": entry["word"], "patterns": entry.get("patterns", [])})
    return history


def save_used_words(history: list) -> None:
    """使用済み単語履歴を古い→新しい順のまま保存する(直近パターン判定に使うため)。"""
    with open(USED_WORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def build_youtube_client():
    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=None,
    )
    return build("youtube", "v3", credentials=creds)


def build_metadata(word, ipa):
    title = f"How to Pronounce {word}"
    description = (
        f"How do you pronounce \"{word}\"?\n"
        f"Phonetic: /{ipa}/\n\n"
        f"#pronunciation #english #howtopronounce"
    )
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["pronunciation", "english", word.lower(), "how to pronounce"],
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_video(youtube, video_path, metadata):
    """動画をアップロードする。一時的なエラーはリトライする。"""
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=metadata, media_body=media)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = request.execute()
            return response["id"]
        except HttpError as e:
            last_error = e
            print(f"    アップロード{attempt}回目失敗: {e}")
            time.sleep(RETRY_BACKOFF_SECONDS)
    raise last_error


def upload_thumbnail(youtube, video_id, thumbnail_path):
    if not os.path.exists(thumbnail_path):
        print(f"    [Warning] サムネイルが見つかりません: {thumbnail_path}")
        return
    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()


def main():
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("candidates.json が空です。アップロードをスキップします。")
        return

    youtube = build_youtube_client()
    history = load_used_words()

    for c in candidates:
        word = c["word"]
        arpabet = c["arpabet"]
        ipa = arpabet_to_ipa(arpabet)

        video_path = os.path.join(VIDEO_DIR, f"{word.lower()}.mp4")
        thumbnail_path = os.path.join(THUMBNAIL_DIR, f"{word.lower()}.jpg")

        if not os.path.exists(video_path):
            print(f"[Skip] {word}: 動画ファイルが見つかりません({video_path})")
            continue

        print(f"アップロード中: {word}")
        metadata = build_metadata(word, ipa)

        try:
            video_id = upload_video(youtube, video_path, metadata)
            print(f"  -> https://youtu.be/{video_id}")
        except Exception as e:
            print(f"[Error] {word} のアップロードに失敗しました: {e}")
            continue

        # アップロードが成功して初めて「使用済み」として記録する。
        # (途中で失敗した単語を使用済み扱いにすると、動画が公開されないまま
        #  二度と候補に上がらなくなってしまうため)
        # patterns も一緒に記録し、次回の fetch_and_score.py が直近と
        # 綴りパターンが被る単語を避けられるようにする。
        history.append({"word": word.upper(), "patterns": c.get("patterns", [])})
        save_used_words(history)

        try:
            upload_thumbnail(youtube, video_id, thumbnail_path)
            print("  -> サムネイル設定完了")
        except Exception as e:
            print(f"[Warning] {word} のサムネイル設定に失敗しました: {e}")

    print("全単語のアップロード処理が完了しました。")


if __name__ == "__main__":
    main()
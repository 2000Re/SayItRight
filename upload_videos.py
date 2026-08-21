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

必要なOAuthスコープについて:
  動画のアップロード(videos.insert)・サムネイル設定(thumbnails.set)だけなら
  https://www.googleapis.com/auth/youtube.upload で足りるが、
  日本語ローカライズ設定(videos.update, apply_localizations)には
  https://www.googleapis.com/auth/youtube (または youtube.force-ssl)
  スコープが必要。youtube.upload のみで発行したrefresh tokenだと
  videos.update が403 insufficientPermissionsで失敗する
  (アップロード自体は成功するので、失敗しても警告のみで処理は継続する)。
"""
import json
import os
import time

import google.oauth2.credentials
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from arpabet_to_ipa import arpabet_to_ipa
from config import (
    CANDIDATES_PATH,
    VIDEO_DIR,
    THUMBNAIL_DIR,
    USED_WORDS_PATH,
    DEFAULT_PRIVACY_STATUS,
    YOUTUBE_CATEGORY_ID as CATEGORY_ID,
    UPLOAD_MAX_RETRIES as MAX_RETRIES,
    UPLOAD_RETRY_BACKOFF_SECONDS as RETRY_BACKOFF_SECONDS,
    DICTIONARY_API_URL,
    DICTIONARY_API_TIMEOUT_SECONDS,
)

# 初回運用時は "unlisted" にして、実際の見え方を確認してから
# "public" に変更するのがおすすめ。
PRIVACY_STATUS = os.environ.get("YT_PRIVACY_STATUS", DEFAULT_PRIVACY_STATUS)


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


def fetch_definition(word: str) -> dict | None:
    """無料の辞書API(dictionaryapi.dev)から意味・例文を取得する。

    SEO対策として説明欄に単語の意味を載せるための補助情報で、
    無くても動画の投稿自体は成立させたいため、取得失敗時は
    警告を出すだけでNoneを返し、呼び出し側で通常の説明文に
    フォールバックする。"""
    url = DICTIONARY_API_URL.format(word=word.lower())
    try:
        resp = requests.get(url, timeout=DICTIONARY_API_TIMEOUT_SECONDS)
        resp.raise_for_status()
        entries = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"    [Info] {word} の意味の取得をスキップします({e})")
        return None

    for entry in entries:
        for meaning in entry.get("meanings", []):
            for definition in meaning.get("definitions", []):
                text = definition.get("definition")
                if not text:
                    continue
                return {
                    "part_of_speech": meaning.get("partOfSpeech", ""),
                    "definition": text,
                    "example": definition.get("example"),
                }
    return None


def build_tags(word, lookup: dict | None = None):
    tags = [
        "pronunciation", "english", word.lower(), "how to pronounce",
        "english pronunciation", "vocabulary", "english learning", "IPA",
    ]
    if lookup and lookup.get("part_of_speech"):
        tags.append(lookup["part_of_speech"])
    return tags


def build_metadata(word, ipa, lookup: dict | None = None):
    title = f"How to Pronounce {word}"
    lines = [
        f'How do you pronounce "{word}"?',
        f"Phonetic: /{ipa}/",
    ]
    if lookup and lookup.get("definition"):
        lines.append("")
        pos = lookup.get("part_of_speech")
        label = f"Meaning ({pos})" if pos else "Meaning"
        lines.append(f"{label}: {lookup['definition']}")
        if lookup.get("example"):
            lines.append(f'Example: "{lookup["example"]}"')
    lines.append("")
    lines.append("#pronunciation #english #howtopronounce")
    description = "\n".join(lines)

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": build_tags(word, lookup),
            "categoryId": CATEGORY_ID,
            # localizations機能(build_localizations)を使うには、動画の
            # 基準言語(defaultLanguage)が設定されている必要がある。
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }


def build_localizations(word, ipa):
    """タイトル/説明の日本語版を返す(YouTubeのlocalizations機能用)。

    メインのタイトル/説明(英語)は変更せず、視聴者の言語設定が日本語の場合に
    追加で表示される訳を提供する形。定型文のみ日本語化し、辞書APIから
    取得した英語の定義・例文自体は翻訳しない(翻訳API未導入のため)。"""
    return {
        "ja": {
            "title": f"「{word}」の発音、正しく言える?",
            "description": (
                f'英単語「{word}」はどう発音する?\n'
                f"発音記号(IPA): /{ipa}/\n\n"
                f"#発音 #英語 #英単語"
            ),
        }
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


def apply_localizations(youtube, video_id, localizations):
    """日本語タイトル/説明(localizations)を設定する。

    メインのメタデータとは独立した付加情報のため、失敗しても動画自体の
    公開は妨げない(警告を出すだけで処理を継続する)。"""
    youtube.videos().update(
        part="localizations",
        body={"id": video_id, "localizations": localizations},
    ).execute()


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
        lookup = fetch_definition(word)
        metadata = build_metadata(word, ipa, lookup)

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

        try:
            apply_localizations(youtube, video_id, build_localizations(word, ipa))
            print("  -> 日本語ローカライズ設定完了")
        except HttpError as e:
            if e.resp.status == 403:
                print(f"[Warning] {word} の日本語ローカライズ設定に失敗しました(権限不足): {e}\n"
                      f"    -> YT_REFRESH_TOKEN が youtube.upload スコープのみで発行されている"
                      f"可能性があります。videos.update には youtube (または youtube.force-ssl) "
                      f"スコープが必要です。OAuth同意画面で該当スコープを追加のうえ、"
                      f"refresh tokenを再発行してください。")
            else:
                print(f"[Warning] {word} の日本語ローカライズ設定に失敗しました: {e}")
        except Exception as e:
            print(f"[Warning] {word} の日本語ローカライズ設定に失敗しました: {e}")

    print("全単語のアップロード処理が完了しました。")


if __name__ == "__main__":
    main()
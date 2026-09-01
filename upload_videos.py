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
from dictionary_lookup import parse_definition_response
from used_words_store import load_used_words, save_used_words
from config import (
    CANDIDATES_PATH,
    VIDEO_DIR,
    THUMBNAIL_DIR,
    DEFAULT_PRIVACY_STATUS,
    YOUTUBE_CATEGORY_ID as CATEGORY_ID,
    UPLOAD_MAX_RETRIES as MAX_RETRIES,
    UPLOAD_RETRY_BACKOFF_SECONDS as RETRY_BACKOFF_SECONDS,
    DICTIONARY_API_URL,
    DICTIONARY_API_TIMEOUT_SECONDS,
    DICTIONARY_API_MAX_RETRIES,
    DICTIONARY_API_RETRY_BACKOFF_SECONDS,
    DICTIONARY_API_HEADERS,
)

# 初回運用時は "unlisted" にして、実際の見え方を確認してから
# "public" に変更するのがおすすめ。
PRIVACY_STATUS = os.environ.get("YT_PRIVACY_STATUS", DEFAULT_PRIVACY_STATUS)

# YouTube Data API v3の公式ドキュメントに基づく、1回あたりのクォータ消費コスト
# (日次クォータ 10,000 units に対する目安として実行ログに表示する)。
# リトライで複数回叩いた場合も、実際に送ったリクエスト数としてそのまま数える。
#
# videos.insert は長らく1600 unitsだったが、2025年12月4日にGoogleが
# 約100 unitsに引き下げた(日次クォータ10,000 units ÷ 100 = 100本/日となり、
# 別枠の「Video Uploads per day: 100」上限と一致する)。
QUOTA_COST_PER_CALL = {
    "videos.insert": 100,
    "thumbnails.set": 50,
    "videos.update": 50,
}
_api_call_counts = {name: 0 for name in QUOTA_COST_PER_CALL}


def _log_api_usage_summary():
    """このスクリプト実行で消費したYouTube Data APIのクォータ概算をログに出す。

    GCP Consoleのクォータ画面を都度開かなくても、実行ログだけで
    (videos.insert=100 units等の)おおよその消費量を把握できるようにする。"""
    total_units = sum(count * QUOTA_COST_PER_CALL[name] for name, count in _api_call_counts.items())
    print("=== API使用量(YouTube Data API v3、概算) ===")
    for name, count in _api_call_counts.items():
        print(f"  {name}: {count}回 (1回あたり{QUOTA_COST_PER_CALL[name]} units)")
    print(f"  概算クォータ消費: {total_units} units (日次上限 10,000 units の目安)")
    print(f"  動画アップロード回数: {_api_call_counts['videos.insert']}回"
          f" (日次上限100本の目安)")


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
    """Wiktionary(en.wiktionary.org)の無料APIから意味・例文を取得する。

    SEO対策として説明欄に単語の意味を載せるための補助情報で、
    無くても動画の投稿自体は成立させたいため、取得失敗時は
    警告を出すだけでNoneを返し、呼び出し側で通常の説明文に
    フォールバックする。

    タイムアウトや接続エラー、5xxエラーなど一時的な障害は数回リトライする。
    404(その単語が辞書に無い)は再試行しても結果が変わらないため、
    リトライせず即座に諦める。"""
    url = DICTIONARY_API_URL.format(word=word.lower())
    last_error = None

    for attempt in range(1, DICTIONARY_API_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=DICTIONARY_API_TIMEOUT_SECONDS, headers=DICTIONARY_API_HEADERS)
        except requests.RequestException as e:
            last_error = e
            print(f"    [Info] {word} の意味の取得{attempt}回目に失敗しました({e})。リトライします。")
            time.sleep(DICTIONARY_API_RETRY_BACKOFF_SECONDS)
            continue

        if resp.status_code == 404:
            print(f"    [Info] {word} の意味は辞書に見つかりませんでした。")
            return None

        try:
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            print(f"    [Info] {word} の意味の取得{attempt}回目に失敗しました({e})。リトライします。")
            time.sleep(DICTIONARY_API_RETRY_BACKOFF_SECONDS)
            continue

        return parse_definition_response(data)

    print(f"    [Info] {word} の意味の取得を{DICTIONARY_API_MAX_RETRIES}回試しても"
          f"取得できませんでした({last_error})。スキップします。")
    return None


def build_tags(word, lookup: dict | None = None):
    tags = [
        "pronunciation", "english", word.lower(), "how to pronounce",
        "english pronunciation", "vocabulary", "english learning", "IPA",
        "shorts",
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
    lines.append("#shorts #pronunciation #english #howtopronounce")
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
                f"#shorts #発音 #英語 #英単語"
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
            _api_call_counts["videos.insert"] += 1
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
    _api_call_counts["thumbnails.set"] += 1
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()


def apply_localizations(youtube, video_id, localizations):
    """日本語タイトル/説明(localizations)を設定する。

    メインのメタデータとは独立した付加情報のため、失敗しても動画自体の
    公開は妨げない(警告を出すだけで処理を継続する)。"""
    _api_call_counts["videos.update"] += 1
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
        # 綴りパターンが被る単語を避けられるようにする。run_id は
        # compile_shorts.py が結合動画作成時に、この回の video-output
        # アーティファクト(GitHub Actions)から動画本体を取得するために使う
        # (GITHUB_RUN_ID はGitHub Actionsが各実行に自動設定する環境変数)。
        history.append({
            "word": word.upper(),
            "patterns": c.get("patterns", []),
            "video_id": video_id,
            "run_id": os.environ.get("GITHUB_RUN_ID"),
        })
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
    _log_api_usage_summary()


if __name__ == "__main__":
    main()
"""
compile_shorts.py

used_words.json に記録された「使用済み(=アップロード成功済み)」の動画のうち、
まだ結合動画に使っていないものが COMPILATION_BATCH_SIZE 件たまったら、
1本の横型(16:9)動画に結合し、「通常動画」として再アップロードする。

[Design] Shorts(縦型9:16、3分以内)を単純に何本か連結しても、合計尺が
3分以内のままだと縦型ゆえにYouTubeにShorts判定されてしまう
(判定は投稿者の意図ではなく、アスペクト比+尺のみで決まる仕様のため)。
そのため結合時に各クリップを横型(16:9)キャンバスにピラーボックス
(左右に無地の帯)で配置し直し、確実に「通常動画」として扱われるようにする。

[Design] 動画本体の取得元について: 当初はYouTubeに公開済みの動画をyt-dlpで
再ダウンロードする方式だったが、GitHub ActionsのIPがYouTube側に
「Sign in to confirm you're not a bot」でボット判定される問題が
player_client変更・cookie認証のいずれでも解決しなかった(cookieを渡しても
なお拒否された)。YouTube側の対ボット対策は年々強化されており、
データセンターのIPからは根本的に不利な戦いのため、YouTube/yt-dlpに一切
依存しない方式に変更した: create_videos.pyが生成した動画は既に
fetch_candidates.ymlの「Upload video files as artifact」ステップで
GitHub Actionsアーティファクト(video-output)として保存されているため、
これをGitHub Actions APIから取得する。取得元のrunは、upload_videos.pyが
used_words.jsonへ記録する各エントリのrun_id(GITHUB_RUN_ID)で特定する。

[Design] アーティファクトの保持期限切れ・該当runが見つからない等の
「恒久的に取得不可能」なケースで、その1本のせいで結合処理全体が永久に
止まってしまわないよう、該当エントリは結合対象から除外し
(compilation_state.pyのskipped_video_idsに記録)、残りの動画で結合を続行する。
run_idが記録されていない旧いエントリ(この方式導入前にアップロードされた
もの)は、そもそもどのrunのアーティファクトか特定できないため結合対象外にする。

YouTube Data API(結合動画のアップロード用)の認証方式・環境変数は
upload_videos.pyと同じ(YT_REFRESH_TOKEN / YT_CLIENT_ID / YT_CLIENT_SECRET)。
GitHub Actions APIの認証には環境変数 GITHUB_TOKEN(ワークフロー側で
secrets.GITHUB_TOKEN を渡す。追加のシークレット登録は不要)を使う。
"""
import os
import time
import uuid

import google.oauth2.credentials
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, concatenate_videoclips

from used_words_store import load_used_words
from compilation_state import (
    load_compilation_state,
    save_compilation_state,
    select_pending,
    pillarbox_scale,
    find_artifact,
    extract_zip_member,
)
from config import (
    COMPILATION_BATCH_SIZE,
    COMPILATION_DOWNLOAD_DIR,
    COMPILATION_OUTPUT_DIR,
    COMPILATION_VIDEO_WIDTH,
    COMPILATION_VIDEO_HEIGHT,
    COMPILATION_BG_COLOR,
    COMPILATION_DOWNLOAD_MAX_RETRIES,
    COMPILATION_DOWNLOAD_RETRY_BACKOFF_SECONDS,
    COMPILATION_GITHUB_API_TIMEOUT_SECONDS,
    COMPILATION_ARTIFACT_NAME,
    DEFAULT_PRIVACY_STATUS,
    YOUTUBE_CATEGORY_ID,
)

GITHUB_API_BASE = "https://api.github.com"


class ArtifactUnavailableError(Exception):
    """該当エントリの動画アーティファクトが恒久的に取得できない
    (該当runが見つからない/保持期限切れ/アーティファクト内に対象の
    ファイルが無い、等)。リトライしても解決しないため、呼び出し側は
    このエントリを結合対象から除外してよい。"""

# upload_videos.pyと同じく、実行ログだけでYouTube Data APIの
# クォータ消費量(概算)を把握できるようにする。
QUOTA_COST_PER_CALL = {"videos.insert": 100}
_api_call_counts = {name: 0 for name in QUOTA_COST_PER_CALL}


def _log_api_usage_summary():
    total_units = sum(count * QUOTA_COST_PER_CALL[name] for name, count in _api_call_counts.items())
    print("=== API使用量(YouTube Data API v3、概算) ===")
    for name, count in _api_call_counts.items():
        print(f"  {name}: {count}回 (1回あたり{QUOTA_COST_PER_CALL[name]} units)")
    print(f"  概算クォータ消費: {total_units} units (日次上限 10,000 units の目安)")


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


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def download_video(entry: dict, output_path: str) -> None:
    """entryが記録しているGitHub Actions run_idから、その回の
    video-outputアーティファクトを取得し、対象の単語のmp4を取り出す。

    run_id未記録・該当runが見つからない・アーティファクトの保持期限切れ・
    アーティファクト内に対象ファイルが無い、のいずれもArtifactUnavailableError
    (恒久的に取得不可能)を送出する。それ以外(ネットワークエラー・GitHub API側の
    5xx等)は通常のExceptionとして送出し、一時的な問題として上位でリトライ対象にする。"""
    run_id = entry.get("run_id")
    if not run_id:
        raise ArtifactUnavailableError(
            f"{entry['word']}: run_idが記録されていないため取得できません"
            "(この方式の導入前にアップロードされたエントリの可能性があります)"
        )

    repo = os.environ["GITHUB_REPOSITORY"]
    headers = _github_headers()

    resp = requests.get(
        f"{GITHUB_API_BASE}/repos/{repo}/actions/runs/{run_id}/artifacts",
        headers=headers,
        timeout=COMPILATION_GITHUB_API_TIMEOUT_SECONDS,
    )
    if resp.status_code == 404:
        raise ArtifactUnavailableError(f"run {run_id} が見つかりません(削除された可能性があります)")
    resp.raise_for_status()

    artifact = find_artifact(resp.json().get("artifacts", []), COMPILATION_ARTIFACT_NAME)
    if artifact is None:
        raise ArtifactUnavailableError(f"run {run_id} に{COMPILATION_ARTIFACT_NAME}アーティファクトが見つかりません")
    if artifact.get("expired"):
        raise ArtifactUnavailableError(f"run {run_id} の{COMPILATION_ARTIFACT_NAME}アーティファクトは保持期限切れです")

    zip_resp = requests.get(
        artifact["archive_download_url"],
        headers=headers,
        timeout=COMPILATION_GITHUB_API_TIMEOUT_SECONDS,
    )
    zip_resp.raise_for_status()

    member_name = f"{entry['word'].lower()}.mp4"
    try:
        content = extract_zip_member(zip_resp.content, member_name)
    except KeyError:
        raise ArtifactUnavailableError(
            f"{COMPILATION_ARTIFACT_NAME}アーティファクト内に{member_name}が見つかりません"
        )

    with open(output_path, "wb") as f:
        f.write(content)


def download_video_with_retry(entry: dict, output_path: str) -> None:
    """取得失敗を数回リトライする(一時的なネットワーク不調対策)。

    ArtifactUnavailableError(恒久的に取得不可能)は即座に再送出し、リトライしない
    (リトライしても結果が変わらないため)。それ以外のエラーは
    COMPILATION_DOWNLOAD_MAX_RETRIES回までリトライし、それでも失敗する場合は
    例外を送出する。呼び出し側は例外の型で恒久的/一時的を判別する。"""
    last_error = None
    for attempt in range(1, COMPILATION_DOWNLOAD_MAX_RETRIES + 1):
        try:
            download_video(entry, output_path)
            return
        except ArtifactUnavailableError:
            raise
        except Exception as e:
            last_error = e
            print(f"    取得{attempt}回目失敗: {e}")
            time.sleep(COMPILATION_DOWNLOAD_RETRY_BACKOFF_SECONDS)
    raise last_error


def pillarbox(clip):
    """縦長のクリップを、横型キャンバスの中央に配置し、左右を無地で埋める。"""
    scale = pillarbox_scale(clip.w, clip.h, COMPILATION_VIDEO_WIDTH, COMPILATION_VIDEO_HEIGHT)
    resized = clip.resized(scale)
    bg = ColorClip(
        size=(COMPILATION_VIDEO_WIDTH, COMPILATION_VIDEO_HEIGHT),
        color=COMPILATION_BG_COLOR,
        duration=clip.duration,
    )
    return CompositeVideoClip([bg, resized.with_position("center")]).with_duration(clip.duration)


def build_compilation_metadata(words: list) -> dict:
    title = f"{len(words)} Tricky English Words to Pronounce | Compilation"
    description = (
        f"A compilation of {len(words)} tricky English pronunciation words:\n"
        + ", ".join(w.title() for w in words)
        + "\n\n#pronunciation #english #compilation #englishlearning"
    )
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["pronunciation", "english", "compilation", "english learning", "IPA"],
            "categoryId": YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY_STATUS", DEFAULT_PRIVACY_STATUS),
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_compilation(youtube, video_path: str, metadata: dict) -> str:
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=metadata, media_body=media)
    _api_call_counts["videos.insert"] += 1
    response = request.execute()
    return response["id"]


def main():
    history = load_used_words()
    # video_id/run_idが無い(旧形式のまま、またはこの方式導入前に
    # アップロードされた)エントリは、どのrunのアーティファクトか
    # 特定できないため結合対象外にする。
    compilable = [h for h in history if h.get("video_id") and h.get("run_id")]

    state = load_compilation_state()
    pending = select_pending(compilable, state)

    if not pending:
        print("結合対象がありません。")
        return

    os.makedirs(COMPILATION_DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(COMPILATION_OUTPUT_DIR, exist_ok=True)

    batch = []
    downloaded_paths = []
    newly_skipped_ids = []
    raw_clips = []
    pillarboxed_clips = []
    final_clip = None
    upload_succeeded = False

    try:
        for entry in pending:
            if len(batch) >= COMPILATION_BATCH_SIZE:
                break
            path = os.path.join(COMPILATION_DOWNLOAD_DIR, f"{entry['video_id']}.mp4")
            print(f"  取得中: {entry['word']} ({entry['video_id']}, run {entry['run_id']})")
            try:
                download_video_with_retry(entry, path)
            except ArtifactUnavailableError as e:
                print(f"::warning::{entry['word']} ({entry['video_id']}) のアーティファクトが"
                      f"恒久的に取得できないため、結合対象から除外します: {e}")
                newly_skipped_ids.append(entry["video_id"])
                continue
            except Exception as e:
                # ネットワークエラー・GitHub API側の5xx等、恒久的とは判断
                # できない一時的な問題である可能性が高い。ここで結合対象から
                # 除外してしまうと、実際には取得可能な動画が二度と結合対象に
                # ならなくなるため、除外せずに今回の結合処理自体を中断する
                # (次回同じ動画から再試行する)。
                print(f"::warning::{entry['word']} ({entry['video_id']}) の取得に"
                      f"{COMPILATION_DOWNLOAD_MAX_RETRIES}回失敗しました。恒久的な問題とは"
                      f"判断できないため、結合対象から除外せず今回の結合処理を中断します"
                      f"(次回同じ動画から再試行します): {e}")
                raise
            downloaded_paths.append(path)
            batch.append(entry)

        if len(batch) < COMPILATION_BATCH_SIZE:
            print(f"結合対象がまだ{len(batch)}件です({COMPILATION_BATCH_SIZE}件たまったら結合します)。今回はスキップします。")
            return

        print(f"{len(batch)}件の動画を結合します: {[b['word'] for b in batch]}")

        for path in downloaded_paths:
            clip = VideoFileClip(path)
            raw_clips.append(clip)
            pillarboxed_clips.append(pillarbox(clip))

        final_clip = concatenate_videoclips(pillarboxed_clips, method="compose")
        output_path = os.path.join(COMPILATION_OUTPUT_DIR, f"compilation_{uuid.uuid4().hex}.mp4")
        final_clip.write_videofile(
            output_path, fps=30, codec="libx264", audio_codec="aac", logger=None
        )

        youtube = build_youtube_client()
        metadata = build_compilation_metadata([b["word"] for b in batch])
        video_id = upload_compilation(youtube, output_path, metadata)
        print(f"[Compilation] アップロード完了: https://youtu.be/{video_id}")
        _log_api_usage_summary()

        # アップロードが成功して初めて結合済みとして記録する
        # (途中で失敗した場合は次回同じバッチで再挑戦できるようにするため)
        state["compiled_video_ids"].extend(b["video_id"] for b in batch)
        upload_succeeded = True

    finally:
        if newly_skipped_ids:
            state["skipped_video_ids"].extend(newly_skipped_ids)
        if newly_skipped_ids or upload_succeeded:
            save_compilation_state(state)

        if final_clip:
            try:
                final_clip.close()
            except Exception:
                pass
        for clip in pillarboxed_clips:
            try:
                clip.close()
            except Exception:
                pass
        for clip in raw_clips:
            try:
                clip.close()
            except Exception:
                pass
        for path in downloaded_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print(f"[Warning] Failed to remove temp file {path}: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 結合動画は本編パイプラインとは独立した追加機能のため、
        # ここで失敗しても当日の単語投稿・コミット処理は止めない。
        print(f"::error::結合動画の処理中にエラーが発生しました: {e}")

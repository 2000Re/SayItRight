"""
compile_shorts.py

used_words.json に記録された「使用済み(=アップロード成功済み)」の動画のうち、
まだ結合動画に使っていないものが COMPILATION_BATCH_SIZE 件たまったら、
YouTubeに公開済みの動画をyt-dlpでダウンロードして1本の横型(16:9)動画に
結合し、「通常動画」として再アップロードする。

[Design] Shorts(縦型9:16、3分以内)を単純に何本か連結しても、合計尺が
3分以内のままだと縦型ゆえにYouTubeにShorts判定されてしまう
(判定は投稿者の意図ではなく、アスペクト比+尺のみで決まる仕様のため)。
そのため結合時に各クリップを横型(16:9)キャンバスにピラーボックス
(左右に無地の帯)で配置し直し、確実に「通常動画」として扱われるようにする。

動画ファイル自体はGitHub Actionsの実行間で永続化していないため、
すでにYouTubeに公開済みの自分の動画をyt-dlpで取得し直す方式にしている
(追加のストレージや再生成コストが不要なため)。

[Design] 動画が削除・非公開化・著作権クレーム等で恒久的に取得できなく
なった場合、その1本のせいで結合処理全体が永久に止まってしまわないよう、
ダウンロードに一定回数失敗した動画は結合対象から除外し
(compilation_state.pyのskipped_video_idsに記録)、残りの動画で結合を続行する。

認証方式・環境変数はupload_videos.pyと同じ
(YT_REFRESH_TOKEN / YT_CLIENT_ID / YT_CLIENT_SECRET)。
"""
import os
import time
import uuid

import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import yt_dlp
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, concatenate_videoclips

from used_words_store import load_used_words
from compilation_state import (
    load_compilation_state,
    save_compilation_state,
    select_pending,
    pillarbox_scale,
    is_permanently_unavailable,
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
    DEFAULT_PRIVACY_STATUS,
    YOUTUBE_CATEGORY_ID,
)

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


def download_video(video_id: str, output_path: str) -> None:
    """公開済みの自分の動画をyt-dlpでダウンロードする。"""
    ydl_opts = {
        "outtmpl": output_path,
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        # GitHub ActionsのようなデータセンターのIPからのアクセスは、
        # YouTube側に「Sign in to confirm you're not a bot」でボット判定
        # され弾かれることがある。web以外のクライアント(android)はこの
        # チェックを要求されにくいことが知られているため、cookie等の
        # 追加設定なしに試せる緩和策としてandroidクライアントを優先する。
        # (万能の解決策ではなく、YouTube側の仕様変更で効かなくなる可能性がある)
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])


def download_video_with_retry(video_id: str, output_path: str) -> None:
    """ダウンロード失敗を数回リトライする(一時的なネットワーク不調対策)。

    それでも失敗する場合は例外を送出する。呼び出し側は is_permanently_unavailable()
    で「恒久的に取得不可能」と判断できた場合のみ結合対象から除外する。それ以外の
    エラー(ボット判定・レート制限等)は実行環境側の一時的な問題の可能性が高いため、
    ここで諦めても skipped_video_ids には入れず、次回同じ動画から再試行する。"""
    last_error = None
    for attempt in range(1, COMPILATION_DOWNLOAD_MAX_RETRIES + 1):
        try:
            download_video(video_id, output_path)
            return
        except Exception as e:
            last_error = e
            print(f"    ダウンロード{attempt}回目失敗: {e}")
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
    # video_id が無い(旧形式のまま/アップロード時にvideo_id記録前の)
    # エントリは結合動画の元にできないため対象外にする。
    compilable = [h for h in history if h.get("video_id")]

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
            print(f"  ダウンロード中: {entry['word']} ({entry['video_id']})")
            try:
                download_video_with_retry(entry["video_id"], path)
            except Exception as e:
                if is_permanently_unavailable(e):
                    print(f"::warning::{entry['word']} ({entry['video_id']}) のダウンロードに"
                          f"{COMPILATION_DOWNLOAD_MAX_RETRIES}回失敗したため、結合対象から除外します"
                          f"(動画の削除/非公開化/著作権クレーム等の可能性があります: {e})")
                    newly_skipped_ids.append(entry["video_id"])
                    continue
                # ボット判定・レート制限・ネットワーク不調等、動画自体では
                # なく実行環境側の一時的な問題である可能性が高いエラー。
                # ここで結合対象から除外してしまうと、実際には取得可能な
                # 動画が二度と結合対象にならなくなるため、除外せずに今回の
                # 結合処理自体を中断する(次回同じ動画から再試行する)。
                print(f"::warning::{entry['word']} ({entry['video_id']}) のダウンロードに"
                      f"{COMPILATION_DOWNLOAD_MAX_RETRIES}回失敗しました。動画自体ではなく"
                      f"実行環境側の一時的な問題の可能性があるため、結合対象から除外せず"
                      f"今回の結合処理を中断します(次回同じ動画から再試行します): {e}")
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
        print(f"[Error] 結合動画の処理中にエラーが発生しました: {e}")

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

認証方式・環境変数はupload_videos.pyと同じ
(YT_REFRESH_TOKEN / YT_CLIENT_ID / YT_CLIENT_SECRET)。
"""
import json
import os
import uuid

import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import yt_dlp
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, concatenate_videoclips

from used_words_store import load_used_words
from config import (
    COMPILATION_STATE_PATH,
    COMPILATION_BATCH_SIZE,
    COMPILATION_DOWNLOAD_DIR,
    COMPILATION_OUTPUT_DIR,
    COMPILATION_VIDEO_WIDTH,
    COMPILATION_VIDEO_HEIGHT,
    COMPILATION_BG_COLOR,
    DEFAULT_PRIVACY_STATUS,
    YOUTUBE_CATEGORY_ID,
)


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


def load_compilation_state() -> int:
    """これまでに結合済みの件数(compilable historyの先頭から何件を消費したか)を読み込む。

    used_words.json同様、ファイルが無い/空/壊れている場合は0件として扱い、
    処理自体は止めない。"""
    if not os.path.exists(COMPILATION_STATE_PATH):
        return 0
    with open(COMPILATION_STATE_PATH, encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return 0
    try:
        return json.loads(content).get("compiled_count", 0)
    except json.JSONDecodeError as e:
        print(f"警告: {COMPILATION_STATE_PATH} の読み込みに失敗しました({e})。0件として続行します。")
        return 0


def save_compilation_state(compiled_count: int) -> None:
    with open(COMPILATION_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"compiled_count": compiled_count}, f, ensure_ascii=False, indent=2)


def download_video(video_id: str, output_path: str) -> None:
    """公開済みの自分の動画をyt-dlpでダウンロードする。"""
    ydl_opts = {
        "outtmpl": output_path,
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])


def pillarbox(clip):
    """縦長のクリップを、横型キャンバスの中央に配置し、左右を無地で埋める。"""
    scale = COMPILATION_VIDEO_HEIGHT / clip.h
    resized = clip.resized(scale)
    if resized.w > COMPILATION_VIDEO_WIDTH:
        scale = COMPILATION_VIDEO_WIDTH / clip.w
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
    response = request.execute()
    return response["id"]


def main():
    history = load_used_words()
    # video_id が無い(旧形式のまま/アップロード時にvideo_id記録前の)
    # エントリは結合動画の元にできないため対象外にする。
    compilable = [h for h in history if h.get("video_id")]

    compiled_count = load_compilation_state()
    pending = compilable[compiled_count:]

    if len(pending) < COMPILATION_BATCH_SIZE:
        print(f"結合対象がまだ{len(pending)}件です({COMPILATION_BATCH_SIZE}件たまったら結合します)。今回はスキップします。")
        return

    batch = pending[:COMPILATION_BATCH_SIZE]
    print(f"{len(batch)}件の動画を結合します: {[b['word'] for b in batch]}")

    os.makedirs(COMPILATION_DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(COMPILATION_OUTPUT_DIR, exist_ok=True)

    downloaded_paths = []
    raw_clips = []
    pillarboxed_clips = []
    final_clip = None

    try:
        for entry in batch:
            path = os.path.join(COMPILATION_DOWNLOAD_DIR, f"{entry['video_id']}.mp4")
            print(f"  ダウンロード中: {entry['word']} ({entry['video_id']})")
            download_video(entry["video_id"], path)
            downloaded_paths.append(path)

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

        # アップロードが成功して初めて結合済みとして記録する
        # (途中で失敗した場合は次回同じバッチで再挑戦できるようにするため)
        save_compilation_state(compiled_count + COMPILATION_BATCH_SIZE)

    finally:
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

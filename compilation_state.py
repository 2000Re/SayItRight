"""
compilation_state.py

compile_shorts.py の結合状態(結合済み・恒久的に取得不可能な動画)を管理する。

yt-dlp/moviepy/google-api-python-client 等の重い依存を持たないため、
requirements-dev.txt だけの軽量なテスト環境からもインポートしてテストできる
(used_words_store.py と同じ狙いでcompile_shorts.pyから切り出している)。
"""
import json
import os

from config import COMPILATION_STATE_PATH


def load_compilation_state() -> dict:
    """結合状態を読み込む。

    {"compiled_video_ids": [...], "skipped_video_ids": [...]}
    - compiled_video_ids: 過去に結合動画へ実際に取り込まれ、アップロードに
      成功した動画のvideo_id。
    - skipped_video_ids: ダウンロードを試みたが恒久的に失敗し、結合対象から
      除外したvideo_id(動画の削除・非公開化・著作権クレーム等が主な原因で、
      リトライしても解決しない)。ここに記録しておかないと、同じ動画のダウン
      ロードに毎回失敗し続け、それ以降の単語が永久に結合されなくなる。

    ファイルが無い/空/壊れている場合は空の状態として扱い、処理を止めない。
    旧形式({"compiled_count": N})しか無い場合も空の状態として扱う
    (本機能はまだ実運用でcompiled_count>0に達していないため、
    データロスの実害はない)。"""
    empty = {"compiled_video_ids": [], "skipped_video_ids": []}
    if not os.path.exists(COMPILATION_STATE_PATH):
        return empty
    with open(COMPILATION_STATE_PATH, encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return empty
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"警告: {COMPILATION_STATE_PATH} の読み込みに失敗しました({e})。状態なしとして続行します。")
        return empty
    return {
        "compiled_video_ids": raw.get("compiled_video_ids", []),
        "skipped_video_ids": raw.get("skipped_video_ids", []),
    }


def save_compilation_state(state: dict) -> None:
    with open(COMPILATION_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def select_pending(compilable: list, state: dict) -> list:
    """結合済みでも恒久スキップ済みでもないエントリを、元の順序のまま返す。"""
    exclude = set(state["compiled_video_ids"]) | set(state["skipped_video_ids"])
    return [h for h in compilable if h["video_id"] not in exclude]


# 「恒久的に取得不可能(=リトライしても再結合対象にしても意味がない)」と
# 判断できる既知のエラーメッセージ。動画の削除・非公開化・著作権クレーム等、
# YouTube側がその動画自体を理由に拒否している場合のみ該当する。
#
# [重要] ここに含まれない全てのエラー(「Sign in to confirm you're not a
# bot」のようなボット判定、レート制限、ネットワーク不調等)は、動画自体では
# なく実行環境側に起因する一時的な問題である可能性が高いとみなし、恒久
# スキップの対象にしない(=skipped_video_idsに入れない)。誤って恒久
# スキップに分類すると、実際には取得可能な動画が二度と結合対象にならなく
# なってしまうため、判定は「恒久的とわかっているものだけを拾う」ホワイト
# リスト方式にしている(実際にこの取り違えで問題のない動画5本が誤って
# skipped_video_idsに入る事故が過去に起きている)。
_PERMANENTLY_UNAVAILABLE_MARKERS = (
    "video unavailable",
    "video is unavailable",
    "video has been removed",
    "private video",
    "this video is private",
    "account associated with this video has been terminated",
    "copyright",
    "no longer available",
)


def is_permanently_unavailable(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _PERMANENTLY_UNAVAILABLE_MARKERS)


def pillarbox_scale(clip_width: int, clip_height: int, canvas_width: int, canvas_height: int) -> float:
    """縦長クリップを横型キャンバスに収めるための拡大率を返す。

    まず高さをキャンバスの高さに合わせる。それでも幅がキャンバス幅を
    超える場合(極端に横長のクリップが来た場合の安全策)は、幅基準にする。"""
    scale = canvas_height / clip_height
    if clip_width * scale > canvas_width:
        scale = canvas_width / clip_width
    return scale

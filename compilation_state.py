"""
compilation_state.py

compile_shorts.py の結合状態(結合済み・恒久的に取得不可能な動画)を管理する。

moviepy/google-api-python-client 等の重い依存を持たないため、
requirements-dev.txt だけの軽量なテスト環境からもインポートしてテストできる
(used_words_store.py と同じ狙いでcompile_shorts.pyから切り出している)。
"""
import io
import json
import os
import zipfile

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


def find_artifact(artifacts: list, name: str) -> dict | None:
    """GitHub Actions APIが返すアーティファクト一覧から、名前が一致する
    ものを探す(見つからなければNone)。"""
    return next((a for a in artifacts if a.get("name") == name), None)


def extract_zip_member(zip_bytes: bytes, member_name: str) -> bytes:
    """GitHub Actionsアーティファクト(zip)のバイト列から、指定した
    ファイル1件の中身を取り出す。見つからない場合はKeyErrorを送出する
    (zipfile.ZipFile.readの標準動作)。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.read(member_name)


def pillarbox_scale(clip_width: int, clip_height: int, canvas_width: int, canvas_height: int) -> float:
    """縦長クリップを横型キャンバスに収めるための拡大率を返す。

    まず高さをキャンバスの高さに合わせる。それでも幅がキャンバス幅を
    超える場合(極端に横長のクリップが来た場合の安全策)は、幅基準にする。"""
    scale = canvas_height / clip_height
    if clip_width * scale > canvas_width:
        scale = canvas_width / clip_width
    return scale

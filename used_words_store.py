"""
used_words.json(使用済み単語履歴)の読み書きを共通化する。

fetch_and_score.py・upload_videos.py・compile_shorts.py の複数箇所で
同じ読み込み/保存ロジックが必要なため、ここに集約する。
"""
import json
import os

from config import USED_WORDS_PATH


def load_used_words() -> list:
    """使用済み単語履歴を古い→新しい順で読み込む。

    各要素は {"word": str, "patterns": list[str], "video_id": str | None}。
    (patterns は score_words.matched_patterns が返す綴りパターン名、
     video_id はYouTubeへのアップロード成功時に記録される動画ID)

    used_words.json 内の「使用済み」の記録は upload_videos.py が
    YouTubeへのアップロードに成功した時点で初めて行う。
    (TTS/動画生成/アップロードのいずれかで失敗した単語を
     ここで使用済み扱いにしてしまうと、二度と候補に上がらず
     動画が1本失われたままになるため)

    旧形式(単語の文字列だけのリスト、またはvideo_idを含まない辞書)の
    ファイルも読み込めるよう、欠けている項目は空リスト/Noneとして扱う。

    ファイルが空、または壊れたJSONの場合は、履歴なし(空リスト)として
    扱う(手動編集や書き込み中の異常終了で空ファイルになるケースがあるため。
    使用済み単語の判定が緩くなるだけで、パイプライン全体は止めない)。"""
    if not os.path.exists(USED_WORDS_PATH):
        return []
    with open(USED_WORDS_PATH, encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"警告: {USED_WORDS_PATH} の読み込みに失敗しました({e})。"
              f"使用済み単語なしとして続行します。")
        return []
    history = []
    for entry in raw:
        if isinstance(entry, str):
            history.append({"word": entry, "patterns": [], "video_id": None})
        else:
            history.append({
                "word": entry["word"],
                "patterns": entry.get("patterns", []),
                "video_id": entry.get("video_id"),
            })
    return history


def save_used_words(history: list) -> None:
    """使用済み単語履歴を古い→新しい順のまま保存する
    (直近パターン判定・結合動画のバッチ管理に使うため)。"""
    with open(USED_WORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

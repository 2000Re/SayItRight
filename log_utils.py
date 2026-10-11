"""
log_utils.py

create_videos.py / upload_videos.py の実行ログに時刻を付けるための
共通ヘルパー。GitHub Actionsのログ画面は相対時刻(経過時間)表示が中心で、
後から実行ログだけを見て特定の単語の処理がいつ行われたか追うのに
不便だったため追加した。日本時間(Asia/Tokyo)・24時間表記
(YYYY-MM-DD HH:MM:SS)で統一する。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")


def timestamp() -> str:
    """現在時刻(日本時間, YYYY-MM-DD HH:MM:SS)の文字列を返す。"""
    return datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str = "") -> None:
    """タイムスタンプ付きで1行出力する。

    GitHub Actionsのワークフローエラー注釈(`::error::`で始まる行)は、
    その文字列が行頭に無いと注釈として認識されないため、`::error::`を
    含むログはこの関数を使わず、呼び出し側で timestamp() を
    `::error::`より後ろに埋め込むこと。"""
    print(f"{timestamp()} {msg}")

"""
content_safety.py

自動生成パイプラインが差別的なスラーを単語候補として選んでしまうことが
無いよう、常時(常用語リストの取得成否に関わらず)適用する専用の
ブロックリスト。

[Design] 通常の卑語は常用語リスト(config.COMMON_WORDS_URL、"no-swears"版)
による絞り込みで除外されるが、このリストの取得(GitHubからのHTTP fetch)に
失敗した場合、fetch_and_score.pyはフィルタなしで続行する設計になっている
(候補が完全に枯渇して投稿が止まるより、多少フィルタが緩んでも投稿を
継続する方を優先する設計判断で、これ自体は変更しない)。

差別的スラーは一般的な卑語よりもはるかに深刻な問題(YouTubeのヘイト
スピーチポリシー違反によるチャンネル停止リスク等)を引き起こしうるため、
常用語リストの取得成否に依存しない、独立した安全策としてここに用意する。

網羅的な卑語辞書を目指すものではない(卑語全般の判断は常用語リスト側に
委ねる)。明確に差別的なスラーのみを対象にした短いリストとする。
"""

BLOCKED_WORDS = frozenset({
    # 人種・民族差別スラー
    "NIGGER",
    "NIGGERS",
    "NIGGA",
    "NIGGAS",
    "NIGGUH",
    "CHINK",
    "CHINKS",
    "GOOK",
    "GOOKS",
    "SPIC",
    "SPICS",
    "WETBACK",
    "WETBACKS",
    "KIKE",
    "KIKES",
    "PACKI",
    "PACKIS",
    "PACKY",
    # 同性愛者差別スラー
    "FAGGOT",
    "FAGGOTS",
    "FAG",
    "FAGS",
    "DYKE",
    "DYKES",
    # 障害者差別スラー
    "RETARD",
    "RETARDS",
})


def is_blocked(word: str) -> bool:
    """word(大文字・小文字は問わない)がブロックリストに含まれるか。"""
    return word.upper() in BLOCKED_WORDS

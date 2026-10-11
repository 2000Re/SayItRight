"""
content_safety.py

自動生成パイプラインが卑語・差別的スラー・下ネタ(排泄・嘔吐等)を
単語候補として選んでしまうことが無いよう、常時(常用語リストの取得
成否に関わらず)適用する専用のブロックリスト。

[Design] 通常はcmudictの候補を常用語リスト(config.COMMON_WORDS_URL、
"no-swears"版)と突き合わせて絞り込むことで卑語を除外しているが、この
リストの取得(GitHubからのHTTP fetch)に失敗した場合、fetch_and_score.py
はフィルタなしで続行する設計になっている(候補が完全に枯渇して投稿が
止まるより、多少フィルタが緩んでも投稿を継続する方を優先する設計判断で、
これ自体は変更しない)。

このフォールバックが発生した場合でも卑語・差別的スラーが確実に除外
されるよう、常用語リストの取得成否に依存しない独立した安全策として
ここに用意する。常用語リスト("no-swears"版)ほど網羅的なリストを
目指すものではない(このリストが機能していれば、そもそもここに載って
いる語の大半は表に出ない想定のため)。代表的な語を短くリストしてある。

差別的スラー(SLURS)は一般的な卑語(PROFANITY)よりもはるかに深刻な
問題(YouTubeのヘイトスピーチポリシー違反によるチャンネル停止リスク等)
を引き起こしうるため、区別してコメントしているが、除外の扱いは同じ。

下ネタ(TOILET_HUMOR)は卑語そのものではないため常用語リスト("no-swears"
版)では除外されず、実際に"peeing"が候補として選ばれコメント欄で
茶化される事態が発生したため追加した。発音教育チャンネルとして
ふさわしくない下ネタ的な語(排泄・嘔吐関連)を対象にしている。
"""

SLURS = frozenset({
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

PROFANITY = frozenset({
    "FUCK",
    "FUCKING",
    "FUCKER",
    "FUCKERS",
    "FUCKED",
    "MOTHERFUCKER",
    "MOTHERFUCKERS",
    "SHIT",
    "SHITTY",
    "BULLSHIT",
    "BITCH",
    "BITCHES",
    "ASSHOLE",
    "ASSHOLES",
    "BASTARD",
    "BASTARDS",
    "CUNT",
    "CUNTS",
    "WHORE",
    "WHORES",
    "SLUT",
    "SLUTS",
    "COCK",
    "COCKS",
    "DICKHEAD",
    "DICKHEADS",
    "PISS",
    "PISSED",
})

TOILET_HUMOR = frozenset({
    # 排泄関連
    "PEE",
    "PEES",
    "PEEING",
    "PEED",
    "POOP",
    "POOPS",
    "POOPING",
    "POOPED",
    "POOPY",
    "POO",
    "POOS",
    "CRAP",
    "CRAPS",
    "CRAPPING",
    "CRAPPED",
    "FART",
    "FARTS",
    "FARTING",
    "FARTED",
    "URINATE",
    "URINATES",
    "URINATING",
    "URINATED",
    "URINE",
    "DEFECATE",
    "DEFECATES",
    "DEFECATING",
    "DEFECATED",
    "FECES",
    "EXCREMENT",
    "DIARRHEA",
    # 嘔吐関連
    "VOMIT",
    "VOMITS",
    "VOMITING",
    "VOMITED",
    "PUKE",
    "PUKES",
    "PUKING",
    "PUKED",
    "BARF",
    "BARFS",
    "BARFING",
    "BARFED",
    # 鼻水等
    "SNOT",
    "BOOGER",
    "BOOGERS",
})

BLOCKED_WORDS = SLURS | PROFANITY | TOILET_HUMOR


def is_blocked(word: str) -> bool:
    """word(大文字・小文字は問わない)がブロックリストに含まれるか。"""
    return word.upper() in BLOCKED_WORDS

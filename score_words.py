"""
発音が難しい英単語を自動抽出するスコアリングツール

考え方:
  「綴りの文字数」と「実際の音素(発音)の数」のギャップが大きいほど、
  見た目と発音のズレが大きい=発音が難しい/覚えにくい単語とみなす。

  さらに以下を加点:
    - 黙字(silent letter)を含みやすいパターンにマッチする
    - 母音の綴りパターンが特殊(-ough, -eigh, -que 等)

  本番(GitHub Actions)では cmudict をネット経由で取得して全語彙(13万語超)を
  スコアリングする想定。ここではネットワークが使えない検証環境のため、
  sample_cmudict.dict の小サンプルで動作確認する。
"""

import random
import re
from dataclasses import dataclass, field
from typing import List

# 黙字などが出やすい"綴りが特殊"なパターン(名前, 正規表現)
# 名前は候補選定時の「直近と系統がかぶっていないか」判定にも使う。
TRICKY_PATTERNS = [
    ("kn-", r"^kn"),       # knight, knife
    ("wr-", r"^wr"),       # wrist, write
    ("gn-", r"^gn"),       # gnome
    ("ps-", r"^ps"),       # psychology
    ("pt-", r"^pt"),       # ptarmigan
    ("-mb", r"mb$"),       # comb, thumb
    ("bt", r"bt"),         # debt, subtle
    ("ough", r"ough"),     # though, through, tough, cough, bough, thorough
    ("augh", r"augh"),     # daughter, laugh
    ("eigh", r"eigh"),     # eight, weigh
    ("-que", r"que$"),     # queue, unique
    ("sc[iey]", r"sc[iey]"),  # scissors, science
    ("dg", r"dg"),         # judge (soft g pattern)
]

VOWELS = set("AEIOU")


@dataclass
class WordScore:
    word: str
    letters: int
    phonemes: int
    gap: int
    pattern_hits: int
    score: float
    patterns: List[str] = field(default_factory=list)


def count_phonemes(arpabet: str) -> int:
    return len(arpabet.split())


def matched_patterns(word: str) -> List[str]:
    """単語にマッチした綴りパターンの名前一覧を返す(選定の多様性判定用)。"""
    w = word.lower()
    return [name for name, pattern in TRICKY_PATTERNS if re.search(pattern, w)]


def score_word(word: str, arpabet: str) -> WordScore:
    letters = len(word)
    phonemes = count_phonemes(arpabet)
    gap = letters - phonemes
    patterns = matched_patterns(word)
    hits = len(patterns)
    # スコア = 文字数と音素数のギャップ + パターン一致数*2 (パターンは強いシグナルなので重み付け)
    score = gap + hits * 2
    return WordScore(word=word, letters=letters, phonemes=phonemes,
                      gap=gap, pattern_hits=hits, score=score, patterns=patterns)


def load_dict(path: str) -> dict:
    entries = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;;"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            word, arpabet = parts
            word = re.sub(r"\(\d+\)$", "", word)  # WORD(1) のような異形を除去
            entries[word] = arpabet
    return entries


def pick_diverse(pool: List[WordScore], n: int) -> List[WordScore]:
    """poolからn件選ぶ。同じバッチ(1回の実行でまとめて選ぶ単語群)内で
    綴りパターンが重複しないよう優先する。

    fetch_and_score.pyのdiverse_poolは「直近の投稿履歴」とのパターン重複を
    除外するが、同じバッチ内で選ばれる候補同士が偶然同じパターンを共有する
    ケースまでは防げない(例: THOUGH/THROUGH/BOROUGHが同時に選ばれ、
    3本とも"ough"パターンになってしまった実例がある)。

    十分な数の多様な候補が無い場合は、残り枠を多少パターンが被っても
    プールから埋める(選定自体を諦めさせないため)。"""
    shuffled = pool[:]
    random.shuffle(shuffled)
    picked = []
    used_patterns = set()
    leftover = []
    for candidate in shuffled:
        if len(picked) >= n:
            leftover.append(candidate)
            continue
        if set(candidate.patterns) & used_patterns:
            leftover.append(candidate)
            continue
        picked.append(candidate)
        used_patterns.update(candidate.patterns)
    if len(picked) < n:
        picked.extend(leftover[: n - len(picked)])
    return picked


def top_tricky_words(entries: dict, top_n: int = 20, min_letters: int = 4):
    scored = []
    for word, arpabet in entries.items():
        if len(word) < min_letters:
            continue
        if not word.isalpha():
            continue
        scored.append(score_word(word, arpabet))
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_n]


if __name__ == "__main__":
    entries = load_dict("sample_cmudict.dict")
    results = top_tricky_words(entries, top_n=15, min_letters=3)

    print(f"{'単語':<16}{'文字数':<8}{'音素数':<8}{'ギャップ':<10}{'パターン':<10}{'スコア':<6}")
    print("-" * 60)
    for r in results:
        print(f"{r.word.title():<16}{r.letters:<8}{r.phonemes:<8}{r.gap:<10}{r.pattern_hits:<10}{r.score:<6}")

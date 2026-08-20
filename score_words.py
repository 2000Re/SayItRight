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

import re
from dataclasses import dataclass

# 黙字などが出やすい"綴りが特殊"なパターン(正規表現)
TRICKY_PATTERNS = [
    r"^kn",       # knight, knife
    r"^wr",       # wrist, write
    r"^gn",       # gnome
    r"^ps",       # psychology
    r"^pt",       # ptarmigan
    r"mb$",       # comb, thumb
    r"bt",        # debt, subtle
    r"ough",      # though, through, tough, cough, bough, thorough
    r"augh",      # daughter, laugh
    r"eigh",      # eight, weigh
    r"que$",      # queue, unique
    r"sc[iey]",   # scissors, science
    r"dg",        # judge (soft g pattern)
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


def count_phonemes(arpabet: str) -> int:
    return len(arpabet.split())


def pattern_score(word: str) -> int:
    w = word.lower()
    return sum(1 for p in TRICKY_PATTERNS if re.search(p, w))


def score_word(word: str, arpabet: str) -> WordScore:
    letters = len(word)
    phonemes = count_phonemes(arpabet)
    gap = letters - phonemes
    hits = pattern_score(word)
    # スコア = 文字数と音素数のギャップ + パターン一致数*2 (パターンは強いシグナルなので重み付け)
    score = gap + hits * 2
    return WordScore(word=word, letters=letters, phonemes=phonemes,
                      gap=gap, pattern_hits=hits, score=score)


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

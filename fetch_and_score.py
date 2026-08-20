"""
GitHub Actions(ネット接続あり)で実行する本番スクリプト。

1. pip でインストールした cmudict パッケージ(13万語超)を読み込む
   ※ requirements.txt に `cmudict` を追加しておくこと
2. first20hours/google-10000-english の頻出1万語リストを取得し、
   「実際によく使われる単語」だけに候補を絞り込む
   (これをしないと、CMU辞書は音声認識用データセットのため
    人名・地名などの固有名詞が大量にヒットしてしまう)
3. score_words.py のロジックでスコアリング
4. すでに使った単語(used_words.json)を除外
5. 上位候補から N 語を抽出し、次の動画生成ステップに渡す candidates.json を出力

sheriff-shorts-bot の movie.py 側から、この candidates.json を
「ネタ元」として読み込む想定。
"""

import json
import os
import random

import cmudict  # pip install cmudict (requirements.txt に追加)
import requests

from score_words import top_tricky_words, score_word

USED_WORDS_PATH = "used_words.json"
OUTPUT_PATH = "candidates.json"
COMMON_WORDS_URL = (
    "https://raw.githubusercontent.com/first20hours/google-10000-english/"
    "master/google-10000-english-usa-no-swears-medium.txt"
)
POOL_SIZE = 15       # スコア上位からこの件数をプール
PICK_N = 1           # 今回の動画用に実際に選ぶ件数
MIN_LETTERS = 4      # これより短い単語は除外


def load_used_words() -> set:
    if os.path.exists(USED_WORDS_PATH):
        with open(USED_WORDS_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_used_words(used: set) -> None:
    with open(USED_WORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(used), f, ensure_ascii=False, indent=2)


def load_common_words() -> set:
    """頻出1万語リストを取得し、大文字化して集合で返す。
    取得に失敗した場合は空集合を返し、呼び出し側でフォールバックする。"""
    try:
        resp = requests.get(COMMON_WORDS_URL, timeout=15)
        resp.raise_for_status()
        words = {line.strip().upper() for line in resp.text.splitlines() if line.strip()}
        print(f"常用語リストを取得しました: {len(words)}語")
        return words
    except requests.RequestException as e:
        print(f"警告: 常用語リストの取得に失敗しました ({e})。フィルタなしで続行します。")
        return set()


def main():
    raw_entries = cmudict.dict()  # {'word': [['P1', 'P2', ...], ...]}
    entries = {w.upper(): " ".join(prons[0]) for w, prons in raw_entries.items()}

    common_words = load_common_words()
    used = load_used_words()

    scored = []
    for word, arpabet in entries.items():
        if word in used:
            continue
        if not word.isalpha() or len(word) < MIN_LETTERS:
            continue
        # 常用語リストが取得できた場合のみ、そのリストで絞り込む
        # (固有名詞・専門用語・レアな姓名などをここで除外する)
        if common_words and word not in common_words:
            continue
        scored.append(score_word(word, arpabet))
    scored.sort(key=lambda s: s.score, reverse=True)

    if not scored:
        print("候補が見つかりませんでした。used_words.json をリセットするか、"
              "フィルタ条件を見直してください。")
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    pool = scored[:POOL_SIZE]
    picked = random.sample(pool, min(PICK_N, len(pool)))

    candidates = [
        {
            "word": p.word.title(),
            "arpabet": entries[p.word],
            "score": p.score,
        }
        for p in picked
    ]

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    used.update(p.word for p in picked)
    save_used_words(used)

    print(f"{len(candidates)}件の候補を {OUTPUT_PATH} に出力しました。")
    for c in candidates:
        print(f"  - {c['word']} (score={c['score']})")


if __name__ == "__main__":
    main()

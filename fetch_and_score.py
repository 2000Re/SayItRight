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
import random

import cmudict  # pip install cmudict (requirements.txt に追加)
import requests

from score_words import score_word
from used_words_store import load_used_words
from config import (
    CANDIDATES_PATH as OUTPUT_PATH,
    COMMON_WORDS_URL,
    POOL_SIZE,
    PICK_N,
    MIN_LETTERS,
    RECENT_PATTERN_WINDOW,
    DICTIONARY_API_URL,
    DICTIONARY_API_TIMEOUT_SECONDS,
)


def recent_patterns(history: list, window: int = RECENT_PATTERN_WINDOW) -> set:
    """直近 window 件の投稿で使われた綴りパターン名の集合を返す。"""
    patterns = set()
    for entry in history[-window:]:
        patterns.update(entry["patterns"])
    return patterns


def is_known_word(word: str) -> bool:
    """辞書API(dictionaryapi.dev)にエントリがあるかどうかを確認する。

    "DEUTSCHE"のような、cmudict/頻出単語リストにたまたま含まれているだけの
    英単語ではない語(外来語・固有名詞等)を候補から除外するために使う。
    API側の一時的な障害やタイムアウトで確認できない場合は、
    誤って候補を減らしすぎないよう「存在する」扱い(True)にフォールバックする。
    プール(POOL_SIZE件)内でのみ呼び出す想定で、cmudict全体には使わない
    (全語彙に対して呼ぶとAPI呼び出し数が多くなりすぎるため)。"""
    url = DICTIONARY_API_URL.format(word=word.lower())
    try:
        resp = requests.get(url, timeout=DICTIONARY_API_TIMEOUT_SECONDS)
    except requests.RequestException:
        return True
    if resp.status_code == 404:
        return False
    return True


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
    history = load_used_words()
    used_words_set = {h["word"] for h in history}

    scored = []
    for word, arpabet in entries.items():
        if word in used_words_set:
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
        message = ("候補が見つかりませんでした。used_words.json をリセットするか、"
                    "フィルタ条件を見直してください。")
        print(message)
        # "::warning::" はGitHub Actionsのワークフローコマンド。実行結果画面に
        # 黄色い警告として表示されるため、ログを開かなくても候補切れに気付ける。
        # (ローカル実行時はただの標準出力になるだけで害はない)
        print(f"::warning::候補単語が見つかりませんでした。{message}")
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    pool = scored[:POOL_SIZE]

    # 辞書API(dictionaryapi.dev)に載っていない語("DEUTSCHE"のような
    # 英単語ではない外来語・固有名詞等)を候補から除外する。
    # プール内の呼び出しに留めることで、cmudict全体をスキャンする
    # ことによる過剰なAPI呼び出しを避けている。
    known_pool = [p for p in pool if is_known_word(p.word)]
    if not known_pool:
        print("プール内に辞書APIで確認できる単語がありませんでした。"
              "フィルタなしで続行します。")
    else:
        pool = known_pool

    # 直近の投稿と綴りパターン(黙字系, -ough系など)が被らない候補を優先する。
    # 内容のマンネリ化(似た系統の単語が連続する)を避けるため。
    avoid = recent_patterns(history)
    diverse_pool = [p for p in pool if not (set(p.patterns) & avoid)] if avoid else pool
    if avoid and not diverse_pool:
        print(f"直近{RECENT_PATTERN_WINDOW}件のパターン{sorted(avoid)}と被らない候補が"
              f"プール内になかったため、プール全体から選びます。")
        selection_pool = pool
    else:
        selection_pool = diverse_pool

    picked = random.sample(selection_pool, min(PICK_N, len(selection_pool)))

    candidates = [
        {
            "word": p.word.title(),
            "arpabet": entries[p.word],
            "score": p.score,
            "patterns": p.patterns,
        }
        for p in picked
    ]

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"{len(candidates)}件の候補を {OUTPUT_PATH} に出力しました。"
          f"(used_words.jsonへの登録はアップロード成功後に upload_videos.py が行います)")
    for c in candidates:
        print(f"  - {c['word']} (score={c['score']})")


if __name__ == "__main__":
    main()

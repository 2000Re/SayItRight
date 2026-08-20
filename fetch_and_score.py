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
RECENT_PATTERN_WINDOW = 5  # 直近何件の投稿と綴りパターンの重複を避けるか


def load_used_words() -> list:
    """既に使用済み(=アップロード成功済み)の単語履歴を、古い→新しい順で読み込む。

    各要素は {"word": str, "patterns": list[str]} の形式。
    (patterns は score_words.matched_patterns が返す綴りパターン名で、
     直近と系統が被った単語を避けるために使う)

    used_words.json 内の「使用済み」の記録は upload_videos.py が
    YouTubeへのアップロードに成功した時点で初めて行う。
    (TTS/動画生成/アップロードのいずれかで失敗した単語を
     ここで使用済み扱いにしてしまうと、二度と候補に上がらず
     動画が1本失われたままになるため)

    旧形式(単語の文字列だけのリスト)のファイルも読み込めるよう、
    文字列の要素は patterns 不明(空リスト)として扱う。"""
    if not os.path.exists(USED_WORDS_PATH):
        return []
    with open(USED_WORDS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    history = []
    for entry in raw:
        if isinstance(entry, str):
            history.append({"word": entry, "patterns": []})
        else:
            history.append({"word": entry["word"], "patterns": entry.get("patterns", [])})
    return history


def recent_patterns(history: list, window: int = RECENT_PATTERN_WINDOW) -> set:
    """直近 window 件の投稿で使われた綴りパターン名の集合を返す。"""
    patterns = set()
    for entry in history[-window:]:
        patterns.update(entry["patterns"])
    return patterns


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
        print("候補が見つかりませんでした。used_words.json をリセットするか、"
              "フィルタ条件を見直してください。")
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    pool = scored[:POOL_SIZE]

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

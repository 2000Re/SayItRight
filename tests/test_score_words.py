import random

from score_words import score_word, matched_patterns, count_phonemes, pick_diverse


def test_matched_patterns_detects_silent_letter_patterns():
    assert "kn-" in matched_patterns("knight")
    assert "ough" in matched_patterns("though")


def test_matched_patterns_igh_excludes_eigh_overlap():
    # "igh"は本番で実際に起きた回帰(プールがeigh/kn-/wr-/ough/augh系の
    # 少数パターンに偏り、直近ウィンドウで使い切られて候補が1件まで
    # 枯渇した)を受けて追加したパターン。既存の"eigh"と二重にマッチして
    # eigh系の単語のスコアをさらに底上げしてしまわないよう、
    # eの直後のighは除外する。
    assert "igh" in matched_patterns("knight")
    assert "igh" in matched_patterns("light")
    assert "igh" not in matched_patterns("weight")
    assert "igh" not in matched_patterns("freight")


def test_matched_patterns_returns_empty_for_plain_word():
    assert matched_patterns("cat") == []


def test_count_phonemes():
    assert count_phonemes("K AE1 T") == 3


def test_score_word_reflects_letter_phoneme_gap_and_patterns():
    # THOUGH: 6文字, 3音素(TH AH0 OW1) -> gap=3, "ough"パターン一致で+2
    result = score_word("THOUGH", "TH AH0 OW1")
    assert result.letters == 6
    assert result.phonemes == 3
    assert result.gap == 3
    assert result.patterns == ["ough"]
    assert result.score == 3 + 2


def test_score_word_with_no_pattern_match():
    result = score_word("CAT", "K AE1 T")
    assert result.patterns == []
    assert result.pattern_hits == 0
    assert result.score == result.gap


def test_pick_diverse_avoids_same_pattern_within_batch_when_possible():
    # 本番で実際に起きた回帰: THOUGH/THROUGH/BOROUGHが同時に選ばれ、
    # 3本とも"ough"パターンになってしまった。プールに他パターンの候補が
    # あるなら、同じバッチ内でパターンが重複しないよう優先されるべき。
    pool = [
        score_word("ALTHOUGH", "AO2 L DH OW1"),
        score_word("THROUGH", "TH R UW1"),
        score_word("BOROUGH", "B ER1 OW2"),
        score_word("KNIGHT", "N AY1 T"),
        score_word("WRIST", "R IH1 S T"),
        score_word("PSYCHOLOGY", "S AY0 K AA1 L AH0 JH IY0"),
    ]
    random.seed(0)
    for _ in range(20):
        picked = pick_diverse(pool, 3)
        assert len(picked) == 3
        seen_patterns = set()
        for p in picked:
            # プール内には"ough"以外のパターンを持つ候補が3件以上あるため、
            # 常にバッチ内で同じパターンが重複しないはず
            assert not (set(p.patterns) & seen_patterns), (
                f"バッチ内でパターンが重複した: {[c.word for c in picked]}"
            )
            seen_patterns.update(p.patterns)


def test_pick_diverse_falls_back_to_pattern_overlap_when_pool_too_small():
    # 多様な候補が足りない場合でも、指定件数は必ず埋める
    pool = [
        score_word("ALTHOUGH", "AO2 L DH OW1"),
        score_word("THROUGH", "TH R UW1"),
        score_word("BOROUGH", "B ER1 OW2"),
    ]
    picked = pick_diverse(pool, 3)
    assert len(picked) == 3
    assert {p.word for p in picked} == {"ALTHOUGH", "THROUGH", "BOROUGH"}


def test_pick_diverse_respects_requested_count():
    pool = [score_word("CAT", "K AE1 T"), score_word("DOG", "D AO1 G")]
    assert len(pick_diverse(pool, 1)) == 1
    assert len(pick_diverse(pool, 2)) == 2

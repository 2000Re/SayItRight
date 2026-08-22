from score_words import score_word, matched_patterns, count_phonemes


def test_matched_patterns_detects_silent_letter_patterns():
    assert "kn-" in matched_patterns("knight")
    assert "ough" in matched_patterns("though")


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

from content_safety import is_blocked


def test_is_blocked_detects_known_slur():
    assert is_blocked("NIGGER")
    assert is_blocked("nigger")
    assert is_blocked("Nigga")


def test_is_blocked_is_case_insensitive():
    assert is_blocked("Faggot")
    assert is_blocked("FAGGOT")
    assert is_blocked("faggot")


def test_is_blocked_returns_false_for_ordinary_words():
    assert not is_blocked("KNIGHT")
    assert not is_blocked("THOUGH")
    assert not is_blocked("PRONOUNCE")

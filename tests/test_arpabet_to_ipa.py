from arpabet_to_ipa import arpabet_to_ipa


def test_basic_conversion():
    assert arpabet_to_ipa("K AE1 T") == "kˈæt"


def test_primary_and_no_secondary_stress():
    # COMPUTER: K AH0 M P Y UW1 T ER0 (第一強勢1つ、第二強勢なし)
    ipa = arpabet_to_ipa("K AH0 M P Y UW1 T ER0")
    assert ipa.count("ˈ") == 1
    assert "ˌ" not in ipa


def test_empty_input_returns_empty_string():
    assert arpabet_to_ipa("") == ""


def test_unknown_phone_is_skipped():
    assert arpabet_to_ipa("XX K AE1 T") == arpabet_to_ipa("K AE1 T")

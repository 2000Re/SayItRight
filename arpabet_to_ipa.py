"""
ARPAbet(CMU Pronouncing Dictionaryの表記) → IPA 変換

ARPAbetは末尾に強勢(stress)を表す数字がつく:
  0 = 強勢なし, 1 = 第一強勢, 2 = 第二強勢
  例: "K AH0 M P Y UW1 T ER0" (computer)

IPAでは強勢記号は音節の前に置く:
  第一強勢 → ˈ (U+02C8)
  第二強勢 → ˌ (U+02CC)
  無強勢   → 記号なし

Google Cloud TTSのSSML <phoneme> タグは alphabet="ipa" を指定して
IPA文字列をそのまま渡す形式に対応している。
"""

import re

# 子音・母音のARPAbet(数字を除いたベース記号) → IPA 対応表
ARPABET_TO_IPA = {
    # 母音
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ",
    "AY": "aɪ", "EH": "ɛ", "ER": "ɝ", "EY": "eɪ", "IH": "ɪ",
    "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    # 子音
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f",
    "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l",
    "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "r",
    "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v",
    "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}

PRIMARY_STRESS = "\u02C8"    # ˈ
SECONDARY_STRESS = "\u02CC"  # ˌ


def arpabet_to_ipa(arpabet: str) -> str:
    """'K AH0 M P Y UW1 T ER0' のようなARPAbet文字列をIPA文字列に変換する。

    音節境界の厳密な判定はせず、強勢記号がついた音素の直前に
    ストレスマークを挿入する簡易実装(TTS用途には十分な精度)。
    """
    phones = arpabet.split()
    ipa_parts = []
    for phone in phones:
        m = re.match(r"^([A-Z]+)([0-2])?$", phone)
        if not m:
            continue
        base, stress = m.group(1), m.group(2)
        ipa = ARPABET_TO_IPA.get(base, "")
        if not ipa:
            continue
        prefix = ""
        if stress == "1":
            prefix = PRIMARY_STRESS
        elif stress == "2":
            prefix = SECONDARY_STRESS
        ipa_parts.append(prefix + ipa)
    return "".join(ipa_parts)


if __name__ == "__main__":
    tests = {
        "WORCESTERSHIRE": "W UH1 S T ER0 SH ER0",
        "THOROUGH": "TH ER1 OW0",
        "BOUTIQUE": "B UW0 T IY1 K",
        "HEIGHT": "HH AY1 T",
    }
    for word, arpabet in tests.items():
        print(f"{word:<16}{arpabet:<28}{arpabet_to_ipa(arpabet)}")

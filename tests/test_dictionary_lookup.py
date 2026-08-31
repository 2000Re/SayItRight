from dictionary_lookup import strip_html, parse_definition_response, has_english_entry


def test_strip_html_removes_tags_and_decodes_entities():
    assert strip_html("A <i>female</i> offspring &amp; heir") == "A female offspring & heir"


def test_strip_html_handles_plain_text():
    assert strip_html("no tags here") == "no tags here"


def test_parse_definition_response_extracts_first_english_definition():
    # en.wiktionary.org の /page/definition/{word} が返す実際の形式を模した
    # サンプル(HTML付きの定義文・例文を含む)
    data = {
        "en": [
            {
                "partOfSpeech": "Noun",
                "language": "English",
                "definitions": [
                    {
                        "definition": "A <a href=\"/wiki/female\">female</a> offspring.",
                        "parsedExamples": [{"example": "She is my <b>daughter</b>."}],
                    },
                    {"definition": "A second, unused definition."},
                ],
            },
            {"partOfSpeech": "Verb", "definitions": [{"definition": "unused"}]},
        ]
    }
    result = parse_definition_response(data)
    assert result == {
        "part_of_speech": "noun",
        "definition": "A female offspring.",
        "example": "She is my daughter.",
    }


def test_parse_definition_response_returns_none_when_no_english_entry():
    # 見出し語がWiktionaryに他言語では存在するが、英語としては存在しない場合
    assert parse_definition_response({"fr": [{"partOfSpeech": "Nom", "definitions": []}]}) is None


def test_parse_definition_response_returns_none_when_definitions_empty():
    assert parse_definition_response({"en": [{"partOfSpeech": "Noun", "definitions": []}]}) is None


def test_parse_definition_response_skips_entries_with_blank_definition_text():
    data = {"en": [{"partOfSpeech": "Noun", "definitions": [{"definition": ""}, {"definition": "Real one."}]}]}
    result = parse_definition_response(data)
    assert result["definition"] == "Real one."


def test_parse_definition_response_handles_missing_parsed_examples():
    data = {"en": [{"partOfSpeech": "Noun", "definitions": [{"definition": "No example here."}]}]}
    result = parse_definition_response(data)
    assert result["example"] is None


def test_has_english_entry_true_when_present():
    assert has_english_entry({"en": [{"partOfSpeech": "Noun", "definitions": []}]})


def test_has_english_entry_false_when_absent_or_empty():
    assert not has_english_entry({"fr": [{"partOfSpeech": "Nom", "definitions": []}]})
    assert not has_english_entry({"en": []})
    assert not has_english_entry({})

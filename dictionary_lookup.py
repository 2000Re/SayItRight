"""
dictionary_lookup.py

Wiktionary(en.wiktionary.org)のREST API `/page/definition/{word}` の
レスポンスから、単語の意味・品詞・例文を取り出す純粋なパース処理を
切り出したモジュール。

requestsやgoogle-api-python-client等の重い依存を持たないため、
requirements-dev.txtだけの軽量なテスト環境からもインポートしてテスト
できる(used_words_store.py/compilation_state.pyと同じ狙い)。

[Design] 以前はdictionaryapi.dev(無料・認証不要の小規模なコミュニティ
運営API)を使っていたが、タイムアウトや5xxエラー(522=オリジンサーバー
との接続失敗、等)が頻発した。Wikimediaのインフラ上で動くWiktionaryの
REST APIは同じく無料・認証不要でありながら、はるかに可用性が高い。
レスポンス形式が異なる({"en": [...]}形式で、定義文にHTMLタグを含む)ため、
パース処理をここに分離している。
"""
import html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Wiktionaryのdefinition/example文字列に含まれるHTMLタグ(<a>, <i>等)を
    除去し、HTMLエンティティ(&amp;等)をデコードする。"""
    return html.unescape(_HTML_TAG_RE.sub("", text)).strip()


def parse_definition_response(data: dict) -> dict | None:
    """Wiktionary REST APIのレスポンスJSONから、最初に見つかった英語の
    定義を取り出す。

    レスポンス例:
      {"en": [{"partOfSpeech": "Noun", "definitions": [
          {"definition": "A female offspring.", "parsedExamples": [{"example": "..."}]}
      ]}]}

    英語エントリ("en")が無い、または定義本文が空の場合はNoneを返す
    (見出し語がWiktionaryに他言語のみ存在し、英語としては存在しない場合等)。"""
    for entry in data.get("en", []):
        for definition in entry.get("definitions", []):
            text = definition.get("definition")
            if not text:
                continue
            examples = definition.get("parsedExamples") or []
            example = examples[0].get("example") if examples else None
            return {
                "part_of_speech": entry.get("partOfSpeech", "").lower(),
                "definition": strip_html(text),
                "example": strip_html(example) if example else None,
            }
    return None


def has_english_entry(data: dict) -> bool:
    """候補の絞り込み(fetch_and_score.is_known_word)用。
    英語のエントリが1件でもあるかどうかを返す。"""
    return bool(data.get("en"))

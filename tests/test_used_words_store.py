import json

import used_words_store


def test_load_used_words_missing_file_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    assert used_words_store.load_used_words() == []


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    history = [{"word": "CAT", "patterns": ["x"], "video_id": "v1"}]
    used_words_store.save_used_words(history)
    assert used_words_store.load_used_words() == history


def test_load_used_words_handles_legacy_string_entries(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    path.write_text(json.dumps(["CAT", "DOG"]))
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    assert used_words_store.load_used_words() == [
        {"word": "CAT", "patterns": [], "video_id": None},
        {"word": "DOG", "patterns": [], "video_id": None},
    ]


def test_load_used_words_handles_legacy_dict_without_video_id(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    path.write_text(json.dumps([{"word": "CAT", "patterns": ["kn-"]}]))
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    assert used_words_store.load_used_words() == [
        {"word": "CAT", "patterns": ["kn-"], "video_id": None}
    ]


def test_load_used_words_handles_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    path.write_text("")
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    assert used_words_store.load_used_words() == []


def test_load_used_words_handles_broken_json(tmp_path, monkeypatch):
    path = tmp_path / "used_words.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(used_words_store, "USED_WORDS_PATH", str(path))
    assert used_words_store.load_used_words() == []

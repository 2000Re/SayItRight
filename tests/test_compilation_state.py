import io
import json
import zipfile

import pytest

import compilation_state


def test_load_compilation_state_missing_file_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "compilation_state.json"
    monkeypatch.setattr(compilation_state, "COMPILATION_STATE_PATH", str(path))
    assert compilation_state.load_compilation_state() == {
        "compiled_video_ids": [],
        "skipped_video_ids": [],
    }


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "compilation_state.json"
    monkeypatch.setattr(compilation_state, "COMPILATION_STATE_PATH", str(path))
    state = {"compiled_video_ids": ["a", "b"], "skipped_video_ids": ["c"]}
    compilation_state.save_compilation_state(state)
    assert compilation_state.load_compilation_state() == state


def test_load_compilation_state_handles_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "compilation_state.json"
    path.write_text("")
    monkeypatch.setattr(compilation_state, "COMPILATION_STATE_PATH", str(path))
    assert compilation_state.load_compilation_state() == {
        "compiled_video_ids": [],
        "skipped_video_ids": [],
    }


def test_load_compilation_state_handles_broken_json(tmp_path, monkeypatch):
    path = tmp_path / "compilation_state.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(compilation_state, "COMPILATION_STATE_PATH", str(path))
    assert compilation_state.load_compilation_state() == {
        "compiled_video_ids": [],
        "skipped_video_ids": [],
    }


def test_load_compilation_state_ignores_legacy_compiled_count(tmp_path, monkeypatch):
    path = tmp_path / "compilation_state.json"
    path.write_text(json.dumps({"compiled_count": 10}))
    monkeypatch.setattr(compilation_state, "COMPILATION_STATE_PATH", str(path))
    assert compilation_state.load_compilation_state() == {
        "compiled_video_ids": [],
        "skipped_video_ids": [],
    }


def test_select_pending_excludes_compiled_and_skipped():
    compilable = [
        {"word": "A", "video_id": "v1"},
        {"word": "B", "video_id": "v2"},
        {"word": "C", "video_id": "v3"},
    ]
    state = {"compiled_video_ids": ["v1"], "skipped_video_ids": ["v3"]}
    pending = compilation_state.select_pending(compilable, state)
    assert [p["video_id"] for p in pending] == ["v2"]


def test_select_pending_preserves_order_with_empty_state():
    compilable = [{"word": "A", "video_id": "v1"}, {"word": "B", "video_id": "v2"}]
    state = {"compiled_video_ids": [], "skipped_video_ids": []}
    assert compilation_state.select_pending(compilable, state) == compilable


def test_pillarbox_scale_fits_by_height_when_width_stays_within_canvas():
    # 9:16の縦動画(1080x1920)を1920x1080キャンバスに収める -> 高さ基準
    scale = compilation_state.pillarbox_scale(1080, 1920, 1920, 1080)
    assert scale == 1080 / 1920
    assert 1080 * scale <= 1920


def test_pillarbox_scale_falls_back_to_width_when_height_based_scale_overflows():
    # 極端に横長のクリップ(2000x100)を1920x1080キャンバスに収める場合、
    # 高さ基準だと幅がキャンバスを超えるため、幅基準にフォールバックする
    scale = compilation_state.pillarbox_scale(2000, 100, 1920, 1080)
    assert scale == 1920 / 2000
    assert 2000 * scale <= 1920


def test_find_artifact_matches_by_name():
    artifacts = [
        {"name": "candidates", "id": 1},
        {"name": "video-output", "id": 2},
        {"name": "audio-output", "id": 3},
    ]
    assert compilation_state.find_artifact(artifacts, "video-output") == {"name": "video-output", "id": 2}


def test_find_artifact_returns_none_when_missing():
    artifacts = [{"name": "candidates", "id": 1}]
    assert compilation_state.find_artifact(artifacts, "video-output") is None


def test_find_artifact_handles_empty_list():
    assert compilation_state.find_artifact([], "video-output") is None


def test_extract_zip_member_reads_matching_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("although.mp4", b"fake video bytes")
        zf.writestr("through.mp4", b"other video bytes")
    zip_bytes = buf.getvalue()

    assert compilation_state.extract_zip_member(zip_bytes, "although.mp4") == b"fake video bytes"
    assert compilation_state.extract_zip_member(zip_bytes, "through.mp4") == b"other video bytes"


def test_extract_zip_member_raises_key_error_when_missing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("although.mp4", b"fake video bytes")
    zip_bytes = buf.getvalue()

    with pytest.raises(KeyError):
        compilation_state.extract_zip_member(zip_bytes, "missing.mp4")

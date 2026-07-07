import io
import os

import pytest
from asrkit import inputs


def test_plain_files_passthrough_even_if_missing(tmp_path):
    a = tmp_path / "a.wav"
    a.write_bytes(b"x")
    paths, cleanups = inputs.resolve([str(a), str(tmp_path / "missing.wav")])
    assert paths == sorted([str(a), str(tmp_path / "missing.wav")])
    assert cleanups == []


def test_glob_expands(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    paths, _ = inputs.resolve([str(tmp_path / "*.wav")])
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["a.wav", "b.wav"]


def test_glob_no_match_fails_loud(tmp_path):
    with pytest.raises(inputs.InputError):
        inputs.resolve([str(tmp_path / "nope*.wav")])


def test_directory_recurses_with_whitelist(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "note.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.mp3").write_bytes(b"x")
    paths, _ = inputs.resolve([str(tmp_path)])
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["a.wav", "b.mp3"]


def test_directory_no_audio_fails_loud(tmp_path):
    (tmp_path / "note.txt").write_bytes(b"x")
    with pytest.raises(inputs.InputError):
        inputs.resolve([str(tmp_path)])


def test_empty_result_fails_loud():
    with pytest.raises(inputs.InputError):
        inputs.resolve([])


def test_stdin_dash_writes_tempfile(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"RIFFDATA")))
    paths, cleanups = inputs.resolve(["-"], stdin_format="wav")
    assert len(paths) == 1 and paths[0].endswith(".wav")
    assert os.path.isfile(paths[0])
    with open(paths[0], "rb") as f:
        assert f.read() == b"RIFFDATA"
    for c in cleanups:
        c()
    assert not os.path.exists(paths[0])   # 清理回调删除临时文件


def test_stdin_format_override(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    paths, cleanups = inputs.resolve(["-"], stdin_format="mp3")
    try:
        assert paths[0].endswith(".mp3")
    finally:
        for c in cleanups:
            c()


def test_multiple_stdin_rejected(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    with pytest.raises(inputs.InputError):
        inputs.resolve(["-", "-"])

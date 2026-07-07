"""Tests for shell completion feature (list --ids + completion subcommand)."""
from asrkit import cli


def _run(args, capsys):
    """Helper: run CLI and capture stdout."""
    rc = cli.main(args)
    return rc, capsys.readouterr().out


def test_list_ids_bare(capsys):
    """list --ids prints bare model ids (no emoji, no size/name columns)."""
    _, out = _run(["list", "--ids"], capsys)
    lines = [x for x in out.splitlines() if x.strip()]
    assert "local/sensevoice" in lines and "openai/whisper-1" in lines
    assert all("☁️" not in x and "💻" not in x for x in lines)   # no emoji
    assert all(" " not in x.strip() for x in lines)               # bare ids, no spaces/columns


def test_list_ids_respects_source(capsys):
    """list --ids respects --source filter."""
    _, out = _run(["list", "--ids", "--source", "cloud"], capsys)
    ids = {x.strip() for x in out.splitlines() if x.strip()}
    assert "openai/whisper-1" in ids and "local/sensevoice" not in ids

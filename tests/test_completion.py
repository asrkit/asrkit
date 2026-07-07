"""Tests for shell completion feature (list --ids + completion subcommand)."""
import shutil
import subprocess

import pytest

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


def test_completion_tokens(capsys):
    """completion subcommand produces shell-specific tokens."""
    for shell, tok in [("bash", "list --ids"), ("zsh", "compdef"), ("fish", "__fish_use_subcommand")]:
        _, out = _run(["completion", shell], capsys)
        assert out.strip() and tok in out


def test_completion_unknown_shell(capsys):
    """completion subcommand rejects unknown shells."""
    with pytest.raises(SystemExit):          # argparse choices → SystemExit(2)
        cli.main(["completion", "tcsh"])


def test_script_for():
    """completion.script_for() returns scripts and rejects unknown shells."""
    from asrkit import completion
    assert completion.script_for("bash")
    with pytest.raises(ValueError):
        completion.script_for("tcsh")


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_syntax(shell, capsys, tmp_path):
    """completion scripts pass shell -n syntax check."""
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    _, out = _run(["completion", shell], capsys)
    p = tmp_path / f"c.{shell}"
    p.write_text(out)
    r = subprocess.run([shell, "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

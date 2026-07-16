"""CLI 模块拆分的入口与延迟导入回归测试。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from asrkit import api, cli
from asrkit.cli_commands import config, diagnostics, engines, models, stream, transcribe
from asrkit.types import PartialResult, TranscribeResult

ROOT = Path(__file__).resolve().parents[1]


def _source_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


@pytest.mark.parametrize(
    ("args", "module"),
    [
        (["list", "--ids"], models),
        (["completion", "bash"], models),
        (["search", "stub"], models),
        (["show", "stub/model"], models),
        (["pull", "stub/model"], models),
        (["rm", "stub/model"], models),
        (["add-model", "stub", "--arch", "senseVoice"], models),
        (["engine", "list"], engines),
        (["config", "list"], config),
        (["doctor"], diagnostics),
        (["serve"], diagnostics),
        (["run", "stub/model", "a.wav"], transcribe),
        (["transcribe", "a.wav", "-m", "stub/model"], transcribe),
        (["stream", "stub/model", "a.wav"], stream),
    ],
)
def test_main_dispatches_to_command_module(monkeypatch, args, module):
    marker = object()
    monkeypatch.setattr(module, "handle", lambda parsed: marker)

    assert cli.main(args) is marker


def test_cli_api_reexport_is_the_public_api_module():
    assert cli.api is api


def test_rebinding_cli_api_is_honored_by_split_handlers(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_transcribe(model, audio, *, config=None, opts=None):
        calls.append(("transcribe", model, audio))
        return TranscribeResult(text="from replacement api")

    def fake_stream(model, audio, *, config=None, opts=None):
        calls.append(("stream", model, audio))
        yield PartialResult(text="stream replacement", is_final=True)

    replacement = SimpleNamespace(
        list_models=lambda: [],
        transcribe=fake_transcribe,
        transcribe_stream=fake_stream,
    )
    monkeypatch.setattr(cli, "api", replacement)

    assert cli.main(["list", "--ids"]) == 0
    assert capsys.readouterr().out == ""

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"placeholder")
    assert cli.main(["transcribe", str(audio), "-m", "stub/model"]) == 0
    assert "from replacement api" in capsys.readouterr().out

    assert cli.main(["stream", "stub/model", str(audio)]) == 0
    assert "stream replacement" in capsys.readouterr().out
    assert [call[0] for call in calls] == ["transcribe", "stream"]


def test_root_and_nested_commands_keep_help_behavior(capsys):
    assert cli.main([]) == 0
    root_help = capsys.readouterr().out
    assert "One interface to run and compare" in root_help
    assert "{list,completion,search,show,pull,rm,engine,config,add-model,doctor,serve,run,transcribe,stream}" in root_help

    assert cli.main(["engine"]) == 0
    engine_help = capsys.readouterr().out
    assert "{list,install,default,rm}" in engine_help

    assert cli.main(["config"]) == 0
    config_help = capsys.readouterr().out
    assert "{set-key,get-key,set,list,path}" in config_help


def test_config_rejects_unsafe_models_root_without_writing(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("ASRKIT_CONFIG", str(config_file))

    assert cli.main(["config", "set", "models-root", str(Path.home())]) == 1
    assert "refusing unsafe models root" in capsys.readouterr().err
    assert not config_file.exists()


def test_argparse_help_and_usage_exit_codes(capsys):
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--help"])
    assert help_exit.value.code == 0
    assert "usage: asrkit" in capsys.readouterr().out

    with pytest.raises(SystemExit) as usage_exit:
        cli.main(["not-a-command"])
    assert usage_exit.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_serve_cli_passes_safe_resource_limits_and_overrides(monkeypatch, capsys):
    from asrkit import server

    calls = []
    monkeypatch.setattr(server, "serve", lambda **kwargs: calls.append(kwargs))

    assert cli.main(["serve"]) == 0
    assert calls[-1] == {
        "host": "127.0.0.1",
        "port": 11435,
        "max_upload_bytes": 200 * 1024 * 1024,
        "max_concurrency": 4,
        "request_timeout_s": 300.0,
    }

    assert cli.main([
        "serve", "--max-upload-mb", "12", "--max-concurrency", "3",
        "--request-timeout", "45",
    ]) == 0
    assert calls[-1]["max_upload_bytes"] == 12 * 1024 * 1024
    assert calls[-1]["max_concurrency"] == 3
    assert calls[-1]["request_timeout_s"] == 45.0
    capsys.readouterr()


@pytest.mark.parametrize(
    "args",
    [
        ["--max-upload-mb", "0"],
        ["--max-concurrency", "0"],
        ["--request-timeout", "0"],
    ],
)
def test_serve_cli_rejects_unsafe_resource_limits(monkeypatch, capsys, args):
    from asrkit import server

    monkeypatch.setattr(
        server, "serve", lambda **kwargs: pytest.fail("invalid limits must fail first"))

    assert cli.main(["serve", *args]) == 2
    assert "[error]" in capsys.readouterr().err


def test_python_module_entrypoint_reports_version():
    proc = subprocess.run(
        [sys.executable, "-m", "asrkit.cli", "--version"],
        cwd=ROOT,
        env=_source_env(),
        check=True,
        capture_output=True,
        text=True,
    )

    assert proc.stdout.strip() == "asrkit 0.5.4"
    assert proc.stderr == ""


def test_unknown_transcribe_model_returns_model_not_found(tmp_path, capsys):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"placeholder")

    assert cli.main(["transcribe", str(audio), "-m", "missing/model"]) == 3
    assert "unknown model" in capsys.readouterr().err.lower()

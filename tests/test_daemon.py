"""asrkit-cloud embedded 生命周期与安全配置契约。"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from asrkit.daemon import cli, lifecycle
from asrkit.daemon.security import SecurityError
from asrkit.daemon.settings import activate_environment, resolve_settings

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
TOKEN = "t" * 48


def _embedded_settings(tmp_path: Path, **overrides):
    values = {
        "embedded": True,
        "host": "127.0.0.1",
        "port": None,
        "parent_pid": os.getpid(),
        "data_dir": str(tmp_path / "data"),
        "token": TOKEN,
    }
    values.update(overrides)
    return resolve_settings(**values)


def test_embedded_settings_use_private_data_dir_and_random_port(tmp_path, monkeypatch):
    settings = _embedded_settings(tmp_path)

    assert settings.port == 0
    assert settings.auth_token == TOKEN
    assert settings.max_upload_bytes == 200 * 1024 * 1024
    assert settings.max_concurrency == 4
    assert Path(settings.temp_dir).is_dir()
    assert (Path(settings.data_dir) / "logs").is_dir()

    monkeypatch.setenv("ASRKIT_CONFIG", "/should/not/be/used.json")
    monkeypatch.setenv("TMPDIR", "/should/not/be/used-tmpdir")
    monkeypatch.setenv("TEMP", "/should/not/be/used-temp")
    monkeypatch.setenv("TMP", "/should/not/be/used-tmp")
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    activate_environment(settings)
    assert os.environ["ASRKIT_CONFIG"] == str(Path(settings.data_dir) / "config.json")
    assert os.environ["TMPDIR"] == settings.temp_dir
    assert os.environ["TEMP"] == settings.temp_dir
    assert os.environ["TMP"] == settings.temp_dir
    assert tempfile.tempdir == settings.temp_dir


def test_non_embedded_environment_does_not_change_tempfile_globals(
    tmp_path, monkeypatch,
):
    sentinel = str(tmp_path / "system-temp")
    monkeypatch.setenv("ASRKIT_CONFIG", str(tmp_path / "original-config.json"))
    monkeypatch.setenv("TMPDIR", sentinel)
    monkeypatch.setenv("TEMP", sentinel)
    monkeypatch.setenv("TMP", sentinel)
    monkeypatch.setattr(tempfile, "tempdir", sentinel)
    settings = resolve_settings(
        embedded=False,
        host="127.0.0.1",
        port=11435,
        parent_pid=None,
        data_dir=str(tmp_path / "data"),
        token=None,
    )

    activate_environment(settings)

    assert os.environ["TMPDIR"] == sentinel
    assert os.environ["TEMP"] == sentinel
    assert os.environ["TMP"] == sentinel
    assert tempfile.tempdir == sentinel


def test_prepare_data_dir_does_not_destroy_existing_write_probe(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(mode=0o700)
    probe = data_dir / ".write-probe"
    probe.write_bytes(b"keep this content")

    settings = _embedded_settings(tmp_path, data_dir=str(data_dir))

    assert settings.data_dir == str(data_dir)
    assert probe.read_bytes() == b"keep this content"
    assert not list(data_dir.glob(".asrkit-write-probe-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_prepare_data_dir_does_not_follow_existing_write_probe_symlink(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(mode=0o700)
    target = tmp_path / "outside.txt"
    target.write_bytes(b"outside content")
    probe = data_dir / ".write-probe"
    probe.symlink_to(target)

    _embedded_settings(tmp_path, data_dir=str(data_dir))

    assert probe.is_symlink()
    assert target.read_bytes() == b"outside content"
    assert not list(data_dir.glob(".asrkit-write-probe-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
@pytest.mark.parametrize("private_name", ["tmp", "logs"])
def test_prepare_data_dir_rejects_symlinked_private_subdirectory(
    tmp_path, private_name,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_dir / private_name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(SecurityError, match="must not be a symlink"):
        _embedded_settings(tmp_path, data_dir=str(data_dir))

    assert not (outside / ".asrkit-write-probe").exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"host": "0.0.0.0"}, "only binds"),
        ({"token": None}, "ASRKIT_GATEWAY_TOKEN"),
        ({"token": "short"}, "at least 32"),
        ({"parent_pid": None}, "--parent-pid"),
        ({"data_dir": None}, "--data-dir"),
        ({"max_upload_mb": 0}, "--max-upload-mb"),
        ({"max_concurrency": 0}, "--max-concurrency"),
        ({"request_timeout_s": 0}, "--request-timeout"),
    ],
)
def test_embedded_settings_reject_unsafe_values(tmp_path, overrides, message):
    with pytest.raises(SecurityError, match=message):
        _embedded_settings(tmp_path, **overrides)


def test_non_embedded_port_zero_and_parent_are_rejected():
    with pytest.raises(SecurityError, match="port 0 requires"):
        resolve_settings(
            embedded=False, host="127.0.0.1", port=0, parent_pid=None,
            data_dir=None, token=None)
    with pytest.raises(SecurityError, match="requires --embedded"):
        resolve_settings(
            embedded=False, host="127.0.0.1", port=11435, parent_pid=os.getpid(),
            data_dir=None, token=None)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_existing_data_dir_must_already_be_private(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)

    with pytest.raises(SecurityError, match="must be private"):
        _embedded_settings(tmp_path, data_dir=str(shared))

    assert shared.stat().st_mode & 0o777 == 0o755


def test_cli_reports_embedded_configuration_errors_without_stdout(capsys):
    assert cli.main(["--embedded"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--parent-pid" in captured.err


def test_parent_monitor_requests_shutdown(monkeypatch):
    class _Server:
        should_exit = False

    server = _Server()
    monkeypatch.setattr(lifecycle, "pid_exists", lambda pid: False)
    reason = asyncio.run(lifecycle.monitor_parent(123, server, interval_s=0.001))

    assert reason == "parent_exited"
    assert server.should_exit is True


def _source_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(SOURCE_ROOT)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["ASRKIT_GATEWAY_TOKEN"] = TOKEN
    return env


def _readline(stream, timeout: float = 10.0) -> str:
    lines: queue.Queue[str] = queue.Queue()

    def read() -> None:
        lines.put(stream.readline())

    threading.Thread(target=read, daemon=True).start()
    return lines.get(timeout=timeout)


def test_embedded_process_ready_auth_health_and_shutdown(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("uvicorn")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "asrkit.daemon", "--embedded",
            "--parent-pid", str(os.getpid()), "--data-dir", str(tmp_path / "data"),
        ],
        cwd=tmp_path,
        env=_source_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    try:
        ready = json.loads(_readline(proc.stdout))
        assert ready["event"] == "ready"
        assert ready["protocol_version"] == 1
        assert ready["pid"] == proc.pid
        assert ready["base_url"].startswith("http://127.0.0.1:")
        assert not ready["base_url"].endswith(":0/v1")

        health_url = ready["base_url"].removesuffix("/v1") + "/health"
        with urllib.request.urlopen(health_url, timeout=5) as response:
            health = json.load(response)
        assert health == {
            "status": "ok",
            "version": "0.5.5",
            "protocol_version": 1,
            "distribution": "cloud",
        }

        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(ready["base_url"] + "/models", timeout=5)
        assert unauthorized.value.code == 401

        request = urllib.request.Request(
            ready["base_url"] + "/models",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            models = json.load(response)
        assert len(models["data"]) == 10

        proc.terminate()
        shutdown = json.loads(_readline(proc.stdout))
        assert shutdown["event"] == "shutdown"
        assert shutdown["reason"] == "signal"
        assert proc.wait(timeout=10) == 0
        assert proc.stdout.read() == ""
        assert TOKEN not in proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.returncode:
            pytest.fail(proc.stderr.read())


def test_embedded_process_exits_when_parent_disappears(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("uvicorn")
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "asrkit.daemon", "--embedded",
            "--parent-pid", str(parent.pid), "--data-dir", str(tmp_path / "data"),
        ],
        cwd=tmp_path,
        env=_source_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    try:
        assert json.loads(_readline(proc.stdout))["event"] == "ready"
        parent.terminate()
        parent.wait(timeout=5)
        shutdown = json.loads(_readline(proc.stdout))
        assert shutdown == {"event": "shutdown", "reason": "parent_exited"}
        assert proc.wait(timeout=10) == 0
        assert proc.stdout.read() == ""
        assert TOKEN not in proc.stderr.read()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.returncode:
            pytest.fail(proc.stderr.read())

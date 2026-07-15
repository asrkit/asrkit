"""asrkit-cloud 冻结构建脚本的轻量契约测试。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_cloud_build_command_uses_spec_and_onedir_paths(tmp_path):
    build = _load("asrkit_cloud_build", ROOT / "packaging" / "cloud" / "build.py")
    dist = tmp_path / "dist"
    work = tmp_path / "work"

    command = build.build_command(dist, work)

    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert command[command.index("--distpath") + 1] == str(dist)
    assert command[command.index("--workpath") + 1] == str(work)
    assert "--clean" in command
    assert "--onefile" not in command
    assert command[-1] == str(ROOT / "packaging" / "cloud" / "asrkit-cloud.spec")


def test_cloud_smoke_environment_removes_development_state():
    smoke = _load("asrkit_cloud_smoke", ROOT / "packaging" / "cloud" / "smoke.py")
    env = smoke.clean_environment({
        "ASRKIT_CONFIG": "/private/config.json",
        "ASRKIT_GATEWAY_TOKEN": "secret",
        "CONDA_PREFIX": "/conda",
        "PYTHONHOME": "/python",
        "PYTHONPATH": "/checkout/src",
        "VIRTUAL_ENV": "/venv",
        "KEEP_ME": "yes",
        "PATH": "/developer/bin",
    })

    assert env == {"KEEP_ME": "yes", "PATH": __import__("os").defpath}


def test_cloud_bootstrap_uses_platform_venv_python(tmp_path, monkeypatch):
    bootstrap = _load(
        "asrkit_cloud_bootstrap", ROOT / "packaging" / "cloud" / "bootstrap.py")

    monkeypatch.setattr(bootstrap.os, "name", "nt")
    assert bootstrap.environment_python(tmp_path) == tmp_path / "Scripts" / "python.exe"

    monkeypatch.setattr(bootstrap.os, "name", "posix")
    assert bootstrap.environment_python(tmp_path) == tmp_path / "bin" / "python"

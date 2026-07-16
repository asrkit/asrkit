"""asrkit-cloud 冻结构建脚本的轻量契约测试。"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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


def _write_fake_venv(bootstrap, environment: Path, *, marker: bool) -> None:
    python = bootstrap.environment_python(environment)
    python.parent.mkdir(parents=True)
    python.write_text("python")
    (environment / "pyvenv.cfg").write_text("home = test\n")
    if marker:
        (environment / bootstrap._ENV_MARKER).write_text(bootstrap._ENV_MARKER_CONTENT)


@pytest.mark.parametrize(
    "target_kind",
    ["root", "home", "repo", "repo_parent", "cwd", "cwd_parent"],
)
def test_cloud_bootstrap_rejects_dangerous_environment_targets(
    tmp_path, monkeypatch, capsys, target_kind,
):
    bootstrap = _load(
        f"asrkit_cloud_bootstrap_danger_{target_kind}",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    monkeypatch.chdir(tmp_path)
    targets = {
        "root": Path(Path.cwd().anchor),
        "home": Path.home(),
        "repo": bootstrap.ROOT,
        "repo_parent": bootstrap.ROOT.parent,
        "cwd": Path.cwd(),
        "cwd_parent": Path.cwd().parent,
    }
    removals = []
    creations = []
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda path: removals.append(path))
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: creations.append(Path(path)),
    )

    assert bootstrap.main(["--env-dir", str(targets[target_kind]), "--recreate"]) == 2

    assert removals == []
    assert creations == []
    assert "unsafe build environment" in capsys.readouterr().err.lower()


def test_cloud_bootstrap_rejects_system_temp_root_as_recreate_target(
    tmp_path, monkeypatch, capsys,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_temp_root",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    temp_root = tmp_path / "system-temp-root"
    _write_fake_venv(bootstrap, temp_root, marker=True)
    monkeypatch.setattr(bootstrap.tempfile, "gettempdir", lambda: str(temp_root))
    removals = []
    monkeypatch.setattr(
        bootstrap.shutil, "rmtree", lambda path: removals.append(Path(path)))

    assert bootstrap.main([
        "--env-dir", str(temp_root), "--recreate", "--skip-install",
    ]) == 2

    assert removals == []
    assert (temp_root / "pyvenv.cfg").is_file()
    assert "unsafe build environment" in capsys.readouterr().err.lower()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_cloud_bootstrap_rejects_leaf_symlink_before_resolve(tmp_path, monkeypatch, capsys):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_symlink", ROOT / "packaging" / "cloud" / "bootstrap.py")
    target = tmp_path / "real-environment"
    target.mkdir()
    environment = tmp_path / "environment-link"
    environment.symlink_to(target, target_is_directory=True)
    removals = []
    creations = []
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda path: removals.append(path))
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: creations.append(Path(path)),
    )

    assert bootstrap.main(["--env-dir", str(environment), "--recreate"]) == 2

    assert removals == []
    assert creations == []
    assert environment.is_symlink()
    assert "symlink" in capsys.readouterr().err.lower()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_cloud_bootstrap_parent_symlink_cannot_grant_legacy_delete(
    tmp_path, monkeypatch, capsys,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_parent_symlink",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "build").symlink_to(outside, target_is_directory=True)
    environment = repo / "build" / "asrkit-cloud-env"
    monkeypatch.setattr(bootstrap, "ROOT", repo)
    monkeypatch.setattr(bootstrap, "DEFAULT_ENV", environment)
    _write_fake_venv(bootstrap, outside / "asrkit-cloud-env", marker=False)
    removals = []
    monkeypatch.setattr(
        bootstrap.shutil, "rmtree", lambda path: removals.append(Path(path)))
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: pytest.fail(f"unexpected create at {path}"),
    )

    assert bootstrap.main([
        "--env-dir", str(environment), "--recreate", "--skip-install",
    ]) == 2

    assert removals == []
    assert (outside / "asrkit-cloud-env" / "pyvenv.cfg").is_file()
    assert "escapes the repository through a symlink" in capsys.readouterr().err.lower()


def test_cloud_bootstrap_recreate_only_removes_marked_valid_environment(
    tmp_path, monkeypatch,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_managed", ROOT / "packaging" / "cloud" / "bootstrap.py")
    environment = tmp_path / "managed"
    _write_fake_venv(bootstrap, environment, marker=True)
    removals = []
    real_rmtree = shutil.rmtree

    def remove(path):
        removals.append(Path(path))
        real_rmtree(path)

    creations = []

    def create(path):
        creations.append(Path(path))
        _write_fake_venv(bootstrap, Path(path), marker=False)

    monkeypatch.setattr(bootstrap.shutil, "rmtree", remove)
    monkeypatch.setattr(bootstrap.venv.EnvBuilder, "create", lambda self, path: create(path))
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: type("R", (), {"returncode": 0})())

    assert bootstrap.main([
        "--env-dir", str(environment), "--recreate", "--skip-install", "--", "--dry-run",
    ]) == 0

    assert removals == [environment.resolve()]
    assert creations == [environment.resolve()]
    assert (environment / bootstrap._ENV_MARKER).read_text() == bootstrap._ENV_MARKER_CONTENT


def test_cloud_bootstrap_migrates_legacy_default_venv_once(
    tmp_path, monkeypatch,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_legacy_default",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    environment = tmp_path / "legacy-default"
    monkeypatch.setattr(bootstrap, "DEFAULT_ENV", environment)
    _write_fake_venv(bootstrap, environment, marker=False)
    removals = []
    creations = []
    real_rmtree = shutil.rmtree

    def remove(path):
        removals.append(Path(path))
        real_rmtree(path)

    def create(path):
        creations.append(Path(path))
        _write_fake_venv(bootstrap, Path(path), marker=False)

    monkeypatch.setattr(bootstrap.shutil, "rmtree", remove)
    monkeypatch.setattr(bootstrap.venv.EnvBuilder, "create", lambda self, path: create(path))
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0})(),
    )

    assert bootstrap.main([
        "--env-dir", str(environment), "--recreate", "--skip-install",
    ]) == 0

    assert removals == [environment.resolve()]
    assert creations == [environment.resolve()]
    assert (environment / bootstrap._ENV_MARKER).read_text() == bootstrap._ENV_MARKER_CONTENT


@pytest.mark.parametrize("broken_part", ["marker", "pyvenv", "python"])
def test_cloud_bootstrap_recreate_refuses_incomplete_managed_environment(
    tmp_path, monkeypatch, capsys, broken_part,
):
    bootstrap = _load(
        f"asrkit_cloud_bootstrap_incomplete_{broken_part}",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    environment = tmp_path / "environment"
    _write_fake_venv(bootstrap, environment, marker=True)
    broken_paths = {
        "marker": environment / bootstrap._ENV_MARKER,
        "pyvenv": environment / "pyvenv.cfg",
        "python": bootstrap.environment_python(environment),
    }
    broken_paths[broken_part].unlink()
    removals = []
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda path: removals.append(path))
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: pytest.fail(f"unexpected create at {path}"),
    )
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unexpected subprocess"),
    )

    assert bootstrap.main([
        "--env-dir", str(environment), "--recreate", "--skip-install",
    ]) == 2

    assert removals == []
    assert environment.exists()
    assert "not a managed" in capsys.readouterr().err.lower()


def test_cloud_bootstrap_reuses_custom_unmarked_venv_but_never_deletes_it(
    tmp_path, monkeypatch, capsys,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_unmarked", ROOT / "packaging" / "cloud" / "bootstrap.py")
    environment = tmp_path / "custom"
    _write_fake_venv(bootstrap, environment, marker=False)
    calls = []
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda path: calls.append(("remove", path)))
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(("run", args[0])) or type("R", (), {"returncode": 0})(),
    )

    assert bootstrap.main(["--env-dir", str(environment), "--skip-install"]) == 0
    assert not (environment / bootstrap._ENV_MARKER).exists()
    assert [kind for kind, _ in calls] == ["run"]

    calls.clear()
    assert bootstrap.main([
        "--env-dir", str(environment), "--recreate", "--skip-install",
    ]) == 2
    assert calls == []
    assert "not a managed" in capsys.readouterr().err.lower()


def test_cloud_bootstrap_failed_creation_never_writes_marker(tmp_path, monkeypatch):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_failed_create", ROOT / "packaging" / "cloud" / "bootstrap.py")
    environment = tmp_path / "new-environment"

    def fail_create(path):
        Path(path).mkdir(parents=True)
        (Path(path) / "partial").write_text("incomplete")
        raise RuntimeError("creation failed")

    monkeypatch.setattr(bootstrap.venv.EnvBuilder, "create", lambda self, path: fail_create(path))

    with pytest.raises(RuntimeError, match="creation failed"):
        bootstrap.main(["--env-dir", str(environment), "--skip-install"])

    assert not (environment / bootstrap._ENV_MARKER).exists()


@pytest.mark.parametrize("precreate", [False, True])
def test_cloud_bootstrap_creates_only_the_validated_requested_environment(
    tmp_path, monkeypatch, precreate,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_requested_path",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    requested = tmp_path / "build-state" / "cloud-env"
    if precreate:
        requested.mkdir(parents=True)
    created = []

    def create(path):
        created.append(Path(path))
        _write_fake_venv(bootstrap, Path(path), marker=False)

    monkeypatch.setattr(bootstrap.venv.EnvBuilder, "create", lambda self, path: create(path))
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0})(),
    )

    assert bootstrap.main(["--env-dir", str(requested), "--skip-install"]) == 0

    assert created == [requested.resolve()]
    assert (requested / bootstrap._ENV_MARKER).is_file()


def test_cloud_bootstrap_refuses_existing_file_target(tmp_path, monkeypatch, capsys):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_file_target",
        ROOT / "packaging" / "cloud" / "bootstrap.py",
    )
    environment = tmp_path / "environment-file"
    environment.write_text("keep")
    monkeypatch.setattr(
        bootstrap.shutil,
        "rmtree",
        lambda path: pytest.fail(f"unexpected removal at {path}"),
    )
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: pytest.fail(f"unexpected create at {path}"),
    )

    assert bootstrap.main(["--env-dir", str(environment), "--recreate"]) == 2

    assert environment.read_text() == "keep"
    assert "not a directory" in capsys.readouterr().err.lower()


def test_cloud_bootstrap_refuses_nonempty_non_venv_without_removal(
    tmp_path, monkeypatch, capsys,
):
    bootstrap = _load(
        "asrkit_cloud_bootstrap_nonvenv", ROOT / "packaging" / "cloud" / "bootstrap.py")
    environment = tmp_path / "not-a-venv"
    environment.mkdir()
    (environment / "user-data").write_text("keep")
    removals = []
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda path: removals.append(path))
    monkeypatch.setattr(
        bootstrap.venv.EnvBuilder,
        "create",
        lambda self, path: pytest.fail(f"unexpected create at {path}"),
    )
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unexpected subprocess"),
    )

    assert bootstrap.main(["--env-dir", str(environment), "--skip-install"]) == 2

    assert removals == []
    assert (environment / "user-data").read_text() == "keep"
    assert "not empty" in capsys.readouterr().err.lower()


def test_linux_container_smoke_has_valid_bash_syntax():
    bash = shutil.which("bash")
    if bash is None:
        return
    subprocess.run(
        [bash, "-n", str(ROOT / "packaging" / "cloud" / "smoke-linux-container.sh")],
        check=True,
    )


def test_cloud_runtime_workflow_connects_build_clean_smoke_and_artifact():
    workflow = (ROOT / ".github" / "workflows" / "cloud-runtime.yml").read_text()

    assert "python packaging/cloud/build.py" in workflow
    assert "smoke-linux-container.sh dist/asrkit-cloud" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "sha256sum" in workflow
    assert '${GITHUB_SHA:0:7}' in workflow
    assert "steps.artifact.outputs.name" in workflow
    assert 'tags: ["v*"]' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow

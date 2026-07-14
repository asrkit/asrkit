"""cloud-only 注册表与命令入口的隔离契约。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
CLOUD_IDS = {
    "dashscope/fun-asr-flash",
    "dashscope/qwen-omni-flash",
    "dashscope/qwen-omni-plus",
    "dashscope/qwen3-asr-flash",
    "doubao/auc-1",
    "doubao/auc-2",
    "elevenlabs/scribe-v1",
    "openai/whisper-1",
    "siliconflow/sensevoice",
    "siliconflow/telespeech",
}


def _source_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(SOURCE_ROOT)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env.update({
        "PYTHONPATH": os.pathsep.join(paths),
        "ASRKIT_CONFIG": str(tmp_path / "config.json"),
        "ASRKIT_MODELS_JSON": str(tmp_path / "models.json"),
        "ASRKIT_MODELS_ROOT": str(tmp_path / "models"),
    })
    return env


def _run_child(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=tmp_path,
        env=_source_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )


def test_cloud_profile_loads_only_builtin_cloud_models(tmp_path: Path) -> None:
    (tmp_path / "models.json").write_text(json.dumps([{
        "id": "sherpa/from-user",
        "config_type": "senseVoice",
        "source": "local",
    }]))
    proc = _run_child(
        f"""
        import importlib.metadata
        import json
        import sys

        def unexpected_plugins(**kwargs):
            raise AssertionError("cloud profile must not discover entry-point plugins")

        importlib.metadata.entry_points = unexpected_plugins

        from asrkit import registry

        registry.configure_profile("cloud")
        metas = registry.list_metas()
        ids = {{meta.id for meta in metas}}
        assert ids == {CLOUD_IDS!r}
        assert all(meta.source == "cloud" for meta in metas)
        assert registry.active_profile() == "cloud"
        assert "asrkit.profiles.cloud" in sys.modules
        assert "asrkit.profiles.full" not in sys.modules
        assert registry.make_adapter(
            "openai/whisper-1", {{"api_key": "test-key"}}
        ).meta.id == "openai/whisper-1"

        for unavailable in (
            "sherpa/sensevoice",
            "transformers/openai/whisper-tiny",
            "sherpa/from-user",
        ):
            try:
                registry.resolve(unavailable)
            except registry.ModelNotFoundError:
                pass
            else:
                raise AssertionError(f"cloud profile resolved {{unavailable}}")

        local_modules = sorted(
            name for name in sys.modules
            if name.startswith("asrkit.adapters.local_") or name.endswith(".models_local")
        )
        assert local_modules == []

        try:
            registry.configure_profile("full")
        except RuntimeError:
            pass
        else:
            raise AssertionError("a loaded cloud registry switched to full")

        print(json.dumps({{
            "count": len(metas),
            "local_modules": local_modules,
            "profile": registry.active_profile(),
        }}))
        """,
        tmp_path,
    )

    assert json.loads(proc.stdout) == {
        "count": 10,
        "local_modules": [],
        "profile": "cloud",
    }


def test_default_profile_keeps_full_registry_behavior(tmp_path: Path) -> None:
    proc = _run_child(
        """
        import importlib.metadata
        import json
        import sys

        importlib.metadata.entry_points = lambda **kwargs: ()

        from asrkit import registry

        metas = registry.list_metas()
        ids = {meta.id for meta in metas}
        assert len(metas) == 71
        assert "sherpa/sensevoice" in ids
        assert "openai/whisper-1" in ids
        assert "asrkit.profiles.full" in sys.modules
        print(json.dumps({"count": len(metas), "profile": registry.active_profile()}))
        """,
        tmp_path,
    )

    assert json.loads(proc.stdout) == {"count": 71, "profile": "full"}


def test_asrkit_cloud_module_version_uses_current_source(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "asrkit.daemon", "--version"],
        cwd=tmp_path,
        env=_source_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    assert proc.stdout.strip() == "asrkit-cloud 0.5.4"
    assert proc.stderr == ""


def test_asrkit_cloud_locks_profile_before_dispatch(tmp_path: Path) -> None:
    proc = _run_child(
        """
        import json

        from asrkit import registry, server
        from asrkit.daemon import cli

        called = {}
        server.serve = lambda **kwargs: called.update(kwargs)

        assert cli.main(["--host", "127.0.0.1", "--port", "11436"]) == 0
        metas = registry.list_metas()
        print(json.dumps({
            "host": called["host"],
            "port": called["port"],
            "max_concurrency": called["max_concurrency"],
            "count": len(metas),
            "profile": registry.active_profile(),
        }))
        """,
        tmp_path,
    )

    assert json.loads(proc.stdout) == {
        "host": "127.0.0.1",
        "port": 11436,
        "max_concurrency": 4,
        "count": 10,
        "profile": "cloud",
    }
    assert "asrkit-cloud serving" in proc.stderr
    assert "cloud-only" in proc.stderr


def test_cloud_http_model_list_excludes_local_models(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    proc = _run_child(
        f"""
        import json
        import sys

        from fastapi.testclient import TestClient
        from asrkit import registry

        registry.configure_profile("cloud")
        from asrkit import server

        with TestClient(server.build_app()) as client:
            payload = client.get("/v1/models").json()
            ids = {{item["id"] for item in payload["data"]}}
            assert ids == {CLOUD_IDS!r}
            response = client.post(
                "/v1/audio/transcriptions",
                data={{"model": "sherpa/sensevoice"}},
                files={{"file": ("a.wav", b"placeholder", "audio/wav")}},
            )
            assert response.status_code == 404

        local_modules = sorted(
            name for name in sys.modules
            if name.startswith("asrkit.adapters.local_") or name.endswith(".models_local")
        )
        assert local_modules == []
        print(json.dumps({{"count": len(ids), "local_modules": local_modules}}))
        """,
        tmp_path,
    )

    assert json.loads(proc.stdout) == {"count": 10, "local_modules": []}

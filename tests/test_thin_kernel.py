"""薄内核契约：发现模型和构造 adapter 不得加载可选重运行时。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT / "src"

# 覆盖 pyproject 中全部本地引擎、音频、麦克风和 serve extras，以及它们常见的重传递依赖。
OPTIONAL_RUNTIME_ROOTS = (
    "av",
    "ctranslate2",
    "fastapi",
    "faster_whisper",
    "httpx",
    "librosa",
    "multipart",
    "numpy",
    "onnxruntime",
    "pywhispercpp",
    "scipy",
    "sherpa_onnx",
    "sounddevice",
    "soundfile",
    "soxr",
    "starlette",
    "tokenizers",
    "torch",
    "transformers",
    "uvicorn",
)


def test_builtin_registry_and_lightweight_surfaces_keep_optional_runtimes_lazy(
    tmp_path: Path,
) -> None:
    code = textwrap.dedent(
        f"""
        import builtins
        import importlib
        import importlib.metadata
        import io
        import json
        import os
        import sys
        from contextlib import redirect_stdout
        from pathlib import Path

        blocked = {OPTIONAL_RUNTIME_ROOTS!r}
        real_import = builtins.__import__
        real_import_module = importlib.import_module

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name.split(".", 1)[0] in blocked:
                raise AssertionError(f"optional runtime imported by thin surface: {{name}}")
            return real_import(name, globals, locals, fromlist, level)

        def guarded_import_module(name, package=None):
            if not name.startswith(".") and name.split(".", 1)[0] in blocked:
                raise AssertionError(f"optional runtime imported by thin surface: {{name}}")
            return real_import_module(name, package)

        # This test owns the built-in boundary; installed third-party entry points are outside it.
        importlib.metadata.entry_points = lambda **kwargs: ()
        importlib.import_module = guarded_import_module
        builtins.__import__ = guarded_import

        import asrkit
        from asrkit import cli, registry
        import asrkit.mic
        import asrkit.server

        source_root = Path(os.environ["ASRKIT_TEST_SOURCE_ROOT"]).resolve()
        assert Path(asrkit.__file__).resolve().is_relative_to(source_root)

        metas = registry.list_metas()
        ids = {{meta.id for meta in metas}}
        assert {{
            "sherpa/whisper-tiny",
            "faster-whisper/tiny",
            "whispercpp/tiny",
            "transformers/openai/whisper-tiny",
            "openai/whisper-1",
        }} <= ids

        for model in (
            "sherpa/whisper-tiny",
            "faster-whisper/tiny",
            "whispercpp/tiny",
            "transformers/openai/whisper-tiny",
            "openai/whisper-1",
        ):
            adapter = registry.make_adapter(model)
            if adapter.meta.source == "local":
                adapter.is_installed()

        with redirect_stdout(io.StringIO()):
            assert cli.main(["list", "--json"]) == 0

        loaded = sorted(
            name for name in sys.modules if name.split(".", 1)[0] in blocked
        )
        print(json.dumps({{"model_count": len(metas), "loaded": loaded}}))
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(SOURCE_ROOT),
            "ASRKIT_TEST_SOURCE_ROOT": str(SOURCE_ROOT),
            "ASRKIT_CONFIG": str(tmp_path / "config.json"),
            "ASRKIT_MODELS_JSON": str(tmp_path / "models.json"),
            "ASRKIT_MODELS_ROOT": str(tmp_path / "models"),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(proc.stdout)
    assert result["model_count"] == 71
    assert result["loaded"] == []

# -*- mode: python ; coding: utf-8 -*-
"""asrkit-cloud 的 PyInstaller onedir 规范。"""

from pathlib import Path


ROOT = Path(SPECPATH).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
ENTRYPOINT = ROOT / "packaging" / "cloud" / "entrypoint.py"

# uvicorn 通过字符串选择 loop/http/lifespan 实现，必须显式收集其子模块。
HIDDEN_IMPORTS = ["asrkit.profiles.cloud"]

# cloud profile 永远不会加载这些模块；排除它们也防止构建机偶然安装的重依赖泄漏进产物。
EXCLUDED_MODULES = [
    "asrkit.adapters.local_faster_whisper",
    "asrkit.adapters.local_sherpa",
    "asrkit.adapters.local_transformers",
    "asrkit.adapters.local_whispercpp",
    "asrkit.adapters.models_local",
    "asrkit.cli",
    "asrkit.cli_commands",
    "asrkit.completion",
    "asrkit.doctor",
    "asrkit.engines",
    "asrkit.mic",
    "asrkit.profiles.full",
    "asrkit.store",
    "asrkit.usermodels",
    "faster_whisper",
    "gunicorn",
    "httptools",
    "mypy",
    "numpy",
    "PIL",
    "pywhispercpp",
    "rich",
    "sherpa_onnx",
    "sounddevice",
    "soundfile",
    "soxr",
    "torch",
    "transformers",
    "trio",
    "uvloop",
    "watchfiles",
    "websockets",
    "wsproto",
]

analysis = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[str(ROOT / "packaging" / "cloud" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="asrkit-cloud",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="asrkit-cloud",
)

"""Known engines and how to install them (for `asrkit engine`).

Engines are Python packages (not weight files). sherpa-onnx ships with the base
install; others are optional pip extras. See docs/engines-and-addressing.md §八.
"""
from __future__ import annotations

import importlib.util

# name -> (python module to probe for availability, pip extra or None if built-in)
ENGINES = {
    "sherpa-onnx":    ("sherpa_onnx", None),               # 基础安装自带
    "faster-whisper": ("faster_whisper", "faster-whisper"),
}


def is_installed(name: str) -> bool:
    mod = ENGINES.get(name, (None, None))[0]
    return bool(mod) and importlib.util.find_spec(mod) is not None


def extra_of(name: str):
    return ENGINES.get(name, (None, None))[1]

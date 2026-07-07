"""Known engines and how to install them (for `asrkit engine`).

Engines are Python packages (not weight files). ALL engines are optional pip extras —
the base install carries only the interface + cloud (HTTP). See docs/engines-and-addressing.md §八.
"""
from __future__ import annotations

import importlib.util

# name -> (python module to probe for availability, pip extra)
ENGINES = {
    "sherpa-onnx":    ("sherpa_onnx", "sherpa"),           # 默认端侧引擎（47 模型）
    "faster-whisper": ("faster_whisper", "faster-whisper"),
    "transformers":   ("transformers", "transformers"),    # 接整个 HF ASR 生态（重,含 torch）
    "whispercpp":     ("pywhispercpp", "whispercpp"),      # whisper.cpp,超轻量（无 torch/onnx）
}


def is_installed(name: str) -> bool:
    mod = ENGINES.get(name, (None, None))[0]
    return mod is not None and importlib.util.find_spec(mod) is not None


def extra_of(name: str):
    return ENGINES.get(name, (None, None))[1]

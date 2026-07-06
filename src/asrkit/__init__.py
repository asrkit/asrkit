"""ASRKit — one interface to run and compare any speech-to-text model, local & cloud.

    from asrkit import transcribe
    r = transcribe(model="local/sensevoice", audio="a.wav", config={"model_dir": "..."})
    r = transcribe(model="siliconflow/sensevoice", audio="a.wav", config={"api_key": "..."})
"""
from __future__ import annotations

__version__ = "0.1.2"

from .api import list_models, transcribe
from .types import (
    AdapterMeta,
    AudioInput,
    BaseAdapter,
    PartialResult,
    Segment,
    TranscribeOptions,
    TranscribeResult,
)

__all__ = [
    "__version__",
    "transcribe",
    "list_models",
    "AudioInput",
    "Segment",
    "TranscribeResult",
    "TranscribeOptions",
    "PartialResult",
    "AdapterMeta",
    "BaseAdapter",
]

"""Nightly real-engine E2E.

This file intentionally lives outside ``tests/`` so the normal unit suite does
not download a model.  The nightly workflow invokes it explicitly; once
invoked, missing dependencies, fixtures, downloads, or inference all fail.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from asrkit import api
from asrkit.types import TranscribeOptions

MODEL = "sherpa/whisper-tiny"
FIXTURE = Path(__file__).parent / "fixtures" / "1089-134686-0001.wav"
TRANSCRIPT_ANCHORS = {"nightfall", "yellow", "lamps"}


def test_pull_and_transcribe_real(tmp_path: Path) -> None:
    # Import explicitly: a broken optional dependency must make nightly red.
    for dependency in ("sherpa_onnx", "numpy", "soundfile", "soxr"):
        importlib.import_module(dependency)

    assert FIXTURE.is_file(), f"missing committed E2E fixture: {FIXTURE}"

    config = {"models_root": str(tmp_path / "models")}
    model_dir = Path(api.pull(MODEL, config=config))
    assert model_dir.is_dir()
    assert model_dir.is_relative_to(tmp_path)

    result = api.transcribe(
        MODEL,
        str(FIXTURE),
        config=config,
        opts=TranscribeOptions(convert=False, lang_hint="en"),
    )
    assert result.error is None, f"transcribe returned error: {result.error}"
    assert result.text.strip(), "expected a non-empty transcript from real inference"
    assert result.metrics and result.metrics.get("duration_s", 0) > 0
    assert "decode_ms" in result.metrics

    words = set(re.findall(r"[a-z]+", result.text.lower()))
    matched = words & TRANSCRIPT_ANCHORS
    assert len(matched) >= 2, (
        f"expected at least 2 transcript anchors, got {sorted(matched)} from {result.text!r}"
    )

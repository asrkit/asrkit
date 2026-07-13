"""Fast guards for the nightly E2E contract; real inference lives in e2e/."""
from __future__ import annotations

import hashlib
import wave
from pathlib import Path

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "e2e" / "fixtures" / "1089-134686-0001.wav"
EXPECTED_SHA256 = "6bc58a4efdf20daac252b6b1502632601a71efe0308f6757dc1eda34891a7e4f"


def test_real_e2e_fixture_is_stable_speech_input() -> None:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == EXPECTED_SHA256
    with wave.open(str(FIXTURE), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000
        assert audio.getcomptype() == "NONE"
        assert audio.getnframes() == 106_000


def test_nightly_e2e_has_no_skip_path() -> None:
    source = (ROOT / "e2e" / "test_real.py").read_text()
    assert "pytest.skip" not in source
    assert "importorskip" not in source
    assert 'MODEL = "sherpa/whisper-tiny"' in source

    workflow = (ROOT / ".github" / "workflows" / "e2e.yml").read_text()
    assert "pytest e2e/test_real.py" in workflow
    assert "ASRKIT_E2E" not in workflow

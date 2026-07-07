"""真实端到端回归 —— 默认 skip，只有 nightly（设 ASRKIT_E2E=1）才跑。

平时的 test_smoke 只覆盖注册/寻址/安全，不碰真引擎。这条补上"真的过了 sherpa 引擎"的
覆盖：装 asrkit[sherpa] → pull 一个小端侧模型 → 用其 tarball 自带的 test_wavs 做一次真实
推理 → 断言无 error 且文本非空。模型自带样本音频，无需外部数据（asr_bench 是只读参考，
不在本仓库）。

  ASRKIT_E2E=1 [ASRKIT_E2E_MODEL=whisper-tiny] pytest tests/test_e2e.py
"""
import glob
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ASRKIT_E2E") != "1",
    reason="real E2E (downloads a model + runs inference); set ASRKIT_E2E=1 to run",
)

E2E_MODEL = os.environ.get("ASRKIT_E2E_MODEL", "whisper-tiny")


def test_pull_and_transcribe_real():
    pytest.importorskip("sherpa_onnx")
    pytest.importorskip("soundfile")
    from asrkit import api
    from asrkit.types import TranscribeOptions

    # pull（幂等：已装直接返回模型目录）
    model_dir = api.pull(E2E_MODEL)
    assert os.path.isdir(model_dir)

    # sherpa 模型 tarball 通常自带 test_wavs/*.wav；拿第一条做真实推理
    wavs = sorted(glob.glob(os.path.join(model_dir, "**", "*.wav"), recursive=True))
    if not wavs:
        pytest.skip(f"{E2E_MODEL} bundle ships no sample wav to transcribe")

    # convert=True 稳妥兜底（样本若非 16k 单声道也能跑；asrkit[sherpa] 含 soxr）
    r = api.transcribe(E2E_MODEL, wavs[0], opts=TranscribeOptions(convert=True))
    assert r.error is None, f"transcribe returned error: {r.error}"
    assert r.text.strip(), "expected a non-empty transcript from real inference"

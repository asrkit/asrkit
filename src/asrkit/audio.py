"""音频归一化：任意输入 → 16kHz 单声道 float32。平台职责，adapter 不碰。

移植自 asr_bench/desktop_bench/scripts/worker.py:load_wav。
"""
from __future__ import annotations

import os
import tempfile

from .types import AudioInput


def load_audio(path: str) -> AudioInput:
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if getattr(data, "ndim", 1) > 1:      # 多声道取均值
        data = data.mean(axis=1)

    norm_path = path
    if sr != 16000:                        # 重采样到 16k，并落一个归一化 wav 供云端上传
        import soxr
        data = soxr.resample(data, sr, 16000)
        sr = 16000
        fd, norm_path = tempfile.mkstemp(suffix="_asrkit16k.wav")
        os.close(fd)
        sf.write(norm_path, data, 16000)

    data = np.ascontiguousarray(data, dtype=np.float32)
    return AudioInput(
        samples=data,
        path=norm_path,
        sample_rate=16000,
        duration_s=round(len(data) / 16000.0, 3),
    )

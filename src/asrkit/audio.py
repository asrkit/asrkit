"""音频工具。

透明层原则（见 docs/adapter-spec.md §0）：**内核对音频零处理**。
core 不解码；只有需要 PCM 的本地 adapter 才调这里的 load_samples。
默认（convert=False）做"格式守卫"：与引擎要求不符即诚实报错，绝不静默出乱码。
"""
from __future__ import annotations

from typing import Tuple


class AudioFormatError(Exception):
    """输入格式/采样率/声道与本地引擎要求不符，且未开启 convert。"""


def load_samples(
    path: str,
    required_sr: int = 16000,
    required_channels: int = 1,
    convert: bool = False,
) -> Tuple["object", int]:
    """读取音频为 float32 采样点，返回 (samples, sample_rate)。

    - convert=False（默认）：采样率/声道/格式与要求不符 → 抛 AudioFormatError（诚实报错）。
    - convert=True：解码 + 混单声道 + 重采样到 required_sr（opt-in 转换）。
    """
    import numpy as np
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=False)
    except Exception as e:
        raise AudioFormatError(
            f"无法解码音频文件（{type(e).__name__}: {e}）。"
            f"本地引擎需要可解码的 WAV；mp3/m4a 等请先转码，或加 --convert / opts.convert=True。"
        )

    channels = 1 if getattr(data, "ndim", 1) == 1 else data.shape[1]

    if convert:
        if channels > 1:
            data = data.mean(axis=1)
        if sr != required_sr:
            import soxr
            data = soxr.resample(data, sr, required_sr)
            sr = required_sr
        return np.ascontiguousarray(data, dtype=np.float32), sr

    # 守卫：不转换，格式必须已符合引擎要求
    if channels != required_channels or sr != required_sr:
        raise AudioFormatError(
            f"输入为 {sr}Hz {channels} 声道，该模型要求 {required_sr}Hz {required_channels} 声道。"
            f"请自行转换，或加 --convert / opts.convert=True 让 asrkit 自动转换。"
        )
    return np.ascontiguousarray(data, dtype=np.float32), sr

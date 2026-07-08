"""音频工具。

透明层原则（见 docs/adapter-spec.md §0）：**内核对音频零处理**。
core 不解码；只有需要 PCM 的本地 adapter 才调这里的 load_samples。
默认（convert=False）做"格式守卫"：与引擎要求不符即诚实报错，绝不静默出乱码。
"""
from __future__ import annotations

from typing import Any, Iterator, Tuple


class AudioFormatError(Exception):
    """输入格式/采样率/声道与本地引擎要求不符，且未开启 convert。"""


# 云端上传时按扩展名如实声明容器格式。内核对音频零处理（见 §0），扩展名是我们
# 唯一诚实的信号：据实上报，绝不硬编码谎报为 "wav"。
_EXT_TO_FORMAT = {
    ".wav": "wav", ".mp3": "mp3", ".m4a": "m4a", ".mp4": "mp4",
    ".flac": "flac", ".ogg": "ogg", ".opus": "opus", ".aac": "aac",
    ".amr": "amr", ".webm": "webm", ".wma": "wma", ".aiff": "aiff", ".aif": "aiff",
}


def container_format(path: str) -> str:
    """Infer the container-format tag to declare to a cloud API, from the file
    extension. The kernel does zero audio processing, so the extension is our
    only honest signal — declare it truthfully, never fake "wav".
    Unknown extension → AudioFormatError (honest failure, no silent lie)."""
    import os
    ext = os.path.splitext(path)[1].lower()
    fmt = _EXT_TO_FORMAT.get(ext)
    if not fmt:
        known = ", ".join(sorted(set(_EXT_TO_FORMAT)))
        raise AudioFormatError(
            f"cannot tell the audio format from '{ext or path}'; a cloud upload "
            f"must declare its format truthfully — use a known extension ({known}).")
    return fmt


def load_samples(
    path: str,
    required_sr: int = 16000,
    required_channels: int = 1,
    convert: bool = False,
) -> Tuple[Any, int]:
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
            f"cannot decode audio file ({type(e).__name__}: {e}). "
            f"The local engine needs a decodable WAV; transcode mp3/m4a first, "
            f"or pass --convert / opts.convert=True."
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
            f"input is {sr}Hz {channels}-channel, but this model requires "
            f"{required_sr}Hz {required_channels}-channel. Convert it yourself, "
            f"or pass --convert / opts.convert=True."
        )
    return np.ascontiguousarray(data, dtype=np.float32), sr


def iter_file_chunks(
    path: str,
    sr: int = 16000,
    channels: int = 1,
    window_s: float = 0.1,
    *,
    convert: bool = False,
) -> Iterator[Any]:
    """解码文件为 sr/channels 后按固定窗切块,逐块 yield float32 采样。

    格式守卫沿用 load_samples:convert=False 且不符 → AudioFormatError(懒抛,首次迭代)。
    仅供流式 adapter 使用;window_s 由 api 层保证 > 0。
    """
    samples, actual_sr = load_samples(path, sr, channels, convert=convert)
    win = max(1, int(actual_sr * window_s))
    for i in range(0, len(samples), win):
        yield samples[i:i + win]

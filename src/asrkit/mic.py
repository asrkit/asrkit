"""麦克风流式输入源(opt-in extra: asrkit[mic])。
透明:直接采 16k 单声道 float32,喂 transcribe_stream;不做任何音频处理。"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from . import log

_INSTALL_HINT = 'mic input needs sounddevice. Run: pip install "asrkit[mic]"'


def record_chunks(samplerate: int = 16000, block_s: float = 0.1,
                  device: Optional[Any] = None) -> Iterator[Any]:
    """麦克风持续采样,逐块 yield float32 单声道数组。
    外壳非生成器:缺 sounddevice call-time RuntimeError;Ctrl-C → 内层干净停。"""
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        raise RuntimeError(_INSTALL_HINT) from e
    return _record(np, sd, samplerate, block_s, device)


def _record(
    np: Any,
    sd: Any,
    samplerate: int,
    block_s: float,
    device: Optional[Any],
) -> Iterator[Any]:
    _LOG = log.get_logger("mic")
    blocksize = max(1, int(samplerate * block_s))
    stream = sd.InputStream(samplerate=samplerate, channels=1, dtype="float32",
                            blocksize=blocksize, device=device)
    warned = False
    try:
        stream.start()
        while True:
            data, overflowed = stream.read(blocksize)
            if overflowed and not warned:
                _LOG.warning("microphone input overflowed — some audio was dropped")
                warned = True
            yield np.ascontiguousarray(data[:, 0], dtype=np.float32)
    except KeyboardInterrupt:
        return
    finally:
        stream.stop()
        stream.close()

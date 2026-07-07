"""输入解析：把 CLI 位置参数展开成有序、去重的音频文件列表。

支持:普通文件(即使不存在也入列,运行阶段自然报错)、glob(*?[)、目录递归(按扩展名白名单)、
stdin(-，见 stdin 处理)。glob/目录匹配 0 个 → fail loud(InputError)，绝不静默吞掉。
"""
from __future__ import annotations

import glob as _glob
import os
import sys
import tempfile
from typing import Callable, List, Tuple

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".webm", ".amr"}
_GLOB_CHARS = ("*", "?", "[")


class InputError(Exception):
    """输入无法解析(空匹配 / 多个 stdin 等)。CLI 映射为退出码 2。"""


def _is_glob(s: str) -> bool:
    return any(c in s for c in _GLOB_CHARS)


def _collect_dir(d: str) -> List[str]:
    hits = []
    for root, _dirs, files in os.walk(d):
        for f in files:
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                hits.append(os.path.join(root, f))
    return hits


def resolve(raw_args: List[str], *, stdin_format: str = "wav") -> Tuple[List[str], List[Callable]]:
    """返回 (有序去重文件路径, 清理回调)。本函数会为 stdin 产生副作用(见后续任务)。"""
    paths: List[str] = []
    cleanups: List[Callable] = []
    seen_stdin = False
    for arg in raw_args:
        if arg == "-":
            if seen_stdin:
                raise InputError("stdin '-' can appear at most once")
            seen_stdin = True
            data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") \
                else sys.stdin.read().encode()
            fd, tmp = tempfile.mkstemp(suffix="." + stdin_format.lstrip("."), prefix="asrkit_stdin_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            paths.append(tmp)
            cleanups.append(lambda p=tmp: os.path.exists(p) and os.unlink(p))
            continue
        if os.path.isdir(arg):
            hits = _collect_dir(arg)
            if not hits:
                raise InputError(f"directory '{arg}' has no audio files "
                                 f"({', '.join(sorted(AUDIO_EXTS))})")
            paths.extend(hits)
        elif _is_glob(arg) and not os.path.exists(arg):
            hits = _glob.glob(arg, recursive=True)
            if not hits:
                raise InputError(f"pattern '{arg}' matched no files")
            paths.extend(hits)
        else:
            paths.append(arg)          # 普通文件(即使不存在)
    out = sorted(dict.fromkeys(paths))  # 去重保序 + 排序确定性
    if not out:
        raise InputError("no audio inputs matched")
    return out, cleanups

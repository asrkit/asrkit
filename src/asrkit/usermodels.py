"""User model registry (~/.asrkit/models.json) read/write.

让用户不改包就能加模型（默认走 sherpa-onnx 引擎）。CLI `asrkit add-model` 写这里。
"""
from __future__ import annotations

import json
import os


def path() -> str:
    return os.environ.get("ASRKIT_MODELS_JSON") or os.path.expanduser("~/.asrkit/models.json")


def load() -> list:
    p = path()
    if not os.path.isfile(p):
        return []
    try:
        data = json.load(open(p, encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add(entry: dict) -> str:
    """追加一条模型（同 id 覆盖），返回写入的文件路径。"""
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    items = [e for e in load() if e.get("id") != entry["id"]]
    items.append(entry)
    json.dump(items, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return p

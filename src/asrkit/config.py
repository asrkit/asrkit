"""持久化配置：密钥库 + 默认值 + 设置（~/.asrkit/config.json）。

凭据解析优先级（见 registry.make_adapter）：显式 config > 环境变量 > 本文件 keystore。
安全：文件权限 0600；对外只打码显示（末 4 位）；明文存储（同 ollama/aws-cli 惯例）。
"""
from __future__ import annotations

import json
import os
from typing import Optional


def path() -> str:
    return os.environ.get("ASRKIT_CONFIG") or os.path.expanduser("~/.asrkit/config.json")


def load() -> dict:
    p = path()
    if not os.path.isfile(p):
        return {"keys": {}, "defaults": {}, "settings": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"keys": {}, "defaults": {}, "settings": {}}
    for k in ("keys", "defaults", "settings"):
        d.setdefault(k, {})
    return d


def save(cfg: dict) -> str:
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # 先写临时文件再 rename，且收紧权限（0600）
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    return p


def get_creds(vendor: str) -> dict:
    """返回该 vendor 存储的凭据 dict（api_key / app_key / access_key），无则空 dict。"""
    return dict(load().get("keys", {}).get(vendor, {}))


def set_creds(vendor: str, **kv) -> str:
    """写入非空凭据字段（api_key/app_key/access_key）。返回配置文件路径。"""
    cfg = load()
    cur = cfg["keys"].get(vendor, {})
    for k, v in kv.items():
        if v:
            cur[k] = v
    cfg["keys"][vendor] = cur
    return save(cfg)


def get_default(name: str, fallback: Optional[str] = None) -> Optional[str]:
    return load().get("defaults", {}).get(name, fallback)


def set_default(name: str, value: str) -> str:
    cfg = load()
    cfg["defaults"][name] = value
    return save(cfg)


def get_setting(name: str, fallback: Optional[str] = None) -> Optional[str]:
    return load().get("settings", {}).get(name, fallback)


def set_setting(name: str, value: str) -> str:
    cfg = load()
    cfg["settings"][name] = value
    return save(cfg)


def mask(secret: str) -> str:
    """打码：仅露末 4 位。"""
    if not secret:
        return ""
    s = str(secret)
    return ("…" + s[-4:]) if len(s) > 4 else "…"

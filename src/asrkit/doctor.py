"""asrkit doctor:离线体检 + opt-in 网络。只读、无持久副作用;不泄露密钥值。

diagnose(net=False) -> list[Check];cli 渲染 + 据 fail 定退出码。
硬失败(fail → 非零):models 存储不可用、config 损坏。缺引擎/密钥/网络 = info。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import List


@dataclass
class Check:
    name: str
    status: str   # "ok" | "info" | "fail"
    detail: str


def _writable(path: str) -> bool:
    """试写探针:向 path(不存在则向最近存在的祖先)写一个临时文件再删。无持久副作用。"""
    probe = path
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe.rstrip(os.sep))
        if parent == probe:
            break
        probe = parent
    if not os.path.isdir(probe):
        return False
    try:
        fd, tmp = tempfile.mkstemp(prefix=".asrkit_doctor_", dir=probe)
    except OSError:
        return False
    os.close(fd)
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return True


def _probe(url: str, timeout: float = 2.0) -> bool:
    """网络可达:短超时 HEAD,失败退回小 Range GET;无重试。"""
    import urllib.request
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method,
                headers={"User-Agent": "asrkit", "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return getattr(r, "status", 200) < 500
        except Exception:
            continue
    return False


def _cloud_vendors() -> list:
    from . import registry
    return sorted({m.vendor for m in registry.list_metas() if m.source == "cloud" and m.vendor})


def diagnose(net: bool = False) -> List[Check]:
    from . import __version__, config, engines, registry, store
    out: List[Check] = []

    out.append(Check("asrkit", "ok", __version__))
    out.append(Check("python", "ok", sys.version.split()[0]))

    # 引擎(仅包存在;sherpa 另需 numpy/soundfile/soxr)
    for name, (mod, extra) in engines.ENGINES.items():
        if engines.is_installed(name):
            out.append(Check(f"engine:{name}", "ok", "package present"))
        else:
            out.append(Check(f"engine:{name}", "info", f"not installed — pip install asrkit[{extra}]"))

    # 密钥(只报 vendor + 来源,绝不打印值)
    for v in _cloud_vendors():
        srcs = []
        if config.get_creds(v):
            srcs.append("keystore")
        vp = v.upper()
        if any(os.environ.get(f"{vp}_{s}") for s in ("API_KEY", "APP_KEY", "ACCESS_KEY")):
            srcs.append("env")
        out.append(Check(f"key:{v}", "info",
                         "present (" + "+".join(srcs) + ")" if srcs else "none"))

    # models 目录(试写探针 + 只统计 sherpa 管理的)
    root = store.models_root()
    if _writable(root):
        managed = [m for m in registry.list_metas() if m.provider == "sherpa-onnx"]
        installed = [m for m in managed if store.is_installed(m)]
        size = sum(store.dir_size(m) for m in installed)
        exists = os.path.isdir(root)
        state = "writable" if exists else "not created yet; created on first pull"
        out.append(Check("models-dir", "ok" if exists else "info",
                         f"{root} ({state}; {len(installed)} models, {size >> 20}MB)"))
    else:
        out.append(Check("models-dir", "fail", f"{root} not writable"))

    # config 完整性(直读,不经会吞错的 load)
    p = config.path()
    if not os.path.isfile(p):
        out.append(Check("config", "info", f"no config yet ({p})"))
    else:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError("not an object")
            de = (d.get("defaults") or {}).get("engine") or "sherpa"
            mr = (d.get("settings") or {}).get("models_root") or "(default)"
            out.append(Check("config", "ok", f"{p} (default-engine={de}, models-root={mr})"))
        except Exception as e:
            out.append(Check("config", "fail", f"config corrupt: {p} ({type(e).__name__})"))

    # 网络(opt-in;不可达=info,永不 fail)
    if net:
        metas = registry.list_metas()
        dl = next((m.download_url for m in metas if m.download_url), None)
        if dl:
            ok = _probe(dl)
            out.append(Check("net:download", "ok" if ok else "info",
                             ("reachable" if ok else "unreachable") + f" ({dl.split('/')[2]})"))
        cloud = next((m for m in metas if m.source == "cloud" and m.default_base_url), None)
        if cloud:
            ok = _probe(cloud.default_base_url)
            out.append(Check(f"net:{cloud.default_base_url.split('/')[2]}", "ok" if ok else "info",
                             "reachable" if ok else "unreachable"))
    return out

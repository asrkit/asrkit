"""注册中心：协议 adapter（按 provider）+ 模型表（按 id）+ Ollama 式别名。

    provider ──▶ 协议 adapter 类（sherpa-onnx / openai / …）
    model id ──▶ 一条 AdapterMeta
    别名：local/<base>[:<tag>] ──▶ 具体 id（默认 tag 优先 int8）
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Type

from .types import AdapterMeta, BaseAdapter

class ModelNotFoundError(Exception):
    """未注册的模型 id / 别名（用普通异常，str() 不会像 KeyError 那样加引号）。"""


_PROTOCOLS: Dict[str, Type[BaseAdapter]] = {}
_MODELS: Dict[str, AdapterMeta] = {}
_ALIASES: Dict[str, str] = {}   # 别名 -> 真实 id
_OPEN: Dict[str, object] = {}   # 开放 provider 前缀 -> factory(model_str)->AdapterMeta（如 transformers/<任意 HF id>）


def register_protocol(provider: str):
    def deco(cls: Type[BaseAdapter]) -> Type[BaseAdapter]:
        _PROTOCOLS[provider] = cls
        return cls
    return deco


def register_open_provider(prefix: str, factory) -> None:
    """开放 provider：`<prefix>/<任意串>` 动态合成 meta（如 transformers 接整个 HF hub）。"""
    _OPEN[prefix] = factory


def register_model(meta: AdapterMeta) -> None:
    _MODELS[meta.id] = meta
    _rebuild_aliases()


def register_models(metas: List[AdapterMeta]) -> None:
    for m in metas:
        _MODELS[m.id] = m
    _rebuild_aliases()


def _rebuild_aliases() -> None:
    _ALIASES.clear()
    groups: Dict[str, list] = {}
    for m in _MODELS.values():
        if not m.base:
            continue
        prefix = m.id.split("/", 1)[0]                 # "local"
        _ALIASES[f"{prefix}/{m.base}:{m.tag}"] = m.id  # 显式 base:tag
        groups.setdefault(f"{prefix}/{m.base}", []).append(m)
    for basekey, ms in groups.items():
        default = next((x for x in ms if x.tag == "int8"), ms[0])
        _ALIASES.setdefault(basekey, default.id)       # 不覆盖真实 id


def resolve(model_id: str) -> AdapterMeta:
    load_builtin()
    if model_id in _MODELS:
        return _MODELS[model_id]
    if model_id in _ALIASES:
        return _MODELS[_ALIASES[model_id]]
    # 裸名简写：不带 '/' 时当本地简名，自动补 local/（含精度别名 name:tag）
    if "/" not in model_id:
        cand = "local/" + model_id
        if cand in _MODELS:
            return _MODELS[cand]
        if cand in _ALIASES:
            return _MODELS[_ALIASES[cand]]
    else:
        # 开放 provider：transformers/<任意 HF id> 动态合成
        prefix, rest = model_id.split("/", 1)
        if rest and prefix in _OPEN:
            return _OPEN[prefix](rest)
    raise ModelNotFoundError(f"unknown model '{model_id}'. Run `asrkit list` to see all.")


def make_adapter(model_id: str, config: Optional[dict] = None) -> BaseAdapter:
    meta = resolve(model_id)
    cls = _PROTOCOLS.get(meta.provider)
    if cls is None:
        raise ModelNotFoundError(f"model '{model_id}': no adapter for provider '{meta.provider}'.")
    config = dict(config or {})
    # H-05：云端 key 环境变量兜底 <VENDOR>_API_KEY（显式 config 优先）
    if meta.source == "cloud" and not config.get("api_key") and meta.vendor:
        env = os.environ.get(f"{meta.vendor.upper()}_API_KEY")
        if env:
            config["api_key"] = env
    return cls(meta, config)


def list_metas() -> List[AdapterMeta]:
    load_builtin()
    return list(_MODELS.values())


_loaded = False


def load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    from .adapters import (  # noqa: F401
        cloud_openai,
        local_faster_whisper,
        local_sherpa,
        local_transformers,
        local_whispercpp,
        models_local,
    )
    _loaded = True           # 先置位，防止插件回调 load_builtin 造成递归
    _load_plugins()          # 第三方引擎插件（entry-point）
    _load_user_models()      # 用户自定义模型（~/.asrkit/models.json）


def _load_plugins() -> None:
    """发现并加载 entry-point 插件（group=asrkit.adapters）。插件模块导入时自注册；坏插件不连坐。"""
    import importlib.metadata as im
    try:
        eps = im.entry_points(group="asrkit.adapters")       # py3.10+
    except TypeError:
        eps = im.entry_points().get("asrkit.adapters", [])   # py3.9
    for ep in eps:
        try:
            ep.load()
        except Exception:
            pass


def _load_user_models() -> None:
    """加载用户自定义模型：$ASRKIT_MODELS_JSON 或 ~/.asrkit/models.json（sherpa 等本地引擎，任意补充）。"""
    import json
    import os
    path = os.environ.get("ASRKIT_MODELS_JSON") or os.path.expanduser("~/.asrkit/models.json")
    if not os.path.isfile(path):
        return
    try:
        entries = json.load(open(path, encoding="utf-8"))
    except Exception:
        return
    metas = []
    for e in (entries if isinstance(entries, list) else []):
        try:
            metas.append(AdapterMeta(
                id=e["id"],
                provider=e.get("provider", "sherpa-onnx"),
                vendor=e.get("vendor", "local"),
                name=e.get("name", e["id"]),
                source=e.get("source", "local"),
                modes=e.get("modes", ["streaming"] if e.get("streaming") else ["batch"]),
                langs=e.get("langs", []),
                config_type=e.get("config_type", ""),
                download_url=e.get("download_url", ""),
                model=e.get("model", ""),
                tag=e.get("tag", "int8"),
                base=e.get("base", ""),
                sha256=e.get("sha256", ""),
            ))
        except Exception:
            pass
    if metas:
        register_models(metas)

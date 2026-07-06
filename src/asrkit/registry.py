"""注册中心：两层——协议 adapter（按 provider）+ 模型表（按 id）。

    provider ──▶ 一个协议 adapter 类（sherpa-onnx / openai / deepgram …）
    model id ──▶ 一条 AdapterMeta（含 provider、config_type、model 等）
    make_adapter(id) = 用 meta.provider 找到协议类，实例化到该模型。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from .types import AdapterMeta, BaseAdapter

_PROTOCOLS: Dict[str, Type[BaseAdapter]] = {}   # provider -> 协议 adapter 类
_MODELS: Dict[str, AdapterMeta] = {}            # model id -> meta


def register_protocol(provider: str):
    def deco(cls: Type[BaseAdapter]) -> Type[BaseAdapter]:
        _PROTOCOLS[provider] = cls
        return cls
    return deco


def register_model(meta: AdapterMeta) -> None:
    _MODELS[meta.id] = meta


def register_models(metas: List[AdapterMeta]) -> None:
    for m in metas:
        _MODELS[m.id] = m


def make_adapter(model_id: str, config: Optional[dict] = None) -> BaseAdapter:
    load_builtin()
    if model_id not in _MODELS:
        raise KeyError(f"未注册的模型 '{model_id}'。用 `asrkit list` 查看全部。")
    meta = _MODELS[model_id]
    cls = _PROTOCOLS.get(meta.provider)
    if cls is None:
        raise KeyError(f"模型 '{model_id}' 的协议 '{meta.provider}' 没有对应 adapter。")
    return cls(meta, config or {})


def list_metas() -> List[AdapterMeta]:
    load_builtin()
    return list(_MODELS.values())


_loaded = False


def load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    # 导入即注册：协议 + 模型表
    from .adapters import cloud_openai, local_sherpa, models_local  # noqa: F401
    _loaded = True

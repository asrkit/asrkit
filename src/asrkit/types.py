"""ASRKit 契约 v1 的数据结构与基类。见 docs/adapter-spec.md。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, List, Optional, cast


@dataclass
class AudioInput:
    """仅用于 batch。内核零处理：只持有原始文件路径。
    云端 adapter 原样上传 original_path；本地 adapter 按需解码（见 audio.load_samples）。"""
    original_path: str                 # 原始音频文件（未改动）
    samples: Any = None                # 解码后的 float32（本地 adapter 填）；内核不填
    sample_rate: int = 0               # samples 的采样率
    duration_s: Optional[float] = None


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscribeResult:
    text: str                                      # 最终文本（唯一必填）
    segments: Optional[List[Segment]] = None
    word_timestamps: Optional[List[dict[str, Any]]] = None  # [{word, start, end, conf?}]
    lang: Optional[str] = None
    latency_ms: Optional[int] = None
    cost_estimate: Optional[float] = None
    metrics: Optional[dict[str, Any]] = None       # {load_ms, decode_ms, rtf, rss_peak_mb, ...}
    warnings: Optional[List[str]] = None           # 非致命提示（如长音频超窗只处理前 Ns）；CLI 应打印
    raw_response: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class TranscribeOptions:
    lang_hint: Optional[str] = None
    enable_punctuation: bool = True
    enable_itn: bool = True
    word_timestamps: bool = False
    convert: bool = False              # opt-in：自动解码/重采样/混单声道适配本地引擎；默认关（不符则报错）
    segment: bool = False             # opt-in：长音频 VAD 分段拼接；默认关（超窗仅警告）


@dataclass
class PartialResult:
    text: str                       # 权威展示文本，消费者一律以此为准
    committed: str = ""             # 可选优化：已定稿部分（端侧/火山留空）
    partial: str = ""              # 可选优化：当前假设
    is_final: bool = False
    ts_ms: Optional[int] = None
    error: Optional[str] = None


@dataclass
class AdapterMeta:
    id: str                         # 全局唯一的不透明字符串
    provider: str                   # 协议/适配实现
    vendor: str                     # 账号/密钥归属（密钥按 vendor 共享）
    name: str
    source: str                     # "cloud" | "local"
    modes: List[str]                # ["batch"] / ["streaming"] / 两者
    langs: List[str]
    model_kind: str = "asr"         # "asr" | "audio_llm"
    capabilities: dict[str, Any] = field(default_factory=dict)
    pricing: Optional[dict[str, Any]] = None
    license: Optional[str] = None
    maturity: str = "stable"        # "stable" | "experimental"
    config_schema: dict[str, Any] = field(default_factory=dict)
    # 云端
    default_base_url: str = ""
    model: str = ""
    resource_id: str = ""
    # 本地
    config_type: str = ""
    download_url: str = ""          # 完整 tarball 地址
    install_files: List[str] = field(default_factory=list)
    sha256: str = ""                # tarball 校验和；pull 后校验（空则跳过）
    tag: str = ""                   # 精度标签（int8/fp32），Ollama 式
    base: str = ""                  # 逻辑模型名（多精度共享，寻址用 base:tag）
    cache_owner: str = "unknown"    # "asrkit" | "engine" | "none" | "unknown"


@dataclass(frozen=True)
class ModelCacheState:
    """模型权重缓存状态；与引擎是否可运行（is_installed）相互独立。"""

    owner: str
    cached: Optional[bool]
    removable: bool
    location: Optional[str]
    size_bytes: Optional[int]


class BaseAdapter:
    """所有 adapter 的基类。一个 adapter 处理一种协议，按 meta 参数化到具体模型。

    至少实现 transcribe；流式可选。
    """

    def __init__(self, meta: AdapterMeta, config: Optional[dict[str, Any]] = None):
        self.meta: AdapterMeta = meta
        self.config: dict[str, Any] = config or {}

    def is_configured(self) -> bool:
        return True

    def is_installed(self) -> bool:
        """本地引擎覆盖：模型/引擎是否就绪。云端/自管理默认 True。"""
        return True

    def supports_concurrent_calls(self) -> bool:
        """同一实例是否允许并行调用；有状态本地引擎默认串行。"""
        return False

    def close(self) -> None:
        """释放 adapter 持有的运行时资源；无资源的 adapter 默认无需处理。"""

    def _effective_cache_owner(self) -> str:
        if self.meta.source == "cloud":
            return "none"
        if self.meta.cache_owner in {"asrkit", "engine", "none", "unknown"}:
            return self.meta.cache_owner
        return "unknown"

    def _managed_cache_config(self) -> dict[str, Any]:
        """缓存管理只认受管根目录，不能把运行时 model_dir 当成删除目标。"""
        config = dict(self.config)
        config.pop("model_dir", None)
        return config

    def cache_state(self) -> ModelCacheState:
        """返回权重缓存事实，不用运行时就绪状态猜测外部引擎缓存。"""
        owner = self._effective_cache_owner()
        if owner == "asrkit":
            from . import store

            config = self._managed_cache_config()
            cached = store.is_installed(self.meta, config)
            return ModelCacheState(
                owner=owner,
                cached=cached,
                removable=True,
                location=store.model_dir(self.meta, config),
                size_bytes=store.dir_size(self.meta, config),
            )
        if owner == "none":
            return ModelCacheState(owner, False, False, None, None)
        return ModelCacheState(owner, None, False, None, None)

    def remove_cached_model(self) -> Optional[str]:
        """只删除 ASRKit 明确拥有的缓存；外部或未知缓存一律拒绝。"""
        owner = self._effective_cache_owner()
        if owner == "asrkit":
            from . import store

            return cast(Optional[str], store.remove(self.meta, self._managed_cache_config()))
        if owner == "engine":
            raise ValueError(
                f"{self.meta.id} cache is managed by its engine; ASRKit will not remove "
                "shared engine caches. Use the engine's cache tools instead."
            )
        if owner == "none":
            raise ValueError(f"{self.meta.id} has no local model cache to remove")
        raise ValueError(
            f"{self.meta.id} cache ownership is unknown; ASRKit will not remove it"
        )

    def install(
        self,
        log: Callable[[str], Any] = print,
        url: Optional[str] = None,
    ) -> str:
        """本地引擎覆盖：下载/安装模型或引擎，返回位置。url 可覆盖默认下载地址（仅 sherpa 用）。默认无需安装。"""
        raise ValueError(f"{self.meta.id} needs no install")

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        raise NotImplementedError

    def transcribe_stream(
        self, chunks: Iterable[Any], opts: TranscribeOptions
    ) -> Iterator[PartialResult]:
        raise NotImplementedError("this adapter does not support streaming")

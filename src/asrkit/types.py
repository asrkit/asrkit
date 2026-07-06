"""ASRKit 契约 v1 的数据结构与基类。见 docs/adapter-spec.md。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, List, Optional


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
    word_timestamps: Optional[List[dict]] = None   # [{word, start, end, conf?}]
    lang: Optional[str] = None
    latency_ms: Optional[int] = None
    cost_estimate: Optional[float] = None
    metrics: Optional[dict] = None                 # {load_ms, decode_ms, rtf, rss_peak_mb, ...}
    warnings: Optional[List[str]] = None           # 非致命提示（如长音频超窗只处理前 Ns）；CLI 应打印
    raw_response: Optional[dict] = None
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
    capabilities: dict = field(default_factory=dict)
    pricing: Optional[dict] = None
    license: Optional[str] = None
    maturity: str = "stable"        # "stable" | "experimental"
    config_schema: dict = field(default_factory=dict)
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


class BaseAdapter:
    """所有 adapter 的基类。一个 adapter 处理一种协议，按 meta 参数化到具体模型。

    至少实现 transcribe；流式可选。
    """

    def __init__(self, meta: AdapterMeta, config: Optional[dict] = None):
        self.meta: AdapterMeta = meta
        self.config: dict = config or {}

    def is_configured(self) -> bool:
        return True

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        raise NotImplementedError

    def transcribe_stream(
        self, chunks: Iterable[Any], opts: TranscribeOptions
    ) -> Iterator[PartialResult]:
        raise NotImplementedError("此 adapter 不支持流式")

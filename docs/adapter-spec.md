# ASRKit Adapter 契约 v1（草案 / DRAFT）

> 状态：**已过独立评审、吸收全部修改，待冻结**。冻结后遵循"字段只增不改"原则（见 §10）。
> 本契约不是凭空设计，而是从两套已跑通的实现中提炼：
> - `asr_bench/desktop_bench`（Python，47 端侧模型真机跑通）
> - `asr_bench`（Flutter/Dart，端侧 32 + 云端 21，含 6 家流式协议）
>
> 契约是 ASRKit 的"宪法"。任何人照本文写一个 adapter，即可接入 ASRKit 的全部能力
> （bench 横评 / CLI / SDK / OpenAI 兼容网关）。

---

## 0. 设计原则（每条都有代码依据）

1. **平台归一化音频，adapter 只管识别。** 平台把任意输入统一转成 `16kHz 单声道 float32 [-1,1]` 再交给 adapter。*依据：`worker.py:load_wav`；Dart 侧同样喂 16k 单声道。*
2. **能力声明消化端云不齐。** adapter 通过 `meta.capabilities` 声明自己能干什么，引擎据此路由与降级。
3. **进程隔离是硬要求（本地 adapter）。** 本地推理必须能在子进程/isolate 中运行。*依据：`worker.py` 每模型一个子进程；Dart `Isolate.run`。*
4. **字段宁少勿多。** 加字段容易、改字段是灾难。可选能力走可选字段。
5. **原始响应可复核。** 结果保留 `raw_response`。

---

## 1. 统一数据结构

```python
# 【仅用于 batch】平台已归一化。流式不走 AudioInput，走 §5 的 chunks。
@dataclass
class AudioInput:
    samples: np.ndarray                  # float32 [-1,1], 16kHz mono（平台保证已填充）
    path: str                            # 已归一化的 16k 单声道 WAV 文件路径（平台保证已生成）
    sample_rate: int = 16000
    duration_s: float | None = None
# 约定：本地 adapter 用 samples；云端批量 adapter 用 path（上传文件/base64）。各取所需。


@dataclass
class Segment:
    start: float; end: float; text: str


@dataclass
class TranscribeResult:
    text: str                                   # 最终文本（唯一必填）
    segments: list[Segment] | None = None
    word_timestamps: list[dict] | None = None   # [{word, start, end, conf?}]，conf 可选
    lang: str | None = None                     # 识别出的语言（SenseVoice/Whisper 会给）
    latency_ms: int | None = None               # 端到端耗时（平台侧兜底）
    cost_estimate: float | None = None
    metrics: dict | None = None                 # 细分指标：{load_ms, decode_ms, rtf, rss_peak_mb, ...}
    raw_response: dict | None = None
    error: str | None = None                    # 失败时填；成功为 None
```

> **改动依据评审 🟡#5**：`load_ms/decode_ms/rtf/rss_peak_mb` 在 `worker.py`、`AsrResult` 里都是一等结构化结果，故提升为可选 `metrics` 字典，而非埋进 `raw_response`。

---

## 2. BaseAdapter 契约

```python
class BaseAdapter:
    meta: AdapterMeta                            # 见 §3，静态可读

    def __init__(self, config: dict): ...        # config 来自 config_schema

    # —— 批量（必须实现）——
    def transcribe(self, audio: AudioInput, opts: "TranscribeOptions") -> TranscribeResult: ...

    # —— 流式（可选）——
    def transcribe_stream(
        self, chunks: Iterable[np.ndarray], opts: "TranscribeOptions"
    ) -> Iterator["PartialResult"]: ...          # 收 chunks（不是 AudioInput），yield 中间/最终结果
```

```python
@dataclass
class TranscribeOptions:
    lang_hint: str | None = None          # 语言提示（whisper 准必需，见 §3 capabilities）
    enable_punctuation: bool = True
    enable_itn: bool = True
    word_timestamps: bool = False
    # 冻结后新增开关一律给默认值，保证旧 adapter 不破
```

---

## 3. 能力声明 AdapterMeta（项目的护照）

```python
@dataclass
class AdapterMeta:
    id: str                       # 全局唯一的【不透明字符串】。推荐 "provider-model" 风格便于阅读，但引擎不解析它
    provider: str                 # 协议/适配实现，如 "doubao" / "openai" / "dashscope-rt"
    vendor: str                   # 账号/密钥归属，如 "doubao" / "openai" / "dashscope"（密钥按 vendor 共享）
    name: str                     # 显示名
    source: str                   # "cloud" | "local"
    modes: list[str]              # ["batch"] / ["streaming"] / ["batch","streaming"]
    langs: list[str]              # ["zh","en","yue",...]
    model_kind: str = "asr"       # "asr"（纯转写）| "audio_llm"（理解型，可能夹带解释；bench 需特殊处理）

    capabilities: dict = field(default_factory=dict)
    # 例：{"punctuation": True, "itn": True, "word_timestamps": False,
    #      "language_hint": "required"|"supported"|"none", "diarization": False}

    pricing: dict | None = None   # {"unit":"hour","cny":4.5}
    license: str | None = None    # 模型许可证（本地模型必填，非商用需显著标注）
    maturity: str = "stable"      # "stable" | "experimental"（best-effort 接入标 experimental）

    config_schema: dict = field(default_factory=dict)   # 见 §4

    # —— 云端专用 ——
    default_base_url: str = ""
    model: str = ""               # 厂商侧真实 model 名（如 "bigmodel" / "qwen3-asr-flash"）
    resource_id: str = ""         # 厂商特有区分位（火山同名 model 靠它区分 1.0/2.0/流式）

    # —— 本地专用（pull 契约，见 §6）——
    config_type: str = ""         # 引擎架构：whisper/paraformer/senseVoice/transducer/qwen3Asr/...
    download_url: str = ""
    install_files: list[str] = field(default_factory=list)  # 支持精确名或 glob，见 §6
```

> **改动依据评审 🔴#4 / 🟡#9**：`id` 不再是可解析的二段式，改为不透明唯一串；`provider`（协议）、`vendor`（账号）、`model`（厂商 model 名）、`resource_id` 各自独立——因为火山同一 `bigmodel` 有三条目、DashScope 一个账号挂多协议，二段式 id 表达不了。原 `default_model_id` 并入 `model`。
> **改动依据评审 🔴#3**：新增 `model_kind` 区分纯 ASR 与"理解音频的大模型"（Qwen-Omni 会夹带解释文字，bench 直接算 CER 会误伤）。
> **改动依据评审 🟡#7**：`language_hint` 从布尔改为三态 `required/supported/none`——whisper 无提示会默认英文、喂中文出幻觉，实为准必需。

---

## 4. config_schema：密钥与自动表单

平台按 `config_schema` 自动渲染配置表单；**密钥只存本地/自部署环境，永不上传**。

```python
config_schema = {
    "api_key":    {"type": "secret", "required": False, "label": "API Key"},
    "app_key":    {"type": "secret", "required": False, "label": "App ID"},
    "access_key": {"type": "secret", "required": False, "label": "Access Key"},
    "base_url":   {"type": "string", "required": False, "label": "Base URL 覆盖"},
}
```

**关键约定（来自 `cloud_config.dart`）**：
- **密钥按 `vendor` 共享，不按 model。** 同厂商多模型共用一套 Key。
- **多密钥厂商**：火山支持"单 `api_key`"或"`app_key`+`access_key`"二选一——用 `required: False` 表达，可用性判断交给 adapter 的 `is_configured()`。

---

## 5. 流式统一状态模型

各家流式协议消息模型互不相同。ASRKit 的**唯一权威输出是 `text`**；`committed/partial` 是给"支持增量定稿"的家用的可选优化。

```python
@dataclass
class PartialResult:
    text: str                # 【权威】展示文本，消费者一律以此为准（唯一必读）
    committed: str = ""      # 可选优化：已定稿部分。端侧流式/火山只吐累计全文，此处留空
    partial: str = ""       # 可选优化：当前假设
    is_final: bool = False
    ts_ms: int | None = None
    error: str | None = None # 流式错误（握手失败/服务端 error 帧），不 raise
```

**各家如何映射**（全部已在源码验证）：

| 来源 | 原始信号 | 映射 |
|---|---|---|
| Deepgram / DashScope | `is_final` / `sentence_end` 布尔 | final → committed；否则 partial |
| OpenAI Realtime | `...transcription.delta` 增量 | partial += delta；completed → committed |
| ElevenLabs | partial / committed 两类消息 | 直接对应两段 |
| **火山豆包** | 二进制帧、text 为**累计全文** | **只填 text（全量覆盖），committed/partial 留空** |
| **端侧流式（zipformer 等）** | 解码器吐**累计全文** | **只填 text，committed/partial 留空** |

生命周期：`connect → feed×N → finish → dispose`（Dart `CloudStreamer`），Python 封装为生成器。平台负责 VAD/心跳/重连/超时收尾；厂商内部细节（OpenAI 24k 重采样、火山 gzip 二进制帧）是 adapter 私事。

> **改动依据评审 🔴#2 / 🟡#6**：明确 `text` 为唯一权威、`committed/partial` 为可选（端侧和火山根本不产出定稿分段）；`PartialResult` 增 `error` 通道。

---

## 6. pull 契约（本地模型，Ollama 式即拉即用）

```python
download_url  = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/<file>.tar.bz2"
install_files = ["encoder.onnx", "decoder.onnx", "tokens.txt"]   # 精确名
# 或 glob / 目录（LLM 架构模型）：
install_files = ["*encoder*.onnx", "*decoder*.onnx", "<tokenizer_dir>/"]
```

- `asrkit pull <id>`：下载 → 解压 →（可选）重命名为规范名。
- **安装检测可插拔**：默认"`install_files` 全部命中（支持 glob/目录）即已安装"；LLM 架构模型（`qwen3Asr`/`funasrNano`/`moonshineV2`/`omnilingualCtc`/`fireRedAed`——用 HF tokenizer 目录 + 通配文件名）可**重写 `is_installed()`**。

> **改动依据评审 🔴#1**：原"固定 canonical_files + 全存在"表达不了你 registry 里 5 个用 glob+tokenizer 目录的模型（`worker.py:_find`/`_find_tokenizer_dir`）——你自有模型集已违反旧写法。故 `canonical_files`→`install_files`（支持 glob/目录），`is_installed` 改为可插拔、重命名可关闭。

---

## 7. 注册与发现

- **目录发现**：`adapters/` 下模块启动时自动扫描。
- **entry point**：第三方包通过 `[project.entry-points."asrkit.adapters"]` 声明，`pip install` 即接入。
- **pip extras**：`asrkit` / `asrkit[cloud]` / `asrkit[local]` / `asrkit[all]`。

---

## 8. 错误处理约定

- adapter **不抛异常给用户**；捕获后填 `error`（`"类型: 信息"`），`text=""`。*依据：worker/CloudResult/AsrResult 全是此模式。*
- 流式握手失败：`connect` 返回 False 并置错误；流式过程错误走 `PartialResult.error`。
- HTTP ≥300 视为错误，`error` 带截断响应体（≤200 字符）。

---

## 9. 平台职责 vs Adapter 职责

| 职责 | 平台/引擎 | Adapter |
|---|---|---|
| 音频解码/重采样到 16k 单声道 | ✅ | ❌ |
| 端到端计时兜底 | ✅ | 可补 metrics |
| 本地推理进程隔离 | ✅（提供 runner） | 实现同步 transcribe |
| 重试/超时/密钥轮换 | ✅（阶段 4） | ❌ |
| VAD/心跳/重连 | ✅ | ❌ |
| 厂商协议细节（鉴权/帧格式/内部重采样） | ❌ | ✅ |
| 能力声明 | ❌ | ✅ |

---

## 10. 版本与冻结策略

- 冻结为 **契约 v1** 后：字段**只增不改、不删**；新增可选能力必须带默认值。
- 破坏性变更 → 契约 v2 + 迁移工具。
- 预留 `spec_version` 字段，v1 隐含。

---

## 附：v1 已定决策（经独立评审确认/修正）

1. 流式 API → 生成器 `Iterator[PartialResult]`；`text` 为唯一权威输出。
2. `vendor` → `meta` 一等字段，密钥按 vendor 聚合。
3. `word_timestamps` → `[{word, start, end, conf?}]`，conf 可选。
4. `maturity="experimental"` → bench 照常展示、显著标注、不人为降权；另用 `model_kind` 表达"纯 ASR / 音频 LLM"。
5. `AudioInput` → 仅 batch，samples/path 双备；流式走 chunks。
6. `id` → 不透明唯一串；provider/vendor/model/resource_id 各自独立字段。

> 评审总判：**改完可冻结**。以上修改已全部吸收。

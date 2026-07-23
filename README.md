<p align="right"><b>简体中文</b> | <a href="README.en.md">English</a></p>

# ASRKit

**语音识别的统一接口 —— 端侧到云端,换一个 model 字符串,代码不动。**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit 之于语音识别,相当于 **Ollama + LiteLLM** 之于大模型:模型即拉即用、端云同一寻址、可选 OpenAI 兼容的本地服务。**内核只是一层薄接口** —— 基础安装仅依赖 `requests`,引擎按需装、模型按需下,不为用不到的东西背 torch。

它把一组少见的能力放进同一接口:中文 SOTA 端侧模型(SenseVoice / Paraformer / FireRed / TeleSpeech,47 个模型即拉即用)+ 国内主要云厂(百炼 / 豆包 / 硅基流动)+ Whisper 全家 + HuggingFace ASR 开放寻址 —— 一套接口横评、混用、随时切换。

> ⚠️ **早期 Beta,开发中。** 核心接口已可用,仍在积极迭代 —— 小版本间寻址/接口可能微调。欢迎试用与反馈。

> **当前发行边界:**PyPI 0.5.5 已包含完整 CLI/Python API、`serve` 和 cloud-only daemon Python 模块。自包含 `asrkit-cloud` 二进制与 npm 平台包**尚未正式发布**；不要把仓库内的冻结构建原型当成公开发行物。当前状态见[路线图](docs/roadmap.md)。

## 安装 —— 按用法选,不必只有 pip

基础安装只依赖 `requests`(云端内置),引擎/模型/`serve` 全按需加。所以**只用云端时几乎零负担**——挑一条适合你的:

| 你的情况 | 装法 |
|---|---|
| **只用云端,想零环境负担** | `uv tool install asrkit` —— `uv` 本身是一行装的单二进制,装完 `asrkit` 直接进 PATH,不用管 Python 环境 |
| **连装都想省(临时跑一次)** | `uvx asrkit transcribe audio.wav -m siliconflow/sensevoice --api-key <KEY>` —— 无需预装 ASRKit,uv 按需创建临时环境(可能保留下载缓存) |
| **常规 Python 用户** | `pip install asrkit` |
| **要全局命令、又不污染当前环境** | `pipx install asrkit` |
| **要用端侧引擎(sherpa,47 模型)** | 装好 asrkit 后 `asrkit engine install sherpa-onnx`(装到你的 Python 环境;免和 shell 引号较劲) |

> `uv` 装法:`curl -LsSf https://astral.sh/uv/install.sh | sh`(macOS/Linux 一行,单二进制;使用 ASRKit 时无需手工管理 Python 环境)。
> 装完 `asrkit doctor` 一条命令体检(引擎/密钥/目录/配置;`--net` 加联网检查)。

## 30 秒上手

```bash
asrkit transcribe audio.wav -m siliconflow/sensevoice --api-key <KEY>   # 云端示例,需供应商账号/API key;价格以供应商为准
asrkit run sherpa/sensevoice audio.wav                     # 端侧:首次自动下模型,然后识别(需先 asrkit engine install sherpa-onnx)
```

## 变的只有 model 字符串

引擎、模型、端侧还是云端,都是同一个调用:

```bash
asrkit run sherpa/sensevoice                      audio.wav              # sherpa-onnx(端侧)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper 引擎
asrkit run whispercpp/base                       audio.wav              # whisper.cpp 引擎
asrkit run transformers/openai/whisper-large-v3  audio.wav              # 任意 HuggingFace 模型
asrkit run dashscope/qwen3-asr-flash             audio.wav --api-key …  # 云端,密钥自带
```

端侧 `sherpa/sensevoice` 与云端 `siliconflow/sensevoice` 是**同一个调用** —— 端云横评,就是换字符串。

> 注:sherpa 模型的规范前缀是 `sherpa/`;旧的 `local/` 前缀作为历史别名永久保留、仍可解析(如 `local/sensevoice` 等价 `sherpa/sensevoice`),存量脚本不受影响。

```python
from asrkit import transcribe
print(transcribe("sherpa/sensevoice", "audio.wav").text)
```

## 为什么用 ASRKit

- **中文/多语优先的端云组合。** 47 个 sherpa 端侧模型 + 5 家云厂商开箱即用;国内云与中文端侧模型是一等公民,不是补丁。
- **接口即内核,一切可插拔。** base 只装接口 + 云端(仅 `requests`);引擎、模型、服务全按需加。没装的引擎给**带安装命令的友好报错**,不是 `ImportError`。
- **一次学会,三种用法。** CLI、Python 库、HTTP(OpenAI 兼容 serve)—— 同一套 model 寻址。
- **兼容性有真实客户端门禁。** CI 使用官方 OpenAI Python/Node SDK 实际调用模型列表与 `json`/`text`/`verbose_json` 转写,不是只用手写 HTTP 自测。
- **透明,不越界。** 默认**不改动你的音频、不改变模型原生行为**;格式不符**诚实报错**,绝不静默出乱码;不支持的选项给 warning 而非静默丢弃。转换/分段都是 opt-in。
- **数据边界清楚。** ASRKit 自身不托管或收集音频;本地模型不出机;选择云模型时,音频与必要鉴权信息会发送给所选供应商,并受其隐私条款约束。

## 批量与脚本化

一次处理多个文件、目录、glob 或 stdin,输出结构化表格 —— 端云横评、脚本消费都顺手:

```bash
asrkit transcribe *.wav        -m sherpa/sensevoice          -f csv          # 每行一条:file,model,text,latency_ms,rtf…
asrkit transcribe ./recordings -m dashscope/qwen3-asr-flash -f json --batch # 目录递归 → NDJSON
cat a.wav | asrkit transcribe  -  -m sherpa/sensevoice                       # stdin
```

- **NDJSON / csv / tsv** 批量输出(单文件仍是单个对象);契约见 [docs/result-contract.md](docs/result-contract.md)。
- **字幕 `srt/vtt`**:whisper 家族(faster-whisper / whispercpp / openai/whisper-1)带时间戳,可直接出字幕;其它模型**诚实报错**,绝不编造时间轴。
- **分级退出码** `0/1/2/3/4`(成功 / 意外 / 用法错 / 模型不存在 / 转写失败;批量任一失败即非零),脚本可判因。
- **云端批量自动重试**瞬时故障,成本安全:计费请求只在限流/连接失败时重试,绝不重复计费(`ASRKIT_HTTP_RETRIES` 可调)。

## 流式转写(最小可用)

对 sherpa online(streaming)模型逐块解码、边喂边出增量文本:

```bash
asrkit stream sherpa/stream-paraformer-zhen meeting.wav             # live 增量 → stderr,最终文本 → stdout
asrkit stream sherpa/stream-paraformer-zhen meeting.wav > out.txt   # 管道友好:只截获最终文本
asrkit stream sherpa/stream-paraformer-zhen --mic                  # 麦克风实时转写,Ctrl-C 停止(需 asrkit[mic])
```

仅 `modes` 含 `streaming` 的模型可用(批处理模型给清晰报错)。`serve` 也支持流式:见下方"当服务跑"一节。

## 发现与体检

```bash
asrkit search whisper        # 按 id/name 搜索模型
asrkit list --lang ja        # 按语言筛选(广多语模型作候选返回)
asrkit doctor                # 体检:引擎装没装 / 密钥配没配(只报有无) / 目录可写否 / config 完整否
asrkit doctor --net          # 加下载源 / 云端可达检查
asrkit completion zsh        # bash/zsh/fish 补全脚本(动态补全模型名)
```

`run`/`transcribe`/`stream`/`serve` 均支持 `-v`(INFO)/`-vv`(DEBUG)提高日志详细度;默认静默,不影响脚本消费的 stdout。

## 可插拔:内核极小,引擎/服务按需装

**基础安装只有接口 + 云端(仅依赖 `requests`,秒装、随处可跑)。** 其余能力按需加(extra 对应下表):

| 想要 | 装什么 |
|---|---|
| 云端 + CLI + `serve` 调用方 | `pip install asrkit` |
| 端侧默认引擎(sherpa,47 模型) | `asrkit engine install sherpa-onnx` |
| 其它引擎 | `asrkit engine install faster-whisper` / `whispercpp` / `transformers` |
| 本地服务 | extra `asrkit[serve]` |
| 麦克风流式输入 | extra `asrkit[mic]` |
| 全都要 | extra `asrkit[all]` |

> 引擎优先用 `asrkit engine install <名>`(替你跑对 `pip install`,且免引号)。直接用 pip 装 extra 时,zsh 里 `asrkit[serve]` 这类要加引号:`pip install 'asrkit[serve]'`。

> **所有权模型:** 引擎是**共享 pip 包** —— `asrkit engine install <名>` 帮你装到对的环境,卸载用你自己的 `pip uninstall`(共享包,你的环境你做主)。只有 `cache_owner=asrkit` 的受管模型由 `pull`/`rm` 对称管理；外部引擎共享缓存和未知所有权缓存均拒绝删除。`asrkit list --json` 的 `cached`、`cache_owner`、`removable` 是缓存事实，不能从 legacy `installed` 字段推断。

## 命令

| 命令 | 作用 |
|---|---|
| `asrkit list` | 列出所有模型(✓ = adapter 定义的 legacy 就绪信号，不等同于已缓存);`--lang/--arch` 筛选、`--ids` 出裸 id |
| `asrkit search <词>` | 按 id/name 搜索模型 |
| `asrkit run <模型> <音频>` | adapter 未就绪时先准备（ASRKit 受管下载或委托外部引擎），再识别 |
| `asrkit transcribe <音频…> -m <模型>` | 只识别(不自动下载);多文件/目录/glob/`-`(stdin)、`--batch`;`--format txt/json/srt/vtt/csv/tsv`、`-o`、`--language` |
| `asrkit stream <模型> <音频>` | 流式转写(sherpa online 模型) |
| `asrkit pull <模型> [--url …]` / `rm <模型>` | 通过 adapter 获取模型 / 仅删除 ASRKit 明确拥有的缓存（`--url` 仅用于 ASRKit 受管下载） |
| `asrkit show <模型>` | 模型详情 |
| `asrkit engine list` / `install <名>` / `default <名>` / `rm <名>` | 管理引擎(`rm` 为劝告版:打印卸载指引,绝不代跑 `pip uninstall`) |
| `asrkit config set-key <厂商> <KEY>` / `list` | 存密钥 / 默认引擎 / models 目录 |
| `asrkit doctor [--net]` | 体检安装与配置 |
| `asrkit serve` | 起 OpenAI 兼容的本地转写服务 |
| `asrkit completion <shell>` | bash/zsh/fish 补全脚本 |
| `asrkit add-model …` | 注册自定义 sherpa 模型 |

## 引擎 × 模型

| 引擎 | 安装 | 寻址 | 覆盖 |
|---|---|---|---|
| **sherpa-onnx**(默认端侧) | `asrkit[sherpa]` | `sherpa/<模型>` 或裸名 `<模型>` | 47 端侧模型,16 个已登记 `config_type` |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<模型>` | 快速 Whisper,自带长音频分块 |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<模型>` | 超轻量 Whisper(无 torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<任意 HF id>` | 整个 HuggingFace ASR 生态 + LLM 架构 SOTA |
| **云端** | 内置 | `<厂商>/<模型>` | 见下表,密钥自带 |

### 云端厂商(内置,只需密钥)

| 厂商 | 寻址 | 密钥 |
|---|---|---|
| 硅基流动 | `siliconflow/sensevoice`、`siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| 阿里云百炼 | `dashscope/qwen3-asr-flash`、`dashscope/fun-asr-flash`、`dashscope/qwen-omni-plus`、`dashscope/qwen-omni-flash` | `--api-key` |
| 火山引擎 / 豆包 | `doubao/auc-2`(2.0 Seed)、`doubao/auc-1`(1.0) | `--api-key` 或 `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

密钥三种给法(优先级从高到低):`--api-key` > 环境变量 `<厂商>_API_KEY`(火山双密钥用 `DOUBAO_APP_KEY`/`DOUBAO_ACCESS_KEY`)> `asrkit config set-key <厂商> <KEY>` 存一次。

## 当服务跑:OpenAI 兼容子集

`asrkit serve` 起一个本地服务。使用 ASRKit 已兼容字段的 OpenAI SDK 应用(或 Agent、任意语言客户端)改 `base_url` 后,即可通过统一端点调用注册表中的端云模型。**调用方零 asrkit 依赖,只发 HTTP。**完整兼容边界见 [文档](docs/openai-compatibility.md)。

> **安全边界:**当前服务仅面向受信任的本机集成，普通 CLI 仍无内置鉴权，但已有 200 MiB 上传、4 并发、300 秒超时默认边界，并拒绝浏览器 `Origin` 转写请求。不要把它直接暴露到公网或不受信任网络；如需反向代理，必须在外层加鉴权和精确访问控制。

```bash
pip install 'asrkit[serve]'
asrkit config set-key dashscope <KEY>     # 密钥存一次(可选,云端才需)
asrkit serve                              # 默认 127.0.0.1:11435,仅本机
```
```python
from openai import OpenAI
c = OpenAI(base_url="http://localhost:11435/v1", api_key="unused")
c.audio.transcriptions.create(model="sherpa/sensevoice", file=open("a.wav", "rb"))
```
- SDK 契约:CI 持续用官方 OpenAI Python/Node SDK 验证模型列表和 `json`/`text`/`verbose_json`;`verbose_json` 使用 SDK 读取的 `language` 字段。这里只承诺[明确兼容子集](docs/openai-compatibility.md),不宣称完整复刻 OpenAI Audio/Realtime API。
- 端点:`POST /v1/audio/transcriptions`(`response_format` 支持 json/verbose_json/text/srt/vtt)、`GET /v1/models`、`GET /health`。
- 流式:同一端点加 `stream=true` → `text/event-stream`,OpenAI 兼容 `transcript.text.delta`(增量)/ `transcript.text.done`(定稿)事件;断连自动清理临时文件。仅 streaming 模型支持,非流式模型请求 `stream=true` 会报错。
- 运行边界:普通 `asrkit serve` 默认单次上传 200 MiB、最多 4 个活动转写、300 秒超时;adapter 缓存是 app-scoped、同模型 single-flight，活跃请求 pin 住实例，淘汰/关停调用 `close()`。
- 浏览器防护:转写 POST 默认拒绝非空 `Origin`，避免恶意网页通过 loopback 触发本地推理或云端计费;确需浏览器访问时应使用带鉴权和精确 CORS allowlist 的前置网关。
- 云端密钥可从权限为 0600 的**明文配置文件**读取,无需每次传;不希望落盘时应使用环境变量。透明原则:原始字节上传,不解码。

## 嵌入式 cloud daemon 与分发状态

0.5.5 Python 包内的 `python -m asrkit.daemon` 是未来 `asrkit-cloud` Sidecar 的 cloud-only 入口:进程只注册 10 个内置云模型,支持 embedded 随机端口、ready/shutdown NDJSON、父进程监控、Bearer token、私有 data dir 和资源上限。它用于宿主集成和冻结产物验证,详细契约见[嵌入与分发](docs/embedding-and-distribution.md)。

当前仓库已有 macOS arm64 与 Linux x64 冻结构建证据,并提供仅手动触发、绑定受保护 environment 的两家真实云厂 E2E；缺少凭据或识别失败会直接使任务失败,不会 skip 假绿。但完整 wheel **不会**安装 `asrkit-cloud` 顶层命令,GitHub Release 也尚无正式自包含二进制,npm `asrkit`/平台包仍是下一阶段交付。

## 扩展

**加任意 sherpa 模型** —— 一条命令或往 `~/.asrkit/models.json` 写一条:

```bash
asrkit add-model sherpa/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
```

**加一个引擎** —— 发一个小包、声明 `asrkit.adapters` entry point,`pip install` 即自动注册。不改源码、不改核心。食谱见 [docs/engines-and-addressing.md](docs/engines-and-addressing.md#engine-plugin-recipe)。

## 设计原则与边界

ASRKit 刻意保持克制 —— "不做什么"和"做什么"同样重要:

- **不碰你的音频。** 内核零处理,原样交给模型/云端;解码/重采样/分段全部 opt-in(`--convert`/`--segment`)。
- **不吞专业生态。** 说话人分离、强制对齐不进接口层 —— 用 `raw_response` 逃生舱或在上层组合。
- **不代卸引擎。** 引擎是共享 pip 包,帮装不代卸;你的环境你做主。
- **不假装支持。** 模型不返回时间戳就不出字幕,选项不生效就给 warning —— 诚实报错优于静默出错。

## 文档

[使用说明](docs/usage.md) · [OpenAI 兼容边界](docs/openai-compatibility.md) · [Adapter 契约](docs/adapter-spec.md) · [结果契约](docs/result-contract.md) · [引擎与寻址](docs/engines-and-addressing.md) · [模型管理](docs/model-management.md) · [产品形态](docs/product-form.md) · [嵌入与分发](docs/embedding-and-distribution.md) · [路线图](docs/roadmap.md)

---

Apache-2.0。模型许可不由 ASRKit 授予;商用前请从模型或供应商官方页面核验。ASRKit 自身不托管音频;云模型会把音频与必要鉴权信息发送给所选供应商。

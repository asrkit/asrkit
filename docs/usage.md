# ASRKit 使用说明

> 现状（v0.x 内核）：端侧 47 个模型可一键下载即用（Ollama 式）；云端 OpenAI 兼容接口已接。
> 一个接口跑遍端云，换模型只换字符串。

## 核心概念：一个接口，两种用法

- **命令行（CLI）**：`asrkit ...`，随手下载、试模型、转写。
- **Python 代码**：`from asrkit import transcribe`，写进自己的程序。

## 安装

```bash
pipx install asrkit           # 当工具用（隔离/全局命令，推荐）；或 pip install asrkit（当库 import）
pip install "asrkit[local]"   # 端侧默认引擎（sherpa，47 模型）；base 不含引擎
pip install "asrkit[all]"     # 引擎全家桶 + serve
pip install -e .              # 开发模式（改代码即时生效）
```

**base 只有接口 + 云端**（仅依赖 `requests`，秒装、随处可跑）。本地引擎按需加 extra；模型权重用 `asrkit pull` 下载；云端填 API key。没装某引擎就用它 → 友好报错（带安装命令）。

---

## 一、命令行

### 模型放哪（端侧）

默认放 `~/.asrkit/models/`；想换位置：

```bash
export ASRKIT_MODELS_ROOT=/your/models
```

### 常用命令

```bash
asrkit list                          # 列出所有模型（✓ = 已安装）
asrkit pull local/sensevoice         # 下载一个端侧模型（Ollama 式）
asrkit run  local/sensevoice a.wav   # 缺则自动下载 + 转写（一步到位，推荐）
asrkit transcribe a.wav -m local/sensevoice   # 只转写（不自动下载）
asrkit transcribe a.wav -m local/whisper --format srt -o a.srt   # 出字幕
asrkit transcribe a.wav -m local/sensevoice --format json        # 全字段 JSON
```

- 换模型只换字符串：`local/whisper-small`、`local/paraformer-zh`、`local/qwen3-asr-0.6b` …
- **精度标签**（Ollama 式）：`local/sensevoice:int8`（默认）/ `local/sensevoice:fp32`。
- **输出格式** `--format txt|json|srt|vtt`（默认 txt）+ `-o <file>`；`--language zh` 给语言提示。
  字幕（srt/vtt）需模型返回时间戳，否则诚实报错。
- 默认输出：第一行为识别文字；stderr 第二行为 `耗时、语言、rtf`。
- 列表：`asrkit list --json`（脚本用）/ `--installed` / `--source cloud|local`。

### 发现模型

```bash
asrkit list --lang ja                 # 支持日语的模型（含多语言候选）
asrkit list --arch senseVoice         # 特定架构的模型（如 senseVoice、whisper）
asrkit search whisper                 # 按 id/name 子串搜索（返回 id、name 中含 whisper 的模型）
asrkit show local/whisper-tiny        # 显示模型详情（含 multilingual 标记）
```

**`--lang` 语义说明**：返回两类模型：
1. **显式支持该语言** —— 模型的 `langs` 列表明确含该语言代码（如 SenseVoice 的 `ja` 代码）。
2. **多语言候选** —— 标有 `capabilities.multilingual` 的广覆盖模型（whisper、dolphin、qwen3-asr、funasr-nano、omnilingual 等），它们被作为候选返回，但**实际覆盖因模型而异，请用 `asrkit show <model>` 验证语言支持清单**。

例如 `asrkit list --lang ja` 会同时返回 `local/sensevoice`（显式 ja）与 `local/whisper-tiny`（多语言模型作为候选），但 whisper-tiny 是否真的支持 ja 需自行确认。

例：

```
$ asrkit run local/whisper-tiny meeting.wav
下载 https://.../sherpa-onnx-whisper-tiny.tar.bz2
  ...110/110 MB
完成 → ~/.asrkit/models/whisper-tiny
So that just raises a point I wonder what our design people think.
  (387ms, lang=en, rtf=0.048)
```

### 批量输入：多文件 / glob / 目录 / stdin

`run`/`transcribe` 的位置参数支持多个，可混用普通文件、glob 通配符、目录（递归按扩展名收音频）、或 `-`（stdin）。一旦触发批量（多输入 / glob / 目录 / stdin / 显式 `--batch`），输出会切换为**聚合契约**（NDJSON / csv / tsv），字段与退出码规则见 `docs/result-contract.md`。

```bash
# glob：多个 wav 转写，csv 输出到 stdout
asrkit transcribe *.wav -m local/sensevoice -f csv

# 目录：递归收集音频文件，NDJSON 输出（每行一个 JSON 对象）
asrkit transcribe ./meetings -m local/sensevoice -f json --batch

# stdin：管道喂音频字节，--stdin-format 指定字节的实际格式（默认 wav）
cat a.wav | asrkit transcribe - -m local/sensevoice --stdin-format wav

# -o <dir>：逐文件镜像输出（每个输入对应一个同名结果文件，重名自动加 -1/-2 后缀）
asrkit transcribe ./meetings -m local/sensevoice -f txt -o ./out
```

- `--batch`：即使只给了一个文件，也强制走聚合输出（NDJSON/csv 稳定契约），给脚本/评测用。
- `--stdin-format`：`-` 输入落地临时文件时使用的扩展名（默认 `wav`），转写完自动清理临时文件。
- 批量字幕（`srt`/`vtt`）无法聚合到 stdout（多份字幕拼一起没有意义），必须配合 `-o <dir>`，否则报**用法错误**（退出码 2）。
- **argparse 限制**：位置输入（音频路径/glob/目录/`-`）必须**连续**给出，不能被 `-m`/`-f` 等选项打断——例如 `asrkit transcribe a.wav b.wav -m X` 可以，但 `asrkit transcribe a.wav -m X b.wav` 里 `nargs="+"` 只会吞到第一个非选项片段，`b.wav` 不会被当作音频输入。把所有音频路径放在一起、其它 flag 放前面或后面。
- **退出码**：`0` 成功 / `1` 意外异常 / `2` 用法错误 / `3` 模型不存在 / `4` 转写失败；批量取批次内最严重（优先级 `1 > 3 > 4`）。完整字段与列定义见 `docs/result-contract.md`。

### 自定义下载源 / 镜像

```bash
asrkit pull local/sensevoice --url https://your-mirror.example.com/sensevoice.tar.bz2
```

- `--url` 一次性覆盖该模型的默认下载地址，仅限 `http://`/`https://`；其它 scheme（如 `file://`）拒绝执行。
- 格式按**内容**（magic bytes）自动识别，支持 `.tar.{bz2,gz,xz}`、纯 `.tar`、`.zip`——不看 URL 扩展名，换源换后缀都不受影响。
- **HF 系引擎镜像**：`faster-whisper`/`transformers`/`whispercpp` 走的是 HuggingFace Hub 下载，不经 `asrkit pull`；设环境变量 `HF_ENDPOINT=https://hf-mirror.com` 即可让底层库（`huggingface_hub`）自动走镜像，asrkit 本身无需任何配置。

```bash
export HF_ENDPOINT=https://hf-mirror.com
asrkit engine install faster-whisper
```

### 卸载引擎（劝告版）：`asrkit engine rm`

引擎是共享的 pip 包，其它项目可能也在用，asrkit **不会代跑卸载**——`engine rm` 只打印手动卸载指引、依赖警告，并在默认引擎正指向它时重置默认引擎。

```bash
asrkit engine rm faster-whisper
# → asrkit does not uninstall engines — they are shared pip packages...
# → To remove 'faster-whisper' yourself, run:
# →     pip uninstall faster-whisper
```

### Diagnose: `asrkit doctor`

Run a health check on your ASRKit setup with no side effects:

```bash
asrkit doctor                 # offline: version / python / engines / keys / models-dir / config
asrkit doctor --net          # add network reachability checks (download source / cloud APIs)
```

**What it checks:**
- **asrkit version** — your installed version.
- **python** — Python version you're running.
- **engines** — which ASR engines are installed (e.g., `engine:sherpa-onnx`, `engine:faster-whisper`). Missing engines show as `info` (not an error) with an install hint.
- **keys** — whether API keys are configured for cloud vendors (e.g., `key:dashscope`, `key:doubao`). Shows presence only (vendor name + source: keystore/env), **never prints secret values**.
- **models-dir** — whether `~/.asrkit/models/` (or `$ASRKIT_MODELS_ROOT`) is writable; counts installed models and their total size. Non-existent directory is `info` (created on first pull); unwritable directory is a hard failure.
- **config** — whether `~/.asrkit/config.json` is valid JSON; shows default engine and models-root setting. Corrupt config is a hard failure.
- **network** (with `--net`) — reachability of the model download source and cloud APIs (e.g., dashscope); checks via short timeout (2s), no retry. Unreachable is `info` (not a failure).

**Exit code:**
- `0` — all checks passed (or only informational warnings).
- `1` — hard failures: models directory not writable, or config file corrupt.

**Read-only, no side effects:** doctor never modifies files or creates directories. It uses a temporary write probe (creates and cleans a temp file in the target directory) to check writability; this probe is always cleaned up, even if the process is interrupted.

**No secret leakage:** the doctor command reports only vendor names and credential sources (e.g., "present (keystore+env)"), never the actual key values.

### Shell Completion

Enable command-line completion for bash, zsh, or fish. Model names are fetched dynamically via `asrkit list --ids`, so newly installed models complete immediately.

**bash:**
```bash
asrkit completion bash | sudo tee /etc/bash_completion.d/asrkit
# Or for local shell session only:
source <(asrkit completion bash)
```

**zsh:**
```bash
# Option 1: Install to fpath (permanent, requires shell restart)
asrkit completion zsh > "${fpath[1]}/_asrkit"
# Option 2: Source in this shell session only
source <(asrkit completion zsh)
```

**fish:**
```bash
asrkit completion fish > ~/.config/fish/completions/asrkit.fish
```

### Streaming (minimal): `asrkit stream`

对一个 streaming（online）sherpa 模型逐块解码,live 进度打在 stderr、最终文本进 stdout(可管道)。

```bash
asrkit stream local/paraformer-online a.wav          # live 进度 stderr,最终文本 stdout
asrkit stream local/paraformer-online a.wav > out.txt  # 只截获最终文本
asrkit stream local/paraformer-online a.m4a --convert  # opt-in 解码/重采样
```

- live partial 只在 stderr 是 TTY 时覆盖同一行(`\r`);管道/重定向时不吐 ANSI,stdout 只落最终文本。
- 仅 `modes` 含 `streaming` 的模型可用(`asrkit list --json` 看 modes);批处理模型会给出清晰报错。
- 退出码:非流式/未配置/坏窗 = 2,模型未注册 = 3,引擎未装/格式错/运行时失败 = 4。
- 流式对 sherpa online 模型做端点检测,长音频/长会话自动分段(`committed` 逐段增长)。

#### 麦克风实时输入:`--mic`

对着麦克风边说边转,`Ctrl-C` 停止并打印最终稿。需要额外安装:`pip install "asrkit[mic]"`(未装会给出清晰报错,退出码 1)。

```bash
asrkit stream local/paraformer-online --mic          # 实时麦克风流式,Ctrl-C 停
asrkit stream local/paraformer-online --mic --device 1   # 指定设备(索引或名称子串)
```

- `--mic` 与音频文件参数互斥(同时给出 → 用法错误,退出码 2);`--device` 必须搭配 `--mic` 使用。
- `Ctrl-C` 干净停止:已有的最终文本(若有)打到 stdout,退出码 0。

### 日志 / `--verbose`

`run`/`transcribe`/`stream`/`serve` 都支持 `-v`/`-vv`,把诊断日志点亮到 stderr(标准库 `logging`,零新依赖)。默认(不加 `-v`)完全静默——不影响既有的 `[error]`/`[warn]` 输出。

```bash
asrkit run local/paraformer a.wav -v      # INFO:看到 _http 重试等
asrkit run local/paraformer a.wav -vv     # DEBUG:额外打印 model/metrics
asrkit serve --verbose                    # INFO:记录每个请求(model/format/成功与否)
```

- `-v` = INFO(如云端调用的重试:`retry 1/3 after 0.8s: ... (HTTP 429)`)。
- `-vv` = DEBUG(额外含单文件转写的 `model=... metrics=...`)。
- 作为库嵌入(`from asrkit.server import build_app`)时,asrkit 的 logger 默认只挂 `NullHandler`(不刷屏、不装 stderr handler);想看日志请自行配置标准 `logging`,例如:
  ```python
  import logging
  logging.getLogger("asrkit").setLevel(logging.INFO)
  logging.getLogger("asrkit").addHandler(logging.StreamHandler())
  ```

---

## 二、Python

```python
from asrkit import transcribe, list_models
from asrkit.api import pull, run

pull("local/sensevoice")                       # 下载
r = run("local/sensevoice", "meeting.wav")     # 缺则下载 + 转写
r = transcribe("local/whisper-small", "meeting.wav")   # 只转写

print(r.text)          # 识别文字
print(r.lang)          # zh
print(r.metrics)       # {'load_ms':..., 'decode_ms':..., 'rtf':...}

for m in list_models():
    print(m.id, m.name)
```

模型不在默认位置：`config={"model_dir": "/path/to/model"}`。

---

## 三、云端模型

用法一致，只需提供 API Key：

```bash
asrkit transcribe a.wav -m siliconflow/sensevoice --api-key <KEY>
```
```python
transcribe("siliconflow/sensevoice", "a.wav", config={"api_key": "<KEY>"})
```

> 项目灵魂：端侧 `local/sensevoice` 与云端 `siliconflow/sensevoice`，**同一个接口，只换字符串**。

### 密钥存一次（免每次 --api-key）

```bash
asrkit config set-key dashscope <KEY>                       # 单密钥厂商
asrkit config set-key doubao --app-key <A> --access-key <B> # 火山等双密钥
asrkit config list                                          # 查看（打码）
asrkit transcribe a.wav -m dashscope/qwen3-asr-flash        # 自动带上密钥
```

凭据解析优先级：**显式 `--api-key` > 环境变量 `<VENDOR>_API_KEY` > `asrkit config` 存的 keystore**。
密钥明文存 `~/.asrkit/config.json`（权限 0600）；不放心就只用环境变量。
另可 `asrkit config set default-engine <name>`（裸名落到该引擎）、`set models-root <path>`。

### 云端调用自动重试

所有云端 adapter 走共享 HTTP 层，遇到瞬时故障会自动重试 + 指数退避（尊重 `Retry-After`），无需自己写重试逻辑。重试次数可调：

```bash
export ASRKIT_HTTP_RETRIES=5   # 默认 3；0 表示不重试
```

> **成本安全（重要）**：计费的转写请求（OpenAI/ElevenLabs/DashScope 的转写、豆包 `submit`）**只在限流（HTTP 429）或连接从未建立（connect timeout）时重试**；读超时、5xx 等"请求可能已被服务端处理"的情况**不重试**，避免同一段音频被重复计费。豆包的轮询查询（`query`，只读、不计费）则会重试全部瞬时错误（429/5xx/超时/连接失败）。

**豆包长音频轮询超时**：豆包（录音文件识别）是异步 submit + 轮询,长音频需要更久。总轮询超时默认 300s,长文件可调大:

```bash
export ASRKIT_DOUBAO_POLL_TIMEOUT_S=600   # 默认 300;非法/<=0 回退默认
```

### serve 的 adapter 缓存

`asrkit serve` 把已加载的 adapter 按 model id 缓存(本地模型不每请求重载),用**有界 LRU**防长跑内存无界增长。容量默认 8,多模型混合服务可调大:

```bash
export ASRKIT_SERVE_CACHE=16   # 默认 8;非法/<=0 回退默认
```

### serve 流式(SSE)：`stream=true`

`POST /v1/audio/transcriptions` 加表单字段 `stream=true` 即走 **SSE**(`text/event-stream`),边转边推,OpenAI 兼容事件形态(`transcript.text.delta` / `transcript.text.done` + `data: [DONE]`)。仅 `modes` 含 `streaming` 的模型可用,批处理模型会 400。

```bash
curl -N http://127.0.0.1:11435/v1/audio/transcriptions \
  -F model=local/paraformer-online \
  -F stream=true \
  -F file=@a.wav
```

```
data: {"type": "transcript.text.delta", "delta": "hello"}

data: {"type": "transcript.text.delta", "delta": " world"}

data: {"type": "transcript.text.done", "text": "hello world"}

data: [DONE]

```

- `delta` 只发已定稿(committed)部分的增量,append-only;末尾 `transcript.text.done` 带全文 `text`。
- 出错(如格式不符、运行时异常)会发 `{"type": "error", "error": "..."}` 事件,随后仍以 `[DONE]` 收尾。
- `stream=false`(默认)行为不变,仍是一次性 JSON/text/srt/vtt。

---

## 四、返回字段（TranscribeResult）

| 字段 | 含义 |
|---|---|
| `text` | 识别文字（核心） |
| `lang` | 自动识别的语言（部分模型给出） |
| `latency_ms` | 总耗时（毫秒） |
| `metrics.rtf` | 实时率，越小越快（0.013 ≈ 比实时快 77×） |
| `error` | 出错信息；成功时为空。**adapter 不抛异常，错误进此字段** |

---

## 五、支持范围（当前）

- **端侧 47 个模型 / 14 种架构**：paraformer、senseVoice、whisper、moonshine(v1/v2)、
  transducer(离线/流式/NeMo)、telespeech、fireRed(CTC/AED)、qwen3-asr、funasr-nano、
  dolphin、omnilingual —— 统一由一个 sherpa-onnx adapter 处理，全部可 `pull` 即用。
- **云端**：硅基流动（SenseVoice 免费 / TeleSpeech）、OpenAI（whisper-1）、阿里云百炼
  （Qwen3-ASR / Fun-ASR-Flash / Qwen-Omni）、火山引擎豆包（录音文件识别 1.0 / 2.0，
  submit+poll）、ElevenLabs（Scribe）均已接入。密钥自带，寻址 `<厂商>/<模型>`。
- **多引擎**：默认 sherpa-onnx；可选装 faster-whisper（`faster-whisper/<model>`）、whisper.cpp（`whispercpp/<model>`）、transformers（**`transformers/<任意 HF 模型 id>`**，接整个 HuggingFace ASR 生态）。`asrkit engine list` / `install <name>` 管理引擎。
- **全开放扩展**：加自定义 sherpa 模型（`asrkit add-model <id> --url <tarball> --arch <type>`，或已有文件加 `--model-dir`）、写第三方引擎插件（`pip install asrkit-<engine>` 自动接入）——实操见 `docs/engines-and-addressing.md §九`。
- **扩展**：非内置的引擎/模型，照 `docs/adapter-spec.md` 写一个 adapter 即可接入（见该文档与 `engines-and-addressing.md`）。
- **许可证**：各模型许可证以其**官方来源**为准（ASRKit 只做接口、不分发权重）；**商用前请自行核对**，`asrkit show <model>` 指向来源。

一句话：`asrkit run 模型 音频` 一步到位；换模型只换字符串。

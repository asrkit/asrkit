<p align="right"><b>简体中文</b> | <a href="README.en.md">English</a></p>

# ASRKit

**语音识别的统一接口 —— 云端内置、引擎按需、模型即拉即用。**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit 是**语音识别领域的 Ollama + LiteLLM**:换个 model 字符串,就在端侧模型、云端 API、任意引擎之间切换,代码不动。**核心只是一个薄接口** —— 云端内置(依赖极小)、本地引擎按需装、模型按需下、还能起一个 OpenAI 兼容的本地服务。

> ⚠️ **早期 Beta,开发中。** 核心接口已可用,仍在积极迭代 —— 小版本间寻址/接口可能微调。欢迎试用与反馈。

```bash
pip install asrkit                                        # 秒装:接口 + 云端(仅 requests)
asrkit transcribe audio.wav -m dashscope/qwen3-asr-flash --api-key <KEY>   # 云端,立即可用

pip install "asrkit[local]"                               # 要端侧再加(sherpa,47 模型)
asrkit run local/sensevoice audio.wav                     # 首次自动下模型,然后识别
```

> 想要"全局命令、不碰当前环境"?`pipx install asrkit` 或 `uv tool install asrkit` 也行。

## 一套接口,任意切换

**变的只有 model 字符串** —— 引擎、模型、端侧还是云端,都是同一个调用:

```bash
asrkit run local/sensevoice                      audio.wav              # sherpa-onnx(端侧)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper 引擎
asrkit run whispercpp/base                       audio.wav              # whisper.cpp 引擎
asrkit run transformers/openai/whisper-large-v3  audio.wav              # 任意 HuggingFace 模型
asrkit run dashscope/qwen3-asr-flash             audio.wav --api-key …  # 云端,密钥自带
```

```python
from asrkit import transcribe
print(transcribe("dashscope/qwen3-asr-flash", "audio.wav", config={"api_key": "…"}).text)
```

## 批量与脚本化

一次处理多个文件、目录、glob 或 stdin,输出结构化表格 —— 端云横评、脚本消费都顺手:

```bash
asrkit transcribe *.wav        -m local/sensevoice          -f csv          # 每行一条:file,model,text,latency_ms,rtf…
asrkit transcribe ./recordings -m dashscope/qwen3-asr-flash -f json --batch # 目录递归 → NDJSON
cat a.wav | asrkit transcribe  -  -m local/sensevoice                       # stdin
```

- **NDJSON / csv / tsv** 批量输出(单文件仍是单个对象);字幕 `srt/vtt` 需模型返回时间戳,否则诚实报错。
- **分级退出码** `0/2/3/4`(成功 / 用法错 / 模型不存在 / 转写失败;批量有任一失败即非零),脚本可判因。
- **云端批量自动重试**瞬时故障(429/5xx),成本安全:计费请求只在限流/连接失败时重试,不重复计费(`ASRKIT_HTTP_RETRIES` 可调)。

## 为什么用 ASRKit

- **接口即内核,一切可插拔。** `pip install asrkit` 只装接口 + 云端(极小,仅 `requests`);引擎、模型、服务全按需加,不为用不到的东西背 torch。
- **端云同一个接口。** 端侧 `local/sensevoice` 与云端 `siliconflow/sensevoice`,**只换字符串**,代码零改动。
- **精选又开放。** 47 个端侧模型 + 5 家云厂商(含百炼 / 豆包 / 硅基流动等国内厂商)开箱即用;自定义模型一行 JSON、新引擎一个插件,**不改源码**。
- **透明,不越界。** 默认**不改动你的音频、不改变模型原生行为**;格式不符**诚实报错**,绝不静默出乱码。转换/分段都是 opt-in。
- **隐私。** 音频与密钥永不离开你的机器 —— 它是库/工具,不是托管服务。

## 安装:接口内核极小,一切可插拔

**基础安装只有接口 + 云端(仅依赖 `requests`,秒装、随处可跑)。** 本地引擎按需加:

| 想要 | 装什么 |
|---|---|
| 云端 + CLI + `serve` 调用方 | `pip install asrkit` |
| 端侧默认引擎(sherpa,47 模型) | `pip install "asrkit[local]"` |
| 其它引擎 | `asrkit[faster-whisper]` / `asrkit[whispercpp]` / `asrkit[transformers]` |
| 本地服务 | `asrkit[serve]` |
| 全都要 | `asrkit[all]` |

没装某引擎就用它 → **友好报错(带安装命令)**,不是 `ImportError`。

> **所有权模型:** 引擎是**共享 pip 包** —— `asrkit engine install <名>` 帮你装到对的环境,卸载用你自己的 `pip uninstall`(共享包,你的环境你做主)。模型是 **asrkit 独占** —— `pull` 下载、`rm` 删除,干净对称。

## 命令

| 命令 | 作用 |
|---|---|
| `asrkit list` | 列出所有模型(✓ = 已安装) |
| `asrkit run <模型> <音频>` | 缺则下载,然后识别 |
| `asrkit transcribe <音频…> -m <模型>` | 只识别(不自动下载);多文件/目录/glob/`-`(stdin)、`--batch`;`--format txt/json/srt/vtt/csv/tsv`、`-o`、`--language` |
| `asrkit pull <模型> [--url …]` / `rm <模型>` | 下载(可 `--url` 换源) / 删除端侧模型 |
| `asrkit show <模型>` | 模型详情 |
| `asrkit engine list` / `install <名>` / `default <名>` | 管理引擎 |
| `asrkit config set-key <厂商> <KEY>` / `list` | 存密钥 / 默认引擎 / models 目录 |
| `asrkit serve` | 起 OpenAI 兼容的本地转写服务 |
| `asrkit add-model …` | 注册自定义 sherpa 模型 |

## 引擎 × 模型

| 引擎 | 安装 | 寻址 | 覆盖 |
|---|---|---|---|
| **sherpa-onnx**(默认端侧) | `asrkit[local]` | `local/<模型>` 或裸名 `<模型>` | 47 端侧模型,14 架构 |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<模型>` | 快速 Whisper,自带长音频分块 |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<模型>` | 超轻量 Whisper(无 torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<任意 HF id>` | 整个 HuggingFace ASR 生态 + LLM 架构 SOTA |
| **云端** | 内置 | `<厂商>/<模型>` | 见下表,密钥自带 |

### 云端厂商(内置,只需密钥)

| 厂商 | 寻址 | 密钥 |
|---|---|---|
| 硅基流动 | `siliconflow/sensevoice`(免费)、`siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| 阿里云百炼 | `dashscope/qwen3-asr-flash`、`dashscope/fun-asr-flash`、`dashscope/qwen-omni-plus`、`dashscope/qwen-omni-flash` | `--api-key` |
| 火山引擎 / 豆包 | `doubao/auc-2`(2.0 Seed)、`doubao/auc-1`(1.0) | `--api-key` 或 `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

密钥三种给法(优先级从高到低):`--api-key` > 环境变量 `<厂商>_API_KEY`(火山双密钥用 `DOUBAO_APP_KEY`/`DOUBAO_ACCESS_KEY`)> `asrkit config set-key <厂商> <KEY>` 存一次。

## 当服务跑:OpenAI 兼容端点

`asrkit serve` 起一个本地服务,任何用 OpenAI SDK 的应用(或 Agent、任意语言)改个 `base_url` 就能调用背后全部端云模型 —— 这就是 "LiteLLM proxy" 那一半。**调用方零 asrkit 依赖,只发 HTTP。**

```bash
pip install "asrkit[serve]"
asrkit config set-key dashscope <KEY>     # 密钥存一次(可选,云端才需)
asrkit serve                              # 默认 127.0.0.1:11435,仅本机
```
```python
from openai import OpenAI
c = OpenAI(base_url="http://localhost:11435/v1", api_key="unused")
c.audio.transcriptions.create(model="local/sensevoice", file=open("a.wav", "rb"))
```
- 端点:`POST /v1/audio/transcriptions`(`response_format` 支持 json/verbose_json/text/srt/vtt)、`GET /v1/models`、`GET /health`。
- 云端密钥走 `asrkit config` 的库,无需每次传;透明原则:原始字节上传,不解码。

## 扩展

**加任意 sherpa 模型** —— 一条命令或往 `~/.asrkit/models.json` 写一条:

```bash
asrkit add-model local/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
```

**加一个引擎** —— 发一个小包、声明 `asrkit.adapters` entry point,`pip install` 即自动注册。不改源码、不改核心。食谱见 [docs/engines-and-addressing.md](docs/engines-and-addressing.md#九扩展实操)。

## 文档

[使用说明](docs/usage.md) · [Adapter 契约](docs/adapter-spec.md) · [引擎与寻址](docs/engines-and-addressing.md) · [模型管理](docs/model-management.md)

---

Apache-2.0。各模型许可证以其官方为准,商用前请自行核对(`asrkit show <模型>` 指向来源)。你的音频与密钥始终留在本机。

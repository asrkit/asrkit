<p align="right"><b>简体中文</b> | <a href="README.en.md">English</a></p>

# ASRKit

**一套接口,跑遍任意语音识别模型 —— 端侧、云端、任意引擎。**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit 是**语音识别领域的 Ollama + LiteLLM**:一条命令拉起端侧模型就跑;换个字符串就切云端 API;想加一个全新的推理引擎,写成插件即可接入。一份契约,背后什么都能挂。

> ⚠️ **早期 Beta,开发中。** 核心接口已可用,我们仍在积极迭代 —— 小版本间 API 与寻址可能调整。欢迎试用与反馈。

```bash
pip install asrkit
asrkit run local/sensevoice audio.wav      # 首次自动下载模型,然后识别
```

## 一套接口,任意切换

**变的只有 model 字符串**——引擎、模型、端侧还是云端,都是同一个调用:

```bash
asrkit run local/sensevoice                      audio.wav              # sherpa-onnx(端侧,默认)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper 引擎
asrkit run whispercpp/base                       audio.wav              # whisper.cpp 引擎
asrkit run transformers/openai/whisper-large-v3  audio.wav              # 任意 HuggingFace 模型
asrkit run siliconflow/sensevoice                audio.wav --api-key …  # 云端,密钥自带
```

```python
from asrkit import transcribe
print(transcribe("local/sensevoice", "audio.wav").text)
```

## 为什么用 ASRKit

- **既精选、又开放。** 47 个端侧模型开箱即用(`asrkit list`);其它的写一行 JSON 或做成插件就能加,**不用改源码**。
- **四个引擎,还能插更多。** sherpa-onnx、faster-whisper、whisper.cpp、transformers(接整个 HuggingFace 生态,含 LLM 架构 SOTA)。`pip install asrkit-<engine>` 加你自己的。
- **透明,不越界。** 默认**不改动你的音频、不改变模型原生行为**。格式不对?**诚实报错**,绝不静默出乱码。格式转换、长音频分段都是 opt-in 开关。
- **隐私。** 音频与密钥永不离开你的机器 —— ASRKit 是个库,不是托管服务。
- **即拉即用。** 模型按需下载、本地缓存,Ollama 式。`pip install asrkit` 只带默认引擎,其余可选装。

## 命令

| 命令 | 作用 |
|---|---|
| `asrkit list` | 列出所有模型(✓ = 已安装) |
| `asrkit run <模型> <音频>` | 缺则下载,然后识别 |
| `asrkit transcribe <音频> -m <模型>` | 只识别(不自动下载) |
| `asrkit pull <模型>` / `rm <模型>` | 下载 / 删除端侧模型 |
| `asrkit show <模型>` | 模型详情 |
| `asrkit engine list` / `install <name>` | 管理引擎 |

## 引擎 × 模型

| 引擎 | 安装 | 寻址 | 覆盖 |
|---|---|---|---|
| **sherpa-onnx**(默认) | 内置 | `local/<模型>` 或裸名 `<模型>` | 47 端侧模型,14 架构 |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<模型>` | 快速 Whisper,自带长音频分块 |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<模型>` | 超轻量 Whisper(无 torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<任意 HF id>` | 整个 HuggingFace ASR 生态 + LLM 架构 SOTA |
| **云端** | 内置 | `<厂商>/<模型>` | 见下表,密钥自带 |

### 云端厂商

| 厂商 | 寻址 | 密钥 |
|---|---|---|
| 硅基流动 | `siliconflow/sensevoice`(免费)、`siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| 阿里云百炼 | `dashscope/qwen3-asr-flash`、`dashscope/fun-asr-flash`、`dashscope/qwen-omni-plus`、`dashscope/qwen-omni-flash` | `--api-key` |
| 火山引擎 / 豆包 | `doubao/auc-2`(2.0 Seed)、`doubao/auc-1`(1.0) | `--api-key` 或 `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

密钥也可走环境变量兜底:`<厂商>_API_KEY`(如 `DASHSCOPE_API_KEY`),火山双密钥用 `DOUBAO_APP_KEY` / `DOUBAO_ACCESS_KEY`。

## 扩展

**加任意 sherpa 模型** —— 往 `~/.asrkit/models.json` 写一条:

```json
[{"id": "local/my-model", "download_url": "https://…/model.tar.bz2", "config_type": "senseVoice", "langs": ["zh"]}]
```

**加一个引擎** —— 发一个小包、声明 `asrkit.adapters` entry point,`pip install` 即自动注册。不改源码、不改核心。食谱见 [docs/engines-and-addressing.md](docs/engines-and-addressing.md#九扩展实操)。

## 文档

[使用说明](docs/usage.md) · [Adapter 契约](docs/adapter-spec.md) · [引擎与寻址](docs/engines-and-addressing.md) · [模型管理](docs/model-management.md)

---

Apache-2.0。各模型许可证以其官方为准,商用前请自行核对(`asrkit show <模型>` 指向来源)。你的音频与密钥始终留在本机。

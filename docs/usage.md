# ASRKit 使用说明

> 现状（v0.x 内核）：端侧 47 个模型 + 云端接口已可用。一个接口跑遍端云。

## 核心概念：一个接口，两种用法

不管什么模型（端侧 / 云端 / 中文 / 英文），都只用两种方式之一调用，**换模型只是换一个字符串**：

- **命令行（CLI）**：`asrkit ...`，适合随手转写、试模型。
- **Python 代码**：`from asrkit import transcribe`，适合写进自己的程序。

## 安装

```bash
pip install asrkit[local]     # 只要端侧（sherpa-onnx）
pip install asrkit[cloud]     # 只要云端 API
pip install asrkit[all]       # 都要
```

开发模式（改代码即时生效）：

```bash
pip install -e ".[all]"
```

---

## 一、命令行

### 1. 指定端侧模型所在目录（一次）

```bash
export ASRKIT_MODELS_ROOT=/path/to/models
```

按 `$ASRKIT_MODELS_ROOT/<模型名>/` 查找。如 `local/sensevoice` → `.../models/sensevoice/`。
转写时加 `--model-dir <路径>` 可临时覆盖。

### 2. 列出模型

```bash
asrkit list
```

列出全部模型（💻 端侧 / ☁️ 云端）。第一列即"模型字符串"。

### 3. 转写

```bash
asrkit transcribe 音频.wav -m local/sensevoice
```

- `-m`：模型字符串（从 `asrkit list` 取）。
- 换模型只换字符串：`-m local/whisper-small` / `-m local/paraformer-zh` / `-m local/qwen3-asr-0.6b` …
- 输出：第一行为识别文字；stderr 第二行为 `耗时、语言、rtf`。

例：

```
$ asrkit transcribe meeting.wav -m local/sensevoice
好，那接下来就是咱们呃食品部的吧，你们来说一下。
  (683ms, lang=zh, rtf=0.013)
```

---

## 二、Python

```python
from asrkit import transcribe, list_models

r = transcribe(model="local/sensevoice", audio="meeting.wav")
print(r.text)          # 识别文字
print(r.lang)          # zh
print(r.latency_ms)    # 683
print(r.metrics)       # {'load_ms':..., 'decode_ms':..., 'rtf':0.013}

# 换模型 = 换字符串，其余不变
r = transcribe(model="local/whisper-small", audio="meeting.wav")

for m in list_models():
    print(m.id, m.name)
```

模型不在默认位置时：

```python
r = transcribe(model="local/sensevoice", audio="a.wav",
               config={"model_dir": "/path/to/sensevoice"})
```

---

## 三、云端模型

用法与端侧完全一致，只需提供 API Key：

```bash
asrkit transcribe a.wav -m siliconflow/sensevoice --api-key <KEY>
```

```python
r = transcribe(model="siliconflow/sensevoice", audio="a.wav",
               config={"api_key": "<KEY>"})
```

> 项目灵魂：端侧 `local/sensevoice` 与云端 `siliconflow/sensevoice`，**同一个 `transcribe`，只换字符串**。

---

## 四、返回字段（TranscribeResult）

| 字段 | 含义 |
|---|---|
| `text` | 识别文字（核心） |
| `lang` | 自动识别的语言（部分模型给出） |
| `latency_ms` | 总耗时（毫秒） |
| `metrics.rtf` | 实时率，越小越快（0.013 = 比实时快约 77×） |
| `metrics` | `{load_ms, decode_ms, rtf, ...}` |
| `error` | 出错信息；成功时为空。**adapter 不抛异常，错误进此字段** |

---

## 五、支持范围（当前）

- **端侧 47 个模型**：涵盖 14 种架构（paraformer / senseVoice / whisper / moonshine(v1/v2) / transducer(离线/流式/NeMo) / telespeech / fireRed(CTC/AED) / qwen3-asr / funasr-nano / dolphin / omnilingual），统一由一个 sherpa-onnx adapter 处理。
- **云端**：OpenAI 兼容协议已接（OpenAI / 硅基流动等）。更多云厂商（Deepgram / DashScope / 火山豆包 / ElevenLabs）陆续接入。

一句话：`export 模型目录` → `asrkit list` → `asrkit transcribe 音频 -m 模型`；代码里 `transcribe(model=..., audio=...)`。换模型永远只换那个字符串。

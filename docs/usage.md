# ASRKit 使用说明

> 现状（v0.x 内核）：端侧 47 个模型可一键下载即用（Ollama 式）；云端 OpenAI 兼容接口已接。
> 一个接口跑遍端云，换模型只换字符串。

## 核心概念：一个接口，两种用法

- **命令行（CLI）**：`asrkit ...`，随手下载、试模型、转写。
- **Python 代码**：`from asrkit import transcribe`，写进自己的程序。

## 安装

```bash
pip install asrkit            # 一步装好端云接口（sherpa-onnx + 云端 + 音频）
pip install -e .              # 开发模式（改代码即时生效）
```

模型权重用 `asrkit pull` 按需下载；云端填 API key。

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
```

- 换模型只换字符串：`local/whisper-small`、`local/paraformer-zh`、`local/qwen3-asr-0.6b` …
- **精度标签**（Ollama 式）：`local/sensevoice:int8`（默认）/ `local/sensevoice:fp32`。
- 输出：第一行为识别文字；stderr 第二行为 `耗时、语言、rtf`。

例：

```
$ asrkit run local/whisper-tiny meeting.wav
下载 https://.../sherpa-onnx-whisper-tiny.tar.bz2
  ...110/110 MB
完成 → ~/.asrkit/models/whisper-tiny
So that just raises a point I wonder what our design people think.
  (387ms, lang=en, rtf=0.048)
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
- **云端**：OpenAI 兼容协议已接（OpenAI / 硅基流动等）。Deepgram / DashScope / 火山豆包 /
  ElevenLabs 陆续接入。
- **多引擎**：默认引擎 sherpa-onnx；可选装 faster-whisper（`pip install "asrkit[faster-whisper]"`），用 `faster-whisper/<model>` 寻址（如 `faster-whisper/large-v3`）。`asrkit engine list` 看引擎、`asrkit engine install <name>` 装引擎。
- **扩展**：非内置的引擎/模型，照 `docs/adapter-spec.md` 写一个 adapter 即可接入（见该文档与 `engines-and-addressing.md`）。
- **许可证**：各模型许可证以其**官方来源**为准（ASRKit 只做接口、不分发权重）；**商用前请自行核对**，`asrkit show <model>` 指向来源。

一句话：`asrkit run 模型 音频` 一步到位；换模型只换字符串。

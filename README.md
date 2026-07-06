<p align="right"><b>简体中文</b> | <a href="README.en.md">English</a></p>

# ASRKit

**一套接口，跑遍端云所有语音识别。**

One interface to run and compare any speech-to-text model — local & cloud.

ASRKit 是语音识别领域的 Ollama + LiteLLM：本地模型一条命令拉起来跑，云端 API 换个字符串就切换，端云共用同一套接口。

## 安装

```bash
pip install asrkit
```

一步装好端云接口。模型权重用 `asrkit pull` 按需下载，云端填 API key（跟 Ollama 一样：装引擎，用时下模型）。

## 快速开始

```bash
asrkit list                                              # 看所有模型（✓=已安装）
asrkit run local/sensevoice a.wav                        # 端侧：缺则自动下载 + 转写
asrkit run siliconflow/sensevoice a.wav --api-key <KEY>  # 云端：换个字符串即切
```

Python：

```python
from asrkit import transcribe
r = transcribe("local/sensevoice", "a.wav")
print(r.text)
```

## 特点

- **本地 47 个端侧模型**（SenseVoice / Paraformer / Whisper / Zipformer / Moonshine / Parakeet / FireRed / Qwen3-ASR …），`pull` 即用。
- **云端 OpenAI 兼容接口**，密钥自带（更多厂商陆续接入）。
- **透明层**：默认不改动你的音频、不改变模型原生行为；格式不符**诚实报错**，转换（`--convert`）与长音频分段（`--segment`）是 opt-in。
- **隐私**：你的音频与密钥永不经过我们——ASRKit 完全跑在你自己的机器上。

Apache-2.0。用法详见 [docs/usage.md](docs/usage.md)，扩展新引擎/模型见 [docs/adapter-spec.md](docs/adapter-spec.md)。

> 各模型的许可证以其**官方来源**为准（ASRKit 只做接口、不分发权重，`pull` 从官方 release 下载）；**商用前请自行核对**。`asrkit show <model>` 会指向来源。

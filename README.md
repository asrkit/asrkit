<p align="right"><b>简体中文</b> | <a href="README.en.md">English</a></p>

# ASRKit

**一套接口，跑遍端云所有语音识别。**

One interface to run and compare any speech-to-text model — local & cloud.

> ⚠️ **占位发布。** 当前 `0.0.1` 仅用于锁定名称，ASRKit 正在积极开发中，**暂未提供实际功能**。
> 首个可用版本请关注 [github.com/asrkit/asrkit](https://github.com/asrkit/asrkit)。

## ASRKit 会是什么

ASRKit 是语音识别领域的 Ollama + LiteLLM：

- **本地模型，`pull` 即用** —— 一条命令跑开源 ASR 模型（SenseVoice、Paraformer、Zipformer、Whisper、Moonshine、Parakeet …），模型按需下载。
- **云端 API，换个字符串即切** —— 用完全相同的接口调用云端 ASR（火山引擎、阿里百炼、OpenAI、Deepgram …），密钥自带。
- **端云一套协议** —— 一份契约、一个 OpenAI 兼容端点，内置 `bench` 把端侧与云端放在同一把尺子上横评。

Apache-2.0 开源。你的音频与密钥永不经过我们——ASRKit 完全跑在你自己的机器上。

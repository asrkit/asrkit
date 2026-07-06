# ASRKit

**One interface to run and compare any speech-to-text model — local & cloud.**

一套接口，跑遍端云所有语音识别。

> ⚠️ **Placeholder release.** This `0.0.1` reserves the name while ASRKit is
> under active development. It does not yet provide functionality.
> Watch [github.com/asrkit/asrkit](https://github.com/asrkit/asrkit) for the first working release.

## What ASRKit will be

ASRKit is the Ollama + LiteLLM for speech recognition:

- **Local models, `pull` and go** — run open-source ASR models (SenseVoice, Paraformer, Zipformer, Whisper, Moonshine, Parakeet …) with one command, models downloaded on demand.
- **Cloud APIs, one string away** — call hosted ASR (Volcengine, DashScope, OpenAI, Deepgram …) through the exact same interface, bring your own key.
- **One protocol across edge and cloud** — a single contract, an OpenAI-compatible endpoint, and a built-in `bench` to compare them all on the same ruler.

Apache-2.0. Your audio and keys never pass through us — ASRKit runs on your machine.

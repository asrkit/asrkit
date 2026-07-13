# OpenAI Transcription 兼容范围

> 当前事实快照:ASRKit 0.5.4。本文是 OpenAI HTTP 兼容性的唯一事实源;“兼容”始终指下列**明确子集**,不是对 OpenAI 全部 Audio/Realtime API 的逐字段复刻。

## 当前端点

| 方法 | 路径 | 状态 |
|---|---|---|
| `POST` | `/v1/audio/transcriptions` | 已实现 |
| `GET` | `/v1/models` | 已实现,仅返回基础 model list 结构 |
| `GET` | `/health` | 已实现,仅返回 `{"status":"ok"}` |
| `POST` | `/v1/audio/translations` | 未实现 |
| WebSocket/Realtime transcription | — | 未实现 |

## Transcriptions 请求字段

当前接收 multipart form:

| 字段 | 状态 | 说明 |
|---|---|---|
| `file` | 必填 | 原始字节写入临时文件,请求结束清理 |
| `model` | 必填 | 使用 ASRKit model string,如 `dashscope/qwen3-asr-flash` |
| `language` | 可选 | 传入 `TranscribeOptions.lang_hint`;是否生效由模型 capability 决定 |
| `response_format` | 可选 | `json`(默认)/`verbose_json`/`text`/`srt`/`vtt` |
| `stream` | 可选 | `true` 时走 SSE;仅 ASRKit streaming 模型可用 |
| `prompt`/`temperature`/`timestamp_granularities` 等 | 未实现 | 不属于当前承诺子集 |

## 响应

- `json`:`{"text":"..."}`。
- `verbose_json`:ASRKit `TranscribeResult` 的非空字段;不是 OpenAI 所有模型的完整 verbose schema。
- `text`:纯文本。
- `srt`/`vtt`:仅当 adapter 返回 `segments`;否则 400。
- 未知 model 返回 404;转写或格式失败通常返回 OpenAI-like `{"error":{"message":"..."}}`,但错误类型/code 字段尚未完全对齐 OpenAI。

## SSE 子集

`stream=true` 使用 `text/event-stream`,当前事件为:

```text
data: {"type":"transcript.text.delta","delta":"..."}

data: {"type":"transcript.text.done","text":"..."}

data: [DONE]
```

这是面向 ASRKit `PartialResult` 的兼容映射。当前云端内置 model 均为 batch;SSE 主要服务 sherpa streaming 模型。它不等于 OpenAI Realtime WebSocket 协议。

## 安全与部署边界

0.5.4 的 `asrkit serve`:

- 默认绑定 `127.0.0.1`;
- 没有内置鉴权、限流或请求体上限;
- 上传内容当前一次性读入内存后写临时文件;
- 只适合受信任本机集成,不得直接暴露公网或不受信任网络。

目标中的 `asrkitd` 将在发布前补齐 embedded 鉴权、上传/并发限制、ready 握手和父进程生命周期;目标设计见 [embedding-and-distribution.md](embedding-and-distribution.md)。在这些能力落地前,它们不属于当前功能。

## 兼容性验证原则

- 用官方 OpenAI Python/Node SDK 对本文列出的字段做持续测试;
- 未在矩阵中声明的参数不得用“OpenAI 完全兼容”概括;
- 新增字段必须同时更新服务测试和本文;
- 内部 provider 协议变化不得改变已声明的 HTTP 结果语义。

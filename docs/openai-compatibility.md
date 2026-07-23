# OpenAI Transcription 兼容范围

> 当前事实快照:ASRKit 0.5.5。本文是 OpenAI HTTP 兼容性的唯一事实源;“兼容”始终指下列**明确子集**,不是对 OpenAI 全部 Audio/Realtime API 的逐字段复刻。

## 当前端点

| 方法 | 路径 | 状态 |
|---|---|---|
| `POST` | `/v1/audio/transcriptions` | 已实现 |
| `GET` | `/v1/models` | 已实现,仅返回基础 model list 结构 |
| `GET` | `/health` | 已实现；`asrkit serve` 返回 status,0.5.5 daemon 模块另含 version/protocol/distribution |
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
- `verbose_json`:ASRKit `TranscribeResult` 的非空字段,其中内部 `lang` 映射为 OpenAI 字段 `language`;不是 OpenAI 所有模型的完整 verbose schema。
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

`asrkit serve` 的 0.5.5 契约:

- 默认绑定 `127.0.0.1`;
- 普通 CLI 无内置鉴权，但默认限制 200 MiB 上传、4 并发、300 秒超时;
- 转写 POST 拒绝任何非空 `Origin`，防止浏览器 loopback CSRF;
- 上传内容分块写入临时文件,超限即清理;
- 仍只适合受信任本机的非浏览器客户端,不得直接暴露公网或不受信任网络。

0.5.5 Python 包中的 daemon 模块已经实现 embedded 鉴权、上传/并发/超时限制、ready/shutdown 握手和父进程生命周期；这些能力尚未随自包含 `asrkit-cloud` 二进制发布。详细契约见 [embedding-and-distribution.md](embedding-and-distribution.md)。

## 兼容性验证原则

- CI 固定使用官方 OpenAI Python SDK 2.47.0 与 Node SDK 6.48.0,对模型列表以及 `json`/`text`/`verbose_json` 转写做真实客户端调用；SDK 版本升级必须显式评审并更新锁文件;
- 两家真实云厂 E2E 使用同一 Python SDK 经 ASRKit daemon 调用,只在受保护的 `cloud-e2e` 环境手动触发；缺密钥、空文本或固定音频识别失真均硬失败;
- 未在矩阵中声明的参数不得用“OpenAI 完全兼容”概括;
- 新增字段必须同时更新服务测试和本文;
- 内部 provider 协议变化不得改变已声明的 HTTP 结果语义。

### 真实云 E2E 的一次性配置

工作流不会读取开发机配置。仓库管理员需在 GitHub 创建 `cloud-e2e` environment,按选用组合写入 environment secrets,再手动运行:

```bash
gh api --method PUT repos/asrkit/asrkit/environments/cloud-e2e
gh secret set --repo asrkit/asrkit --env cloud-e2e DASHSCOPE_API_KEY
gh secret set --repo asrkit/asrkit --env cloud-e2e SILICONFLOW_API_KEY
gh workflow run cloud-e2e.yml --repo asrkit/asrkit -f second_provider=siliconflow
```

若第二家选择豆包,改为写入 `DOUBAO_API_KEY`,或同时写入 `DOUBAO_APP_KEY` 与 `DOUBAO_ACCESS_KEY`,并传 `second_provider=doubao`。建议在 environment 上配置 required reviewer；工作流不自动触发、不保存转写正文或厂商响应 artifact。

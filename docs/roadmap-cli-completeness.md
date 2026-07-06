# 完善路线：CLI 补全 · 配置持久化 · 本地服务（0.4.1 → 0.5.0）

> 目标：对照 Ollama + LiteLLM，把 ASRKit 从"能用的接口"做成"顺手的工具 + 可挂载的服务"。
> 三组改动**严格分版本、按依赖顺序**推进：A(纯增量) → B(配置) → C(服务，依赖 A+B)。
> 每组做完即可独立发版。标注：`目标 / 表面 / 设计 / 涉及文件 / 验收 / 非目标`。

---

## 版本与依赖总览

| 版本 | 主题 | 内容 | 依赖 |
|---|---|---|---|
| **0.4.1** | 快速完善（A 组） | 输出格式、list 增强、--language、文档缺口、py.typed | 无 |
| **0.4.2** | 配置持久化（B 组） | `asrkit config`：密钥/默认引擎/models 根目录 | 无 |
| **0.5.0** | 工具→服务（C 组） | `asrkit serve`：OpenAI 兼容 HTTP 端点 | A(formats) + B(keystore) |

顺序理由：C 的 `response_format` 复用 A 的 formats 模块，C 的免密钥调用复用 B 的 keystore。故 A、B 必须先落地。

---

## A 组 — 0.4.1 快速完善（纯增量，不碰架构）

### A1. 输出格式 `--format` + `-o/--output`

**目标**：语音工具的刚需——除纯文本外，能出 **JSON（脚本可解析）** 和 **字幕（SRT/VTT）**。`TranscribeResult` 已有 `segments` / `word_timestamps` / `lang` / `metrics` 字段，目前 CLI 只吐第一行文本，白白浪费。

**表面**：
```bash
asrkit transcribe a.wav -m local/whisper --format srt -o a.srt
asrkit transcribe a.wav -m local/sensevoice --format json      # 全字段 JSON 到 stdout
asrkit run local/sensevoice a.wav                              # 默认 txt，行为不变
```
- `--format {txt,json,srt,vtt}`，默认 `txt`（保持现有行为，向后兼容）。
- `-o/--output <file>`，默认 stdout。
- 同时加到 `run` 和 `transcribe`（都走 `_add_transcribe_flags`）。

**设计**：
- 新模块 `src/asrkit/formats.py`：`render(result: TranscribeResult, fmt: str) -> str`。
  - `txt`：`result.text`。
  - `json`：`json.dumps` 全部非空字段（text/lang/latency_ms/segments/word_timestamps/metrics/error）。
  - `srt` / `vtt`：从 `result.segments` 渲染带时间轴的字幕；时间格式化 `HH:MM:SS,mmm`（SRT）/ `HH:MM:SS.mmm`（VTT）。
  - **诚实降级**：`srt/vtt` 但 `segments` 为空时 → 返回错误提示"该模型未返回时间戳，请用 --format txt/json"，绝不假装。
- `cli.py._print_result` 重构：txt 保持"文本 stdout + 指标 stderr"；其它格式整体写到 `-o` 或 stdout；错误仍走 stderr + 退出码 1。

**涉及文件**：`src/asrkit/formats.py`(新)、`cli.py`(_add_transcribe_flags/_print_result/_opts)。

**验收**：`tests/` 加 `test_formats.py`——用带 2 个 `Segment` 的合成 `TranscribeResult` 断言 SRT/VTT/JSON 文本；无 segments 时 srt 报错。

### A2. `list` 增强

**目标**：脚本友好 + 对齐 Ollama `ls`。

**表面**：
```bash
asrkit list --json           # 机器可读（id/name/source/provider/langs/installed/size）
asrkit list --installed      # 只看已安装（本地）
asrkit list --source cloud   # 按来源过滤（cloud|local）
```

**设计**：
- `--json`：输出模型 dict 列表（含 `installed` 布尔、本地 `size_bytes`）。
- `--installed` / `--source`：过滤。
- 体积列：仅对已安装本地模型算 `store` 目录大小（懒算，未装不算）。人读格式加一列 SIZE。

**涉及文件**：`cli.py`(list 分支)、可能 `store.py`(加 `dir_size(meta)`)。

**验收**：`asrkit list --json` 输出可被 `json.loads`；`--installed` 只含已装。

### A3. `--language` 透传

**目标**：`TranscribeOptions.lang_hint` 已存在但 CLI 未暴露；Whisper 类模型给语言提示能显著提准。

**表面**：`asrkit transcribe a.wav -m local/whisper --language zh`

**设计**：`_add_transcribe_flags` 加 `--language`；`_opts` 填 `lang_hint`。

**涉及文件**：`cli.py`。**验收**：解析进 opts（单测）。

### A4. 修文档-代码缺口（诚实性）

**问题**：`docs/engines-and-addressing.md §八` 把 `asrkit engine rm` 和 `asrkit engine default <name>` 当**已有命令**写，但 `cli.py` 只实现了 `engine list|install`。读者照敲会失败。

**决策**：`engine default` 的正确实现依赖 B 组的配置持久化（要存"默认引擎"），`engine rm` 涉及安全卸载（torch 等共享包不能乱删）。故 **0.4.1 先把文档这两行标成 `路线`（未实现）**；`engine default` 在 B 组真正实现，`engine rm` 视情况再定。

**涉及文件**：`docs/engines-and-addressing.md`。

### A5. `py.typed`（库层面）

**目标**：ASRKit 是库，加类型标记让下游 IDE/mypy 拿到类型提示。

**设计**：新建空文件 `src/asrkit/py.typed`；确认 hatchling wheel 打包含它（`packages=["src/asrkit"]` 默认纳入包内文件）。

**验收**：wheel 内含 `asrkit/py.typed`。

### A6. `api.py` 对称（可选，随手）

`api.py` 补 `remove(model)` 和 `show(model)`（= `registry.resolve`），与 CLI 对称；导出 `formats.render`。

### A 组非目标
- 不做 config 持久化（B 组）。
- 不做批量/目录输入（挪到 B 之后按需）。
- 不改寻址/adapter 契约。

**版本动作**：`__init__.py` → `0.4.1`；同步 `test_smoke.py` 断言；CHANGELOG 加节；tag `v0.4.1`。

---

## B 组 — 0.4.2 配置持久化 `asrkit config`

### 目标
让云端"像本地一样顺手"：密钥存一次、默认引擎可切、models 根目录可配。当前要么每次 `--api-key`、要么设一堆环境变量——这是 LiteLLM 那半边体验的缺口。

### 表面
```bash
asrkit config set-key dashscope <KEY>                      # 单密钥厂商
asrkit config set-key doubao --app-key <A> --access-key <B># 双密钥厂商（火山）
asrkit config get-key dashscope                            # 打码显示（仅末 4 位）
asrkit config set default-engine whispercpp               # 裸名落到该引擎
asrkit config set models-root /data/asr-models
asrkit config list                                        # 全部配置（密钥打码）
asrkit config path                                        # 打印配置文件位置
```

### 设计
- 文件 `~/.asrkit/config.json`（可 `$ASRKIT_CONFIG` 覆盖）。结构：
  ```json
  {
    "keys": {
      "dashscope": {"api_key": "sk-..."},
      "doubao": {"app_key": "...", "access_key": "..."}
    },
    "defaults": {"engine": "sherpa-onnx"},
    "settings": {"models_root": "/data/asr-models"}
  }
  ```
- 新模块 `src/asrkit/config.py`：`load()/save()`、`get_creds(vendor)->dict`、`set_creds(vendor, **kv)`、`get_default(name)`、`set_default(name,val)`、`path()`。
- **凭据解析顺序**（`registry.make_adapter` 内，改现有 env 兜底段）：
  1. 显式 `config=` 参数（最高）
  2. 环境变量 `<VENDOR>_API_KEY` / `_APP_KEY` / `_ACCESS_KEY`
  3. **config.json keystore（新增，兜底）**
  4. 都没有 → 交给 adapter 报"missing credentials"
- **默认引擎**：`registry.resolve` 裸名解析由硬编码 `local/` 改为读 `config.get_default("engine")`（缺省仍 `sherpa-onnx`/`local`），实现文档承诺的 `engine default`。保持向后兼容：不配就和现在完全一样。
- **`engine default <name>`** 现在可实现：写 `defaults.engine`，等价 `config set default-engine`（留作 alias）。
- **安全**：
  - 写文件设权限 `0600`。
  - `config list`/`get-key` **一律打码**（`sk-…abcd`，仅末 4 位），绝不明文回显。
  - 文档明确：密钥**明文存储**（与 ollama/aws-cli 同惯例）；不放心者继续用环境变量。首次 `set-key` 时 stderr 提示存储位置与明文性质。

### 涉及文件
`src/asrkit/config.py`(新)、`registry.py`(凭据解析 + resolve 默认引擎)、`cli.py`(config 子命令 + engine default)、`store.py`(models_root 读 config)、`docs/`(usage + engines-and-addressing 更新)。

### 验收
`test_config.py`（`monkeypatch` `ASRKIT_CONFIG` 到 tmp）：set/get 往返；`make_adapter` 从 keystore 取到密钥；打码正确；文件权限 0600；默认引擎切换后裸名解析改变。

### 非目标
- 不做多 profile / 远程配置。
- 不做密钥加密（明文 + 权限 + 打码，够用且透明）。

**版本动作**：`0.4.2`；CHANGELOG；tag。

---

## C 组 — 0.5.0 `asrkit serve`（工具→服务里程碑）

### 目标
坐实 "Ollama + **LiteLLM**" 的服务那一半：起一个本地 HTTP 服务，暴露 **OpenAI 兼容**的转写端点，任何用 OpenAI SDK 的应用改个 `base_url` 就能调用 ASRKit 背后的全部端云模型。

### 表面
```bash
asrkit serve                          # 默认 127.0.0.1:11435（仅本机）
asrkit serve --host 0.0.0.0 --port 8000   # 对外（带安全警告）
```
```python
# 任意 OpenAI 客户端
from openai import OpenAI
c = OpenAI(base_url="http://localhost:11435/v1", api_key="unused")
c.audio.transcriptions.create(model="local/sensevoice", file=open("a.wav","rb"))
```

### 端点（OpenAI 兼容）
- `POST /v1/audio/transcriptions`：multipart，字段 `file`、`model`、可选 `language`、`response_format`(json|text|srt|vtt|verbose_json)。默认 `{"text": "..."}`。
- `GET /v1/models`：列出可用模型（OpenAI list 结构，复用 `list_models()`）。
- `GET /health`：存活探针。

### 设计
- **依赖走可选 extra**：`asrkit[serve] = ["fastapi", "uvicorn"]`（与引擎 extra 同哲学）。懒加载；没装时 `asrkit serve` 给友好报错（`pip install "asrkit[serve]"`），不崩。
- **透明原则贯穿**：上传文件按原始字节落到临时文件 → `AudioInput(original_path=tmp)` → `registry.make_adapter(model).transcribe()`；不解码、不重采样。请求结束清理临时文件。
- **免密钥**：服务端用 B 组 keystore 解析云端凭据，故云端模型无需每次带 key；也支持 `Authorization: Bearer` 透传覆盖。
- **`response_format` 复用 A 组 `formats.render`**（这就是 A 必须先行的原因）。
- **安全**：默认绑 `127.0.0.1`；`--host 0.0.0.0` 时 stderr 显式警告"暴露到网络"。
- **并发**：uvicorn 处理；adapter 每请求实例化。**已知局限**：本地模型每请求重新加载（慢）——v1 先简单，文档标注"模型缓存（LRU 常驻）"为后续优化。

### 涉及文件
`src/asrkit/server.py`(新)、`cli.py`(serve 子命令)、`pyproject.toml`(serve extra)、`engines.py` 或新 `_optional` 探测、`docs/`(新增 serve 用法 + README 秀一段)。

### 验收
`test_serve.py`：注册一个 stub adapter，起测试客户端（fastapi `TestClient`），POST 一个 wav 断言返回 JSON `text`；`GET /v1/models` 返回列表；未装 extra 时 CLI 友好报错。

### 非目标（v1）
- 不做模型常驻缓存 / `ps` / 流式 `stream=true`（列为 0.5.x 后续）。
- 不做鉴权/多租户（本机工具定位）。
- 不做 WebSocket 实时。

**版本动作**：`0.5.0`，作为"工具→服务"版本主题；README 中英加 serve 段；CHANGELOG 醒目；tag `v0.5.0`。

---

## 落地顺序清单

- [x] **0.4.1 (A)** ✅：formats 模块 → CLI `--format/-o` → `list --json/--installed/--source` → `--language` → 修文档缺口 → `py.typed` → api 对称 → 测试 → tag `v0.4.1`
- [x] **0.4.2 (B)** ✅：config 模块 → make_adapter 凭据链 → resolve 默认引擎 → `config` 子命令 + `engine default` → 安全(0600/打码) → 测试 → tag `v0.4.2`
- [x] **0.5.0 (C)** ✅：serve extra → server 模块（复用 formats+keystore）→ `serve` 子命令 → 安全默认 → 测试 → README/docs → tag `v0.5.0`

**三组全部完成。** 每组遵循 CHANGELOG 顶部的"发版三步"。破坏性变更：三组均**无**（纯增量，裸名默认引擎缺省不变，故向后兼容）。

> 0.5.x 后续（已在 C 组非目标记录）：本地模型常驻缓存（LRU）、`stream=true` 流式、`asrkit ps`、`engine rm` 安全卸载。

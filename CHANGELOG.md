# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。**0.x 阶段的版本纪律**：
- **PATCH（0.4.0→0.4.1）= 日常**：新功能、修 bug 都走这里。绝大多数发布都是 PATCH。
- **MINOR（0.4→0.5）= 里程碑或破坏性变更**：慢、且有分量。参考 Ollama——两年才到 0.31。宁可在 0.4.x 里多磨几个补丁版，也不轻易动中间位数。
- **1.0** 留到"项目宪法"（model string 寻址 / adapter 契约 / CLI 核心命令）真正稳定、愿为其背书时。

> **发版三步**
> 1. 改版本号 —— 只改 `src/asrkit/__init__.py` 的 `__version__`(单一版本源,pyproject 自动同步),并同步 `tests/test_smoke.py` 的断言。
> 2. 记 CHANGELOG —— 在下方加一节 `## [X.Y.Z] - YYYY-MM-DD`,分 `### 新增 / 变更 / 修复` 三段;**破坏性变更要醒目标出**。
> 3. 打 tag 并推 —— `git tag -a vX.Y.Z -m "…" && git push origin main --tags`(tag 与 PyPI 版本一一对应)。

## [0.5.2] - 2026-07-07

主题：**批量 + 结果契约化 + 云端健壮性**（W0/W1/W2 三波累积;均向后兼容,唯退出码为醒目的行为微调）。

### 新增
- **批量 / 目录 / glob / stdin 输入**：`asrkit run/transcribe` 接受多个路径、目录（递归按扩展名收音频）、glob、`-`（stdin，`--stdin-format` 指定格式）。
- **`--batch`**：强制聚合输出（即便单文件），给脚本/评测稳定 NDJSON/csv。
- **结果契约化**：批量 `-f json` 出 **NDJSON**（每行加 `file`/`model`/`schema_version`）；新增 **csv/tsv**（11 列）；契约文档 `docs/result-contract.md`。
- 批量 `-o <dir>` 逐文件镜像；sherpa `metrics` 补 `duration_s`。
- **云端重试**：云端 adapter 走共享 Session + 分级重试/退避（`asrkit/_http.py`）。计费转写请求只重试 429/连接未建立（读超时/5xx 不重，避免重复计费）；doubao 轮询（只读）重试全部。`ASRKIT_HTTP_RETRIES` 可调（默认 3）。doubao 改用 uuid 幂等 `X-Api-Request-Id`。
- **`asrkit pull --url`**：从自定义地址下载（限 http/https；格式按内容识别）。HF 系引擎镜像用 `HF_ENDPOINT`（零配置）。
- openai/elevenlabs 上传补 200MB 大小守卫（与 dashscope/doubao 对齐）。
- **`pull` 多格式** —— `store.pull` 按内容（magic bytes）识别 `.tar.{bz2,gz,xz}` / 纯 tar / `.zip`,不再限死 bz2;`add-model --url` 给任意压缩包都能解（zip 加同款路径穿越防护）。

### 变更（行为）
- **退出码分级**（醒目）：从"几乎都 1"改为 `0` 成功 / `1` 意外 / `2` 用法错 / `3` 模型不存在 / `4` 转写失败。批量取最严（优先级 `1>3>4`）。单文件转写失败退出码可能由 `1` 变 `4`。

### 修复
- **transformers adapter 不再崩** —— pipeline 返回 dict 无 `text` 键时不再 `None.strip()` 抛错，改为兜底空串。

### 工程
- **CI 加固**：纳入 `ruff`（lint）+ `mypy`（类型）;`serve` 测试不再 skip、出覆盖率;新增 nightly 真实 E2E（`pull whisper-tiny` → 用其自带样本做真实推理）。

## [0.5.1] - 2026-07-07

主题：**加固**（一轮 fresh-eyes 代码评审后的缺陷修复,纯修复、无破坏性）。

### 修复
- **`serve` 不再卡死** —— 同步推理改用 `run_in_threadpool`,推理期间事件循环不再阻塞(此前推理时连 `/health` 都挂);并**按 model id 缓存已加载 adapter**,本地模型不再每请求重载。
- **`serve` 资源/信息安全** —— 上传临时文件的 fd 在 `finally` 兜底关闭(防 fd 泄漏);500 响应只回通用信息、细节记服务端(不再泄露文件路径/库版本)。
- **原子写 `~/.asrkit/models.json`**（`usermodels.add`）—— 改 tmp + `os.replace`,中途失败不再截断/损坏、丢失自定义模型。
- **路径穿越防御** —— `store.model_dir` 与 `add-model` 拒绝含 `../` 逃逸 models 根目录的 model id(防越界 `rm`/symlink)。
- **裸文件名不崩** —— `ASRKIT_CONFIG` / `ASRKIT_MODELS_JSON` 为裸文件名时 `makedirs("")` 不再抛错。
- **插件加载出声** —— 坏的第三方引擎插件从静默吞异常改为 `warnings.warn`(带插件名),便于排查。
- **云端大文件守卫** —— base64 内联上传(DashScope/豆包)超 200MB 时友好报错,防内存尖峰。

### 变更
- **whisper.cpp 遵循透明原则** —— 之前硬编码自动重采样,现改为遵循 `opts.convert`(默认格式不符即诚实报错,与其它 adapter 一致)。**行为变更**:非 16k 单声道输入需加 `--convert`。

## [0.5.0] - 2026-07-06

主题：**接口内核极简化——引擎/模型/云端全可插拔**。定位钉死：ASRKit 是个**接口**，base 只有接口 + 云端。

### ⚠️ 破坏性变更（安装契约）
- **`pip install asrkit` 不再自带本地引擎。** base 依赖砍到只剩 `requests`（云端内置，仅需 HTTP）。端侧需显式 `pip install "asrkit[local]"`（sherpa + 音频 io）。
  - 迁移：本地用户加装 `asrkit[local]`（或 `asrkit[all]`）。CLI/API/model string/寻址**均不变**——只是 base 更薄。
  - 用未安装的引擎 → 友好报错（带安装命令），不是 `ImportError`。
- 这是本项目 0.x 里第一个**真正的 MINOR**（破坏性变更 → MINOR，见顶部纪律）；不是版本虚涨。

### 变更
- **依赖分层**：`sherpa`(=默认端侧引擎，含 numpy/soundfile/soxr)、`whispercpp`、`faster-whisper`、`transformers`、`serve` 各自 extra；`local`=sherpa，`engines`=全引擎，`all`=引擎+serve；`cloud` 内置（空别名）。
- **单一版本源**已在 0.4.x 生效（hatchling 从 `__init__.py` 读）。
- 安装文档改为**分层 + 推荐 `pipx` / `uv tool install`**（当工具用，不折腾 Python 环境）。
- `asrkit engine install sherpa-onnx` 对齐到 `asrkit[sherpa]`（不再跳成 `local`）；未知引擎报错去掉过时的 "built-in" 措辞。
- 定位澄清：引擎（共享 pip 包）asrkit 只帮装（用对的环境）、不代卸（卸归 `pip uninstall`，你的环境你做主）；模型（asrkit 独占）`pull`/`rm` 对称管理。

### 说明
- 云端秒装即用（`pip install asrkit` → 只有 asrkit + requests）；`asrkit serve` 的**调用方**零 asrkit 依赖（走 HTTP）。

## [0.4.1] - 2026-07-06

主题：**完善——工具与服务**（对照 Ollama + LiteLLM，见 `docs/roadmap-cli-completeness.md` A/B/C 三组，合并为一个补丁版发布）。均为向后兼容增量。

### 新增 · 输出格式与 CLI（A）
- **输出格式** `--format {txt,json,srt,vtt}` + `-o/--output`（`run` 与 `transcribe` 均支持）：
  - `json` 输出全字段（含 segments/word_timestamps/metrics），脚本可解析。
  - `srt` / `vtt` 输出字幕（依赖模型返回 segments；无时间戳时诚实报错，不伪造）。
  - 新模块 `asrkit.formats.render`（`asrkit serve` 的 response_format 复用）。
- **`asrkit list` 增强**：`--json`（机器可读）、`--installed`（只看已装本地）、`--source cloud|local`；人读输出加体积列。
- **`--language`** 语言提示透传（`TranscribeOptions.lang_hint`），利于 Whisper 类模型。
- **`py.typed`** 类型标记：下游 IDE/mypy 可获取类型提示。
- **api 对称**：`asrkit.api.show()` / `remove()`，与 CLI 对齐。

### 新增 · 配置持久化（B）
- **`asrkit config`** —— 持久化配置（`~/.asrkit/config.json`，`$ASRKIT_CONFIG` 可覆盖）：
  - `config set-key <vendor> <key>`（单密钥）/ `--app-key --access-key`（火山等双密钥）。
  - `config set default-engine <name>` / `config set models-root <path>`。
  - `config get-key <vendor>` / `config list`（**一律打码，仅末 4 位**）/ `config path`。
- **凭据解析优先级**：显式 config > 环境变量 > **config.json keystore**（新兜底）。存一次，之后该 vendor 的模型自动带密钥。
- **默认引擎可切**：`asrkit engine default <name>`（= `config set default-engine`）——裸名解析改读配置（缺省仍 `local`/sherpa，向后兼容）。
- **models 根目录**可持久化：`config set models-root`（优先级：显式 > `ASRKIT_MODELS_ROOT` > config > 默认）。
- 安全：配置文件权限 **0600**；密钥**明文存储**（同 ollama/aws-cli 惯例），首次 `set-key` 提示；不放心者继续用环境变量。

### 新增 · 本地服务（C）
- **`asrkit serve`** —— OpenAI 兼容的本地转写服务（可选 extra `pip install "asrkit[serve]"`）：
  - `POST /v1/audio/transcriptions`（multipart：`file` / `model` / `language` / `response_format`），`response_format` 支持 `json`(默认) / `verbose_json` / `text` / `srt` / `vtt`。
  - `GET /v1/models`（OpenAI list 结构）、`GET /health`。
  - 任何 OpenAI 客户端改 `base_url` 即可调用 ASRKit 背后的全部端云模型；云端密钥走 keystore，无需每次传。
- 透明原则：上传文件按原始字节落临时文件，不解码/不重采样，请求结束清理。
- 安全默认：绑 `127.0.0.1`（仅本机）；`--host 0.0.0.0` 显式警告。懒加载：基础安装不受影响，缺 extra 时友好报错。
- 已知局限（后续）：本地模型每请求重新加载（无常驻缓存）；无 `stream=true` / 无鉴权。

### 修复
- 文档-代码缺口：`docs/engines-and-addressing.md` 中 `asrkit engine rm` 标为"路线"（未实现）。

## [0.4.0] - 2026-07-06

主题：**云端第 2 波** —— 火山豆包（双版本）、阿里百炼、ElevenLabs、OpenAI Whisper 全部接入（协议移植自作者已真机接通的 asr_bench）。

### 新增
- **火山引擎 / 豆包**（`doubao` 协议，submit + poll）：`doubao/auc-2`（2.0 Seed，`volc.seedasr.auc`）与 `doubao/auc-1`（1.0，`volc.bigasr.auc`）。双鉴权：新版单 `api_key`（`x-api-key`）或旧版 `app_key` + `access_key`。
- **阿里云百炼 / DashScope**：
  - `dashscope/qwen3-asr-flash`（`qwen` 协议，compatible chat/completions，input_audio-only）。
  - `dashscope/fun-asr-flash`（`funasr-flash` 协议，原生 multimodal-generation）。
  - `dashscope/qwen-omni-plus` / `dashscope/qwen-omni-flash`（`qwen-omni` 协议，audio LLM，标 experimental）。
- **ElevenLabs Scribe**（`elevenlabs` 协议，multipart + `xi-api-key`）：`elevenlabs/scribe-v1`。
- **OpenAI Whisper**：`openai/whisper-1`；**硅基流动 TeleSpeech**：`siliconflow/telespeech`（复用 openai 协议）。
- **CLI**：`--app-key` / `--access-key`（火山双密钥）。
- **环境变量兜底扩展**：除 `<VENDOR>_API_KEY` 外，双密钥厂商支持 `<VENDOR>_APP_KEY` / `<VENDOR>_ACCESS_KEY`（如 `DOUBAO_APP_KEY` / `DOUBAO_ACCESS_KEY`）。

### 说明
- 云端 adapter 沿用透明原则：原始文件字节级上传，不解码/不重采样。
- 所有 adapter 不抛异常，错误进 `TranscribeResult.error`。

## [0.3.1] - 2026-07-06

### 新增
- **`asrkit add-model`** —— 一条命令注册自定义 sherpa 模型（写入 `~/.asrkit/models.json`），无需手动编辑文件：
  - 知道地址：`asrkit add-model local/my-model --url <tarball> --arch senseVoice --langs zh,en` → `asrkit pull`。
  - 已有文件：加 `--model-dir <dir>` 软链到位、立即"已安装"（免下载）。

## [0.3.0] - 2026-07-06

主题：**全开放** —— 引擎开放 + 模型开放。

### 新增
- **entry-point 插件机制**：第三方可发布 `asrkit-<engine>` 包，用 `[project.entry-points."asrkit.adapters"]` 声明；`pip install` 即自动发现注册（坏插件不连坐）。加引擎无需改核心。
- **whisper.cpp 引擎**（`pip install "asrkit[whispercpp]"`）：`whispercpp/<model>`，超轻量（无 torch/onnx）。
- **sherpa 模型开放：用户模型注册表** `~/.asrkit/models.json`（或 `$ASRKIT_MODELS_JSON`）——登记任意 sherpa 模型（id/download_url/config_type/langs）即 `pull` 即用，无需改包。
- 至此：四个本地引擎（sherpa-onnx / faster-whisper / transformers / whisper.cpp）+ 云端 + 第三方插件 + 开放寻址（transformers 任意 HF id、sherpa 用户注册表）。

### 说明
- 默认仍只带 sherpa-onnx；引擎按需装或走插件。

## [0.2.0] - 未发布

### 新增
- **多引擎**：引擎作为可选组件，通过同一接口 `引擎/模型` 寻址。新增两个引擎：
  - **faster-whisper**（`pip install "asrkit[faster-whisper]"`）：`faster-whisper/<model>`（如 `faster-whisper/large-v3`）；HF 自动下载、自带长音频分块。
  - **transformers**（`pip install "asrkit[transformers]"`，含 torch）：**开放寻址 `transformers/<任意 HF 模型 id>`**——接入整个 HuggingFace ASR 生态，含 LLM 架构 SOTA 模型（大模型建议 GPU）。
- `asrkit engine list` / `asrkit engine install <name>` 管理引擎（install = `sys.executable -m pip` 装对应 extra，回显命令）。
- **安装机制可插拔**：`is_installed` / `install` 下沉到各 adapter（sherpa 走 release tarball；faster-whisper 走 HF 缓存）。缺引擎时友好报错（带安装命令），不崩。

### 说明
- 默认仍只带 sherpa-onnx；其它引擎按需装。entry-point 第三方引擎插件为后续路线。

## [0.1.2] - 2026-07-06

### 新增
- `asrkit --version` / `-V` 显示版本。
- `asrkit rm <model>` 删除已下载的本地模型（补全 pull/rm 生命周期，Ollama 对齐）。
- **本地模型名可省略 `local/` 前缀**：`asrkit pull sensevoice` = `local/sensevoice`（含精度别名 `sensevoice:fp32`）。全名与云端 `provider/model` 不受影响；命名空间仍是正式名（未来多引擎不打脸）。
- **终端输出全英文**：CLI 帮助/报错/提示/模型显示名/`show` 字段全部英文（面向全球开发者；代码注释与设计文档仍为中文）。

### 说明
- 无 `update` 命令：模型按 id 钉死（换模型即 `pull` 另一个 id）；升级软件包用 `pip install -U asrkit`。

## [0.1.1] - 2026-07-06

### 变更
- **安装简化**：`pip install asrkit` 一步装好端云接口（sherpa-onnx + 云端 + 音频）——运行时依赖从 extras 提升为基础依赖，不再需要 `asrkit[all]`。模型权重仍按需 `asrkit pull`、云端填 API key。
- 新增 `asrkit show <model>` 显示模型详情（含许可证展示位）。

## [0.1.0] - 2026-07-06

首个有功能的版本：一套接口跑遍端云。

### 新增
- 统一接口：Python `transcribe()` + CLI（`list` / `pull` / `run` / `transcribe`）。
- 端侧 **47 个 sherpa-onnx 模型**，`pull` 即用（Ollama 式），支持精度标签寻址 `base:tag`（如 `local/sensevoice:fp32`）。
- 云端 **OpenAI 兼容协议**（硅基流动 SenseVoice）；`provider/model` 路由。
- **透明音频**：内核零处理；云端原样上传原始文件；本地格式守卫，采样率/声道/格式不符即诚实报错；`--convert` / `--segment` 为 opt-in；长音频超窗给 `warnings`。
- **pull 安全**：tar 路径穿越防护、下载超时、可选 sha256 校验、原子安装（`.partial` + rename）。
- 云端 API Key 环境变量兜底 `<VENDOR>_API_KEY`。

### 说明
- 评测 / bench 横评、流式转写、serve 常驻为**后续路线项**，本版不含。
- 契约见 `docs/adapter-spec.md`（音频透明原则二次修订后待重评审冻结）。

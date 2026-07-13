# ASRKit 全生命周期审核（综合评价底稿）

> **历史快照，不再维护。** 本文用于保留当时的对标与审计结论；当前项目事实以 [`../project-overview.md`](../project-overview.md)，当前优先级以 [`../roadmap.md`](../roadmap.md) 为准。

> 对标一线开源工具（CLI：ripgrep / gh / kubectl / httpie；模型：Ollama / HuggingFace CLI / faster-whisper / whisper.cpp / yt-dlp），
> 按**数据/用户的生命周期**逐段审 asrkit 的不足。这是 [roadmap.md](../roadmap.md) 的详细版底稿；优先级标记 🔴高 / 🟠中 / 🟡低 / 🟢已不错。

---

## ① 发现模型（discover）

- 现状：`list`（--json/--installed/--source + 体积）、`show`。71 个模型平铺。
- 标杆：Ollama 模型库+标签；HF 搜索/筛选；gh/kubectl 的 `--json`+`--jq`。
- 差距：
  - 🔴 71 个模型只能"滚屏",缺按语言/架构/能力筛选：`asrkit list --lang zh` / `asrkit search whisper`。新手不知选谁。
  - 🟠 无"推荐/默认"引导（Ollama 有 `llama3` 心智锚点）——该给"中文首选 X、英文首选 Y"。
  - 🟠 无 shell 补全（bash/zsh/fish）。模型名一长串，补全是巨大体验提升。
  - 🟡 `show` 可更丰富：下载前体积、许可证链接、示例命令、能力标注。

## ② 获取（acquire：pull / engine install）

- 现状：`pull` 有 MB 进度、原子换入、sha256；`engine install` 装对环境。
- 标杆：Ollama/yt-dlp 带 %/速度/ETA 进度条 + 断点续传；HF 有镜像；pip 有缓存。
- 差距：
  - 🔴 **中国网络现实被忽略（核心受众！）**：sherpa 走 GitHub release、faster-whisper/transformers 走 HuggingFace，国内又慢又常被墙。缺 HF 镜像/`HF_ENDPOINT`、下载源可切换。**高频痛点。**
  - 🟠 无断点续传（大模型下一半断了要重来）。
  - 🟡 进度是裸 MB 打印，非真进度条；下载前无磁盘空间检查。

## ③ 配置（configure）

- 现状：`config` 存密钥/默认引擎/models 目录，0600+打码。相对完善。
- 差距：🟡 `config edit`（打开文件）、补全安装命令。

## ④ 输入·音频（明显短板）

- 现状：只接单个文件路径。透明原则：云端原样上传、本地要可解码 wav（否则 --convert）。
- 标杆：ripgrep/httpie 吃 stdin/管道；whisper.cpp/faster-whisper 用 ffmpeg 啥格式都吃；yt-dlp 吃 URL。
- 差距：
  - 🔴 无 stdin/管道：`cat a.wav | asrkit transcribe -`。
  - 🔴 无批量/目录/glob：`asrkit transcribe *.wav` 或传文件夹。ASR 常批处理，评测项目也刚需。
  - 🟠 无 URL 输入；无麦克风/实时输入。
  - 🟡 格式便利 vs 透明的取舍：现在"格式不符即报错、要转得 --convert"哲学纯粹但不便；多数用户期望"丢个 mp3 就能转"。可考虑默认仍报错但更强引导，或对 CLI 放宽默认。
  - 🟡 无音频预检：`asrkit inspect a.wav`（时长/采样率/声道）。

## ⑤ 处理·运行（run）

- 现状：language/convert/segment/format；sherpa 长音频靠 opt-in VAD（需自备 VAD 模型）。
- 标杆：faster-whisper 自动分块；whisper 生态有词级时间戳、说话人分离；下载/推理有进度。
- 差距：
  - 🔴 无流式（`transcribe_stream` 声明未实现）。实时字幕/语音输入法刚需。
  - 🟠 sherpa 长音频体验弱（要自备 `ASRKIT_VAD_MODEL`，faster-whisper 自动搞定）；不一致、有门槛。
  - 🟠 长转写无进度（1 小时文件跑完前毫无反馈）。
  - 🟡 词级时间戳未在 CLI 暴露；无置信度、无说话人分离；云端调用无统一超时/取消（豆包固定 30s 轮询）。

## ⑥ 输出·结果

- 现状：txt/json/srt/vtt + `-o`。
- 标杆：kubectl `-o json/yaml/wide/custom`、gh `--json` 当契约；httpie/bat 美化；明确退出码。
- 差距：
  - 🟠 JSON 不是"契约"：dataclass 裸 dump，无版本化/文档化。脚本消费者需稳定、有文档的 schema。
  - 🟠 无 csv/tsv（批量聚合、评测项目直接相关）。
  - 🟠 退出码不分级（配置错/模型不存在/转写失败都返 1）。
  - 🟡 无 `--quiet`/`--verbose`；无颜色/美化（NO_COLOR 未尊重）；无结果缓存。

## ⑦ 维护（maintain）

- 现状：`rm`、`list --installed`+体积。
- 差距：🟠 `asrkit doctor`（引擎/密钥/目录/网络一键体检）；🟡 `prune`/总用量视图、update/更新检查。

## ⑧ 集成（integrate：库 / 服务 / 脚本）

- 现状：库 API、OpenAI 兼容 serve（0.5.1 加缓存）。
- 标杆：gh 扩展机制；kubectl 补全+插件；man page、NO_COLOR、稳定退出码。
- 差距：🟠 无 shell 补全；🟡 无 man page、`--no-color`/NO_COLOR 未尊重；库返回契约（JSON schema）该文档化。

---

## 横切：开源健康度

- 🟠 社区 hygiene 缺失：无 `CONTRIBUTING.md` / issue·PR 模板 / `CODE_OF_CONDUCT`。
- 🟠 CI 单薄：缺 lint(ruff)/类型(mypy)/覆盖率；serve 测试默认 skip。
- 🟡 无托管文档站、无 cookbook/示例集、无自动 API reference。
- 🟢 已不错：版本纪律、CHANGELOG、透明原则、错误友好度、0.5.1 加固——别丢。

---

## 综合评价 + Top 5

**一句话**：内核与架构一线水准（定位清晰、可插拔、干净），但外围生命周期还停在"能用",离"顺手/专业"差一层——差在**输入广度、结果契约化、发现可扩展、中国网络现实**。

最高杠杆的 5 件（痛 × 对受众/场景相关度）：

1. 🔴 **音频输入广度**：stdin + 批量/目录/glob。CLI 基本功，评测项目也要。
2. 🔴 **下载源/镜像**：HF 镜像 + 源可切 + 断点续传。**用户在国内，最实。**
3. 🔴 **流式**：最小可用流式。语音输入法/实时 Agent 岗最看重（求职方向）。
4. 🟠 **结果契约化**：文档化稳定 JSON + csv/tsv + 分级退出码。可靠脚本化/被评测项目消费。
5. 🟠 **发现 + 补全**：按语言/架构筛选 + shell 补全。驾驭 71 个模型。

> 1、3、4 与两个战略目标（评测独立项目 + 求语音团队）重叠，优先做一举多得。🟡 类（美化、man page、缓存）晚点再说。

> 版本纪律提醒：以上任何一项落地都默认走 PATCH；升版本号前先向人类提议、等批准（见 CHANGELOG 顶部策略）。

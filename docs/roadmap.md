# ASRKit 路线图 / 待办

> 活文档:记录**尚未做**的改进与**明确不做**的决定。初期"完善三组(输出格式/config/serve)"的详细计划见
> [roadmap-cli-completeness.md](roadmap-cli-completeness.md)(已全部完成)。
> 版本策略见 [CHANGELOG](../CHANGELOG.md):0.x 阶段功能/修复默认走 PATCH,MINOR 只留破坏性/里程碑。

---

## 已完成(近期)

- **0.5.0** 接口内核极简化(base 只留接口+云端,引擎全 opt-in)。
- **0.5.1** 加固(一轮 fresh-eyes 评审后):serve 不再卡死 + **按 model id 缓存 adapter**(本地模型不再每请求重载)、原子写 models.json、路径穿越防御、裸文件名不崩、插件告警、云端大文件守卫。
- **W0 · 安全网(未发版,待下个 PATCH)**:
  - **`pull` 多格式**:`store.pull` 按内容(magic bytes)识别 tar.{bz2,gz,xz}/纯 tar/zip,不再硬编码 bz2;`add-model --url` 给任意压缩包都能解(zip 加同款防穿越)。
  - **CI 加固(已完成)**:`ruff`(lint)+ `mypy` 入 CI(与 test 并行);`test` job 装 `.[cloud,serve,dev]` 让 **serve 测试不再 skip** + 出覆盖率;新增 `dev` extra。顺带修 2 个真·潜在 bug(transformers `None.strip()` 崩、cli 变量遮蔽 ArgumentParser)。
  - **最小真实 E2E(已完成)**:`tests/test_e2e.py` + `.github/workflows/e2e.yml` nightly——`pull whisper-tiny` → 用其自带 test_wavs 做真实推理 → 断言无 error 且非空。默认 skip,`ASRKIT_E2E=1` 才跑。
- **W1 · 批量输入 + 结果契约化(未发版)**:多文件/glob/目录递归/stdin(`-`)输入;`--batch` 强制聚合;批量 `-f json`=**NDJSON**(带 `file`/`model`/`schema_version`)、新增 **csv/tsv**(11 列)、`-o <目录>` 逐文件镜像;**分级退出码** `0/1/2/3/4`(批量优先级 `1>3>4`);契约文档 `docs/result-contract.md`;sherpa metrics 补 `duration_s`。批量复用同一 adapter(本地模型不每文件重载)。
- **W2 · 云端重试 + 下载源可自定义(未发版)**:
  - **云端 HTTP 健壮性(已完成)**:新 `asrkit/_http.py`——线程局部 `Session` + 分级重试/退避。**成本安全**:计费转写只重 `429`+`ConnectTimeout`,不重 5xx/读超时(避免重复计费);只读 doubao 轮询重全部。`ASRKIT_HTTP_RETRIES` 可调(默认 3);429 认 `Retry-After`。doubao 改用 uuid 幂等 `X-Api-Request-Id` 并 submit/query 复用;openai/elevenlabs 补 200MB 守卫。
  - **下载源可自定义(已完成)**:`asrkit pull <model> --url <tarball>` 一次性覆盖(限 http/https,经 install 边界透传);HF 系引擎镜像用 `HF_ENDPOINT`(底层库自理,零代码)。**不做**持久 `download-base`/镜像配置(YAGNI)。
- **W3 · 发现 + 元数据 + 体检(未发版,待下个 PATCH)**:
  - **字幕落地**:whisper 家族(faster-whisper / whispercpp / openai/whisper-1)返回 `segments`,`srt/vtt` 对这些模型可用(此前全模型只报错)。
  - **选项诚实**:显式"忽略语言提示"的模型(如 SenseVoice)传 `--language` 给 warning 而非静默丢弃;`capabilities.language_hint` 三态判读;whispercpp 现透传 `--language`。
  - **发现**:`asrkit list --lang/--arch` 筛选、`asrkit search <term>`、`asrkit list --ids`(裸 id,供补全)。
  - **元数据修真**:广多语模型标 `capabilities.multilingual`(`--lang X` 作候选返回);SenseVoice 语言补全为 zh/en/ja/ko/yue。
  - **shell 补全(已完成)**:`asrkit completion <bash|zsh|fish>` 输出补全脚本(子命令 + 动态 model 名 + 格式值)。
  - **`asrkit doctor`(已完成)**:一条命令体检引擎/密钥(只报有无)/models 目录可写/config 完整;`--net` 加下载源/云端可达。硬问题(目录不可写/config 损坏)退非零;纯只读、零新依赖、网络 opt-in。
- **W4 · 最小流式(未发版,待下个 PATCH)**:`asrkit stream <model> <audio>` + `api.transcribe_stream` —— 对 sherpa online 模型逐块解码、边喂边出增量文本(live→stderr 覆盖行、final→stdout 可管道);**首次行使 `PartialResult` 契约**(只用 text+is_final,committed/partial 按契约留空)——1.0 前"契约行使一次"的关卡。文件分块、零新依赖。麦克风/serve 流式/词级时间戳明确留后续。

---

## 待办(按优先级)

### P3 · 功能补全(按需)

- **流式扩面** —— 最小文件流式已落地(W4)。后续:**麦克风输入**(需 sounddevice)、**serve 流式端点**(SSE/WebSocket)、**`committed`/`partial` 精细化**(仅追加已定稿,契约已预留字段)、词级时间戳。均为独立后续刀。
- **`--verbose` / 日志** —— serve 与调试用;现在信息只进 `result.error`,服务端不好排障。

### P4 · 打磨

- **`asrkit engine rm`(劝告版)** —— 打印手动 `pip uninstall <包>` + 提醒(可能被别的项目共享),并重置默认引擎若指向它;**绝不代跑 uninstall**。让命令面完整而不越权。

---

## 生态方向(独立项目,非本仓库)

- **asrbench —— 评测/选型工具(独立 repo,依赖 asrkit,单向)。** 顶层设计见 [asrbench-blueprint.md](asrbench-blueprint.md)(定位/方法论/研究问题/论文路径)。 让开发者在自己的音频上、端云一起横评 ASR 模型并选型。**定案:新开项目,不加进 asrkit 模块**(否则打脸"接口内核极小"的定位;依赖方向 asrbench→asrkit)。asrkit 只管跑模型出文本+延迟/RTF/成本;asrbench 管它不做的:归一化正确的 WER/CER、多维对比、数据集、报告。老的 `asr_bench`(Flutter/真机)是**只读参考**,新项目干净重构。待定三岔路:有参考 vs 无参考、输出形态(CLI 表/HTML/榜单)、面向个人选型 vs 公开榜。

## 明确不做(已讨论定案,勿重复起意)

- **asrkit 自动 `pip uninstall` 引擎** —— 引擎是**共享 pip 包**,asrkit 无产权,删了会连累别的项目。装可帮(装对环境)、卸归用户。
- **为"卸引擎"引入隔离环境** —— 引擎体积小(几十 MB,torch 除外),不卸也罢;占体积的是模型,而模型 `pull`/`rm` 已对称干净。隔离得不偿失。
- **`engine disable` 开关** —— YAGNI:引擎既然不用卸,就不需要"不删包地拔"。
- **把 base 依赖装回去** —— 定位是"接口内核极小",引擎按需装是刻意设计,不回退。

---

## 所有权模型(一句话备忘)

- **模型 = asrkit 独占**(下到 `~/.asrkit/models`)→ `pull` / `rm` 对称、干净。
- **引擎 = 共享 pip 包** → `asrkit engine install`(帮你装对环境)/ 卸载归 `pip uninstall`(你的环境你做主)。
- **云端 = 内置**(仅 `requests`)。

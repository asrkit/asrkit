# ASRKit 路线图 / 当前执行队列

> 当前事实快照:2026-07-23,已发布版本为 0.5.5(PyPI + tag)。发布历史只以 [CHANGELOG](../CHANGELOG.md) 为准;产品边界见 [product-form.md](product-form.md)。
> 本文是**唯一当前执行队列**。历史评审、spec 和 plan 在 [archive/](archive/) 中保留原始时点,不再作为当前待办。

---

## 已完成能力

- **0.5.0**:基础安装收缩为接口 + 云端,全部本地引擎改为 opt-in extras。
- **0.5.1**:serve 线程池与 adapter 缓存、原子配置写入、路径穿越和临时资源加固。
- **0.5.2**:批量/目录/glob/stdin、NDJSON/csv/tsv、分级退出码、成本安全 HTTP 重试、下载源覆盖和多格式模型包。
- **0.5.3**:segments/字幕、选项诚实告警、元数据筛选、搜索/补全/doctor、最小文件流式。
- **0.5.4**:流式端点分段、麦克风、serve SSE、日志、`engine rm`、有界 LRU、豆包长音频轮询与 `sherpa/` 寻址正名。
- **0.5.5**:HTTP/adapter/缓存/归档安全边界、CLI 模块化、可信构建与安装 smoke、cloud-only daemon/embedded 契约及 Linux 冻结原型验证。

当前注册表:71 个模型(61 local + 10 cloud),其中 sherpa 47 个;Python/CLI/HTTP 三个入口均已落地。HTTP 兼容范围见 [openai-compatibility.md](openai-compatibility.md)。

---

## 0.5.5 已发布的工程收口

1. **CLI 模块拆分**:`cli.py` 已收缩为入口与分发表,实现进入 `cli_commands/`;已锁定全部 14 个命令分发、帮助/退出码、`cli.api` mock seam 和可选依赖延迟导入,源码路径全量验证通过。
2. **`add-model --model-dir` 外部软链**:允许 models root 内的 leaf symlink 指向有效外部目录;父路径软链、递归源目录、空/`.`/`..` ID 和 runtime `model_dir` 破坏性写删仍被拒绝;`rm` 只 unlink,不完整外链不被 `pull` 覆盖。已有 CLI 端到端与安全回归测试。
3. **让真实 E2E 不能假绿**:真实测试已移出默认单测目录并由 nightly 显式调用;使用仓库固定、注明来源与许可的 LibriSpeech 音频和规范 `sherpa/whisper-tiny` 寻址;依赖、fixture、下载或推理任一失败都会直接使任务失败,不再存在 `skip` 成功路径。
4. **锁住薄内核**:独立子进程强制从当前 `src/` 加载代码,隔离本机配置和第三方插件,覆盖注册表、五类 adapter 构造/安装探测、CLI 列表及 `server`/`mic` 轻量导入;任何 torch/transformers/sherpa/numpy/fastapi 等可选运行时的提前 import 都会直接失败。
5. **统一开发验证入口**:pytest 配置固定优先加载当前 `src/`,冒烟测试断言 `asrkit.__file__` 指向本 checkout,CLI 子进程显式继承源码路径;CI 统一使用 `python -m` 命令并在 Python 3.13 构建 wheel、临时安装后验证 CLI 与模型注册。
6. **cloud-only 与 daemon 边界**:当前源码已将 `full/cloud` 加载逻辑放入独立 `profiles/`,并建立 `daemon/` 命令、安全、设置和生命周期边界；cloud 子进程只加载 10 个内置云模型,跳过本地 adapter、模型表、用户模型和 entry-point 插件。隔离、HTTP model list、命令分发与 wheel 命令所有权均有回归验证。
7. **embedded 与安全契约**:`--embedded` 默认随机端口,通过纯 stdout NDJSON 报告 ready/shutdown；强制 loopback、宿主 token、私有 data dir、父进程监控和信号优雅退出。网关已具备 200 MiB 上传、4 并发、300 秒转写和 10 秒关停默认边界,并覆盖 401/413/429/504 与临时文件清理。
8. **macOS arm64 冻结原型**:已建立隔离 venv、PyInstaller `onedir` spec、自定义 Uvicorn HTTP hook 和冻结产物 smoke；约 32 MiB 的本地产物已在清除 Python/Conda/ASRKit 环境并收缩 PATH 的子进程中通过 version/help、ready/shutdown、health、鉴权、10 云模型和父进程退出验证。产物不包含本地 adapter 或其重依赖,动态库无开发机绝对路径引用。

以上源码与 Python 模块能力已经随 0.5.5 发布。自包含 `asrkit-cloud` 二进制仍只是构建原型,尚未作为 GitHub Release 资产发布；当前开发焦点转入官方 SDK 契约、真实云转写和其余平台的发行验证。

## P0 · `asrkit-cloud` 产品形态验证

1. **已完成（0.5.5 Python 模块）**:cloud-only 加载入口与 `asrkit-cloud` 内部构建入口；只注册 10 个内置云模型,不加载本地引擎、插件或用户模型；完整 Python wheel 只占用 `asrkit` 命令。
2. **已完成（0.5.5 Python 模块）**:embedded 契约:`--embedded --port 0`、ready/shutdown NDJSON、父进程监控、显式 data dir 和信号优雅关停。
3. **已完成（0.5.5 Python 模块）**:loopback 强制、宿主随机 bearer token、上传上限、并发/超时与断连清理。
4. **已完成（macOS arm64 本机原型）**:用隔离环境构建 PyInstaller `onedir`,以干净子进程 smoke 锁定运行目录、HTTP 栈、cloud-only 模型和 embedded 生命周期；`onefile` 后置。
5. **Linux x64 无 Python 验证已完成**:GitHub Actions [run 29396109425](https://github.com/asrkit/asrkit/actions/runs/29396109425) 已构建 onedir,并在不含 Python 的只读 Debian 容器通过完整 embedded HTTP 生命周期；可复现 tar.gz、SHA256 和临时 artifact 均已生成。仍需以受控密钥完成真实云转写,并验证其余平台。
6. 建立 macOS arm64/x64、Windows x64、Linux glibc arm64/x64 构建和 smoke matrix;签名、SHA256、SBOM 与第三方许可证属于交付物的一部分。
7. 在同一仓库实现 npm `asrkit` 薄 SDK,通过内部 `@asrkit/cloud-<platform>` 包按 OS/CPU/libc 携带运行时;不复制云厂 adapter,不使用首版 `postinstall` 下载。
8. 验证 npm/pnpm、Node 和 Electron `extraResources` 集成,让产品开发者只需安装 `asrkit`,无需手工选择或管理二进制。
9. **部分完成**:官方 OpenAI Python 2.47.0/Node 6.48.0 SDK 已在 CI 对模型列表和 `json`/`text`/`verbose_json` 做硬失败契约测试；DashScope + SiliconFlow/Doubao 的受保护手动 E2E 已落地,待配置环境密钥并取得首轮两厂远端证据。
10. 接入一个真实桌面应用,验证随宿主启动、退出和升级。

详细规范见 [embedding-and-distribution.md](embedding-and-distribution.md)。源码保持单仓库,PyPI/npm/平台运行时/Docker 是同一项目的不同产物。纯 Go 第二代必须等待冻结版获得真实采用后再决定。

## P1 · 交付与供应链

- 补齐本地模型的 `license`/官方来源数据;商用前不能依赖当前空字段。
- 为可下载模型补 sha256 或可信 manifest;至少对缺校验和与明文 HTTP 源给醒目警告。
- 增加模型 URL/资产健康检查,避免 47 条手维护下载源静默腐烂。
- 增加 Windows 验证或在支持矩阵中明确未验证;二进制目标另需 macOS/Linux/Windows 构建与签名。
- npm 平台包使用精确版本、平台元数据和发布 provenance;主包后发,不得指向缺失平台产物。
- 增加依赖安全检查；sdist 重建、wheel 双路径安装 smoke 与发布产物校验已在 0.5.5 CI 落地。
- **已完成**:所有 GitHub Actions 升级到 Node 24 代际并固定官方提交 SHA；发布流分别验证 GitHub Release 可见和精确 PyPI 版本可用,避免把二者混为一次成功。
- 建 adapter/provider conformance fixtures,约束请求、响应、错误和重试语义。

## P2 · 生态与专业字段

- **asrbench**:保持独立仓库、单向依赖 `asrbench -> asrkit`;启动时机服从本路线图,先做小规模中文端云验收,不直接追公开大榜。
- 词级时间戳、`ts_ms` 和更丰富的置信度:有明确消费者后做。
- `enable_punctuation`/`cost_estimate` 等空心字段:要么填实,要么明确标为预留,不继续扩大未兑现契约。
- WebSocket/Realtime:当前 SSE 已覆盖单向文件流式;双向低延迟需求明确后再立项。
- 第三方 adapter 模板、兼容测试和插件目录:在核心契约经过真实消费者验证后推进。

---

## 明确不做

- 自动 `pip uninstall` 引擎、为卸载引擎自建隔离环境、`engine disable`。
- 把重引擎重新塞回 base 依赖。
- 在核心中吞入 diarization、强制对齐、自研 VAD/降噪或 GUI。
- 没有真实用户需求时按供应商名单扩充云厂长尾。
- 把不同发行物拆成需要同步 adapter、catalog 和契约的独立 Git 仓库。
- 在 `asrkit-cloud` 冻结版尚未被采用前重写 Go 或开发 `asrkit-sherpa` 原生口味。
- 由 ASRKit 自动静默更新宿主应用携带的 Sidecar。

## 完成标准

下一阶段不是以“新增多少模型/命令”衡量,而以这些证据衡量:源码测试真实命中当前 checkout、OpenAI 客户端替换成功、真实 provider E2E 通过、主流平台分发可启动、`npm install asrkit` 能在 Node/Electron 完成生命周期、协议无破坏漂移、外部产品完成集成。

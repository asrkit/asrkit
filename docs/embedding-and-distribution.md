# ASRKit 嵌入与无依赖分发规范

> 状态:**目标设计 + 当前源码契约**(2026-07-13)。cloud-only profile、embedded 生命周期和网关安全边界已在未发布源码实现；第一代自包含构建和无系统 Python 环境验证仍未完成。
> 北极星与边界见 [product-form.md](product-form.md);本文只讨论云端网关的分发和集成,不改变本地引擎仍以 Python 侧为主的决定。
> 已发布的 0.5.4 只有 Python `asrkit serve`。当前未发布源码已把 `profiles/` 与 `daemon/` 物理分开，实现只含 10 个云模型的进程 profile、embedded 握手、Bearer 鉴权、资源限制和父进程监控；完整 Python wheel 仍不安装 `asrkitd` 命令。尚无自包含二进制。当前 HTTP 子集见 [openai-compatibility.md](openai-compatibility.md)。

---

## 一、目标与术语

“无依赖集成”指:

- 最终用户不安装 Python、pip、venv、ASRKit 或系统服务;
- 不要求管理员权限,不修改 PATH,不污染系统环境;
- Sidecar 随宿主应用出现、退出和升级;
- 宿主只依赖 OpenAI-compatible HTTP,不依赖 Python ABI;
- 平台标准能力(进程、loopback、TLS 根证书、文件系统)不算外部运行时依赖。

它不等于“一个文件适配所有操作系统”,也不等于“第一代二进制内部完全没有 CPython”。第一代目标是 **no Python installation required**;纯 Go 静态运行时是经真实需求验证后的第二代实现选择。

## 二、最终产品结构

```text
一份协议
├── model string: source/model[:tag]
├── TranscribeResult / Error / Capabilities
└── OpenAI-compatible /v1/audio/transcriptions

两个发行物
├── asrkit (PyPI)
│   └── Python API + CLI + 云端 + 可选本地引擎
└── asrkitd (平台二进制 / Docker)
    └── 云端 provider + OpenAI-compatible Sidecar

两类后端
├── 云端:内置于两种发行物
└── 本地:默认只属于 Python 发行物;非 Python 产品用自身原生引擎
```

`asrkitd` 是非 Python 产品的**目标旗舰集成物**。当前源码模块已能验证完整的 cloud-only Sidecar 协议,但不向完整 wheel 注册同名命令；完成冻结分发后,宿主应用才会把 `asrkitd` 自包含产物放进资源目录,启动为私有子进程,读取 ready 消息,然后用 OpenAI SDK 或普通 HTTP 调用。

## 三、宿主集成流程

### 3.1 发布包布局

ASRKit 按 OS/架构发布独立产物:

```text
asrkitd-vX.Y.Z/
├── asrkitd-darwin-arm64
├── asrkitd-darwin-x64
├── asrkitd-linux-x64
├── asrkitd-linux-arm64
├── asrkitd-windows-x64.exe
├── SHA256SUMS
├── LICENSE
└── THIRD_PARTY_NOTICES
```

产品开发者在**构建期**选择目标平台文件并放入应用资源目录;最终用户不单独下载或安装 Sidecar。

Electron/macOS 示例:

```text
MyProduct.app/
└── Contents/
    ├── MacOS/MyProduct
    └── Resources/asrkit/asrkitd
```

Windows 示例:

```text
MyProduct/
├── MyProduct.exe
└── resources/asrkitd.exe
```

### 3.2 启动握手

嵌入模式使用随机空闲端口,避免固定端口冲突:

```bash
ASRKIT_GATEWAY_TOKEN=<宿主每次启动生成的至少32字符随机值> \
asrkitd \
  --embedded \
  --host 127.0.0.1 \
  --port 0 \
  --parent-pid 12345 \
  --data-dir <宿主应用数据目录>
```

当前源码实现启动成功后,stdout 输出一条 NDJSON 控制消息:

```json
{"event":"ready","base_url":"http://127.0.0.1:52137/v1","pid":23456,"protocol_version":1}
```

`protocol_version: 1` 是当前未发布源码的 embedded 协议版本；只有随正式发行物发布后才成为公开兼容承诺。

约定:

- stdout 仅输出 `ready`/`shutdown` 等机器控制消息;
- 日志全部写 stderr,不得污染握手通道;
- `--port 0` 由操作系统选择空闲端口;
- embedded 只接受精确的 `127.0.0.1` 或 `::1`;
- token 只从 `ASRKIT_GATEWAY_TOKEN` 读取,不得通过命令行传递;
- `--parent-pid` 对应进程消失时 Sidecar 自动退出;
- 宿主正常退出时主动终止 Sidecar;
- Sidecar 应响应 SIGTERM/Windows terminate 并清理临时文件。

正常退出前会输出第二条控制消息,其中 reason 当前为 `signal`、`parent_exited` 或 `server_stopped`:

```json
{"event":"shutdown","reason":"parent_exited"}
```

### 3.3 调用

宿主拿到 `base_url` 后,使用现有 OpenAI 客户端:

```text
POST {base_url}/audio/transcriptions
Authorization: Bearer <gateway-token>
Content-Type: multipart/form-data

model=dashscope/qwen3-asr-flash
file=@meeting.mp3
```

宿主不需要知道 DashScope、Doubao 等协议差异。切换后端只改变 model string。

## 四、密钥与安全边界

### 4.1 密钥所有权

嵌入模式不默认读取用户全局 `~/.asrkit/config.json`。推荐流程:

1. 宿主使用系统 Keychain/Credential Manager/Secret Service 保存云厂密钥;
2. 启动 Sidecar 时通过环境变量或受控 stdin/IPC 传递;
3. Sidecar 只在内存中持有,不回显、不写日志、不落盘;
4. 禁止把密钥放在命令行参数中,避免出现在进程列表和崩溃报告。

示例环境变量:

```text
ASRKIT_GATEWAY_TOKEN=<每次启动随机生成>
DASHSCOPE_API_KEY=<secret>
DOUBAO_API_KEY=<secret>
```

使用云模型时,音频与必要鉴权信息会发送给用户选择的云厂;ASRKit 自身不托管或留存。对外文档必须区分“本地模型不出机”和“云模型直传所选供应商”。

### 4.2 嵌入模式默认安全策略

- 只允许绑定 `127.0.0.1`/`::1`;
- 每次启动使用随机 bearer token;
- 限制单次上传大小和最大并发;
- 设置请求、连接、厂商轮询与关停超时;
- 临时文件使用后立即删除,断连也清理;
- 500 响应不暴露本地路径、密钥或依赖版本;
- 父进程消失后自动退出;
- 默认不开放公网监听,不承担多租户网关职责。

当前源码默认值为单次上传 200 MiB、最多 4 个活动转写、转写请求 300 秒、优雅关停 10 秒；CLI 可在受控范围内调整。并发超额立即返回 429,上传超额返回 413,转写超时返回 504。同步厂商调用超时后,临时文件和并发槽会保留到后台调用真正结束,避免仍在读取的音频被提前删除。

已发布的 `asrkit serve` 仍只应描述为受信任本机服务,不应宣传为公网生产网关；上述鉴权和资源默认值属于当前未发布的 `asrkitd` 入口。

## 五、数据目录与生命周期

应用资源目录通常只读;配置、日志和临时文件必须进入宿主指定的可写目录:

```text
<app-data>/asrkit/
├── tmp/
└── logs/
```

云端发行物不下载模型权重,因此不需要 models 目录。`--data-dir` 必须由宿主显式传入,避免 Sidecar 在不同产品之间共享全局状态。POSIX 上新目录会以 0700 创建；既有目录必须已经是 0700,daemon 不会擅自修改共享目录权限。

Sidecar 版本随宿主产品钉死和升级,不得自行静默更新。当前源码的健康端点返回:

```json
{
  "status": "ok",
  "version": "0.x.y",
  "protocol_version": 1,
  "distribution": "cloud"
}
```

宿主只接受经过自己验证的协议版本。

以上扩展字段属于当前未发布的 `asrkitd` 源码契约；已发布的 0.5.4 `asrkit serve` 的 `/health` 仍只返回 `{"status":"ok"}`。

## 六、平台打包

### 6.1 macOS

- 分别构建 arm64/x64,初期不强求 Universal Binary;
- Sidecar 与宿主应用一起 codesign、启用 hardened runtime 并 notarize;
- 未签名子二进制可能被 Gatekeeper 拦截。

### 6.2 Windows

- 发布独立 `.exe`,使用 Authenticode 签名;
- 运行时隐藏控制台窗口;
- 第一代把 CPython 和所需 DLL 一起分发;纯 Go 版可避免 VC Runtime 等额外运行库。

### 6.3 Linux

- 至少提供 x64/arm64;
- PyInstaller 版在较老的 glibc 基线环境构建,降低兼容风险;
- Alpine/musl 必须单独验证或单独发布,不能把所有 Linux 当成一个平台;
- 纯 Go 版优先 `CGO_ENABLED=0` 生成静态二进制。

### 6.4 Electron

二进制不能在 `app.asar` 内直接执行,必须通过 `extraResources` 或 `asarUnpack` 放到真实文件系统。运行时从 `process.resourcesPath` 定位,不得依赖开发目录相对路径。

## 七、分发渠道

### 7.1 GitHub Releases

提供平台二进制、SHA256、SBOM、许可证和第三方 notices。适合 Go/Rust/Java/Qt 等宿主直接供应商化(vendor)。

### 7.2 npm 启动器

Electron/Node 可提供一个不实现 ASR 的薄启动器:

```text
@asrkit/cloud
@asrkit/cloud-darwin-arm64
@asrkit/cloud-darwin-x64
@asrkit/cloud-linux-x64
@asrkit/cloud-win32-x64
```

主包只负责选择当前平台二进制、启动、读取 ready 消息和关停。云厂协议仍全部在 Sidecar 中,避免维护 Node 版 adapter。

### 7.3 Docker

Docker 适合服务器和内网部署,不作为桌面嵌入的默认方案。镜像暴露同一 OpenAI-compatible HTTP 契约。

## 八、第一代:冻结 Python

第一代使用 PyInstaller/Nuitka,只打入:

```text
asrkitd
├── CPython runtime
├── requests
├── FastAPI/Uvicorn/python-multipart
├── cloud adapters
├── cloud model catalog
└── gateway
```

当前源码已经形成两条可冻结边界,不再仅依赖“本地重依赖目前恰好懒加载”:

```text
asrkit/
├── profiles/
│   ├── full.py       # Python 完整发行形态
│   └── cloud.py      # asrkitd 仅云端形态
├── daemon/
│   ├── cli.py        # 独立入口参数
│   ├── settings.py   # 参数归一与私有环境
│   ├── security.py   # loopback/token/data-dir 约束
│   └── lifecycle.py  # ready/shutdown/父进程监控
└── server.py         # 两种入口共享的 HTTP 实现
```

后续拆分语言中立 catalog 时,可逐步收敛到以下长期边界:

```text
asrkit/
├── protocol/   # result/error/capabilities/model addressing
├── cloud/      # provider + cloud registry/runtime
├── local/      # Python 本地引擎
├── gateway/    # HTTP/embedded lifecycle/auth
└── cli/
```

PyInstaller `onedir` 更容易诊断且启动稳定,原型优先使用;跑通后再评估 `onefile`。物理上一个目录同样满足“无需安装和管理依赖”。

## 九、第二代:可选纯 Go 运行时

只有以下证据出现后才值得重写:

- 冻结版已被真实产品采用;
- 体积、启动速度、签名或 CPython CVE 管理成为实际阻碍;
- 企业客户明确要求静态、无解释器运行时;
- 多平台长期交付成本证明 Go 更低。

迁移时保持 HTTP、model string、result/error schema 和 embedded handshake 不变:

```text
第一代:App -> HTTP -> frozen Python -> Cloud
第二代:App -> HTTP -> Go static binary -> Cloud
```

用户应用不感知内部替换。

## 十、共享规范与一致性测试

迁移完成后的语言中立资产放在 `spec/`:

```text
spec/
├── cloud-models.json
├── transcribe-result.schema.json
├── capabilities.schema.json
├── error.schema.json
└── openai-compatibility.md
```

迁移规则必须单向且明确:

- 迁移完成前,当前 Python adapter 注册代码仍是 model catalog 的权威源;
- 迁移完成后,`spec/cloud-models.json` 才成为唯一权威源,Python/Go 只能从它加载或生成;
- 禁止 Python 表与 spec 表长期双边手工维护;
- `error.schema.json` 等文件只有在 schema 和版本策略实际定义后才进入权威层,不能因文档列名就视为已存在。

数据可以共享,厂商协议逻辑保留为代码。不要为豆包轮询、DashScope 消息解析等创建复杂 JSON DSL。

Python/Go 两套实现通过共享 conformance fixtures 防漂移:

- 相同输入生成相同 URL/header/body;
- 相同厂商响应归一为相同结果;
- 429、连接超时、5xx 重试语义一致;
- 音频格式声明和错误分类一致;
- 官方 OpenAI Python/Node SDK 对两种 runtime 均通过。

## 十一、明确不做

- 不为每种宿主语言维护一套云厂 SDK;
- 不以 C ABI/JNI/Node addon 作为主要跨语言边界;
- 不把 torch/Transformers/faster-whisper 塞进默认 Sidecar;
- 不在第一步重写 Go,先证明冻结版集成形态;
- 不在 Web/iOS/Android 客户端内放云厂密钥;这些场景应调用部署在后端的 `asrkitd`;
- 不让 Sidecar 自行静默更新;
- 不在没有真实需求前开发 `asrkit-sherpa` 原生口味。

## 十二、实施与验收顺序

1. **已完成（当前源码,尚未发布）**:抽出 `full/cloud` 加载 profile 和 `asrkitd` 内部构建入口,完整 wheel 只安装 `asrkit`;
2. **已完成（当前源码,尚未发布）**:实现 `--embedded --port 0`、ready/shutdown NDJSON、信号退出和父进程监控;
3. **已完成（当前源码,尚未发布）**:强制 loopback、宿主随机 token、私有 data dir、上传/并发/请求/关停边界;
4. 用 PyInstaller `onedir` 构建首个原型;
5. 在无系统 Python 的干净环境验证启动与转写;
6. 用 OpenAI Python/Node SDK 跑兼容测试;
7. 接入一个真实桌面应用,验证随应用启动/退出/升级;
8. 至少真实接通两家中国云厂;
9. 建立 macOS/Windows/Linux 构建、签名、校验和与 smoke test;
10. 在冻结边界稳定后抽出语言中立 model catalog 和 conformance fixtures;
11. 根据真实数据决定是否开发纯 Go 第二代。

最终用户体验应始终只有五步:**随应用携带二进制 → 启动 → 读取 base URL → 用 OpenAI HTTP 调用 → 随应用退出**。

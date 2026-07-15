# ASRKit 嵌入与无依赖分发规范

> 状态:**目标设计 + 当前源码契约**(2026-07-15)。cloud-only profile、embedded 生命周期、网关安全边界、macOS arm64 原型和 Linux x64 无 Python Debian 验证已完成；真实云转写、其余平台发行和 npm 入口仍未完成。
> 北极星与边界见 [product-form.md](product-form.md);本文只讨论云端网关的分发和集成,不改变本地引擎仍以 Python 侧为主的决定。
> 已发布的 0.5.4 只有 Python `asrkit serve`。当前未发布源码已把 `profiles/` 与 `daemon/` 物理分开，实现只含 10 个云模型的进程 profile、embedded 握手、Bearer 鉴权、资源限制和父进程监控；完整 Python wheel 仍不安装 `asrkit-cloud` 命令。仓库现可构建自包含原型,但尚无正式发布的二进制。当前 HTTP 子集见 [openai-compatibility.md](openai-compatibility.md)。

---

## 一、目标与术语

“无依赖集成”指:

- 最终用户不安装 Python、pip、venv、ASRKit 或系统服务;
- 不要求管理员权限,不修改 PATH,不污染系统环境;
- Sidecar 随宿主应用出现、退出和升级;
- 宿主只依赖 OpenAI-compatible HTTP,不依赖 Python ABI;
- 平台标准能力(进程、loopback、TLS 根证书、文件系统)不算外部运行时依赖。

它不等于“一个文件适配所有操作系统”,也不等于“第一代二进制内部完全没有 CPython”。第一代目标是 **no Python installation required**;纯 Go 静态运行时是经真实需求验证后的第二代实现选择。

## 二、源码与发行拓扑

### 2.1 一个源码仓库,多个独立产物

ASRKit 采用**单仓库、多发行物**结构。GitHub 上只有一个规范源码仓库;PyPI、npm、平台运行时和 Docker 都从同一提交构建。这里的“独立”只指用户可按需安装和运行,不指拆成多个 Git 仓库。

```text
GitHub: asrkit/asrkit
├── 共享协议、model catalog、adapter 与 conformance tests
├── Python 完整发行物源码
├── asrkit-cloud 构建入口与平台打包
├── npm asrkit 启动器源码
└── native/                  # 未来原生运行时,如 sherpa

同一提交生成
├── PyPI: asrkit
├── npm: asrkit
├── npm: @asrkit/cloud-<platform>   # 内部平台包
├── GitHub Releases: asrkit-cloud-<platform>
└── Docker: asrkit-cloud
```

新增或修改云厂 adapter 时,实现、模型注册、完整 Python profile、cloud profile、npm 集成和协议回归应在同一个 PR 中完成。npm 包不得重写一套 TypeScript 云厂 adapter;它只管理共享 Python 实现冻结出的 Sidecar。这样不会出现多个仓库之间的功能和版本漂移。

### 2.2 产品边界

```text
一份协议
├── model string: source/model[:tag]
├── TranscribeResult / Error / Capabilities
└── OpenAI-compatible /v1/audio/transcriptions

按需发行物
├── asrkit (PyPI): Python API + CLI + 云端 + 可选本地引擎
├── asrkit (npm): Node/Electron API + 平台运行时选择与生命周期
├── asrkit-cloud: 云端 provider + OpenAI-compatible Sidecar
└── asrkit-<runtime>: 未来本地或专用运行时
```

`asrkit-cloud` 不是另一个源码项目,而是 ASRKit 家族中职责明确的云端运行时产物。未来运行时统一使用 `asrkit-<能力>` 命名,在用户机器上互不依赖、按需安装,但源码继续留在同一仓库。本文只定义 `asrkit-cloud` 的嵌入与分发契约。

`asrkit-cloud` 是非 Python 产品的底层跨语言运行时,但**不应成为 Node/Electron 用户手工管理的集成界面**。正常体验是 `npm install asrkit`,由 JS 启动器选择平台包、启动私有子进程、读取 ready 消息并关停。Go/Rust/Java/Qt 等非 npm 宿主仍可直接携带平台产物并通过普通 HTTP 调用。

## 三、宿主集成流程

### 3.1 发布包布局

ASRKit 按 OS/架构发布独立归档。第一代 `onedir` 的交付单元是**完整运行目录**,不是只有一个裸可执行文件:

```text
GitHub Release assets
├── asrkit-cloud-vX.Y.Z-darwin-arm64.tar.gz
├── asrkit-cloud-vX.Y.Z-darwin-x64.tar.gz
├── asrkit-cloud-vX.Y.Z-linux-arm64-gnu.tar.gz
├── asrkit-cloud-vX.Y.Z-linux-x64-gnu.tar.gz
├── asrkit-cloud-vX.Y.Z-win32-x64.zip
├── SHA256SUMS
├── LICENSE
├── THIRD_PARTY_NOTICES
└── SBOM

每个平台归档解压后
asrkit-cloud/
├── asrkit-cloud[.exe]
├── _internal/             # CPython、动态库和冻结依赖,具体名称由构建器决定
├── LICENSE
└── THIRD_PARTY_NOTICES
```

这是底层发行矩阵,不是 Node/Electron 用户的日常操作步骤。npm 集成由包管理器根据平台元数据选择产物;其它语言的产品开发者才在**构建期**选择目标平台文件并放入应用资源目录。最终用户不单独下载、安装或升级 Sidecar。

Electron/macOS 示例:

```text
MyProduct.app/
└── Contents/
    ├── MacOS/MyProduct
    └── Resources/asrkit-cloud/
        ├── asrkit-cloud
        └── _internal/
```

Windows 示例:

```text
MyProduct/
├── MyProduct.exe
└── resources/asrkit-cloud/
    ├── asrkit-cloud.exe
    └── _internal/
```

### 3.2 启动握手

下面是所有宿主实现必须遵守的底层契约。npm `asrkit` 会封装这些步骤,普通 Node/Electron 业务代码不需要自行拼命令。嵌入模式使用随机空闲端口,避免固定端口冲突:

```bash
ASRKIT_GATEWAY_TOKEN=<宿主每次启动生成的至少32字符随机值> \
asrkit-cloud \
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

已发布的 `asrkit serve` 仍只应描述为受信任本机服务,不应宣传为公网生产网关；上述鉴权和资源默认值属于当前未发布的 `asrkit-cloud` 入口。

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

以上扩展字段属于当前未发布的 `asrkit-cloud` 源码契约；已发布的 0.5.4 `asrkit serve` 的 `/health` 仍只返回 `{"status":"ok"}`。

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

二进制不能在 `app.asar` 内直接执行,必须通过 `extraResources` 或 `asarUnpack` 放到真实文件系统。npm 启动器需要同时支持开发目录和打包后的 `process.resourcesPath`,并允许宿主显式覆盖 `binaryPath`;不得依赖仓库相对路径或偷偷回退到开发机的全局安装。

Sidecar 只能从 Electron main process 启动。renderer 不直接接触本地路径、子进程能力、网关 token 或云厂密钥;需要时通过宿主定义的受限 IPC 调用 main process。

## 七、分发渠道

### 7.1 GitHub Releases

提供平台二进制、SHA256、SBOM、许可证和第三方 notices。适合 Go/Rust/Java/Qt 等宿主直接供应商化(vendor)。

### 7.2 npm:Node/Electron 的首要集成入口

面向用户只提供一个自然入口:

```bash
npm install asrkit
```

`asrkit` 是小型 JS/TS SDK,通过固定版本的 `optionalDependencies` 引用内部平台包:

```text
asrkit
├── @asrkit/cloud-darwin-arm64
├── @asrkit/cloud-darwin-x64
├── @asrkit/cloud-linux-arm64-gnu
├── @asrkit/cloud-linux-x64-gnu
└── @asrkit/cloud-win32-x64
```

每个平台包只含对应平台的完整 `asrkit-cloud` 运行目录、`LICENSE`、`THIRD_PARTY_NOTICES` 和必要元数据,并用 `os`、`cpu`、Linux `libc` 限定适用环境。主包必须精确钉住同批平台包版本;平台包先发布,主包最后发布,避免主包指向尚不存在的产物。

这仍是“一个 npm 包”的用户体验,但不是把五个平台二进制塞进一个巨大 tarball。单一胖包会浪费下载、缓存和 Electron 安装包体积,也会把 glibc/musl 等未来组合混在一起。初期不使用 `postinstall` 从网络下载可执行文件,避免安装脚本被禁用、离线构建失败和供应链审查升级。

目标 SDK 负责:

- 检测 `process.platform`、`process.arch` 和 Linux libc,解析当前平台包;
- 生成每次启动随机的网关 token 和私有 data dir;
- 用 `--embedded --port 0 --parent-pid` 启动 Sidecar;
- 解析 stdout ready/shutdown NDJSON,把 stderr 作为日志通道;
- 暴露 `baseURL`/token 给已有 OpenAI 客户端,并提供最小 `transcribe` 便利 API;
- 处理启动超时、协议版本不兼容、父进程退出和显式 `close()`;
- 允许 Electron 打包器传入真实资源目录中的 `binaryPath`;
- 当用户使用 `--omit=optional`、平台不受支持或二进制缺失时给出可操作错误,绝不静默调用系统 Python 或 PATH 中的同名程序。

目标 API 草案如下,只说明使用形态,在实现和测试落地前不构成已发布契约:

```ts
import { startASRKit } from "asrkit";

const runtime = await startASRKit({
  dataDir: appDataDir,
  providerEnv: { DASHSCOPE_API_KEY: process.env.DASHSCOPE_API_KEY }
});

const result = await runtime.transcribe({
  model: "dashscope/qwen3-asr-flash",
  file: "meeting.mp3"
});

await runtime.close();
```

包名、import 名和品牌都叫 `asrkit`;内部可执行物仍叫 `asrkit-cloud`,因为它准确描述运行时职责。npm 主包初期不暴露全局 `asrkit` CLI,避免与 `pip install asrkit` 的完整 Python CLI 争抢 PATH。

未来本地原生运行时不进入默认安装。需要 Sherpa 的用户显式安装:

```bash
npm install asrkit @asrkit/sherpa
```

`@asrkit/sherpa` 复用同一生命周期和调用接口,但拥有自己的平台包和模型管理;默认 `npm install asrkit` 仍只承担轻量云端集成。

### 7.3 Docker

Docker 适合服务器和内网部署,不作为桌面嵌入的默认方案。镜像暴露同一 OpenAI-compatible HTTP 契约。

### 7.4 场景矩阵

| 宿主场景 | 推荐入口 | 用户是否管理二进制 |
|---|---|---|
| Python | `pip install asrkit` | 否 |
| Node.js | `npm install asrkit` | 否 |
| Electron/桌面产品 | npm `asrkit` + `extraResources` | 否,构建系统携带平台包 |
| Go/Rust/Java/C#/Qt | GitHub Release 平台产物 + HTTP | 产品开发者在构建期 vendor |
| 服务器/Kubernetes | Docker 或独立服务进程 | 运维管理镜像/服务 |
| Web 浏览器 | 调用部署在后端的 ASRKit endpoint | 浏览器不能启动本地 Sidecar |
| iOS/Android | 云端走受信任后端;本地能力另做原生运行时 | 不能照搬桌面 Sidecar 假设 |

“覆盖全平台”指为主流开发生态提供自然入口和相同协议,不表示一个 npm 包可以在浏览器、移动沙箱和所有 CPU 上启动桌面二进制。每个平台必须明确标注支持级别,未验证的平台不得笼统宣称支持。

### 7.5 发布、依赖与供应链规则

早期所有发行物应从同一个提交和同一发布批次生成,平台 npm 包使用完全相同的版本并由主包精确依赖。`protocol_version` 独立表达进程协议兼容性,不能拿包版本猜协议。

第一阶段支持矩阵:

- macOS arm64/x64;
- Windows x64;
- Linux glibc arm64/x64;
- Alpine/musl、Windows arm64 和其它平台只有完成独立构建与真实 smoke 后才能加入。

发布流水线按以下顺序执行:

1. 各目标平台从固定提交构建 `asrkit-cloud`;
2. 在不依赖系统 Python 的干净环境执行启动、health、鉴权和真实转写 smoke;
3. 生成 SHA256、SBOM、`LICENSE` 与 `THIRD_PARTY_NOTICES`,完成 macOS/Windows 签名要求;
4. 将已验证产物封装为内部平台 npm 包;
5. 先发布全部平台包,再发布 npm `asrkit` 主包;
6. 从同一批产物生成 GitHub Release 和 Docker,不分别手工重建。

冻结产物必须携带其运行所需的 CPython、动态库和 Python 依赖;目标机器不再安装 Python 或 pip。npm 主包只声明 JS 侧真实依赖和平台 `optionalDependencies`,不得把构建依赖伪装成用户运行依赖。新增第三方依赖必须同步完成许可证、漏洞与体积审查。

## 八、第一代:冻结 Python

第一代使用 PyInstaller/Nuitka,只打入:

```text
asrkit-cloud
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
│   └── cloud.py      # asrkit-cloud 仅云端形态
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

当前原型通过 `python packaging/cloud/bootstrap.py` 构建。bootstrap 在已忽略的 `build/` 下创建隔离 venv,避免开发机已有的可选包进入产物；spec 排除完整 CLI、本地 adapter 及 Torch/Sherpa/Numpy 等重依赖,并将 Uvicorn 固定为 asyncio+h11 的纯 HTTP 栈。2026-07-15 的 macOS arm64 本机证据为约 32 MiB/84 文件,动态库无开发机绝对路径引用；Linux x64 已在 [GitHub Actions run 29396109425](https://github.com/asrkit/asrkit/actions/runs/29396109425) 进入不含 Python 的只读 Debian 容器,通过 ready、health、鉴权、模型列表、multipart 路由和关停验证。详细命令和 smoke 边界见 [`packaging/cloud/README.md`](../packaging/cloud/README.md)。真实 provider 转写、其余平台、签名公证和长期供应链材料仍待完成。

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

- 不把 `asrkit-cloud`、`asrkit-sherpa` 等运行时拆成需要同步维护的独立 Git 仓库;
- 不为每种宿主语言维护一套云厂 SDK;
- 不在 npm 包中重写一套 TypeScript 云厂 adapter;
- 不以 C ABI/JNI/Node addon 作为主要跨语言边界;
- 不把 torch/Transformers/faster-whisper 塞进默认 Sidecar;
- 不把所有平台二进制塞入一个 npm 胖包,也不在第一版使用 `postinstall` 在线下载并执行程序;
- 不在第一步重写 Go,先证明冻结版集成形态;
- 不在 Web/iOS/Android 客户端内放云厂密钥;这些场景应调用部署在后端的 `asrkit-cloud`;
- 不让 Sidecar 自行静默更新;
- 不在没有真实需求前开发 `asrkit-sherpa` 原生口味。

## 十二、实施与验收顺序

1. **已完成（当前源码,尚未发布）**:抽出 `full/cloud` 加载 profile 和 `asrkit-cloud` 内部构建入口,完整 wheel 只安装 `asrkit`;
2. **已完成（当前源码,尚未发布）**:实现 `--embedded --port 0`、ready/shutdown NDJSON、信号退出和父进程监控;
3. **已完成（当前源码,尚未发布）**:强制 loopback、宿主随机 token、私有 data dir、上传/并发/请求/关停边界;
4. **已完成（macOS arm64 本机原型）**:用隔离 venv 和 PyInstaller `onedir` 构建,并通过干净子进程 smoke;
5. **部分完成**:Linux x64 已在无系统 Python 的 Debian 环境验证启动与 HTTP 路由；真实 provider 转写仍待受控 E2E;
6. 建立 macOS arm64/x64、Windows x64、Linux glibc arm64/x64 构建、签名、校验和与 smoke test;
7. 在同一仓库新增 npm `asrkit` 薄 SDK 和内部平台包,封装选择、启动、ready、调用与关停;
8. 验证 npm/pnpm 安装、`--omit=optional` 错误、Node 开发模式和 Electron `extraResources` 打包模式;
9. 用官方 OpenAI Python/Node SDK 跑兼容测试,并至少真实接通两家中国云厂;
10. 接入一个真实桌面应用,验证随应用启动、退出和升级;
11. 从同一提交生成 PyPI、npm、GitHub Release 与 Docker 的可追溯产物;
12. 在冻结边界稳定后抽出语言中立 model catalog 和 conformance fixtures;
13. 根据真实数据决定是否开发纯 Go 第二代或 `asrkit-sherpa`。

最终用户体验按生态收口:

- Python:`pip install asrkit`;
- Node/Electron:`npm install asrkit`;
- 其它语言:构建期携带平台产物,运行时只面对 HTTP;
- 最终用户不安装 Python、不选择二进制、不配置 PATH,也不单独管理 Sidecar。

# ASRKit 产品形态 · 北极星 + 交接文档

> 本文两部分:**上半是持久的"最终产品形态"结论(北极星)**,下半是**会过期的"当前状态 / 下一步"(交接给下一个 AI)**。
> 交接对象:任何接手继续干 asrkit 的 AI / 协作者。读完本文即可上手,不必重新推导已定的结论。
> 成文:2026-07-09,基于一轮关于"如何把 asrkit 做成可嵌入任何系统的轻量统一 STT 接口"的深度讨论。

---

# 第一部分:最终产品形态(北极星 · 持久)

## 一句话定性

**asrkit = 一个"统一语音转写协议"。** 跨语言底座是一个**轻量、OpenAI 兼容、无需用户安装或管理 Python 的自包含云端网关**(`asrkit-cloud`),但产品开发者应优先通过生态包接入,例如 Node/Electron 只需 `npm install asrkit`;Python 用户额外享受本地引擎的统一管理。对外身份是 **"统一 STT 界的 ffmpeg + 冒充 OpenAI 端点"**。
**不追求让用户管理 Python,只追求把统一协议送到任何语言的门口。** 第一代网关可以内嵌 CPython 冻结分发;只有真实部署证明有必要时,才在不改变 HTTP 契约的前提下替换为纯 Go 运行时。

## 核心原理:统一的是"协议",不是"打包"

> 一个协议,多个后端,按需装。统一活在"寻址格式 + 结果契约 + HTTP 接口"这层薄薄的路由里;干活的后端全是可插拔、用哪个才装哪个。每个消费者把这根光谱**塌缩成自己需要的那一小段**——所以"轻"和"统一"能同时成立。

**不是"云 vs 本地"两个产品打架,是一根协议脊柱 + 一排按需插拔的后端。**

## 结构:三层同心环 + 两张脸

```
        ┌─────────────────────────────────────────────┐
        │  脊柱(永远在,零重量)= 统一                  │
        │  寻址 source/model + 结果契约 + 路由器        │
        └─────────────────────────────────────────────┘
                 │                          │
        ┌────────┴─────────┐      ┌─────────┴──────────┐
        │   脸 A:Python     │      │  脸 B:HTTP 接口     │
        │ import asrkit /   │      │ asrkit serve →      │
        │ asrkit transcribe │      │ OpenAI 兼容端点     │
        │ (给 Python 应用/人)│      │ → 冻成二进制(给所有人)│
        └────────┬─────────┘      └─────────┬──────────┘
                 └───────────┬──────────────┘
              后端(opt-in,每个只拉自己的依赖)
   ┌──────────────┬────────────────┬──────────────────┐
   │ 云端(内置)   │ Python 系本地   │ 纯 C++ 本地       │
   │ 豆包/百炼/    │ faster-whisper  │ sherpa/whisper.cpp│
   │ openai/11labs │ transformers    │                   │
   │ dep=requests  │ 天生 Python     │ 能脱 Python(见边界)│
   └──────────────┴────────────────┴──────────────────┘
```

## 杀手级细节:OpenAI 兼容 = 到处都能插

脸 B 的目标是 **OpenAI transcription API 兼容子集**。对于只使用已兼容参数、且宿主已管理 Sidecar 生命周期的产品,通常只需切换 `base_url` 和 model string,无需重写业务转写流程。已发布的 0.5.4 只有 Python `asrkit serve`;当前源码已具备 cloud-only daemon、embedded 生命周期与安全契约,自包含二进制仍是下一阶段目标。兼容范围见 [openai-compatibility.md](openai-compatibility.md)。

## 必须画死的边界(让一切自洽的关键)

"sherpa 不用 Python 那就别用"——这条**由消费者决定,不由 asrkit 决定**:

- **Python 应用消费** → 所有引擎(含 sherpa)走 Python 绑定。反正已在 Python 里,sherpa 顺便走 Python **零额外成本**。
- **非 Python 应用消费云端** → 使用 `asrkit-cloud`,只拿**云端 + 统一协议**。
- **非 Python 应用消费本地模型** → 宿主自己原生绑 sherpa(像 Orca 那样),或使用未来的 `asrkit-sherpa` 原生运行时;两者都不穿过 Python `asrkit serve`或 `asrkit-cloud`。

> **边界:`asrkit-cloud` 的跨语言价值 = 云端广度 + 统一协议(经 HTTP)。本地原生能力必须是另一个独立运行时,不混入云端产物。**

---

# 第二部分:已确立的技术事实(别再重新推导)

## 引擎 × Python 依赖矩阵

| 本地引擎 | 内核 | 能零 Python 跑? | asrkit 现在怎么用它 |
|---|---|---|---|
| **sherpa-onnx** | C++ | ✅ 能(官方有 Node/Go/Swift/Rust/C++ 绑定) | 走 **Python 绑定** `import sherpa_onnx` |
| **whisper.cpp** | C/C++ | ✅ 能(本身是 CLI 二进制) | 走 Python 绑定 pywhispercpp |
| **faster-whisper** | C++(CTranslate2) | ⚠️ 实践上不能(管线只在 Python 成型) | Python |
| **transformers** | PyTorch | ❌ 不能(深度 Python) | Python |

**关键三条:**
1. **模型(权重)永远不是 Python**——`.onnx/.gguf/.bin` 都是跨语言数据。模型 = 数据,不是代码。
2. **asrkit 自身是 Python 程序**,经 **Python 绑定**消费**所有**本地引擎(包括本可脱 Python 的 sherpa)。所以只要经过 asrkit-Python,就一定过 Python。sherpa 能脱 Python 是对**别的消费者**(如 Orca 用 Node 绑定)成立,不是对 asrkit。
3. "引擎能不能脱 Python" 和 "asrkit 本地侧能不能脱 Python" 是**两个问题**。

## 轻量性已实测验证(教科书级,要守住)

三条铁律,asrkit **已全部满足**:

| 铁律 | 作用 | 现状 |
|---|---|---|
| ① 每个后端独立成 extra | 隔离**安装重量** | ✅ sherpa/whispercpp/faster-whisper/transformers/serve/mic 全分开 |
| ② 可选重运行时只在**实际执行边界** import | 隔离**加载重量** | ✅ torch/transformers/sherpa_onnx/numpy/fastapi 等不在注册与轻量模块导入期加载 |
| ③ 缺依赖给**友好安装提示** | pay-per-use 体验 | ✅ 有 `engine install` + `doctor` |

**实测与回归证据**(2026-07-13,`tests/test_thin_kernel.py`):
- 独立子进程固定从当前 `src/` 加载,隔离本机配置和第三方 entry-point,覆盖内置注册表、五类 adapter 构造/安装探测、普通 CLI 列表及 `server`/`mic` 模块导入。
- **torch/transformers/sherpa/numpy/soundfile/fastapi 等可选运行时一个都不加载**;测试同时用 import guard 主动阻断回归,不只事后检查 `sys.modules`。
- 基础依赖 `requests` 会随云端 adapter 的 `_http` 注册路径加载,这是 base 安装契约内的允许成本;“requests 也始终懒加载”的旧描述不准确,已纠正。
- `tests/test_cloud_runtime.py` 另用独立进程证明 cloud profile 只有 10 个云模型,不会导入本地 adapter、`models_local`、用户模型或 entry-point 插件。
- 结论:薄内核属性已达成且有 CI 护栏;这里保证的是**可选重运行时惰性 + cloud 进程加载隔离**,不是“注册表绝对零模块加载”。

## 分发形态:模型 vs 引擎运行时的关键区分

**这是最容易踩的坑,务必分清:**

| | 是什么 | 二进制里能"需要时才下载"? | 要 Python? |
|---|---|---|---|
| **模型**(.onnx/.gguf) | 数据文件 | ✅ 能,永远能(Ollama 式 `pull`) | ❌ 不要 |
| **引擎运行时**(sherpa 库/torch/ct2) | 代码/二进制库 | ⚠️ 冻结二进制里**打包时焊死**,运行时不能现装 | 看引擎 |

- **pip 渠道(Python 用户)**:`asrkit engine install X` + `asrkit pull Y` —— 引擎**和**模型都按需装(有真 Python + pip)。
- **二进制渠道(非 Python 产品)**:能跑哪些引擎 = **打包时决定**;模型仍运行时按需 `pull`。所以发**几个口味的二进制**,不是"一个能自己装引擎的二进制"。

## 二进制口味规划

| 口味 | 内含 | 大小 | 场景 | 工程量 |
|---|---|---|---|---|
| **`asrkit-cloud`** ⭐ | 仅云端(requests+fastapi,第一代内嵌 CPython) | ~20-40MB | 默认集成物,插进任何产品,只吃云;目标机器无需安装 Python | 小(PyInstaller/Nuitka 冻结) |
| **`asrkit-sherpa`**(候选) | 仅本地 sherpa 原生运行时 + ASRKit 协议适配 | 大些 | 要离线+可嵌入+零 Python 的产品 | **中大**:需直接基于 sherpa C/C++ API 实现 |
| transformers/faster-whisper | —— | ⛔ 不做二进制 | torch 是 GB 级,只走 pip 渠道 | —— |

### 家族命名规则

- GitHub 只维护一个 `asrkit` 源码仓库,统一承载协议、adapter、各运行时源码、构建和一致性测试;
- PyPI 与 npm 都使用 `asrkit` 作为各自生态的首要安装入口;
- 独立运行时统一使用 `asrkit-<能力>`,如 `asrkit-cloud`、候选的 `asrkit-sherpa`和未来可能的 `asrkit-whisper`;
- 运行时发行包与可执行命令按能力命名,但它们是同一仓库生成的不同产物,不是多个 Git 项目;
- 内部实现目录可按职责命名(如 `daemon/`),不作为对外产品名;
- 各发行物在用户机器上相互独立、按需安装,源码则共享协议、adapter 和契约测试,避免跨仓库同步。

`asrkitd` 不再作为对外名称:它会暗示“ASRKit 唯一守护进程”,无法与今后的多运行时家族平行扩展。

## 最终交付定案:一份协议、核心发行物、可扩展运行时家族

| 层 | 交付物 | 面向谁 | 能力 |
|---|---|---|---|
| 统一协议 | model string + result/error schema + OpenAI HTTP 子集 | 所有人 | 稳定的跨语言边界 |
| Python 发行物 | `pip install asrkit` | Python 用户 | 云端 + 全部可选本地引擎 |
| Node 发行物 | `npm install asrkit` | Node/Electron/桌面产品 | 自动选择平台运行时、管理 Sidecar、提供 JS API |
| 云端运行时 | `asrkit-cloud` 平台产物 / Docker | npm 内部平台包、Go/Rust/Java/服务端 | 云端 + OpenAI 兼容网关 |
| 本地原生运行时(候选) | `asrkit-sherpa` 平台二进制 | 需要离线 ASR 的非 Python 产品 | sherpa 本地模型 + 同一协议 |

非 Python 应用不链接 Python ABI,也不为每种语言重写云厂 adapter。Node/Electron 用户只安装 `asrkit` npm 包,由包内启动器选择并管理对应平台的 `asrkit-cloud`;其它语言可以直接携带同一平台产物并通过 loopback HTTP 调用。HTTP 是跨语言 ABI,内部实现可从冻结 Python 演进为 Go 而不影响宿主应用。

详细的启动握手、密钥传递、平台打包、发行矩阵、安全边界与演进方案见 [嵌入与无依赖分发规范](embedding-and-distribution.md)。

### 当前可用性 vs 目标形态

| 能力 | 已发布 0.5.4 / 当前源码 | 目标 |
|---|---|---|
| Python API/CLI | 已可用 | 持续兼容 |
| `asrkit serve` | 已可用;需 Python + serve extra,仅适合受信任本机 | 保留为 Python 入口 |
| `asrkit-cloud` | 0.5.4 无；当前源码已有 macOS arm64 onedir 原型,完整 wheel 不安装同名命令 | cloud-only 自包含 Sidecar |
| npm `asrkit` | 尚未实现 | 单一 Node/Electron 安装入口 + 平台运行时包 |
| embedded ready/随机端口/父进程监控/data dir | 当前源码已实现并有真实子进程回归 | 随冻结产物交付 |
| 网关鉴权/上传上限/并发/超时边界 | 当前源码已实现并有 HTTP 回归 | 随冻结产物交付 |
| 纯 Go runtime | 尚未立项 | 冻结版获真实采用后再评估 |

---

# 第三部分:下一步行动(交接 · 按优先级 · 会过期)

> 以下按"先证明形态成立,再锁住优势"排序。每条含足够上下文可直接动手。
> **动手前先看第四部分的铁律**(尤其版本号 / 提交 / 不推送)。

### ① [进行中 · 高价值] 冻结并验证 `asrkit-cloud`
- **已完成**:`profiles/`/`daemon/` 边界、10 云模型隔离、wheel 命令所有权、`--embedded --port 0` ready/退出契约、鉴权和资源限制；macOS arm64 已用隔离 venv 构建约 32 MiB 的 PyInstaller `onedir`,并通过无开发环境 PATH 的 frozen smoke。
- **接下来**:在真正未安装系统 Python 的干净宿主完成启动和真实云转写,随后建立 macOS x64、Windows x64、Linux glibc arm64/x64 构建矩阵；`onefile` 后置。
- **随后**:在同一仓库实现 npm `asrkit` 薄 SDK和平台包,让 Node/Electron 用户不感知二进制选择、启动与关停细节。
- **怎么验**:在一个真正未安装系统 Python 的干净环境里启动,`curl` 和官方 OpenAI SDK 打通一次云端转写(`POST /v1/audio/transcriptions`)。
- **为什么**:这是给"用户无需安装或管理 Python"这个产品形态**背书的最小验证**。跑通了,`asrkit-sherpa` 那口味要不要投工程也就有底了。
- **注意**:先做**云端专用小包**,别一上来就想把本地引擎塞进去。serve 入口见 `src/asrkit/server.py`(fastapi,已懒加载)。

### ② [已完成 · 护栏] 轻量回归测试
- `tests/test_thin_kernel.py` 已用源码路径独立子进程锁住注册、adapter 构造、CLI 和轻量服务模块的导入边界。
- 覆盖 pyproject 全部可选 extras 及常见传递重依赖;任何提前 import 都会使 CI 当场失败。

### ③ [可选 · 大工程] `asrkit-sherpa` 原生口味
- **做什么**:把 sherpa 从 Python 绑定(`import sherpa_onnx`)改为调用其 **C API / 原生库**,使其可焊进二进制、真·零 Python 跑本地。
- **前置**:①②先做完、形态验证通过再评估投不投。这是实打实的工程,不是免费的。

### ④ [文档] 把本形态写进对外定位
- 把第一部分的"北极星"提炼进 `README.md` / `README.en.md` 的定位段,和 `docs/project-overview.md` 呼应。让外部读者一眼 get"统一 STT 的 ffmpeg + OpenAI 兼容"。

---

# 第四部分:铁律(接手的 AI 必须遵守)

摘自 `CLAUDE.md`(本地私有,含署名/邮箱,已 gitignore)。**违反下列任一条都是严重问题:**

1. **版本号**:升 `__version__` / 打 tag / 定版本号,**必须由人类明确批准**。AI 只能**提议**,不能自作主张。0.x 阶段默认一切走 **PATCH**,MINOR 只留破坏性变更/里程碑。
2. **提交**:用 `git -c user.name="BolynWang" -c user.email="1710998763@qq.com"`,**显式 `git add <具体文件>`,绝不 `git add .`**。
3. **推送 / 发 PyPI 由人类做**,AI 不推、不发。
4. **i18n**:终端输出 / CLI 帮助 / 报错**一律英文**;注释与设计文档**中文**。
5. **透明音频**:内核对音频零处理,格式不符**诚实报错**,绝不静默出乱码。`--convert`/`--segment` 是 opt-in。
6. **敏感文件绝不提交**:`CLAUDE.md`、`AGENTS.md`(均含隐私,已 gitignore)、凭据、`dist/`、`.omc/` 等。

---

# 第五部分:当前状态入口

北极星文档不再保存易腐烂的分支、ahead 数、工作树和代码行数。当前发布与工作状态见 [project-overview.md](project-overview.md),唯一执行队列见 [roadmap.md](roadmap.md),历史计划和评审见 [archive/](archive/)。

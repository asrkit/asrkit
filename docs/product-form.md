# ASRKit 产品形态 · 北极星 + 交接文档

> 本文两部分:**上半是持久的"最终产品形态"结论(北极星)**,下半是**会过期的"当前状态 / 下一步"(交接给下一个 AI)**。
> 交接对象:任何接手继续干 asrkit 的 AI / 协作者。读完本文即可上手,不必重新推导已定的结论。
> 成文:2026-07-09,基于一轮关于"如何把 asrkit 做成可嵌入任何系统的轻量统一 STT 接口"的深度讨论。

---

# 第一部分:最终产品形态(北极星 · 持久)

## 一句话定性

**asrkit = 一个"统一语音转写协议"。** 旗舰交付物是一个**轻量、OpenAI 兼容、无需用户安装或管理 Python 的自包含网关**(`asrkitd`),前置所有云厂;Python 用户额外享受本地引擎的统一管理。对外身份是 **"统一 STT 界的 ffmpeg + 冒充 OpenAI 端点"**。
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
- **非 Python 应用消费** → 走脸 B(HTTP 二进制),只拿**云端 + 统一**。想要本地 sherpa?它**自己原生绑 sherpa(像 Orca 那样)更优**,不该穿过 asrkit 的 Python serve。

> **边界:asrkit 的跨语言价值 = 云端广度 + 统一协议(经 HTTP)。本地引擎是 Python 侧的赠品,不参与跨语言。** 这条画死,"割裂感"就消失。

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
| **`asrkitd`** ⭐ | 仅云端(requests+fastapi,第一代内嵌 CPython) | ~20-40MB | 默认集成物,插进任何产品,只吃云;目标机器无需安装 Python | 小(PyInstaller/Nuitka 冻结) |
| **`asrkit-sherpa`**(可选) | 云端 + sherpa **原生库**焊入 | 大些 | 要离线+可嵌入+零 Python 的产品 | **中大**:需把 sherpa 从 Python 绑定改为调 C-API |
| transformers/faster-whisper | —— | ⛔ 不做二进制 | torch 是 GB 级,只走 pip 渠道 | —— |

## 最终交付定案:一份协议、两个发行物、两类后端

| 层 | 交付物 | 面向谁 | 能力 |
|---|---|---|---|
| 统一协议 | model string + result/error schema + OpenAI HTTP 子集 | 所有人 | 稳定的跨语言边界 |
| Python 发行物 | `pip install asrkit` | Python 用户 | 云端 + 全部可选本地引擎 |
| 无安装发行物 | `asrkitd` 平台二进制 / Docker | Node/Go/Rust/Java/Electron/服务端 | 云端 + OpenAI 兼容网关 |

非 Python 应用不链接 Python ABI,也不为每种语言维护一套 ASR SDK;它把 `asrkitd` 当作私有 Sidecar 子进程,通过 loopback HTTP 调用。HTTP 是跨语言 ABI,内部实现可从冻结 Python 演进为 Go 而不影响宿主应用。

详细的启动握手、密钥传递、平台打包、发行矩阵、安全边界与演进方案见 [嵌入与无依赖分发规范](embedding-and-distribution.md)。

### 当前可用性 vs 目标形态

| 能力 | 已发布 0.5.4 / 当前源码 | 目标 |
|---|---|---|
| Python API/CLI | 已可用 | 持续兼容 |
| `asrkit serve` | 已可用;需 Python + serve extra,仅适合受信任本机 | 保留为 Python 入口 |
| `asrkitd` | 0.5.4 无；当前源码已有内部构建入口,完整 wheel 不安装同名命令 | cloud-only 自包含 Sidecar |
| embedded ready/随机端口/父进程监控/data dir | 当前源码已实现并有真实子进程回归 | 随冻结产物交付 |
| 网关鉴权/上传上限/并发/超时边界 | 当前源码已实现并有 HTTP 回归 | 随冻结产物交付 |
| 纯 Go runtime | 尚未立项 | 冻结版获真实采用后再评估 |

---

# 第三部分:下一步行动(交接 · 按优先级 · 会过期)

> 以下按"先证明形态成立,再锁住优势"排序。每条含足够上下文可直接动手。
> **动手前先看第四部分的铁律**(尤其版本号 / 提交 / 不推送)。

### ① [进行中 · 高价值] 冻结并验证 `asrkitd`
- **已完成**:`profiles/`/`daemon/` 边界、10 云模型隔离、wheel 命令所有权、`--embedded --port 0` ready/退出契约、鉴权和资源限制。
- **接下来**:用 PyInstaller(或 Nuitka)冻成自包含 `onedir`,在无系统 Python 环境完成启动和真实云转写；跑通后评估 `onefile`。
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

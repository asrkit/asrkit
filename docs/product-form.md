# ASRKit 产品形态 · 北极星 + 交接文档

> 本文两部分:**上半是持久的"最终产品形态"结论(北极星)**,下半是**会过期的"当前状态 / 下一步"(交接给下一个 AI)**。
> 交接对象:任何接手继续干 asrkit 的 AI / 协作者。读完本文即可上手,不必重新推导已定的结论。
> 成文:2026-07-09,基于一轮关于"如何把 asrkit 做成可嵌入任何系统的轻量统一 STT 接口"的深度讨论。

---

# 第一部分:最终产品形态(北极星 · 持久)

## 一句话定性

**asrkit = 一个"统一语音转写协议"。** 旗舰交付物是一个**轻量、OpenAI 兼容、可冻成零 Python 二进制**的网关,前置所有云厂;Python 用户额外享受本地引擎的统一管理。对外身份是 **"统一 STT 界的 ffmpeg + 冒充 OpenAI 端点"**。
**不追求把 Python 带到别人家里,只追求把统一协议送到任何语言的门口。**

## 核心原理:统一的是"协议",不是"打包"

> 一个协议,多个后端,按需装。统一活在"寻址格式 + 结果契约 + HTTP 接口"这层薄薄的路由里;干活的后端全是可插拔、用哪个才装哪个。每个消费者把这根光谱**塌缩成自己需要的那一小段**——所以"轻"和"统一"能同时成立。

**不是"云 vs 本地"两个产品打架,是一根协议脊柱 + 一排按需插拔的后端。**

## 结构:三层同心环 + 两张脸

```
        ┌─────────────────────────────────────────────┐
        │  脊柱(永远在,零重量)= 统一                  │
        │  寻址 vendor/model + 结果契约 + 路由器        │
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

脸 B 是 **OpenAI Whisper API 兼容**。任何已接 OpenAI 语音转写的产品,**endpoint 一改指向 asrkit 二进制,立刻白嫖国内云 + 统一切换,一行业务代码不用动**。集成故事不是"发明新接口让人学",而是"冒充人人已在用的接口"。

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
| ② 重依赖只在**函数体内** import | 隔离**加载重量** | ✅ torch/transformers/sherpa_onnx/numpy 的 import 全在方法内,无一在模块顶层 |
| ③ 缺依赖给**友好安装提示** | pay-per-use 体验 | ✅ 有 `engine install` + `doctor` |

**实测证据**(2026-07-09,`PYTHONPATH=src python -c "import asrkit; from asrkit import registry"`):
- 构建完注册表(统一路由层)共 45 个模块,**torch/transformers/sherpa/numpy/soundfile/fastapi 一个都没加载**。
- 连 base 依赖 `requests` 都是**用到才加载**。
- 结论:`import asrkit` 零重依赖。轻量属性已达成,**风险只在退化**(见下一步的"护栏测试")。

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
| **`asrkit-cloud`** ⭐ | 仅云端(requests+fastapi) | ~20-40MB | 默认集成物,插进任何产品,只吃云 | 小(PyInstaller 直接冻) |
| **`asrkit-sherpa`**(可选) | 云端 + sherpa **原生库**焊入 | 大些 | 要离线+可嵌入+零 Python 的产品 | **中大**:需把 sherpa 从 Python 绑定改为调 C-API |
| transformers/faster-whisper | —— | ⛔ 不做二进制 | torch 是 GB 级,只走 pip 渠道 | —— |

---

# 第三部分:下一步行动(交接 · 按优先级 · 会过期)

> 以下按"先证明形态成立,再锁住优势"排序。每条含足够上下文可直接动手。
> **动手前先看第四部分的铁律**(尤其版本号 / 提交 / 不推送)。

### ① [验证 · 高价值] 冻结 `asrkit-cloud` 二进制并跑通
- **做什么**:用 PyInstaller(或 Nuitka)把"云端 serve"冻成单个自包含二进制。
- **怎么验**:在一个**假装没装 Python 的环境**里启动该二进制,`curl` 打通一次云端转写(OpenAI 兼容端点 `POST /v1/audio/transcriptions`)。
- **为什么**:这是给"零 Python 集成"这个产品形态**背书的最小验证**。跑通了,`asrkit-sherpa` 那口味要不要投工程也就有底了。
- **注意**:先做**云端专用小包**,别一上来就想把本地引擎塞进去。serve 入口见 `src/asrkit/server.py`(fastapi,已懒加载)。

### ② [护栏 · 高价值 · 纯增量] 加轻量回归测试
- **做什么**:在 `tests/` 加一个测试,断言 `import asrkit` 不拉重依赖,锁死上面实测到的属性。
- **参考实现**:
  ```python
  def test_import_stays_lightweight():
      import asrkit, asrkit.registry  # noqa: F401  构建路由层
      import sys
      heavy = {"torch", "transformers", "sherpa_onnx", "numpy", "fastapi"}
      leaked = heavy & set(sys.modules)
      assert not leaked, f"重依赖在 import 期被拉进来了: {leaked}"
  ```
- **为什么**:轻量属性靠"重 import 都在函数内"这个约定撑着;一次手滑写到模块顶层就悄悄崩。CI 里焊死它,谁破坏谁当场红。
- **顺带**:核一遍所有 adapter 确实没有顶层重 import(目前是干净的)。

### ③ [可选 · 大工程] `asrkit-sherpa` 原生口味
- **做什么**:把 sherpa 从 Python 绑定(`import sherpa_onnx`)改为调用其 **C API / 原生库**,使其可焊进二进制、真·零 Python 跑本地。
- **前置**:①②先做完、形态验证通过再评估投不投。这是实打实的工程,不是免费的。

### ④ [文档] 把本形态写进对外定位
- 把第一部分的"北极星"提炼进 `README.md` / `README.en.md` 的定位段,和 `docs/project-overview.md` 呼应。让外部读者一眼 get"统一 STT 的 ffmpeg + OpenAI 兼容"。

---

# 第四部分:铁律(接手的 AI 必须遵守)

摘自 `CLAUDE.md`(本地私有,含署名/邮箱,已 gitignore)。**违反下列任一条都是严重问题:**

1. **版本号**:升 `__version__` / 打 tag / 定版本号,**必须由人类明确批准**。AI 只能**提议**,不能自作主张。0.x 阶段默认一切走 **PATCH**,MINOR 只留破坏性变更/里程碑。
2. **提交**:用 `git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com"`,**显式 `git add <具体文件>`,绝不 `git add .`**。
3. **推送 / 发 PyPI 由人类做**,AI 不推、不发。
4. **i18n**:终端输出 / CLI 帮助 / 报错**一律英文**;注释与设计文档**中文**。
5. **透明音频**:内核对音频零处理,格式不符**诚实报错**,绝不静默出乱码。`--convert`/`--segment` 是 opt-in。
6. **敏感文件绝不提交**:`CLAUDE.md`、`AGENTS.md`(均含隐私,已 gitignore)、凭据、`dist/`、`.omc/` 等。

---

# 第五部分:当前状态快照(交接时点 2026-07-09 · 会过期)

- **版本**:`0.5.4`(源码 + 本地 tag `v0.5.4`),**未推送、未发 PyPI**。
- **分支**:`main`,工作树干净。
- **本地领先 origin 约 4 个 commit**(README 正名 + 本会话三次整理),等人类择机推送。
- **本会话已完成的整理**(仅整理,未动核心代码):
  - `38e400c` — .gitignore 收编工具缓存 + AI 工具目录
  - `a76eede` — docs 归档:26 份历史/已完成文档搬入 `docs/archive/`,根目录 32→8,修 7 处断链
  - `cc5d749` — AGENTS.md 私有化(含隐私,gitignore)
- **代码本体评估**:3671 行 / 30 文件,结构干净(**不是屎山**)。多引擎 adapter + 4 云厂 + 流式四入口 + doctor + 补全均已完成。roadmap 自述"当前无未认领的核心待办"。
- **活跃文档**(`docs/` 根):usage / adapter-spec / result-contract / engines-and-addressing / model-management / roadmap / project-overview / asrbench-blueprint。历史/已完成文档在 `docs/archive/`。
- **相关外部上下文**:另一个项目 **Orca**(Node/Electron STT 应用)的改动停在其 `feat/custom-stt-endpoint` 分支,未提交但保留。Orca 用 sherpa 的 **Node 原生绑定**(零 Python),它对 asrkit 的真正需求是**国内云厂 + 统一切换**,不是本地 sherpa(那是重复)。
- **参考源(只读,勿改)**:`/Users/user/Documents/AI-Lab/asr_bench`(真机端到端验证在此仓库,不在 asrkit repo)。

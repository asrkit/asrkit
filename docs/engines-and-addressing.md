# 模型、引擎与寻址（设计说明）

> 本文解释 ASRKit 的两个核心概念（模型 vs 引擎）和寻址规则，并给出**多引擎将来**的命令形态。
> 目的：让"以后加本地引擎"这件事**从第一天就不跑偏、不产生破坏性变更**。
> 标注：`现状` = 已实现；`路线` = 前瞻设计，尚未实现但已为其留好口子。

---

## 一、模型 ≠ 引擎

- **模型（model）= "内容"**：训练好的权重 + 架构（如 Whisper-small）。它本身只是一堆数字，不会自己跑。
- **引擎（engine / 运行时）= "播放器"**：把权重加载、喂音频、算出文字的软件。模型是死的，引擎让它动。

**同一个模型可以被多个引擎跑**，速度/内存/精度/功能各异——就像同一部电影用不同播放器放。

主流 ASR 引擎：

| 引擎 | 特点 | 能跑什么 |
|---|---|---|
| **sherpa-onnx**（现状唯一） | 端侧首选，一个依赖覆盖几十个模型，平台全 | Zipformer/Paraformer/SenseVoice/Whisper/Moonshine/FireRed-CTC/Dolphin/NeMo… |
| whisper.cpp | 超轻超便携（Metal/CUDA） | **只有 Whisper** |
| faster-whisper | CPU/GPU 上最快的 Whisper 实现之一 | **只有 Whisper(+distil)** |
| transformers | 啥都能跑但重（PyTorch） | 几乎所有 |
| vLLM | 专跑 LLM 架构大模型 ASR | Qwen3-ASR-large、FireRedASR-LLM… |

> 注意：whisper.cpp / faster-whisper 名字带 whisper，但它们是**引擎**、只跑 Whisper 一个家族；sherpa-onnx 是**引擎**、跑几十个家族。别混。

---

## 二、为什么"同模型不同引擎"要分开

**① 格式不同**：同一个 Whisper-small 要在不同引擎上跑，得先转成各引擎认的文件格式——是**不同的下载文件**：

| 引擎 | 格式 |
|---|---|
| sherpa-onnx | ONNX（`.onnx`） |
| whisper.cpp | GGML/GGUF |
| faster-whisper | CTranslate2 |
| transformers | PyTorch / safetensors |

**② 优化不同**：量化方式、算子、是否支持流式/时间戳/说话人分离都可能不同。

结论：同一模型的不同引擎化身，**要分别下载、分别存放、分别寻址**。

---

## 三、寻址规则：`来源/模型[:精度]`

统一成一条规则：**`<来源>/<模型>[:<tag>]`**，来源 = 本地引擎名 或 云厂商名。

| 形态 | 例子 | 状态 |
|---|---|---|
| 裸名（= 默认引擎简写） | `sensevoice`、`whisper-small` | `现状` |
| 精度 tag | `sensevoice:fp32` | `现状` |
| 本地默认引擎全名 | `local/sensevoice` | `现状` |
| **具体本地引擎** | `sherpa/whisper-small`、`whispercpp/whisper-small`、`faster-whisper/whisper-small` | `路线` |
| 云厂商 | `siliconflow/sensevoice`、`openai/gpt-4o-transcribe` | `现状`（OpenAI 兼容已接） |

**解析优先级**：带 `/` 按全名解析；不带 `/` 当默认引擎的简写（自动补默认前缀）。云端因需指明厂商+密钥，始终带 `/`，故裸名永远只落到本地默认引擎，无歧义。

---

## 四、多引擎将来的命令形态（路线）

规则不变，只是前缀从"默认引擎"扩展到"指定引擎"：

```bash
# 裸名 = 默认引擎(现在是 sherpa)——老命令永远不变
asrkit run whisper-small a.wav

# 指定引擎
asrkit run sherpa/whisper-small a.wav
asrkit run whispercpp/whisper-small a.wav
asrkit run faster-whisper/whisper-small:int8 a.wav

# pull / rm / show / 云端 同一套 来源/模型
asrkit pull whispercpp/whisper-small
asrkit rm   faster-whisper/whisper-large-v3
asrkit run  siliconflow/sensevoice a.wav --api-key <KEY>
```

`asrkit list` 按来源分组：

```
💻 sherpa/            (本地引擎 · 默认)
   ✓ sherpa/whisper-small
💻 whispercpp/        (本地引擎)
     whispercpp/whisper-small
☁️ siliconflow/       (云端)
     siliconflow/sensevoice
```

---

## 五、存储布局（路线）

按引擎分目录，不同格式互不覆盖：

```
~/.asrkit/models/sherpa/whisper-small/           # ONNX
~/.asrkit/models/whispercpp/whisper-small/       # GGML
~/.asrkit/models/faster-whisper/whisper-small/   # CTranslate2
```

> 现状：单引擎，平铺 `~/.asrkit/models/<model>/`（见 model-management.md）。多引擎时按 `<engine>/<model>/` 分层。

---

## 六、默认引擎

裸名与 `local/` 落到"默认引擎"。默认可由项目内定（当前 = sherpa-onnx，覆盖面最广），或用户配置（如 `ASRKIT_DEFAULT_ENGINE`）。

- 想省事 → 写裸名；
- 想精确控制 → 写 `引擎/模型`。

---

## 七、现状 vs 路线，以及"不破坏"保证

**现状（已实现，0.3.0）**：四个本地引擎——**sherpa-onnx（默认）**、**faster-whisper**、**transformers（含 torch）**、**whisper.cpp**；+ **entry-point 第三方引擎插件**；+ **sherpa 用户模型注册表**（模型开放）。寻址 `local/<model>` / `faster-whisper/<model>` / `whispercpp/<model>` / **`transformers/<任意 HF id>`** + 裸名简写 + `:tag`；云端 `provider/model`。`asrkit engine list/install` 管理引擎；`is_installed`/`install` 下沉各 adapter。

**路线（未实现，已留口子）**：更多引擎（whisper.cpp / transformers/vLLM）；entry-point 第三方引擎插件；`local/` 作"默认引擎"别名的进一步统一。

**不破坏保证**：因为命名空间从第一天就是正式名、裸名只是"默认引擎"的简写——将来新增引擎时，新引擎用自己的前缀，**所有既有写法（裸名 / `local/x` / 云端）含义不变、永不失效**。这就是我们保留命名空间的回报。

---

## 八、引擎作为可选组件（0.2.0 起部分实现）

> 状态（0.3.0）：pip extras + `asrkit engine list/install` + 懒加载/友好报错 + 可插拔 install + 开放 provider + **entry-point 第三方插件** + **sherpa 用户模型注册表** = **全部已实现**。首批第一方引擎：faster-whisper、transformers、whisper.cpp。扩展实操见 §九。

引擎不像模型是"下个权重文件"，它是**一个 Python 包**（含代码+二进制、有依赖树）。所以：

| | 模型（model） | 引擎（engine） |
|---|---|---|
| 是什么 | 权重文件（`.onnx` 等） | Python 包（sherpa-onnx / faster-whisper / pywhispercpp） |
| 怎么获取 | `asrkit pull`（下文件 → `~/.asrkit/models`） | **`pip` 安装**（有依赖树） |

**默认**：`pip install asrkit` 只带 sherpa-onnx（覆盖面最广）；其它引擎按需装，避免基础安装被 torch/ctranslate2 等撑爆。

注册中心本就按 `provider`（=引擎名）路由，故多引擎是**纯增量**，不改核心结构。

### 三个机制

**① pip extras —— 官方内置引擎**
```bash
pip install "asrkit[faster-whisper]"   # 装 ctranslate2 等 + 内置 adapter
pip install "asrkit[whispercpp]"
pip install "asrkit[engines]"          # 内置引擎全装
```
adapter 内置于 asrkit，但**懒加载**（用到才 import 引擎库），没装不崩。

**② entry-point 插件 —— 第三方/社区引擎**（见 §7 契约的 entry point）
```bash
pip install asrkit-vosk    # 独立包，启动时被 asrkit 自动发现注册
```
外部贡献者写新引擎无需改主仓。

**③ `asrkit engine` 命令 —— Ollama 式封装（对 pip 的糖）**
```bash
asrkit engine list                    # 引擎列表：装没装 / 谁是默认   （现状）
asrkit engine install faster-whisper  # 底层 = pip 装对应 extra/插件  （现状）
asrkit engine default whispercpp      # 设默认引擎（裸名落到它）       （现状，0.4.2）
asrkit engine rm faster-whisper       # 卸载引擎                      （路线）
```
> 现状：`engine` 实现 `list` / `install` / `default`（0.4.2 起，`default` 写入 `~/.asrkit/config.json`，裸名解析改读配置，缺省仍 `local`/sherpa）。`rm`（安全卸载，需处理 torch 等共享包）仍为路线。

### 跑起来什么样

```bash
asrkit engine install faster-whisper
asrkit pull faster-whisper/whisper-large-v3
asrkit run  faster-whisper/whisper-large-v3 a.wav

# 没装该引擎就用它 → 友好报错（带安装命令），不是 ModuleNotFoundError
asrkit run faster-whisper/whisper-small a.wav
# [error] engine 'faster-whisper' not installed. Run: pip install "asrkit[faster-whisper]"
```

`asrkit list` 里未安装引擎的模型照样列出（可发现），标注"引擎未装"引导安装。

### 两个设计要点

1. **懒加载 + 友好错误**：引擎库只在真正推理时 import；缺了返回"装这个引擎"的提示。没装某引擎的人，`list` / `pull sherpa/...` 一切照常。
2. **`engine install` 用 `sys.executable -m pip`**：即用 asrkit 当前所在的 Python/venv 去装，避免装错环境；执行前回显真实 `pip install ...` 命令（透明）。默认真跑（Ollama 式），留 `--print-only` 逃生舱。

---

## 九、扩展实操（0.3.0）

### 加一个自定义 sherpa 模型（模型开放）

**最简单：一条命令**（无需编辑文件）：
```bash
asrkit add-model local/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
asrkit pull local/my-model && asrkit run local/my-model a.wav
# 已有模型文件时：加 --model-dir /path 软链到位，免下载、立即可用
asrkit add-model local/my-model --arch senseVoice --model-dir /path/to/files
```

或**手动**写进 `~/.asrkit/models.json`（或 `$ASRKIT_MODELS_JSON`）：

```json
[
  {
    "id": "local/my-firered",
    "download_url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/xxx.tar.bz2",
    "config_type": "fireRedAsrCtc",
    "langs": ["zh", "en"]
  }
]
```

然后 `asrkit pull local/my-firered` → `asrkit run local/my-firered a.wav`。
字段：`id`（必填）、`download_url`、`config_type`（引擎架构，见 local_sherpa 支持列表）、`langs`；可选 `provider`（默认 sherpa-onnx）、`tag`、`base`、`sha256`。

### 写一个引擎插件（引擎开放）

第三方包让任何人加引擎，无需改 asrkit 核心：

1. 你的包里写一个 adapter 模块，导入时自注册：
```python
# asrkit_vosk/adapter.py
from asrkit.registry import register_protocol, register_models
from asrkit.types import AdapterMeta, BaseAdapter, TranscribeResult

@register_protocol("vosk")
class Vosk(BaseAdapter):
    def is_installed(self): ...
    def install(self, log=print): ...
    def transcribe(self, audio, opts): ...

register_models([AdapterMeta(id="vosk/small-en", provider="vosk", vendor="vosk",
    name="Vosk small (en)", source="local", modes=["batch"], langs=["en"])])
```
2. 在你的 `pyproject.toml` 声明 entry point：
```toml
[project.entry-points."asrkit.adapters"]
vosk = "asrkit_vosk.adapter"
```
3. `pip install asrkit-vosk` → asrkit 启动时自动发现、导入、注册；用户即可 `asrkit run vosk/small-en a.wav`。

契约细节见 `adapter-spec.md`。这就是"无偏见开放"：项目不当裁判，任何引擎都能插进来、且住在自己的包里（核心零维护负担）。

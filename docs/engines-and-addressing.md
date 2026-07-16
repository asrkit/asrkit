# 模型、引擎与寻址（设计说明）

> 本文解释 ASRKit 的两个核心概念（模型 vs 引擎）、已实现的多引擎寻址,以及仍未实现的存储/扩展路线。
> 目的：让新增本地引擎不改变既有 model string 含义。
> 标注：`现状` = 已实现；`路线` = 前瞻设计，尚未实现但已为其留好口子。

---

## 一、模型 ≠ 引擎

- **模型（model）= "内容"**：训练好的权重 + 架构（如 Whisper-small）。它本身只是一堆数字，不会自己跑。
- **引擎（engine / 运行时）= "播放器"**：把权重加载、喂音频、算出文字的软件。模型是死的，引擎让它动。

**同一个模型可以被多个引擎跑**，速度/内存/精度/功能各异——就像同一部电影用不同播放器放。

主流 ASR 引擎：

| 引擎 | 特点 | 能跑什么 |
|---|---|---|
| **sherpa-onnx**（当前默认） | 端侧首选，一个依赖覆盖几十个模型，平台广 | Zipformer/Paraformer/SenseVoice/Whisper/Moonshine/FireRed-CTC/Dolphin/NeMo… |
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
| 本地默认引擎全名 | `sherpa/sensevoice` | `现状` |
| **具体本地引擎** | `whispercpp/small`、`faster-whisper/small` | `现状` |
| sherpa 引擎 | `sherpa/whisper-small` | `现状`（sherpa-onnx 模型走 `sherpa/<folder>` 寻址；旧 `local/` 前缀作为历史别名永久保留、仍可解析，见下方说明） |
| 云厂商 | `siliconflow/sensevoice`、`openai/whisper-1` | `现状`（OpenAI transcription 兼容子集已接） |

**解析优先级**：带 `/` 按全名解析；不带 `/` 当默认引擎的简写（自动补默认前缀）。云端因需指明厂商+密钥，始终带 `/`，故裸名永远只落到本地默认引擎，无歧义。

> 注：sherpa 模型的规范前缀是 `sherpa/`；旧的 `local/` 前缀作为历史别名永久保留、仍可解析（如 `local/sensevoice` 等价 `sherpa/sensevoice`），存量脚本不受影响。

---

## 四、多引擎命令形态（现状）

规则不变，前缀从"默认引擎"扩展到"指定引擎"，已随 faster-whisper / whisper.cpp 两个引擎落地：

```bash
# 裸名 = 默认引擎(现在是 sherpa-onnx，寻址前缀 sherpa/)——老命令永远不变
asrkit run whisper-small a.wav

# 指定引擎（sherpa 走 sherpa/ 前缀；旧 local/ 前缀作为历史别名永久保留、仍可解析）
asrkit run sherpa/whisper-small a.wav
asrkit run whispercpp/small a.wav
asrkit run faster-whisper/small a.wav

# pull / show / 云端使用同一套 来源/模型；rm 还受缓存所有权约束
asrkit pull sherpa/whisper-small
asrkit rm   sherpa/whisper-small
asrkit run  siliconflow/sensevoice a.wav --api-key <KEY>
```

`asrkit list` 按来源分组（示意）：

```
💻 sherpa/            (本地引擎 · 默认 · sherpa-onnx)
   ✓ sherpa/whisper-small
💻 whispercpp/        (本地引擎)
     whispercpp/small
☁️ siliconflow/       (云端)
     siliconflow/sensevoice
```

---

## 五、存储布局（现状）

- ASRKit 自己下载和删除的 sherpa 模型平铺在 `~/.asrkit/models/<id 去掉首段 namespace>/`。
- faster-whisper/Transformers 等由上游 HuggingFace 生态管理缓存,不进入 `~/.asrkit/models`。
- whisper.cpp adapter 也遵循其上游模型获取方式;当前没有一套统一的 `<engine>/<model>` 本地目录树。
- `cache_owner` 明确记录所有权：sherpa/用户模型为 `asrkit`，上述外部缓存为 `engine`，云模型为 `none`，未声明的第三方 adapter 默认为 `unknown`。
- `asrkit rm` 只接受 `cache_owner=asrkit`。对 `engine/unknown` 返回英文指引且不调用本地 store；上游缓存请使用对应引擎自己的管理工具。

`is_installed()` 仍是兼容的 adapter-defined legacy installed/readiness hook,语义随引擎而异：sherpa 检查受管模型文件,外部引擎通常检查运行时包。它不代表权重一定已缓存；机器可读输出用独立的 `cached: true|false|null` 表达缓存事实,不能用 `installed` 推断。

Python 侧的冻结值对象 `ModelCacheState` 同时给出 `owner/cached/removable/location/size_bytes`。`BaseAdapter.cache_state()` 和 `remove_cached_model()` 是查询/删除边界；只有 owner 为 `asrkit` 时默认实现才进入 ASRKit store。外部引擎仍可在自己的 `install()` 中委托上游下载,但其缓存不会因此变成 ASRKit 资产。

未来若统一多引擎模型资产,必须先定义所有权、迁移和 `rm` 安全语义;不能只按目录美观重排公开存储契约。

---

## 六、默认引擎

裸名会补当前默认引擎前缀;显式 `sherpa/` 和历史别名 `local/` 始终指向 sherpa,不随默认引擎改变。默认引擎当前为 sherpa-onnx,可用 `asrkit engine default <name>` 或 `asrkit config set default-engine <name>` 持久化修改。

- 想省事 → 写裸名；
- 想精确控制 → 写 `引擎/模型`。

---

## 七、现状 vs 路线，以及"不破坏"保证

**现状（已实现，0.3.0）**：四个本地引擎——**sherpa-onnx（默认）**、**faster-whisper**、**transformers（含 torch）**、**whisper.cpp**；+ **entry-point 第三方引擎插件**；+ **sherpa 用户模型注册表**（模型开放）。寻址 `sherpa/<model>` / `faster-whisper/<model>` / `whispercpp/<model>` / **`transformers/<任意 HF id>`** + 裸名简写 + `:tag`；云端同样使用 `<source>/<model>`。`asrkit engine list/install` 管理引擎；legacy installed/readiness、缓存状态和安全删除分别由 `is_installed`、`cache_state`、`remove_cached_model` 表达。

**路线（未实现）**：新增有真实需求的引擎(如 vLLM ASR runtime)、插件 conformance kit,以及更完整的第三方 adapter 发现/兼容治理。whisper.cpp、transformers、entry-point 插件和 `local/ -> sherpa/` 历史别名均已实现,不再属于路线项。

**不破坏保证**：因为命名空间从第一天就是正式名、裸名只是"默认引擎"的简写——将来新增引擎时，新引擎用自己的前缀，**所有既有写法（裸名 / `sherpa/x` / 历史别名 `local/x` / 云端）含义不变、永不失效**。这就是我们保留命名空间的回报。

---

## 八、引擎作为可选组件（0.2.0 起部分实现）

> 状态（0.3.0）：pip extras + `asrkit engine list/install` + 懒加载/友好报错 + 可插拔 install + 开放 provider + **entry-point 第三方插件** + **sherpa 用户模型注册表** = **全部已实现**。首批第一方引擎：faster-whisper、transformers、whisper.cpp。扩展实操见 §九。

引擎不像模型是"下个权重文件"，它是**一个 Python 包**（含代码+二进制、有依赖树）。所以：

| | 模型（model） | 引擎（engine） |
|---|---|---|
| 是什么 | 权重文件（`.onnx` 等） | Python 包（sherpa-onnx / faster-whisper / pywhispercpp） |
| 怎么获取 | sherpa 由 `asrkit pull` 下载到 `~/.asrkit/models`；其它引擎可委托上游缓存 | **`pip` 安装**（有依赖树） |

**默认（0.5.0 起）**：`pip install asrkit` 只装**接口 + 云端**（仅 `requests`，秒装）；**所有本地引擎都是 opt-in extra**（含默认的 sherpa：`pip install "asrkit[local]"`）。避免基础安装被 onnx/torch/ctranslate2 等撑爆——ASRKit 是接口，引擎按需挂。

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

**功能性 opt-in extra（非引擎）**：`mic`、`serve` 不装模型/引擎，而是给某个 CLI 能力开关所需的依赖：
```bash
pip install "asrkit[mic]"    # 麦克风实时输入依赖（sounddevice + numpy），配合 asrkit stream <model> --mic
pip install "asrkit[serve]"  # HTTP 网关依赖（fastapi/uvicorn 等），配合 asrkit serve
```
和上面"引擎" extra（sherpa/faster-whisper/whispercpp/transformers）不是一类：引擎 extra 决定"能跑哪个模型"，`mic`/`serve` 决定"能不能用某个 CLI 功能"。

**③ `asrkit engine` 命令 —— Ollama 式封装（对 pip 的糖）**
```bash
asrkit engine list                    # 引擎列表：装没装 / 谁是默认   （现状）
asrkit engine install faster-whisper  # 底层 = pip 装对应 extra/插件  （现状）
asrkit engine default whispercpp      # 设默认引擎（裸名落到它）       （现状，0.4.1）
asrkit engine rm faster-whisper       # 卸载引擎                      （现状，劝告版，不代跑卸载）
```
> 现状：`engine` 实现 `list` / `install` / `default` / **`rm`**。`default` 自 0.4.1 写入 `~/.asrkit/config.json`;`rm` 劝告版已随 0.5.4 发布,只打印手动 `pip uninstall` 指引和共享依赖警告,若删除的是默认引擎则重置为 sherpa,**绝不代跑卸载**。

### 跑起来什么样

```bash
asrkit engine install faster-whisper
asrkit run faster-whisper/large-v3 a.wav   # 首次使用由 faster-whisper/HF 管理下载与缓存

# 没装该引擎就用它 → 友好报错（带安装命令），不是 ModuleNotFoundError
asrkit run faster-whisper/small a.wav
# [error] engine 'faster-whisper' not installed. Run: pip install "asrkit[faster-whisper]"
```

`asrkit list` 里未安装引擎的模型照样列出（可发现），标注"引擎未装"引导安装。

### 两个设计要点

1. **懒加载 + 友好错误**：引擎库只在真正推理时 import；缺了返回"装这个引擎"的提示。没装某引擎的人，`list` / `pull sherpa/...` 一切照常。
2. **`engine install` 用 `sys.executable -m pip`**：即用 asrkit 当前所在的 Python/venv 去装，避免装错环境；执行前回显真实 `pip install ...` 命令（透明）,然后执行安装。

---

<a id="engine-plugin-recipe"></a>

## 九、扩展实操（0.3.0）

### 加一个自定义 sherpa 模型（模型开放）

**最简单：一条命令**（无需编辑文件）：
```bash
asrkit add-model sherpa/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
asrkit pull sherpa/my-model && asrkit run sherpa/my-model a.wav
# 已有模型文件时可登记 --model-dir;rm 只删除 models root 内的链接,不删除外部文件
asrkit add-model sherpa/my-model --arch senseVoice --model-dir /path/to/files
```

或**手动**写进 `~/.asrkit/models.json`（或 `$ASRKIT_MODELS_JSON`）：

```json
[
  {
    "id": "sherpa/my-firered",
    "download_url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/xxx.tar.bz2",
    "config_type": "fireRedAsrCtc",
    "langs": ["zh", "en"]
  }
]
```

然后 `asrkit pull sherpa/my-firered` → `asrkit run sherpa/my-firered a.wav`。
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
    def supports_concurrent_calls(self): return False  # 默认即 False;仅无共享可变状态时返回 True
    def install(self, log=print): ...
    def transcribe(self, audio, opts): ...
    def close(self): ...                              # LRU 淘汰/app shutdown 时释放资源

register_models([AdapterMeta(id="vosk/small-en", provider="vosk", vendor="vosk",
    name="Vosk small (en)", source="local", modes=["batch"], langs=["en"],
    cache_owner="unknown")])  # 默认 unknown;只有确实使用 ASRKit store 时才声明 asrkit
```
2. 在你的 `pyproject.toml` 声明 entry point：
```toml
[project.entry-points."asrkit.adapters"]
vosk = "asrkit_vosk.adapter"
```
3. `pip install asrkit-vosk` → asrkit 启动时自动发现、导入、注册；用户即可 `asrkit run vosk/small-en a.wav`。

契约细节见 `adapter-spec.md`。这就是"无偏见开放"：项目不当裁判，任何引擎都能插进来、且住在自己的包里（核心零维护负担）。

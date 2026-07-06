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

**现状（已实现）**：单本地引擎 sherpa-onnx；寻址 `local/<model>` + 裸名简写 + `:tag` 精度；云端 `provider/model`。

**路线（未实现，已留口子）**：多本地引擎，用引擎名作命名空间；`local/` 退化为"默认引擎"的友好别名。

**不破坏保证**：因为命名空间从第一天就是正式名、裸名只是"默认引擎"的简写——将来新增引擎时，新引擎用自己的前缀，**所有既有写法（裸名 / `local/x` / 云端）含义不变、永不失效**。这就是我们保留命名空间的回报。

# ASRKit 项目详情概览

> 快照日期:2026-07-08(v0.5.3 + Unreleased 累积)。这是一份"项目全貌"文档,给新协作者/未来的自己快速建立完整心智。
> `[Unreleased]` 里已经又攒了一批未发版功能(serve SSE 流式、麦克风流式、流式端点检测分段、engine rm、`--verbose`/日志);本文档已把它们当作"已建成能力"记入。
> 深度底稿:批评与规划见 [expert-review-2026-07.md](expert-review-2026-07.md);对标业界见 [lifecycle-audit.md](lifecycle-audit.md);待办见 [roadmap.md](roadmap.md)。

---

## 一、这是什么

**语音识别的统一接口层** —— 换一个 model 字符串,就在**端侧模型 / 云端 API / 任意引擎**之间切换,代码不动。

类比 = **Ollama(模型 pull/rm 生命周期)+ LiteLLM(统一接口 + serve 代理)** 的语音版。

真正的差异化(西方工具的盲区):**端侧 47 个模型 pull-即用(含中文 SOTA:SenseVoice/Paraformer/FireRed/TeleSpeech)+ 中国云厂全覆盖(百炼/豆包/硅基流动)+ HuggingFace 开放寻址兜底**。

---

## 二、当前状态(快照)

| 维度 | 值 |
|---|---|
| 版本 | **0.5.3**(单一版本源 `src/asrkit/__init__.py`,hatchling 动态读) |
| 代码规模 | 源码 2516 行 / 20 文件(不含 adapters)+ adapters/ 1112 行 / 10 文件;测试 2013 行 / 19 文件 |
| 测试 | 165 passed, 2 skipped(e2e nightly);ruff + mypy 全绿 |
| 模型总数 | 71(47 sherpa 端侧 + 7 faster-whisper + 5 whispercpp + 2 transformers 精选 + 10 云端) |
| 成熟度 | 早期 Beta —— 内核 + 外围能力已随 0.5.0→0.5.3 补齐,流式契约(文件/分段/麦克风/serve SSE 四入口)已首次完整行使;ASR 专业字段(word-level 时间戳等)与生态收口(asrbench)是下一阶段重点 |

---

## 三、已建成的能力

### CLI
- **转写**:`run`(缺则下载再转)/ `transcribe`(只转);多文件/glob/目录递归/stdin(`-`)/`--batch`;
  格式 txt/json/srt/vtt/csv/tsv + `-o` + `--language`;`-v/-vv` 详细日志。
- **流式**:`stream <model> <audio>`(文件分块)/ `stream <model> --mic`(麦克风,opt-in `asrkit[mic]`);
  端点检测驱动 committed/partial 分段;共用 `transcribe_stream` + `PartialResult` 契约。
- **模型生命周期**:`pull`(`--url` 换源、tar.*/zip 多格式自动识别)/ `rm` / `show`
  (显示 multilingual/modes)/ `list`(`--json/--installed/--source/--lang/--arch/--ids`)/
  `search <term>`(id/name 子串)/ `add-model`。
- **引擎**:`engine list/install/default/rm`(rm 为劝告版,绝不代跑 pip uninstall)。
- **配置**:`config set-key/get-key/set/list/path`(密钥库 0600、打码)。
- **服务**:`serve`(OpenAI 兼容 HTTP,支持 `stream=true` SSE)。
- **体检**:`doctor [--net]`(引擎/密钥/models目录/config;硬问题退非零)。
- **补全**:`completion <bash|zsh|fish>`。

### Python API
`transcribe / pull / run / show / remove / list_models / transcribe_stream / transcribe_stream_mic`;附 `py.typed`。

### 引擎 × 模型
| 引擎 | 模型 | 特点 |
|---|---|---|
| sherpa-onnx(默认端侧) | 47,17 架构 | SenseVoice/Paraformer/Whisper/Zipformer/Parakeet/FireRed/Qwen3-ASR/Dolphin/Moonshine/Omnilingual…;pull 即用 |
| faster-whisper | 7 | HF 自动下载 + 自带长音频分块 |
| whispercpp | 5 | 超轻量,无 torch/onnx |
| transformers | 开放寻址 | `transformers/<任意 HF id>` |
| 云端(内置) | 10 | siliconflow×2、openai×1、dashscope×4、doubao×2、elevenlabs×1 |

### 三根支柱(设计哲学)
1. **薄内核**:`pip install asrkit` 只有 `requests`;引擎全 opt-in extra(含新增 `asrkit[mic]` = sounddevice+numpy,麦克风流式用)。
2. **透明音频**:core 零处理,格式不符诚实报错;`--convert`/`--segment` opt-in。
3. **model string 寻址**:精确 id → `base:tag` 别名(默认 int8)→ 裸名补默认引擎前缀 / 开放 provider 动态合成。

### 所有权模型
- **模型 = asrkit 独占**(pull/rm 对称)· **引擎 = 共享 pip 包**(帮装不代卸)· **云端 = 内置**(仅 requests)。

---

## 四、架构(分层)

```
契约   types.py         AdapterMeta / TranscribeResult / BaseAdapter(契约 v1)
能力   capabilities.py  language_hint 三态判读 / multilingual 判定
路由   registry.py      provider→adapter、id→meta、别名、开放 provider、插件
引擎   engines.py       引擎清单/安装状态/默认引擎解析
门面   api.py           transcribe/pull/run/show/remove/list_models/transcribe_stream(_mic)
CLI    cli.py           全部命令(644 行,最大;god-file 苗头)
体检   doctor.py        asrkit doctor —— 引擎/密钥/models目录/config 体检
补全   completion.py    asrkit completion <bash|zsh|fish>
日志   log.py           标准 logging 封装,-v/-vv 分级
麦克风 mic.py            实时采集(opt-in asrkit[mic])
输入   inputs.py        glob/目录递归/stdin 解析 → 文件列表 + 清理回调
发射   emit.py          批量 NDJSON/csv/tsv/-o 镜像 + 分级退出码
HTTP   _http.py         线程局部 Session + 分级重试(成本安全)
持久   config / usermodels / store   密钥库、用户模型表、pull/rm(原子/防穿越/多格式)
音频   audio.py         零处理内核 + 格式守卫
输出   formats.py       txt/json/srt/vtt 渲染 + result_dict
服务   server.py        OpenAI 兼容 /v1(adapter 缓存 LRU + 线程池 + SSE 流式)
adapters/  本地4引擎(sherpa 通吃 17 架构 / faster-whisper / whispercpp / transformers 开放)
           云端6协议(openai / doubao / qwen / qwen-omni / funasr-flash / elevenlabs)
```

**关键约定**:adapter 从不抛异常,错误进 `TranscribeResult.error`;插件走 entry-point(`asrkit.adapters`),坏插件不连坐。

---

## 五、质量与工程(项目强项)

- **版本纪律**:升号必人类批准,默认 PATCH;已发布(tag/PyPI)永久冻结。见 [CLAUDE 准则 / CHANGELOG]。
- **CI 双门**:`ruff` + `mypy` + 165 测试(3.9/3.13 矩阵)+ nightly 真实 E2E(pull whisper-tiny 真推理)。
- **全留档**:CHANGELOG、结果契约文档、每个功能波的 spec + plan(`docs/superpowers/`)。
- **开发流程**(W1/W2 实践):spec → Codex 评审 → 实现计划 → subagent 逐任务实现 + 两段式评审(契约+质量)→ opus 终审 → 合并。

---

## 六、还需要继续开发/完善的(按优先级)

> 核心结论:**广度 + 实度已基本兑现**(segments/选项诚实/元数据/流式四入口皆已行使,见 §五、§七);剩下的是零星打磨与生态收口。与 [roadmap.md](roadmap.md)"待办(按优先级)"章节保持同步,避免两处维护同一份清单。

### 仍真实待办
1. **`enable_punctuation` 未实现**:无 adapter 消费该选项,仍是纯占位参数。
2. **`cli.py` god-file**:644 行(比早前估的 ~490 行还严重),命令全堆一个文件,应升级为"更紧迫"的重构项。
3. **Windows 未验证未声明**:CI 只跑 3.9/3.13 矩阵(未含 Windows),README/文档也未声明支持状态。
4. **71 模型手维护表会腐烂**:无 nightly URL 体检,模型下载源失效不会被自动发现。

### 后续候选(按需,均非紧要,与 roadmap.md 一致)
- **词级时间戳**:流式/批量的 word-level timestamps(sherpa/whisper 部分支持);有明确消费者再做。
- **serve WebSocket 流式**:SSE 已覆盖单向流式;双向/低延迟场景才需要 WS。
- **`cost_estimate` 恒空、无置信度**:专家评审遗留的打磨项,非紧要。

---

## 七、路线图前瞻

| 波 | 主题 | 状态 |
|---|---|---|
| W3 | 元数据修真 + 发现 + 体检 | 已完成(0.5.3) |
| W4 | 最小流式(文件入口) | 已完成(0.5.3) |
| 流式扩面 | 端点分段(E)/ 麦克风(C)/ serve SSE(D) | 已完成(Unreleased,待发版) |
| W5 | 生态收口 | 待启动 —— asrbench 独立 repo、README 定位钉死、Windows CI/声明、发版节奏化 |

**1.0 门槛**(遥远且刻意):三样"项目宪法"——model string 寻址 / adapter 契约 / CLI 核心命令——稳定且愿背书。流式契约(W4 + 流式扩面)已首次完整行使,是 1.0 前必经关的已完成项。

---

## 八、明确不做(避免重复起意)

自动卸引擎 · 隔离环境 · engine disable · 装回 base 依赖 · 持久镜像配置 · 说话人分离(diarization)· 自研 VAD/音频前处理 · GUI/桌面端 · 主动追西方云厂长尾(Deepgram/AssemblyAI…)。需要的走 `raw_response` 逃生舱或 asrbench 侧组合;新云厂走 entry-point 插件。

---

## 九、生态定位

- **asrkit** = 跑模型出文本 + 延迟/RTF/成本的**接口**。
- **asrbench**(未来独立 repo,单向依赖 asrkit)= 评测/选型:归一化正确的 WER/CER、多维对比、数据集、报告。**依赖方向 asrbench→asrkit,绝不反向**,否则打脸"接口内核极小"。
- 老的 `asr_bench`(Flutter/真机)是**只读参考**,新项目干净重构。

---

> 一句话:**下一仗:实度已基本兑现(segments/选项诚实/元数据/流式四入口皆已行使);接下来是生态收口——启动 asrbench 作真用户验收、拆 cli.py god-file、补 Windows CI,零星打磨(enable_punctuation/词级时间戳)按需跟进。**

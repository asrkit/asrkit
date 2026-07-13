# ASRKit 项目详情概览

> 快照日期:2026-07-13(已发布版本 v0.5.4)。这是一份"项目全貌"文档,给新协作者/未来的自己快速建立完整心智。
> 当前源码另含尚未发布的 CLI 模块拆分、模型软链加固、nightly E2E/薄内核/源码验证收口、cloud-only registry/命令入口和文档修订;它们不是 v0.5.4 的发布事实。
> 历史分析快照见 [expert-review-2026-07.md](archive/expert-review-2026-07.md) 与 [lifecycle-audit.md](archive/lifecycle-audit.md)；它们不再维护。当前待办只看 [roadmap.md](roadmap.md)。
> 产品北极星见 [product-form.md](product-form.md);非 Python 产品的 Sidecar 集成、平台分发与未来 Go 运行时边界见 [embedding-and-distribution.md](embedding-and-distribution.md)。

---

## 一、这是什么

**语音识别的统一接口层** —— 换一个 model 字符串,就在**端侧模型 / 云端 API / 任意引擎**之间切换,代码不动。

类比 = **Ollama(模型 pull/rm 生命周期)+ LiteLLM(统一接口 + serve 代理)** 的语音版。

真正的差异化(西方工具常见的盲区):**端侧 47 个模型 pull-即用(含 SenseVoice/Paraformer/FireRed/TeleSpeech)+ 中国主流云厂首批覆盖(百炼/豆包/硅基流动)+ HuggingFace 开放寻址兜底**。

---

## 二、当前状态(快照)

| 维度 | 值 |
|---|---|
| 版本 | **0.5.4**(单一版本源 `src/asrkit/__init__.py`,hatchling 动态读) |
| 代码规模 | 当前源码 Python 源码 4020 行 / 40 文件;测试/E2E 3010 行 / 25 文件 |
| 测试 | 225 passed, 1 skipped;nightly 真实 E2E 1 passed;wheel 安装 smoke、ruff、mypy 全绿(2026-07-13,源码路径验证) |
| 模型总数 | 71(47 sherpa 端侧 + 7 faster-whisper + 5 whispercpp + 2 transformers 精选 + 10 云端) |
| 成熟度 | 早期 Beta —— 内核 + 外围能力已随 0.5.0→0.5.4 补齐,流式契约(文件/分段/麦克风/serve SSE 四入口)已首次完整行使;分发、安全边界和 ASR 专业字段仍需继续收口 |

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
- **配置**:`config set-key/get-key/set/list/path`(本地明文配置 0600、展示时打码)。
- **服务**:`serve`(OpenAI 兼容 HTTP,支持 `stream=true` SSE)。
- **云端专用入口**:`asrkit-cloud serve`(当前源码,尚未发布)在进程首次加载前锁定 cloud profile,只暴露 10 个内置云模型；目前仍需 Python + `serve` extra,不是自包含二进制。
- **体检**:`doctor [--net]`(引擎/密钥/models目录/config;硬问题退非零)。
- **补全**:`completion <bash|zsh|fish>`。

### Python API
`transcribe / pull / run / show / remove / list_models / transcribe_stream / transcribe_stream_mic`;附 `py.typed`。

### 引擎 × 模型
| 引擎 | 模型 | 特点 |
|---|---|---|
| sherpa-onnx(默认端侧) | 47,16 个 `config_type` | SenseVoice/Paraformer/Whisper/Zipformer/Parakeet/FireRed/Qwen3-ASR/Dolphin/Moonshine/Omnilingual…;pull 即用 |
| faster-whisper | 7 | HF 自动下载 + 自带长音频分块 |
| whispercpp | 5 | 超轻量,无 torch/onnx |
| transformers | 开放寻址 | `transformers/<任意 HF id>` |
| 云端(内置) | 10 | siliconflow×2、openai×1、dashscope×4、doubao×2、elevenlabs×1 |

### 三根支柱(设计哲学)
1. **薄内核**:`pip install asrkit` 只有 `requests`;引擎全 opt-in extra(含 `asrkit[mic]` = sounddevice+numpy),且独立子进程回归锁定注册表/CLI/server/mic 不提前加载任何可选重运行时；cloud profile 进一步跳过全部本地 adapter、插件和用户模型。
2. **透明音频**:core 零处理,格式不符诚实报错;`--convert`/`--segment` opt-in。
3. **model string 寻址**:精确 id → `base:tag` 别名(默认 int8)→ 裸名补默认引擎前缀 / 开放 provider 动态合成。

### 所有权模型
- **模型 = asrkit 独占**(pull/rm 对称)· **引擎 = 共享 pip 包**(帮装不代卸)· **云端 = 内置**(仅 requests)。

---

## 四、架构(分层)

```
契约   types.py         AdapterMeta / TranscribeResult / BaseAdapter(契约 v1)
能力   capabilities.py  language_hint 三态判读 / multilingual 判定
路由   registry.py      full/cloud 进程 profile、provider→adapter、id→meta、别名、开放 provider、插件
引擎   engines.py       引擎清单/安装状态/默认引擎解析
门面   api.py           transcribe/pull/run/show/remove/list_models/transcribe_stream(_mic)
CLI    cli.py + cli_commands/   完整 Python CLI；cloud_cli.py = cloud-only serve 入口(均尚未发布)
体检   doctor.py        asrkit doctor —— 引擎/密钥/models目录/config 体检
补全   completion.py    asrkit completion <bash|zsh|fish>
日志   log.py           标准 logging 封装,-v/-vv 分级
麦克风 mic.py            实时采集(opt-in asrkit[mic])
输入   inputs.py        glob/目录递归/stdin 解析 → 文件列表 + 清理回调
发射   emit.py          批量 NDJSON/csv/tsv/-o 镜像 + 分级退出码
HTTP   _http.py         线程局部 Session + 分级重试(成本安全)
持久   config / usermodels / store   本地配置、用户模型表、pull/rm(原子/防穿越/多格式)
音频   audio.py         零处理内核 + 格式守卫
输出   formats.py       txt/json/srt/vtt 渲染 + result_dict
服务   server.py        OpenAI 兼容 /v1(adapter 缓存 LRU + 线程池 + SSE 流式)
adapters/  本地4引擎(sherpa 通吃 16 个 config_type / faster-whisper / whispercpp / transformers 开放)
           云端6协议(openai / doubao / qwen / qwen-omni / funasr-flash / elevenlabs)
```

**关键约定**:adapter 从不抛异常,错误进 `TranscribeResult.error`;插件走 entry-point(`asrkit.adapters`),坏插件不连坐。

---

## 五、质量与工程(项目强项)

- **版本纪律**:升号必人类批准,默认 PATCH;已发布(tag/PyPI)永久冻结。见 [CLAUDE 准则 / CHANGELOG]。
- **CI 双门**:`ruff` + `mypy` + Python 3.9/3.13 测试矩阵;nightly 用固定 LibriSpeech fixture 执行 `sherpa/whisper-tiny` 的真实下载与推理,依赖/样本/下载/推理失败均为硬失败。
- **源码与产物双验**:普通 `python -m pytest` 强制命中当前 `src/`;CI 另从 wheel 临时安装目录启动完整 CLI 与 cloud CLI,检查 console entry 元数据和内置模型注册,避免“源码绿、安装包坏”。
- **全留档**:CHANGELOG、结果契约文档、每个功能波的历史 spec + plan(`docs/archive/superpowers/`)。
- **开发流程**(W1/W2 实践):spec → Codex 评审 → 实现计划 → subagent 逐任务实现 + 两段式评审(契约+质量)→ opus 终审 → 合并。

---

## 六、还需要继续开发/完善的(按优先级)

> 当前执行队列只在 [roadmap.md](roadmap.md) 维护。本节只列风险类别,不复制优先级和完成状态。

### 仍真实待办
1. **契约空字段**:`enable_punctuation`/`cost_estimate`/word timestamps 尚未普遍兑现。
2. **模型供应链**:下载 URL 手维护,license/sha256 覆盖不足,缺持续健康检查。
3. **跨平台**:常规 CI 只有 Linux;Windows 尚未验证,未来 Sidecar 还需要三平台构建与签名。
4. **HTTP 边界**:当前 `serve` 是受信任本机服务,无内置鉴权、限流和请求体上限；cloud-only Python 入口已落地,但自包含 `asrkit-cloud` 发行物与 embedded 安全边界仍未实现。

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
| 流式扩面 | 端点分段(E)/ 麦克风(C)/ serve SSE(D) | 已完成(0.5.4) |
| 工程收口 | CLI + 可信性缺口 | 已完成并评审,尚未发布 |
| 当前 P0 | `asrkit-cloud` 形态验证 | cloud-only 入口已完成；embedded 生命周期与安全边界下一步 |
| 生态 | asrbench / 插件 conformance / 专业字段 | P0 稳定后按需启动 |

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

> 一句话:**cloud-only Python 运行边界已经落地;下一刀是 embedded 启动/退出契约与安全边界,随后再冻结成真正无 Python 安装要求的 Sidecar。**

# ASRKit 项目详情概览

> 快照日期:2026-07-07(v0.5.2)。这是一份"项目全貌"文档,给新协作者/未来的自己快速建立完整心智。
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
| 版本 | **0.5.2**(单一版本源 `src/asrkit/__init__.py`,hatchling 动态读) |
| 代码规模 | 源码 ~2800 行 / 25 文件;测试 ~940 行 / 9 文件 |
| 测试 | 82 passed, 1 skipped(e2e nightly);ruff + mypy 全绿 |
| 模型总数 | 71(47 sherpa 端侧 + 7 faster-whisper + 5 whispercpp + 2 transformers 精选 + 10 云端) |
| 成熟度 | 早期 Beta —— 内核可用、外围(批量/契约/重试)刚随 0.5.0→0.5.2 补齐 |

---

## 三、已建成的能力

### CLI
- **转写**:`run`(缺则下载再转)/ `transcribe`(只转);**多文件/glob/目录递归/stdin(`-`)/`--batch`**;格式 `txt/json/srt/vtt/csv/tsv` + `-o` + `--language`。
- **模型生命周期**:`pull`(`--url` 换源、多格式 tar.*/zip 自动识别)/ `rm` / `show` / `list`(`--json/--installed/--source`)/ `add-model`。
- **引擎**:`engine list/install/default`。
- **配置**:`config set-key/get-key/set/list/path`(密钥库 0600、打码)。
- **服务**:`serve`(OpenAI 兼容 HTTP)。

### Python API
`transcribe / pull / run / show / remove / list_models`;附 `py.typed`。

### 引擎 × 模型
| 引擎 | 模型 | 特点 |
|---|---|---|
| sherpa-onnx(默认端侧) | 47,15 架构 | SenseVoice/Paraformer/Whisper/Zipformer/Parakeet/FireRed/Qwen3-ASR/Dolphin/Moonshine/Omnilingual…;pull 即用 |
| faster-whisper | 7 | HF 自动下载 + 自带长音频分块 |
| whispercpp | 5 | 超轻量,无 torch/onnx |
| transformers | 开放寻址 | `transformers/<任意 HF id>` |
| 云端(内置) | 10 | siliconflow×2、openai×1、dashscope×4、doubao×2、elevenlabs×1 |

### 三根支柱(设计哲学)
1. **薄内核**:`pip install asrkit` 只有 `requests`;引擎全 opt-in extra。
2. **透明音频**:core 零处理,格式不符诚实报错;`--convert`/`--segment` opt-in。
3. **model string 寻址**:精确 id → `base:tag` 别名(默认 int8)→ 裸名补默认引擎前缀 / 开放 provider 动态合成。

### 所有权模型
- **模型 = asrkit 独占**(pull/rm 对称)· **引擎 = 共享 pip 包**(帮装不代卸)· **云端 = 内置**(仅 requests)。

---

## 四、架构(分层)

```
契约   types.py         AdapterMeta / TranscribeResult / BaseAdapter(契约 v1)
路由   registry.py      provider→adapter、id→meta、别名、开放 provider、插件
门面   api.py           transcribe/pull/run/show/remove/list_models
CLI    cli.py           全部命令(~490 行,最大;god-file 苗头)
输入   inputs.py        glob/目录递归/stdin 解析 → 文件列表 + 清理回调
发射   emit.py          批量 NDJSON/csv/tsv/-o 镜像 + 分级退出码
HTTP   _http.py         线程局部 Session + 分级重试(成本安全)
持久   config / usermodels / store   密钥库、用户模型表、pull/rm(原子/防穿越/多格式)
音频   audio.py         零处理内核 + 格式守卫
输出   formats.py       txt/json/srt/vtt 渲染 + result_dict
服务   server.py        OpenAI 兼容 /v1(adapter 缓存 + 线程池)
adapters/  本地4引擎(sherpa 通吃 15 架构 / faster-whisper / whispercpp / transformers 开放)
           云端6协议(openai / doubao / qwen / qwen-omni / funasr-flash / elevenlabs)
```

**关键约定**:adapter 从不抛异常,错误进 `TranscribeResult.error`;插件走 entry-point(`asrkit.adapters`),坏插件不连坐。

---

## 五、质量与工程(项目强项)

- **版本纪律**:升号必人类批准,默认 PATCH;已发布(tag/PyPI)永久冻结。见 [CLAUDE 准则 / CHANGELOG]。
- **CI 双门**:`ruff` + `mypy` + 82 测试(3.9/3.13 矩阵)+ nightly 真实 E2E(pull whisper-tiny 真推理)。
- **全留档**:CHANGELOG、结果契约文档、每个功能波的 spec + plan(`docs/superpowers/`)。
- **开发流程**(W1/W2 实践):spec → Codex 评审 → 实现计划 → subagent 逐任务实现 + 两段式评审(契约+质量)→ opus 终审 → 合并。

---

## 六、还需要继续开发/完善的(按优先级)

> 核心结论:**广度已一线,ASR 专业字段还空心**。详见 [expert-review-2026-07.md](expert-review-2026-07.md)。

### 🔴 高(信誉/功能缺口)
1. **字幕空心**:**零 adapter 填 `segments`** → `srt/vtt` 对全部 71 模型只报错。faster-whisper/whispercpp 引擎免费给了带时间戳的 segments 却被丢弃。修法优先级:faster-whisper(零成本)→ whispercpp → openai `verbose_json` → sherpa。
2. **选项静默丢弃**:`enable_punctuation` 无人实现;`--language` 云端 openai 不透传。应 `capabilities` 驱动 → 不支持进 `warnings`。

### 🟠 中
3. **元数据失真**:omnilingual 标 `["zh","en"]`(实 1600 语)、whisper 全系同病 → `list --lang` 会漏。先修数据再上筛选。
4. **doubao 定时炸弹**:轮询固定 30×1s(长音频必超时);submit 硬编码 `format:"wav"`。
5. **serve 缓存无上限**:`_ADAPTERS` 只进不出 → 多大模型 OOM。
6. **流式契约从未行使**:`PartialResult`/`transcribe_stream` 零实现;13 streaming 模型已注册,离最小实现很近。**1.0 前必走通**。

### 🟡 低
7. `cost_estimate` 恒空、无置信度;`--segment` VAD 要自备(可做成 `pull silero-vad`);71 模型手维护表会腐烂(nightly URL 体检);`cli.py` god-file(抽分发表);Windows 未验证未声明;`asrkit doctor`;shell 补全。

---

## 七、路线图前瞻

| 波 | 主题 | 内容 |
|---|---|---|
| **W3** | 先修真,再发现 | 元数据修真 → 契约做实(segments/选项/language/doubao)→ 发现(`list --lang`/search/补全/`doctor`)→ 运维(URL 体检/serve 缓存/cli 重构) |
| **W4** | 最小流式 | sherpa online 实现 `transcribe_stream`,以此校订 PartialResult 契约(1.0 前必经仪式) |
| **W5** | 生态收口 | 启动 **asrbench**(独立 repo,消费 W1 契约 = 第一个真用户)、README 定位钉死、Windows CI/声明、发版节奏化 |

**1.0 门槛**(遥远且刻意):三样"项目宪法"——model string 寻址 / adapter 契约 / CLI 核心命令——稳定且愿背书。流式契约(W4)是必经关。

---

## 八、明确不做(避免重复起意)

自动卸引擎 · 隔离环境 · engine disable · 装回 base 依赖 · 持久镜像配置 · 说话人分离(diarization)· 自研 VAD/音频前处理 · GUI/桌面端 · 主动追西方云厂长尾(Deepgram/AssemblyAI…)。需要的走 `raw_response` 逃生舱或 asrbench 侧组合;新云厂走 entry-point 插件。

---

## 九、生态定位

- **asrkit** = 跑模型出文本 + 延迟/RTF/成本的**接口**。
- **asrbench**(未来独立 repo,单向依赖 asrkit)= 评测/选型:归一化正确的 WER/CER、多维对比、数据集、报告。**依赖方向 asrbench→asrkit,绝不反向**,否则打脸"接口内核极小"。
- 老的 `asr_bench`(Flutter/真机)是**只读参考**,新项目干净重构。

---

> 一句话:**内核与纪律一线,广度随 0.5.2 补齐;下一仗打"实度"——兑现 segments、选项诚实、元数据、流式契约,再用 asrbench 当第一个真用户验收。**

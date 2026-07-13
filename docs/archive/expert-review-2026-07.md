# ASRKit 专家评估 — 批评意见与发展规划(2026-07)

> **历史快照，不再维护。** 本文保留当时的评审判断和阶段编号；当前事实与优先级以 [`../project-overview.md`](../project-overview.md) 和 [`../roadmap.md`](../roadmap.md) 为准。

> 立场:以 **ASR 领域专家 + 工程/架构师** 视角对项目做一次"红队式"评估。刻意苛刻,每条批评附代码证据。
> 与 [lifecycle-audit.md](lifecycle-audit.md) 的关系:那篇对标业界 CLI 的**外围生命周期**(发现/获取/输入/输出/维护),本篇聚焦它没覆盖的三层——**ASR 专业深度、架构隐患、战略定位**。重叠处不赘述。
> 评估时点:v0.5.1 + 未发版的 W0(安全网)/W1(批量+契约)/W2(云端重试+下载覆盖)。
> 严重度:🔴 高(功能性/信誉性缺口) / 🟠 中(该修,不急) / 🟡 低(记账)。

---

## 一、总评

**一句话:接口的"广度"已经一线,但 ASR 专业字段的"实度"还是空心的。**

内核架构(薄接口 + 可插拔 + model string 寻址)、工程纪律(版本纪律、CHANGELOG、82 条测试、CI 双门)、透明原则,在个人开源项目里是罕见的好。W0-W2 三波把外围(批量、契约、重试、多格式)补齐后,**"能用"层面没有明显短板了**。

但以 ASR 专家的眼光看:`TranscribeResult` 里那些专业字段——`segments`、`word_timestamps`、`cost_estimate`、`enable_punctuation`——**大多是"接口上写了、实现里没人管"的装饰**。这批空心字段构成了当前最大的信誉风险:用户按文档用 `-f srt`,10 个模型 10 个报错。广度够了,下一阶段的主题应该是**把已承诺的字段做实,而不是继续加新面**。

---

## 二、值得保住的(不展开)

版本纪律(升号必问人)/ 透明音频(诚实报错不出乱码)/ 薄内核(base 只有 requests)/ 所有权模型(模型独占、引擎共享、云端内置)/ 成本安全的重试分级(W2)/ 测试文化(0→82 条,全 mock 不打真 API)。**这些是身份,别为任何功能牺牲。**

---

## 三、批评意见

### A. ASR 专业域(最需要补的一层)

**A1 🔴 字幕功能是空中楼阁:没有任何 adapter 填 `segments`。**
`grep segments= src/asrkit/adapters/` → 零命中。后果:W1 刚建好的 `-f srt/vtt`(含 `-o` 目录镜像)**对全部 71 个模型都只会诚实报错**——诚实,但覆盖率 0% 的功能等于没有。最刺眼的是浪费:
- `local_faster_whisper.py:transcribe` 拿到引擎免费给的 `segments`(带起止时间),却 `"".join(s.text ...)` 拼完就丢;
- `local_whispercpp.py` 的 pywhispercpp segments 自带 `t0/t1`,同样丢弃;
- `cloud_openai.py` 不请求 `verbose_json`,whisper-1 明明能返回 segments。
**修法优先级:faster-whisper(零成本)→ whispercpp → openai verbose_json → sherpa(部分架构有 timestamps)。**

**A2 🔴 选项静默丢弃,违反自家"诚实"原则。**
- `TranscribeOptions.enable_punctuation`:**全仓库无人实现**(仅 types.py 定义)。
- `--language`:`cloud_openai.py` 的 `data={"model": ...}` **不透传 language**——whisper-1 支持该参数,用户传了等于没传。
- `enable_itn`:只有 sherpa senseVoice 用。
项目对音频格式"不符即报错、绝不静默",对**选项**却全面静默吞掉——双标。`AdapterMeta.capabilities` 字段早就存在却无人消费,正是现成的解法:**选项 → capabilities 核对 → 不支持就 warning**(进 `result.warnings`,CLI 已会打印)。

**A3 🟠 模型元数据失真,W3 的发现功能会建在坏数据上。**
`models_local.py`:`omnilingual-300m` 名字写着 "1600 langs",`langs=["zh","en"]`;whisper 全系(~100 语)也标 `["zh","en"]`;云端 `openai/whisper-1` 标 4 语。计划中的 `list --lang` 一旦上线,`--lang ja` 会漏掉一堆其实支持日语的模型——**先修数据再建筛选,顺序不能反**。

**A4 🟠 流式契约从未被行使过,冻结前必须先用一次。**
`PartialResult`/`transcribe_stream` 是"项目宪法"三件套之一的候选,但从 0.1.0 至今**零实现、零调用**。未经行使的契约几乎必然是错的(缺 endpoint 事件?缺 VAD 信号?`committed/partial` 语义对不对?)。而实现门槛其实不高:**13 个 streaming 模型已注册、`_decode_online` 已存在**——离最小流式只差一层管道。1.0 之前必须至少走通一次,否则冻结的是猜想。

**A5 🟠 云端 adapter 对透明原则自相矛盾 + doubao 定时炸弹。**
- `cloud_doubao.py` submit 硬编码 `"audio": {"format": "wav"}`、`cloud_dashscope.py` funasr 硬编码 `"format": "wav", "sample_rate": "16000"`——用户传 mp3 时**字节透明上传、元数据却撒谎说是 wav**。
- doubao 轮询 `for _ in range(30): sleep(1)` 固定 30 秒:长音频(转写处理 >30s)**必然超时**。轮询上限应随音频大小/时长伸缩。

**A6 🟡 `cost_estimate` 恒空 + 无置信度。**
pricing 元数据齐全(`{"unit":"hour","cny":...}`),但 `grep cost_estimate= adapters/` 零命中。诚实的说法:透明架构下云端不解码就不知时长,**本地端能算但免费没意义**。修法:优先从 vendor 响应里的 usage/duration 字段(dashscope/doubao 的 raw_response 常带)提取计算;取不到就在 result-contract.md 里诚实标注"预留,当前恒空"。置信度(word/segment confidence)同理——contract 有位、无人填,标注清楚。

**A7 🟡 `--segment` 的 VAD 是 env-var footgun。**
要用户自备 `ASRKIT_VAD_MODEL=silero_vad.onnx` 路径——silero-vad 才 ~2MB,完全可以注册成一个可 `pull` 的内置模型(`local/silero-vad`),`--segment` 缺了就提示 `asrkit pull silero-vad`。与 pull/rm 生命周期完美同构,体验从"翻文档找模型"变成一条命令。

### B. 工程 / 架构

**B1 🟠 serve 的 adapter 缓存无上限、永不逐出。**
`server.py` `_ADAPTERS: dict = {}` 只进不出。连续调 5 个 whisper-large 级本地模型 → 每个常驻数 GB → OOM。最小修:环境变量上限 + 简单 LRU(或至少上限报错),几十行。

**B2 🟠 71 个模型的手维护表会腐烂,且无人会先知道。**
`models_local.py` 的下载 URL 指向 sherpa-onnx release 的**具体资产名**(带日期)。上游改名/删档 → 用户 `pull` 404 → issue 才暴露。nightly e2e 已有,**顺手加一个 URL 存活体检**(71 个 HEAD 请求,几秒)即可把"用户报障"变"自己先知道"。

**B3 🟡 `cli.py` 正在长成 god-file。**
~470 行、全部命令内联在 `main()` 的 if 链里。现在还行,但 doctor / list 筛选 / 补全进来必然突破 600+。**下一个新命令落地前**先抽 `{cmd: handler}` 分发表,一次小重构,别拖到疼。

**B4 🟡 测试隔离靠 hack + 跨模块私有依赖。**
registry 是模块级可变单例,测试里到处 `registry._loaded = False` 强刷;W1 的 cli 批量直接调 `api._run_adapter`(私有)。都能用,但都是债:前者该给个 `registry.reset()`(仅测试用),后者该把 `_run_adapter` 转正或给个受祝福的入口。

**B5 🟡 Windows 从未被验证,却也没被诚实排除。**
CI 只有 ubuntu;`chmod 0600` 在 Windows 无意义(密钥保护静默失效);glob/路径大体没问题但没人跑过。二选一:CI 加 windows job,或 README 诚实写"Linux/macOS;Windows 未验证"。**装作支持是最差选项。**

**B6 🟡 纯 http 拉权重 + sha256 可选 = 可被 MITM 的模型安装。**
W2 的 `pull --url` 放行 `http://`;内置表虽全是 https,但用户自定义源走明文时应至少 **警告**(或要求带 `--sha256`)。模型权重是要执行推理的二进制,供应链敏感度不低。
另:云端 adapter 的**真机覆盖为零**(全 mock,可理解——要钥匙要钱)。可选项:secrets 驱动的 nightly 云端冒烟(打一条最便宜的 siliconflow 免费模型),是否开由人类定(涉及成本)。

### C. 战略 / 定位

**C1 🟠 真正的护城河没有被说破。**
README 现在讲"one interface, local & cloud"——这是 category 描述,不是差异化。看竞品:speaches/faster-whisper-server 只做 whisper 系 serve;LiteLLM 迟早碰音频但不会碰端侧;西方工具**没有一个**覆盖 dashscope/doubao/siliconflow。ASRKit 实际的独特组合是:**① sherpa 47 个端侧模型的 pull-即用(含中文 SOTA:SenseVoice/Paraformer/FireRed/TeleSpeech)+ ② 中国云厂全覆盖 + ③ transformers 开放寻址兜底**。一句话定位应该钉成:**"中文/多语 ASR 全景的统一接口——端侧到云端,一个 model string。"** 这也反过来指导优先级:A3 的元数据修真、中文文档,比追西方云厂(Deepgram 等)优先。

**C2 🟡 三波改动攒着未发版,风险在累积。**
W0+W1+W2 = 退出码行为变更 + 新契约 + 重试语义,全堆在 `[Unreleased]`。攒得越久,一次发版的 blast radius 越大,回滚定位越难。**建议尽快切一个 PATCH(如 0.5.2)**——数字由人拍板,这里只提"该切了"。

**C3 🟡 asrbench 的启动时机已经到了。**
W1 的 NDJSON/csv/退出码契约就是为它铺的路基,再不开工,契约就会在没有真实消费者的情况下继续演化——**契约的最好测试是第一个真用户**。启动 asrbench(独立 repo)本身就是对 asrkit 契约的验收。

---

## 四、发展规划(修订波次)

原 W3(发现)/W4(流式)保留,但**插入"做实"优先于"做多"的排序**。每项落地默认 PATCH,升号先问人类。

### W3 · 先修真,再发现(合并波)
| 步 | 内容 | 对应批评 |
|---|---|---|
| 3a | **元数据修真**:langs 按官方口径修正(whisper 全系/omnilingual/云端);capabilities 补 `word_timestamps`/`punctuation` 等真实能力位 | A3 |
| 3b | **契约做实**:faster-whisper/whispercpp 填 `segments`(srt/vtt 从 0% 覆盖变可用);openai 走 `verbose_json`;`--language` 云端透传;不支持的选项 → `result.warnings`(capabilities 驱动);doubao 轮询按文件大小伸缩 + format 字段不再撒谎;cost_estimate 从 vendor usage 提取或诚实标"预留" | A1 A2 A5 A6 |
| 3c | **发现体验**:`list --lang/--arch`、`search`、shell 补全(bash/zsh/fish)、`asrkit doctor`(3a/3b 修完,doctor 才有真东西可检) | 承接 lifecycle-audit |
| 3d | **运维便宜活**:nightly URL 存活体检;serve 缓存上限;`pull --url` http 警告;cli 分发表重构(随 doctor 一起) | B1 B2 B3 B6 |

### W4 · 最小流式(单独慎做,先行使契约)
- 给 sherpa online 模型实现 `transcribe_stream`(管道已有八成);CLI `--stream`(文件分块喂,麦克风可后置);**以此校订 PartialResult 契约**——1.0 前的必经仪式。serve 的 SSE/WS 流式端点后置。(A4)

### W5 · 生态与收口
- **启动 asrbench**(独立 repo,消费 W1 契约,反向验收 asrkit);README 一句话定位钉死(C1);Windows CI 或诚实声明(B5);registry.reset() 等测试债清理(B4);发版节奏化(每 1-2 波一个 PATCH)。

### 发版建议(需人类拍板)
- **现在**:W0+W1+W2 → 一个 PATCH(建议 0.5.1 → 0.5.2),CHANGELOG 已备好,退出码变更已醒目标注。
- W3 完成 → 再一个 PATCH。**MINOR 继续留给破坏性/里程碑,不动。**

---

## 五、明确不做(重申 + 新增)

重申 roadmap 既有不做项(自动卸引擎/隔离环境/engine disable/装回 base 依赖/持久镜像配置)。**新增**:
- **说话人分离(diarization)/ 强制对齐** —— 独立生态(pyannote 等),接口层不吞;需要的用户走 `raw_response` 逃生舱或 asrbench 侧组合。
- **自研 VAD / 音频前处理** —— 永远只集成(silero),透明原则不破。
- **GUI / 桌面端** —— asr_bench(Flutter)是只读参考,asrkit 永远是 CLI/库/HTTP。
- **追平西方云厂长尾(Deepgram/AssemblyAI/Azure…)** —— 不主动追;entry-point 插件机制就是给社区留的门,核心只维护现有 6 协议 + 有真实用户需求再说。

---

## 六、一句话收尾

> **广度已经赢了,下一仗打"实度":把 segments、选项诚实、元数据、流式契约这些已经写在接口上的承诺一一兑现——然后用 asrbench 当第一个真用户来验收它。**

# ASRKit 0.1.0 硬化规格（开发流程文档）

> 目的：把两轮评审（多智能体 + Codex 交叉复核）的所有发现，转成**可执行、可验收**的规格条目。
> 用法：每条 = 问题 / 决策 / 规格 / 涉及 / 验收 / 状态。**先定规格，再实现，实现须过验收。**
> 状态：`TODO` · `DOING` · `DONE`（完成并验收）· `DEFER`（明确推迟）。
> Codex 评审（2026-07）结论：好底稿，`REQUEST CHANGES`——本文件已吸收其全部改进。

---

## 一、核心设计决定（最高优先）

### D-1 透明层：内核对音频零处理 · `DONE`(契约) / `TODO`(实现)
**决策（项目主人拍板）**：ASRKit **内核对音频不做任何处理**——用户输入什么，就原样递给 adapter。不解码、不重采样、不混声道、不做增强（VAD/降噪/音量归一化/切段）、不对输出做后处理。用 asrkit 跑某模型 == 直接用该模型；ASRKit 只是"统一接口 + 快速换模型"这一层。
**规格（统一原则）**：
- **内核**：把原始音频（`original_path` / 字节）原样交给 adapter，自身零处理。
- **云端 adapter**：原始文件**字节级原样上传**，连解码都不做。
- **本地 adapter**：默认**也不转换**。读原始文件采样点，做**格式守卫**：若采样率/声道/格式 ≠ 引擎要求（sherpa = 16k 单声道）→ 返回**清晰 error**（诚实告知"实际 44100Hz 立体声，要求 16000Hz 单声道，请自行转换或加 `--convert`"），**绝不静默出乱码**。用户显式 `--convert` / `opts.convert=True` 才做解码+重采样+混单声道。
- **增强**（VAD/降噪/切段/长音频分块）：全部 opt-in，默认关。
- **输出**：原样返回，不加/改标点、大小写、ITN——除非模型自带或用户显式开启（注意：现 `use_itn=True` 需改为跟随模型默认/可配置，见 H-07）。
**验收（Codex：改为可测，不用"逐字一致"）**：
- 云端：mock `requests.post`，断言上传文件的 sha256 == 原始文件 sha256（未被预处理）。
- 本地守卫：喂 44.1k/立体声 → 默认返回明确 error（含实际 vs 要求）；`convert=True` → 正常转写。
- 少量真机 golden 仅做 smoke。
**措辞收窄（Codex）**：不承诺"与官方示例字节级等价"（本地解码/重采样本就存在），只承诺"内核不加工 + 本地仅做引擎必需转换 + 转换规则公开"。

### D-2 音频入口重构：内核零处理，解码下沉到本地 adapter · `TODO` · P0
**问题**：现 `api.transcribe()` 先全局 `load_audio()` 解码，再把（重采样后的）文件当 path 上传云端——违反 D-1，且会让"云端能吃、本地 soundfile 解不了"的 mp3/m4a 在云端路径先本地失败（Codex 反例）。
**规格**：
- `load_audio()` 移出内核路径；`AudioInput` = `original_path`（+ 可选原始字节）；`samples` 惰性、默认 `None`。
- **云端 adapter 必须走 `samples=None`**：不得 import/调用 `soundfile`/`soxr`/解码——直接上传 `original_path`。
- 本地 adapter：调 `audio.load_samples(path, required_sr, required_ch, convert=opts.convert)`（内核不调）。默认 `convert=False`：格式/采样率/声道不符即返回**清晰 error**，不静默出乱码；`convert=True` 才解码+重采样+混单声道。新增 `TranscribeOptions.convert`（默认 False）+ CLI `--convert`。
- 云端遇厂商不支持的格式/大小/时长：返回友好错误，或用户显式 `opts.preprocess_for_cloud=True` 才转码——**绝不偷偷转码**。
**涉及**：`types.py`、`audio.py`、`api.py`、`adapters/cloud_openai.py`、`adapters/local_sherpa.py`。
**验收**：`import` 云端 adapter 不触发 soundfile；云端上传 hash == 原始；本地仍能转写；不支持格式给明确错误。
（H-06 临时 wav 泄漏并入本条：内核不再生成临时 wav。）

### D-3 长音频：不静默截断，warnings 一等字段 · `TODO` · P0（警告部分）
**问题**：whisper 系（15 个）对 >30s 音频只转前 30 秒、`text` 正常返回、`error` 为空——静默数据丢失。
**决策**：默认不切段（尊重原生），但**绝不静默丢数据**。
**规格（Codex：定死字段，不再二选一）**：
- `TranscribeResult.warnings: list[str]`（新增一等字段）；CLI **必须** stderr 打印 warnings。
- `AdapterMeta.capabilities` 增 `max_input_duration_s`（或 `truncation_behavior`）——引擎据此判断是否超窗、发警告，取代模糊的"其它离线给保守阈值"。
- opt-in：`TranscribeOptions.segment=False`（默认）；开启后移植 `worker.py` 的 silero-VAD 分段拼接。
**验收**：60s 音频喂 whisper：默认 → 前 30s 文本 + `warnings` 非空 + CLI stderr 有提示；`segment=True` → 全长文本。

---

## 二、安全与正确性

### H-01 [P0] tar 解压路径穿越 · `TODO`
**规格**：Python≥3.12 传 `extractall(..., filter="data")`；<3.12 逐成员校验 `realpath` 落在解压目录内、拒绝 symlink/hardlink/device。
**验收（Codex：覆盖全类型）**：`../evil`、绝对路径、symlink、hardlink、device 成员各构造一个 tar，pull 时全部被拒且不写出目录外。

### H-02 [P1] pull 原子化 + 按 install_files 校验完整性 · `TODO`
**规格**：解压到 `dest + ".partial"` → 全部就位后 `os.rename` 原子换入；`is_installed` **不只靠 `.done`，还按每模型 `install_files`（glob/目录）逐项校验**（Codex）。
**验收**：pull 中途 kill → 再次 pull 重下而非误判已装；缺文件的目录判为未装。

### H-03a [P1] 下载超时 · `TODO`
`urlopen(req, timeout=30)`；失败清理半截文件、抛带 URL 的可读错误。验收：断网 30s 内报错退出。

### H-03b [P1·发布阻断] 下载 sha256 校验 · `TODO`
`_TABLE` 每条登记 sha256（`AdapterMeta` 加 `sha256` 字段，回写契约 §6）；下载后校验，不匹配即删除报错。验收：篡改一字节的 tar 被拒。

### H-04 [P1] CLI 异常兜底 · `TODO`
**Codex 实测确认**：`asrkit run local/sensevoic x.wav` 现在输出 KeyError traceback。
**规格**：`run`/`transcribe` 复用 `pull` 分支的 try/except，打印 `[错误] {e}` 并 `return 1`；`api` 层用语义异常（`ModelNotFoundError`）替代裸 `KeyError`。验收：拼错模型名 → 一行友好错误，无 traceback。

### H-05 [P1] API Key 环境变量兜底 · `TODO`
key 链 = 显式 `config["api_key"]` > 环境变量 `<VENDOR>_API_KEY` > 无。文档把 env 列推荐、`--api-key` 标注慎用（进 shell history）。验收：`export SILICONFLOW_API_KEY=… && asrkit transcribe …` 免 `--api-key` 可用。

### H-07 [P2] 输出透明：whisper 语言默认 + use_itn · `TODO`
`.en` 模型强制 `language='en'`；`use_itn` 改为跟随模型默认/可配置（对齐 D-1 不后处理）。

---

## 三、发布就绪

### H-08 [P0] 版本 0.0.1 → 0.1.0 · `DONE`
已改 pyproject + `__init__`。

### H-09 [P1] sherpa-onnx 下限 → `>=1.13.3` · `TODO`
下限远低于代码用到的 `from_qwen3_asr`/`from_funasr_nano`/`from_moonshine_v2`/`from_omnilingual_asr_ctc`。三处 extras 同步。
**CI（Codex）**：CI 用 **fake `sherpa_onnx`** 验证构造器符号存在即可，真机 14 架构放 nightly/手动（真机不适合普通 CI）。

### H-10 [P1] 重写 README（中/英） · `TODO`
**Codex 确认**：`README.en.md` 仍写 0.0.1 placeholder（:9）+ 内置 bench（:19）。英文版即 PyPI 主页。
**规格**：改为 0.1.0 真实能力（47 端侧 pull 即用 + OpenAI 兼容云端 + 一接口换模型）；删占位/删 bench（标"路线项"）；加 quickstart（install→pull→run）。验收：每句与代码一致。

### H-11 [P1] 分类器 · `TODO`
`1 - Planning` → `4 - Beta`；补 Python 3.9~3.13 分类器（与 CI 矩阵对应）。

### H-12 [P2] extras 摊平 + 单一来源版本 · `TODO`
`all` 自引用摊平为显式依赖；可选 hatch dynamic version。

### H-13 [P1] 冒烟测试 + CI + CHANGELOG · `TODO`（Codex 上调 P1）
pytest：`import` / `list_models` / `resolve("local/sensevoice")` / alias `resolve("local/sensevoice:fp32")`。GitHub Actions 3.9 + 3.13（fake sherpa）。建 `CHANGELOG.md`。**没有 CI 对陌生人不可发布。**

### H-14 [P0] PyPI 恢复码移出仓库树 · `TODO`（待项目主人手动）
`ASR全景调研/PyPI-Recovery-Codes-*.txt` 移进密码管理器并从磁盘删除。**凭据文件不由 AI 移动/删除**（避免误操作），请你手动处理。现状：已被 `.gitignore` 挡住、确认未进 git 历史，故无泄漏风险，仅为纵深防御。发布用 Trusted Publisher / 项目级 scoped token。

### H-16 [P1] model-management.md 对齐 · `TODO`（Codex 上调 P1：文档一致性阻断）
存储布局如实写**平铺** `models/<folder>`（tag 仅寻址别名）；env key 实现后同步；未实现动词（`show`/`rm`/`list --available`）标"路线项"。

### H-17 [P1] 模型许可证标注 · `TODO`（需核实的数据，暂不臆造）
`AdapterMeta.license` 字段已就绪，但 47 个模型的 `license` 全为 None。
**决策**：**不臆造许可证**——错误的许可证信息比没有更糟（例：Meta Omnilingual 可能是非商用，标成 Apache 会坑用户，反而毁掉"标许可证"这个信任卖点）。需一次**逐模型核实**（对官方仓库/HF 卡）后再填，配套 `asrkit show <model>` 展示。列为发布前独立数据任务。

### H-18 [P2] config_schema / is_configured 通电 · `TODO`
`api.transcribe` 调用前 `if not adapter.is_configured(): return 友好 error`。

### H-19 [P0·发布阻断] 发布包内容审计 · `TODO`（Codex 新增）
确认 sdist/wheel **不含** `ASR全景调研/`、恢复码、`.omx/`/`.omc/`、旧 `dist/`。验收：`tar tzf` / `unzip -l` 只见 `src/asrkit/**` + 元数据。

### H-15 [P1] 契约回写 · `DONE`（本轮再补 D-1/D-2 措辞）
`adapter-spec.md` §0/§1/§9 已改为"内核零处理 + 云端原样直传 + 本地 adapter 引擎必需解码"。**契约二次修订后需重走评审再冻结。**

---

## 四、明确范围外（记录在案）

| 项 | 决策 | 说明 |
|---|---|---|
| 评测 / bench / 榜单 | `DEFER` | 后续接，现在只做统一接口；README/契约不宣传为现有功能。 |
| 流式 api/cli 入口 | `DEFER` | 契约已定义（§5），Dart 已验证 6 协议；本阶段不接入口。 |
| serve 常驻 / 模型缓存复用 | `DEFER` | 到有需求再做。 |
| 托管 / 中转 | 永不 | 音频与密钥永不过手（红线）。 |
| 进程隔离 runner | `DEFER` | 契约已降为路线项。 |

---

## 五、0.1.0 发布检查单（全绿方可 `twine upload`）

**P0（阻断）**
- [x] D-1 内核零处理 · D-2 云端 samples=None 原样直传 · D-3 warnings 不静默截断
- [x] H-01 tar 安全解压（穿越/绝对/symlink 全拒绝）
- [ ] **H-14 恢复码移出仓库树 —— 待项目主人手动（凭据不由 AI 处置）**
- [x] H-19 sdist/wheel 内容审计（已确认无敏感文件）

**P1**
- [x] H-02 pull 原子（.partial+rename）+ install_files 校验
- [x] H-03a 下载超时 · H-03b sha256 校验（机制就绪；具体校验值待登记）
- [x] H-04 CLI 异常兜底（语义异常，无 traceback）
- [x] H-05 环境变量 key `<VENDOR>_API_KEY`
- [x] H-09 sherpa ≥1.13.3 · H-10 README 重写 · H-11 分类器 Beta · H-12 extras 摊平
- [x] H-13 冒烟测试 8/8 过 + CI 配置 · H-16 文档一致 · H-18 is_configured 通电
- [ ] **H-17 许可证标注 —— 需按模型逐一核实的数据（不臆造，见该条）**

**构建/安装验证（Codex）**
- [x] `python -m build` + `twine check dist/*` 通过
- [x] 全新 venv 装 wheel（零 extras）后 `asrkit list` 正常
- [x] CLI 拼错模型名无 traceback

> 进度：**代码/打包/文档全部完成并验证；仅剩 H-14（凭据，手动）与 H-17（许可证数据，需核实）两项非代码项。**

**mock 测试清单（Codex）**
- [ ] 云端上传 hash == 原始文件
- [ ] 环境变量 key 注入生效
- [ ] tar slip（穿越）被拒
- [ ] 半装模型不算已装
- [ ] `local/sensevoice:fp32` alias 可解析
- [ ] README 不再出现 `0.0.1` / placeholder / 现有 bench

---

## 附：执行顺序

1. **透明音频三件套**（D-1/D-2/D-3）——最高原则，牵动 audio.py/types.py/api.py/两个 adapter。
2. **安全 + 正确性**（H-01/02/03a/03b/04/05）。
3. **发布卫生**（H-09~H-14、H-19）。
4. **文档 + 许可证**（H-16/H-17/H-18）。
5. 每组过验收 → 提交；全绿 → 发 0.1.0。

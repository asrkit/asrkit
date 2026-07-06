# ASRKit 0.1.0 硬化规格（开发流程文档）

> 目的：把一次多智能体全面评审的所有发现，转成**可执行、可验收**的规格条目。
> 用法：每条 = 问题 / 决策 / 规格 / 涉及 / 验收标准 / 状态。按开发流程——**先定规格，再实现，实现须过验收**。
> 状态图例：`TODO` 未开始 · `DOING` 进行中 · `DONE` 完成并验收 · `DEFER` 明确推迟。
> 目标：把"能在作者机器上跑的 v0.x"变成"能发给陌生人的 0.1.0"。

---

## 一、核心设计决定（最高优先，已写入契约 §0）

### D-1 透明层原则：默认不改变模型原生行为 · `DONE`(契约) / `TODO`(实现)
**决策（项目主人拍板）**：ASRKit 只做"统一接口 + 快速换模型"这一层。用 asrkit 跑某模型，结果与直接用该模型**一致**。默认**不做任何音频增强、不对输出做后处理**；此类能力全部 opt-in（默认关）。
**规格**：
- **云端**：默认上传**原始音频文件**（`original_path`），不重采样、不转码。
- **本地**：只做"喂给模型它能吃的格式"所必需的最小转换（解码 + 必要时重采样到模型要求采样率，用 soxr）；不做增强。
- **输出**：原样返回模型结果，不加/改标点、大小写、ITN——除非模型自带或用户显式开启。
- 增强能力（VAD/降噪/切段/长音频分块）→ 统一走 opt-in 开关（见 D-3）。
**验收**：同一音频，`asrkit` 与直接调该模型（sherpa 官方示例 / 云端官方 SDK）输出一致（本地逐字一致；云端字节级上传一致）。

### D-2 AudioInput 重构：original_path（云端）+ samples（本地） · `TODO`
**问题**：现 `audio.py` 只在 `sr!=16000` 时才落归一化 wav，且把归一化文件当 `path` 上传云端——违反 D-1（削弱云端对原始格式的处理）。
**规格**：`AudioInput` 改为 `original_path`（原始文件，未改动）+ `samples`（本地解码，可 None，按需生成）+ `sample_rate`。云端 adapter 上传 `original_path`；本地 adapter 用 `samples`。
**涉及**：`src/asrkit/types.py`、`src/asrkit/audio.py`、`adapters/cloud_openai.py`、`adapters/local_sherpa.py`。
**验收**：云端转写上传的文件哈希 == 原始文件哈希；44.1k 立体声 mp3 走云端不被预处理。

### D-3 长音频：不静默截断，增强作 opt-in · `TODO`（原 P0-1）
**问题**：移植时丢了原型 `worker.py` 的 VAD 分段。whisper 系（15 个）对 >30s 音频**只转前 30 秒，text 正常返回、error 为空**——静默数据丢失。
**决策（按 D-1）**：默认**不**自动切段（尊重模型原生行为），但**绝不静默丢数据**。
**规格**：
- 默认：不切段。当音频时长 > 模型已知窗口（whisper=30s，其它离线给保守阈值）时，在 `TranscribeResult` 加**警告**（`metrics.warning` 或新增 `warnings` 字段），提示"仅处理了前 Ns，完整请开启 `--vad` / `opts.segment=True`"。
- opt-in：`TranscribeOptions.segment`（默认 False）→ 开启后移植 `worker.py` 的 silero-VAD 分段拼接。
**涉及**：`local_sherpa.py`、`types.py`（opts + 警告字段）。
**验收**：60s 音频喂 whisper：默认→前 30s 文本 + 明确警告；`segment=True`→全长文本。

---

## 二、安全与正确性（0.1.0 前必修）

### H-01 [P0] tar 解压路径穿越 · `TODO`
**问题**：`store.py` `tf.extractall(tmp)` 无 `filter`；Python 3.9–3.13 默认全信任，恶意/被篡改 tarball 可写任意文件。
**规格**：Python≥3.12 传 `filter="data"`；<3.12 逐成员校验 `realpath` 落在解压目录内、拒绝 symlink/hardlink/device 成员。
**验收**：构造含 `../evil` 成员的 tar，pull 时被拒绝且不写出目录外文件。

### H-02 [P1] pull 非原子 + is_installed 太松 · `TODO`（原 P1-1）
**问题**：逐文件复制中断后，"有任意 .onnx 即已装"误判 → 模型永久残废且被判已装。
**规格**：解压安装到 `dest + ".partial"`，全部就位后 `os.rename` 原子换入；`is_installed` 只认换入完成的目录（或 `.done` 标记）。
**验收**：pull 中途 kill，再次 pull 会重下而非误判已装。

### H-03 [P1] 下载无超时 + 无校验和 · `TODO`（原 P1-3 / security#2,#3）
**规格**：`urlopen(req, timeout=30)`；`_TABLE` 每条登记 `sha256`，下载后校验，不匹配即删除报错；失败清理半截文件并抛可读错误（带 URL）。
**涉及**：`store.py`、`models_local.py`（加 sha256）、`AdapterMeta`（加 `sha256` 字段，回写契约 §6）。
**验收**：断网/超时 30s 内报错退出；篡改一个字节的 tar 被校验拒绝。

### H-04 [P1] CLI 异常兜底 · `TODO`（原 P1-2）
**问题**：`cli.py` `run`/`transcribe` 分支无 try/except，打错模型名/坏音频直接甩 traceback，违背"错误不抛"契约（§8）。
**规格**：`run`/`transcribe` 复用 `pull` 分支的 try/except，打印 `[错误] {e}` 并 `return 1`；`api` 层用语义异常（`ModelNotFoundError`）替代裸 `KeyError`。
**验收**：`asrkit run local/sensevoic x.wav`（拼错）→ 一行友好错误，无 traceback。

### H-05 [P1] API Key 环境变量兜底 · `TODO`（原 P1-8 / 文档承诺未实现）
**规格**：key 解析链 = 显式 `config["api_key"]` > 环境变量 `<VENDOR>_API_KEY`（如 `SILICONFLOW_API_KEY`）> 无。在 `make_adapter` 注入层或云端 adapter 实现。文档把 env 列为推荐、`--api-key` 标注慎用（进 shell history）。
**验收**：`export SILICONFLOW_API_KEY=... && asrkit transcribe a.wav -m siliconflow/sensevoice` 无需 `--api-key` 即可用。

### H-06 [P2] 重采样临时 wav 泄漏 · `TODO`
**规格**：`AudioInput` 标记临时文件归属，`api.transcribe` `try/finally` 用后删除（或落 `~/.asrkit/tmp` 启动清扫）。
**验收**：批量转写 100 个 44.1k 文件后 `/tmp` 无残留 `_asrkit16k.wav`。

### H-07 [P2] whisper 语言默认值 · `TODO`
**规格**：`.en` 模型（langs==['en']）强制 `language='en'`；多语模型 `''` 自动检测（真机验证后定）。对齐 D-1（不引入原型没有的行为漂移）。

---

## 三、发布就绪（0.1.0 发布卫生）

### H-08 [P0] 版本号 0.0.1 → 0.1.0 · `DONE`
PyPI 上 0.0.1 已被占位包占用。已改 `pyproject.toml` + `__init__.py` 为 `0.1.0`。（后续可单一来源化：hatch dynamic version，见 H-13。）

### H-09 [P1] sherpa-onnx 依赖下限 · `TODO`
**问题**：`>=1.10` 远低于代码用到的 `from_qwen3_asr`/`from_funasr_nano`/`from_moonshine_v2`/`from_omnilingual_asr_ctc`（2026 新 API）。
**规格**：下限提到实测通过的 **`>=1.13.3`**（三处 extras 同步）。
**验收**：干净环境装 `asrkit[local]` 后，14 种架构各跑一个不报 AttributeError。

### H-10 [P1] 重写 README（中/英） · `TODO`（原 P1-6）
**问题**：两份仍写"占位/暂未提供功能"；还宣传"内置 bench"（bench 已推迟）；英文版即 PyPI 主页。
**规格**：改为 0.1.0 真实能力——47 端侧模型 `pull` 即用 + OpenAI 兼容云端 + 一个接口换模型；删占位警告、删 bench（或标"路线项"）；加 quickstart（install → pull → run 三行）。
**验收**：README 每句都与当前代码行为一致（可对照 usage.md）。

### H-11 [P1] 分类器更新 · `TODO`
`Development Status :: 1 - Planning` → `4 - Beta`；补 `Programming Language :: Python :: 3.9`~`3.13`（与 CI 矩阵对应）。

### H-12 [P2] extras 摊平 + 单一来源版本 · `TODO`
`all = ["asrkit[local]","asrkit[cloud]"]` 自引用在旧 pip 下不可靠 → 摊平为显式依赖列表。可选：hatch dynamic version 从 `__init__.__version__` 单一来源。

### H-13 [P2] 冒烟测试 + CI + CHANGELOG · `TODO`
最小 pytest：`import asrkit` / `list_models()` / `registry.resolve("local/sensevoice")` / `resolve("local/sensevoice:fp32")` 别名。GitHub Actions 跑 3.9 + 3.13。建 `CHANGELOG.md`。
**验收**：CI 绿；`pytest` 通过。

### H-14 [卫生] PyPI 恢复码移出仓库树 · `TODO`
`ASR全景调研/PyPI-Recovery-Codes-*.txt` 移进密码管理器并从磁盘删除（现仅靠 `.gitignore` 兜底，已确认未进 git 历史）。发布用 PyPI Trusted Publisher 或项目级 scoped token。

---

## 四、文档 / 契约一致性

### H-15 [P1] 契约回写 · `DONE`（本轮）
`adapter-spec.md` 已对齐：透明原则（§0）、`AudioInput`（original_path+samples）、`__init__(meta,config)`、`tag`/`base` 字段、进程隔离降为路线项。**注：契约二次修订后需重走评审再冻结。**

### H-16 [P1] model-management.md 对齐 · `TODO`
存储布局如实描述为**平铺** `models/<folder>`（tag 仅是寻址别名，非子目录）；环境变量 key 实现后（H-05）同步该节；未实现的 CLI 动词（`show`/`rm`/`list --available`）标"路线项"。

### H-17 [P2] 模型许可证标注 · `TODO`（评审完整性补漏）
`models_local.py` 全部 `license=None`。补每个模型的许可证（研究型模型显著标注"仅研究用途"）。这是项目规划里的差异化卖点（注册表标许可证），别家没有。
**验收**：`asrkit show <model>` / `list` 能显示许可证。

### H-18 [P2] config_schema / is_configured 通电 · `TODO`
两者当前无人消费。`api.transcribe` 调用前 `if not adapter.is_configured(): return 缺配置的友好 error`。

---

## 五、明确范围外（本阶段不做，记录在案）

| 项 | 决策 | 说明 |
|---|---|---|
| **评测 / bench / CER-WER 榜单** | `DEFER` | 项目主人明确：后续会接，现在只做统一接口。README/契约不得宣传为现有功能。 |
| **流式转写（transcribe_stream 的 api/cli 入口）** | `DEFER` | 契约已定义（§5），Dart 侧已验证 6 家协议；本阶段本地模型 `modes` 仅声明，不接 api 入口。 |
| **serve 常驻服务 / 模型缓存复用** | `DEFER` | 关联"每次调用重建 adapter"性能项；到有 `serve` 或库级缓存需求时再做。 |
| **托管 / 中转服务** | 永不 | 音频与密钥永不经过项目方（红线）。 |
| **进程隔离 runner** | `DEFER` | 契约已降为路线项；同进程加载为当前实现。 |

---

## 六、0.1.0 发布检查单（全绿方可 `twine upload`）

- [ ] D-1/D-2/D-3 透明音频 + 长音频不静默截断
- [ ] H-01 tar 安全解压
- [ ] H-02 pull 原子化
- [ ] H-03 下载超时 + sha256 校验
- [ ] H-04 CLI 异常兜底
- [ ] H-05 环境变量 key
- [ ] H-08 版本 0.1.0 ✅
- [ ] H-09 sherpa 下限 1.13.3
- [ ] H-10 README 重写
- [ ] H-11 分类器 Beta
- [ ] H-13 冒烟测试 + CI 绿
- [ ] H-14 恢复码移出
- [ ] H-15 契约回写 ✅ / 重走评审
- [ ] `twine check dist/*` 通过

---

## 附：执行顺序建议

1. **透明音频三件套**（D-1/D-2/D-3）——最高原则，牵动 audio.py/types.py/两个 adapter。
2. **安全 + 正确性**（H-01~H-05）——"会坏"的。
3. **发布卫生**（H-09~H-14）——"能发"的。
4. **文档 + 许可证**（H-16/H-17/H-18）——"可信"的。
5. 每组完成过验收 → 提交。全绿 → 发 0.1.0。

# W1 设计 — 批量输入 + 结果契约化

> 状态:已通过 brainstorming,待写实现计划。
> 目标波次:W1(见 [roadmap.md](../../roadmap.md))。落地默认下个 PATCH,升号前问人类。
> 定位约束:守住"接口内核极薄"——批量逻辑待在 CLI 层 + 一个薄 `inputs.py`,**不动 core / `transcribe()` / `formats.render` 的每结果语义**,不加运行时依赖。

---

## 1. 背景与目标

ASRKit 现在只接**单个文件路径**,结果只有 txt/json/srt/vtt 单结果渲染,退出码不分级(几乎都返 1)。两类消费者都受限:

- **人类 / shell**:不能 `asrkit transcribe *.wav`,不能读 stdin。
- **程序 / 评测(asrbench)**:JSON 是 dataclass 裸 dump、无文档化契约;无 csv/tsv;退出码无法判因。

W1 一次补齐两半(用户已确认两类消费者同等重要):

1. **输入广度**:多文件 / glob / 目录递归 / stdin(`-`)。
2. **结果契约化**:稳定且文档化的 JSON schema、csv/tsv 输出、分级退出码。

**契约的定义** = 稳定的"每结果" schema(不管消费者循环 `transcribe()` 还是吃 `--format json` 都能依赖)。**不新增公共批量 API**(asrbench 自己循环即可 → YAGNI)。

---

## 2. 已定决策(brainstorming 结论)

| # | 决策 | 取值 |
|---|---|---|
| D1 | 消费者 | 人类 shell + 程序化契约,**同等重要**,两半都做 |
| D2 | 批量输出形态 | **默认 stdout 聚合表**;`-o <目录>` → 逐文件镜像 |
| D3 | 批量 JSON 形态 | **NDJSON**(每行一对象,带 `file`/`model`);单文件仍是单对象 |
| D4 | 批量失败语义 | 遇错**不中止**、跑完;**有任何失败即非零**,码=最严失败类别 |
| D5 | JSON 版本字段 | **不加**(工具 semver + 契约文档即契约) |
| D6 | csv/tsv 列 | `file, model, text, lang, duration_s, latency_ms, load_ms, decode_ms, rtf, cost_estimate, error`(11 列) |
| D7 | stdin 混批量 | 允许,不特别优化 |

---

## 3. 架构:薄 CLI 聚合器(Approach A)

三个新单元,各自单一职责、可独立测试:

```
inputs.resolve_inputs(args) ──▶ [具体文件路径...]   (glob/目录/stdin 展开;纯函数)
        │
        ▼
CLI 运行循环:每个输入 → api.transcribe/run → Record(file, model, result)   (遇错不中止)
        │
        ▼
emitter:按 (模式, fmt, 输出目标) 决定怎么落地 + 计算退出码
```

- **core / api / `transcribe()` 不变**;`formats.render(result, fmt)` 的每结果语义不变。
- `formats.py` 仅**新增** csv/tsv 的行渲染(数据导向)。
- `cli.py` 新增编排 + 退出码常量;若 `cli.py` 因此过大,把 emitter 抽到 `cli` 内私有函数即可(不强开新模块,除非超篇幅)。

### 3.1 输入解析 `asrkit/inputs.py`(新,纯函数)

```
resolve_inputs(raw_args: list[str]) -> list[str]
```
- 位置参数 `run`/`transcribe` 由单个改 `nargs="+"`。
- 逐个 raw arg:
  - `-` → 读 stdin 全部字节,落临时 `.wav`(透明:原样字节,不解码),路径入列。
  - 含 glob 元字符 `*?[` 且该路径不作为字面文件存在 → `glob.glob(recursive=True)` 展开。
  - 目录 → 递归 `os.walk`,按**扩展名白名单**收音频。
  - 其它 → 原样入列(普通文件,**即使不存在也入列**)。不存在的文件在**运行阶段**自然成为一条 `error` 记录(open 失败 → adapter 返回 `result.error`),符合 continue-on-error;解析期不中断。
- 白名单:`.wav .mp3 .m4a .flac .ogg .opus .aac .wma .webm .amr`(小写比较)。
- 结果 `sorted()` 去重保序,保证**确定性**(评测可复现)。
- 返回空 → 调用方报错(exit 2 用法错:"no audio inputs matched")。

### 3.2 单 / 批判定(向后兼容关键)

- **单文件模式**:解析后**恰好 1 个文件**,且来自**单个非目录、非 glob、非 stdin** 参数 → 走**今天的** `_print_result`(txt→stdout、指标进 stderr;或 `-o <file>`)。**一字不改**,保住兼容与现有测试。
- 否则 → **批量模式**。

> 即:`asrkit transcribe a.wav -m X` 行为与今天完全一致;`*.wav` / 目录 / 多参数 / `-` 进批量。

### 3.3 emitter(输出编排)

`Record = {file: str, model: str, result: TranscribeResult}`

- **批量 + `-o <目录>`**:每条 `formats.render(result, fmt)` → 写 `<目录>/<stem>.<fmt>`;srt/vtt 在此正常出。目录不存在则创建;stem 冲突(不同目录同名文件)时**追加 `-1`/`-2` 去重并告警**(不静默覆盖)。
- **批量 + stdout(无 -o)聚合**:
  - `txt` → 每行 `"{file}\t{text}"`
  - `json` → **NDJSON**:`_json_payload(result)` 的对象 + 注入 `file`、`model`,每条一行(`ensure_ascii=False`,单行 compact)
  - `csv` / `tsv` → 表头 + 每条一行(见 §4.2)
  - `srt` / `vtt` → **诚实报错**:`"batch srt/vtt needs -o <dir> (subtitles can't be aggregated to stdout)"`,exit 2

### 3.4 退出码(新增常量,文档化)

| 码 | 含义 |
|---|---|
| 0 | 全部成功 |
| 1 | 其它意外异常 |
| 2 | 用法错(argparse 既有;无输入匹配、批量 srt/vtt→stdout 等) |
| 3 | 模型不存在(`ModelNotFoundError`) |
| 4 | 转写失败(`result.error`:未配置 / 音频格式 / 云端 API 错等) |

- **批量**:遍历所有 Record;退出码 = 记录中出现过的失败码里,按**固定优先级 `3 > 4 > 1`** 取第一个命中的(模型不存在最靠前,因它通常是整批性配置问题)。全成功 → `0`。
- 单文件模式沿用等价映射(今天返 1 的分支按类别改 3/4)。

---

## 4. 数据契约

### 4.1 JSON schema(冻结 + 文档化)

- 新写 `docs/result-contract.md`,文档化 `TranscribeResult` 序列化后的稳定字段:
  `text`(必有)、`segments[]`、`word_timestamps[]`、`lang`、`latency_ms`、`cost_estimate`、`metrics{load_ms,decode_ms,rtf,...}`、`warnings[]`、`error`。
- 渲染规则维持现状:**空字段不输出**(`None/""/[]/{}` 略去)。
- **批量 NDJSON** 每行额外注入:`file`(输入路径)、`model`(解析用的 model 字符串)。
- **不加**版本字段(D5)。契约稳定性由 semver + 本文档背书;破坏字段=破坏契约=按纪律要慎重(见 CLAUDE.md model string / adapter 契约稳定性)。

### 4.2 csv/tsv 列(D6,固定顺序)

```
file, model, text, lang, duration_s, latency_ms, load_ms, decode_ms, rtf, cost_estimate, error
```
- 来源:`file`/`model` 由 CLI 注入;`text/lang/latency_ms/cost_estimate/error` 取 `result` 顶层;`duration_s/load_ms/decode_ms/rtf` 取 `result.metrics`(缺则空)。
- 值缺失 → 空串。`text` 里的换行/分隔符按 csv 标准转义(用 `csv` 标准库,`tsv` = `delimiter="\t"`)。
- **单文件也可出 csv/tsv**(1 行表);此时因为是"表格格式",走 emitter 的表格分支而非 `_print_result`。

> 小增强:让 sherpa 本地 adapter 在 `metrics` 里补 `duration_s`(现在只有 rtf 用到 dur 但没存),这样本地模型该列不空;云端不解码故留空(诚实)。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/inputs.py` | **新增**:`resolve_inputs` + 白名单 + stdin 处理 |
| `asrkit/formats.py` | 新增 csv/tsv 行渲染;`FORMATS` 扩到含 `csv,tsv`;单结果 txt/json/srt/vtt 不变 |
| `asrkit/cli.py` | `run`/`transcribe` 位置参数改 `nargs="+"`;`-f` choices 加 csv/tsv;新增退出码常量 + emitter 编排;单文件路径完全保留 |
| `asrkit/adapters/local_sherpa.py` | `metrics` 补 `duration_s`(小增强) |
| `docs/result-contract.md` | **新增**:JSON/csv 契约文档 |
| `docs/usage.md` | 补批量 / stdin / csv / 退出码用法 |
| `CHANGELOG.md` | 记一节(版本号等人类定) |

---

## 6. 测试

- **`test_inputs.py`(新)**:glob 展开、目录递归 + 白名单过滤、`sorted` 确定性、stdin(`-`)落临时文件、无匹配报错。
- **`test_formats.py`(扩)**:csv/tsv 行渲染(含转义、空值、单行)。
- **批量端到端(新,用 stub adapter)**:仿 `test_serve` 注册假协议/模型返回固定结果 + 一个返回 `error` 的假模型;`cli.main(argv)` 捕获 stdout,断言:
  - NDJSON 行数 = 文件数、每行含 `file`;
  - csv 表头 + 行数;
  - 退出码:全成功=0、含失败=非零且为对应类别、模型不存在=3、批量 srt/vtt→stdout=2。
- **向后兼容(新/扩)**:单文件 txt/json/srt/vtt 输出与今天一致(含 txt 指标进 stderr)。

---

## 7. 明确不做(YAGNI)

- 公共批量 API(`transcribe_many`)——asrbench 自己循环。
- 并发 / 多进程加速、进度条 / ETA。
- URL / 麦克风输入。
- csv 里塞 segments / word_timestamps(表格里放长嵌套无意义;要细节用 json)。
- JSON per-object 版本字段。

以上留 W2+ 或按需。

---

## 8. 风险与兼容

- **最大风险 = 破坏单文件现有行为**。缓解:单文件模式走**原封不动**的 `_print_result`;新增回归测试钉死。
- `nargs="+"` 对既有 `transcribe a.wav -m X` 无感(1 个也合法)。
- csv/tsv 是**新增**格式,不影响旧 `-f` 取值。
- 退出码从"几乎都 1"变成分级:属**行为微调**,CHANGELOG 醒目记一笔;仍归 PATCH。

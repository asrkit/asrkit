# W1 设计 — 批量输入 + 结果契约化(v2,含 Codex 评审修订)

> 状态:brainstorming 定案 + Codex(gpt-5.5)评审修订,待写实现计划。
> 目标波次:W1(见 [roadmap.md](../../../roadmap.md))。落地默认下个 PATCH,升号前问人类。
> 定位约束:守住"接口内核极薄"——批量逻辑待在 CLI 域(`inputs.py` + `emit.py`),**不动 core / `api.transcribe()` / `formats.render` 的每结果语义**,不加运行时依赖。
>
> **v2 修订**:Codex 评审(2026-07-07)采纳 11 项;`.omc/artifacts/ask/codex-*2026-07-07T04-24-21*.md` 存档。主要变更:显式 `--batch`、退出码是**明确行为变更**、退出优先级翻为 `1>3>4`、stdin 生命周期、unmatched glob fail-loud、批量 NDJSON 用恒含 text 的 dict 助手 + `schema_version` 且排除 raw_response、流式发射、表格发射独立成 `emit.py`。

---

## 1. 背景与目标

ASRKit 现在只接**单个文件路径**,结果只有 txt/json/srt/vtt 单结果渲染,退出码不分级(几乎都返 1)。两类消费者都受限:

- **人类 / shell**:不能 `asrkit transcribe *.wav`,不能读 stdin。
- **程序 / 评测(asrbench)**:JSON 是 dataclass 裸 dump、无文档化契约;无 csv/tsv;退出码无法判因。

W1 一次补齐两半(两类消费者同等重要):

1. **输入广度**:多文件 / glob / 目录递归 / stdin(`-`)。
2. **结果契约化**:稳定且文档化的 JSON schema、csv/tsv 输出、分级退出码。

**契约的定义** = 稳定的"每结果" schema(不管消费者循环 `transcribe()` 还是吃 `--format json` 都能依赖)。**不新增公共批量 API**(asrbench 自己循环即可 → YAGNI)。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 消费者 | 人类 shell + 程序化契约,**同等重要**,两半都做 |
| D2 | 批量输出形态 | **默认 stdout 聚合表**;`-o <目录>` → 逐文件镜像 |
| D3 | 批量 JSON 形态 | **NDJSON**(每行一对象);单文件仍是单对象 |
| D4 | 批量失败语义 | 遇错**不中止**、跑完;**有任何失败即非零**;批量退出码优先级 **`1 > 3 > 4`** |
| D5' | schema 版本 | **NDJSON 每行加 `schema_version:1`**;csv/tsv 不加;单文件 json 不变 |
| D6 | csv/tsv 列 | `file, model, text, lang, duration_s, latency_ms, load_ms, decode_ms, rtf, cost_estimate, error`(11 列) |
| D7 | stdin 混批量 | 允许;`-` 只能出现一次;默认按 wav,`--stdin-format` 可改 |
| **D8** | **显式 `--batch`** | 强制批量/聚合输出,与输入数量无关(消除 shell glob 展开导致的输出形态不确定) |
| **D9** | 退出码 | **明确行为变更**(不再是"几乎都 1"):`0/1/2/3/4` 分级,单/批一致;CHANGELOG 醒目记 |

---

## 3. 架构:薄 CLI 聚合器 + 独立 emitter

四个新单元,各自单一职责、可独立测试:

```
inputs.resolve(raw_args, stdin_format) ──▶ ([具体文件...], [cleanup...])   (glob/目录/stdin 展开)
        │
        ▼
CLI 运行循环:每个输入 → api.transcribe/run → Record(file, model, result)   (遇错不中止)
        │  (边跑边发射,不囤全量结果)
        ▼
emit.emit(records_iter, fmt, output, batch) ──▶ 落地 + 返回退出码
```

- **core / api / `transcribe()` 不变**;`formats.render(result, fmt)` 的每结果语义不变。
- `formats.py` 仅**新增** `result_dict(result)`(每结果 → dict,`text` 恒含)供 NDJSON/csv 取数;txt/json/srt/vtt 渲染不变。
- **表格/记录发射独立成 `asrkit/emit.py`**(CLI 域,import formats),不塞进"薄结果渲染器"。
- `cli.py`:`run`/`transcribe` 位置参数改 `nargs="+"` + 新旗标;单文件输出路径**完全保留**。

### 3.1 输入解析 `asrkit/inputs.py`(新)

```
resolve(raw_args: list[str], *, stdin_format: str = "wav") -> tuple[list[str], list[Callable]]
```
返回 (有序去重的文件路径列表, 需在结束时调用的清理回调列表)。**stdin 的副作用被显式建模为清理回调**(不再号称"纯函数")。

逐个 raw arg:
- `-` → 读 stdin 全部字节,落临时 `.{stdin_format}` 文件(透明:原样字节,不解码),路径入列,登记清理回调。**`-` 只允许出现一次**,重复 → 用法错(exit 2)。
- 含 glob 元字符 `*?[` 且不作为字面文件存在 → `glob.glob(recursive=True)` 展开;**匹配 0 个 → fail loud**(exit 2,列出该 pattern)。
- 目录 → 递归 `os.walk` 按扩展名白名单收音频;**收到 0 个 → fail loud**(exit 2)。
- 其它 → 原样入列(普通文件,**即使不存在也入列**)。不存在的文件在**运行阶段**自然成为一条 `error` 记录(open 失败 → `result.error`),符合 continue-on-error。
- 白名单:`.wav .mp3 .m4a .flac .ogg .opus .aac .wma .webm .amr`(小写比较)。
- `sorted()` 去重保序,保证确定性。整体解析后仍为空 → 用法错(exit 2:"no audio inputs matched")。

### 3.2 单 / 批判定(向后兼容关键)

- **`--batch` 显式指定** → 恒批量模式(哪怕只 1 个文件),输出恒为聚合形态。**给脚本/评测的确定性契约**(shell 把 `*.wav` 展开成 1 个文件时也稳定出 NDJSON)。
- 未加 `--batch`:
  - 解析后**恰好 1 个文件**且来自**单个非目录、非 glob、非 stdin** 参数 → **单文件模式**。
  - 否则 → **批量模式**。
- **单文件模式的 stdout/stderr 输出字节与今天完全一致**(走原 `_print_result`)。**注意**:退出码是全局分级(见 §3.4,D9)——这是 W1 唯一对单文件的可见变更(输出不变、退出码从 1 细化为 3/4)。

> `asrkit transcribe a.wav -m X` 的**输出**和今天一模一样;失败时退出码可能从 1 变 4(文档+CHANGELOG 记)。
> **argparse 限制**:位置输入须**连续**——`transcribe a.wav b.wav -m X` 可以,`transcribe a.wav -m X b.wav` 会报 `unrecognized b.wav`。文档注明。

### 3.3 发射 `asrkit/emit.py`(新)

`Record = {file: str, model: str, result: TranscribeResult, code: int}`(`code` 由退出码映射得出)。**边跑边发射**:每条 Record 产生即写出,只累积 (最严退出码, 镜像文件名去重集),**不囤全量结果**(巨批量友好)。

- **批量 + `-o <目录>`**:每条 `formats.render(result, fmt)` → 写 `<目录>/<stem>.<fmt>`;srt/vtt 在此正常出。目录不存在则建;stem 冲突(不同目录同名)→ 追加 `-1`/`-2` 去重并告警。渲染失败(如 srt 缺 segments 抛 `FormatError`)→ 该条计 exit 4,错误进 stderr,继续。
- **批量 + stdout(无 -o)聚合**:
  - `txt` → 每行 `"{file}\t{text}"`;**失败行 text 为空、错误进 stderr**。txt 批量**对错误有损**(stdout 不含错误)——文档注明:要判错用 json/csv/tsv。
  - `json` → **NDJSON**:`formats.result_dict(result)`(恒含 `text`)+ 注入 `file`、`model`、`schema_version:1`,**排除 `raw_response`**(每行噪音),每条一行 compact(`ensure_ascii=False`)。
  - `csv` / `tsv` → 表头 + 每条一行(见 §4.2);`csv` 标准库 + `newline=""`。
  - `srt` / `vtt` → **诚实报错**:`"batch srt/vtt needs -o <dir> (subtitles can't be aggregated to stdout)"`,exit 2。

### 3.4 退出码(新增常量,文档化;D9 = 明确行为变更)

| 码 | 含义 |
|---|---|
| 0 | 全部成功 |
| 1 | 其它意外异常(工具自身 bug / 未预期) |
| 2 | 用法错(argparse;无输入匹配、多个 `-`、unmatched glob/dir、批量 srt/vtt→stdout) |
| 3 | 模型不存在(`ModelNotFoundError`) |
| 4 | 转写/渲染失败(`result.error`:未配置 / 音频格式 / 云端 API 错;或 `FormatError`) |

- **批量退出码 = 记录中出现过的失败码里,按固定优先级 `1 > 3 > 4` 取第一个命中的。** 即:只要有任何**意外异常(1)** 就返 1(**绝不让工具 bug 被普通转写失败掩盖**,CI 友好);否则模型不存在(3);否则转写失败(4);全成功 0。
- 单文件模式沿用同一映射(今天返 1 的转写失败分支改按类别返 3/4)——**这是可见行为变更,记 CHANGELOG**。

---

## 4. 数据契约

### 4.1 JSON schema

- 新写 `docs/result-contract.md`,文档化 `TranscribeResult` 序列化字段:
  `text`、`segments[]`、`word_timestamps[]`、`lang`、`latency_ms`、`cost_estimate`、`metrics{load_ms,decode_ms,rtf,duration_s,...}`、`warnings[]`、`error`。
- **单文件 `--format json`**:维持现状(`_json_payload`,空字段略去,含 `raw_response`)——**输出不变**。
- **批量 NDJSON** 每行(经 `formats.result_dict`):
  - **`text` 恒含**(即便失败为 `""`——修正现渲染器"空串略去"导致失败行缺 text 的问题)。
  - 注入 `file`(输入路径)、`model`(model 字符串)、**`schema_version: 1`**。
  - **排除 `raw_response`**(每行塞 vendor 原始响应是噪音;要它用单文件 json)。
  - 其它空字段仍略去。
- 契约稳定性由 semver + 本文档 + NDJSON 的 `schema_version` 共同背书;破坏字段=破坏契约,按纪律慎重(见 CLAUDE.md)。

### 4.2 csv/tsv 列(D6,固定顺序)

```
file, model, text, lang, duration_s, latency_ms, load_ms, decode_ms, rtf, cost_estimate, error
```
- 来源:`file`/`model` 由 emitter 注入;`text/lang/latency_ms/cost_estimate/error` 取 `result` 顶层;`duration_s/load_ms/decode_ms/rtf` 取 `result.metrics`(缺则空串)。
- **不加 `schema_version` 列**(D5';csv 面向人/表格,每行重复版本号是噪音)。
- 用 `csv` 标准库,`open(..., newline="")`;`tsv` = `delimiter="\t"`。`text` 含换行 → 合法多行 CSV 记录:**文档注明"行数≠物理行数"**,脚本按 CSV 解析器读、勿按行 split。
- **单文件也可出 csv/tsv**(1 行表),走 emitter 表格分支。

> 小增强:sherpa 本地 adapter 在 `metrics` 补 `duration_s`(现在只有 rtf 用到 dur 但没存),本地模型该列不空;云端不解码故留空(诚实)。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/inputs.py` | **新增**:`resolve`(glob/目录/白名单/stdin+清理回调/fail-loud) |
| `asrkit/emit.py` | **新增**:单/批发射、NDJSON/csv/tsv/txt 聚合、`-o` 镜像、流式、退出码累积 |
| `asrkit/formats.py` | **新增** `result_dict(result)`(恒含 text);txt/json/srt/vtt 渲染不变 |
| `asrkit/cli.py` | `run`/`transcribe` 位置参数改 `nargs="+"`;加 `--batch` / `--stdin-format`;`-f` choices 加 csv/tsv;退出码常量;单文件路径保留;编排调 inputs+emit |
| `asrkit/adapters/local_sherpa.py` | `metrics` 补 `duration_s`(小增强) |
| `docs/result-contract.md` | **新增**:JSON/NDJSON/csv 契约文档(含 schema_version、行数≠行数说明) |
| `docs/usage.md` | 补批量 / `--batch` / stdin / csv / 退出码用法 |
| `CHANGELOG.md` | 记一节,**退出码行为变更醒目标出**(版本号等人类定) |

---

## 6. 测试

- **`test_inputs.py`(新)**:glob 展开、目录递归+白名单、`sorted` 确定性、stdin(`-`)落临时文件+清理回调被调、**多个 `-` 报错**、**unmatched glob/dir fail-loud(exit 2)**、全空报错。
- **`test_formats.py`(扩)**:`result_dict` 恒含 text;csv/tsv 行渲染 + **往返转义测试**(逗号/引号/tab/换行)+ 空值 + 单行。
- **`test_emit`/批量端到端(新,stub adapter)**:仿 `test_serve` 注册假协议——一个返固定结果、一个返 `error`、一个不存在模型;`cli.main(argv)` 捕获 stdout,断言:
  - NDJSON 行数=文件数、每行含 `file`/`model`/`schema_version`、失败行含 `text:""`+`error`、**无 `raw_response`**;
  - csv 表头 + 行数;
  - 退出码:全成功 0;含意外异常→**1(不被 4 掩盖)**;模型不存在→3;仅转写失败→4;批量 srt/vtt→stdout→2;
  - `--batch` 强制单文件也走聚合(NDJSON)。
- **向后兼容(新/扩)**:单文件 txt/json/srt/vtt **输出字节**与今天一致(含 txt 指标进 stderr);单文件 json **不含** schema_version、**仍含** raw_response。

---

## 7. 明确不做(YAGNI)

- 公共批量 API(`transcribe_many`)——asrbench 自己循环。
- 并发 / 多进程加速、进度条 / ETA。
- URL / 麦克风输入。
- csv 里塞 segments / word_timestamps(要细节用 json)。
- 单文件 json 加 schema_version(避免破坏现有输出;版本信号只在批量 NDJSON)。

以上留 W2+ 或按需。

---

## 8. 风险与兼容

- **最大风险 = 破坏单文件现有行为**。缓解:单文件模式走**原封不动**的 `_print_result`;回归测试钉死输出字节。
- **可见行为变更(必须文档+CHANGELOG)**:退出码从"几乎都 1"改为分级 `0/1/2/3/4`,单/批一致。属 PATCH 但醒目标出。
- `nargs="+"` 对 `transcribe a.wav -m X` 无感;但位置输入须**连续**(argparse 限制,文档注明)。
- `--batch` 让脚本可绕开"shell glob 展开成 1 个文件→输出形态漂移"的坑,是契约确定性的关键。
- csv/tsv、`--batch`、`--stdin-format` 均为**新增**,不影响旧 `-f`/旧调用。

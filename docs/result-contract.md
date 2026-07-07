# 结果契约（TranscribeResult / NDJSON / CSV / 退出码）

本文档定义 `asrkit run` / `asrkit transcribe` 的**机读输出契约**：字段、单文件 JSON 与批量 NDJSON 的差异、csv/tsv 列、以及退出码分级。目标是让脚本/评测能稳定解析输出，不因内部实现变化而破裂。

---

## 一、`TranscribeResult` 字段

内核统一返回 `TranscribeResult`（见 `src/asrkit/types.py`），所有 adapter（本地/云端）共用：

| 字段 | 类型 | 含义 | 空值规则 |
|---|---|---|---|
| `text` | `str` | 识别文字（唯一必填字段） | 失败时为 `""`，序列化时**恒含**（见下） |
| `segments` | `list[Segment]` \| `None` | 分句时间戳（`start`/`end`/`text`），字幕（srt/vtt）依赖此字段；目前由 whisper 家族（faster-whisper / whispercpp / openai/whisper-1）填充，sherpa 与 transformers 暂不填充（TODO） | 无则整字段略去；序列化时展开为 dict 列表 |
| `word_timestamps` | `list[dict]` \| `None` | 逐词时间戳 `{word, start, end, conf?}` | 无则略去 |
| `lang` | `str` \| `None` | 自动识别/指定的语言 | 无则略去 |
| `latency_ms` | `int` \| `None` | 本次调用总耗时（毫秒） | 无则略去 |
| `cost_estimate` | `float` \| `None` | 云端调用的估算成本 | 无则略去 |
| `metrics` | `dict` \| `None` | 附加指标，如 `load_ms`/`decode_ms`/`rtf`/`duration_s`（各 adapter 视情况填充，非固定 schema） | 无则略去 |
| `warnings` | `list[str]` \| `None` | 非致命提示（如长音频超窗只处理前 N 秒） | 无则略去；CLI 单文件模式会打印到 stderr |
| `raw_response` | `dict` \| `None` | 云端厂商原始响应（调试用） | 单文件 json：有则含；批量 NDJSON：**恒不含**（见下） |
| `error` | `str` \| `None` | 出错信息；adapter 不抛异常，错误一律进此字段 | 成功时略去；失败时含 |

> 序列化通用规则（`formats.result_dict`）：**`text` 恒含**（即便是空字符串，失败行也要有这个 key，方便脚本统一按 `text` 取值）；其它字段为空（`None`/`""`/`[]`/`{}`）时**整字段省略**，不会出现 `"lang": null` 这种噪音键。

---

## 一点五、能力位（capabilities）

每个模型的 `AdapterMeta.capabilities` 包含一组三态字符串与布尔标记，描述该模型的特性与局限：

| 能力位键 | 类型 | 含义 |
|---|---|---|
| `language_hint` | `"required"` / `"supported"` / `"none"` | 模型对语言提示的态度：`"required"` 必须指定、`"supported"` 支持但可选、`"none"` 忽略语言提示（如 SenseVoice 自动检测，不接受 `--language`） |
| `segment_timestamps` | `bool` | 模型是否返回 `segments`（分句时间戳）；仅 whisper 家族的 capabilities 包含此字段（值为 `True`） |

**选项诚实**：若模型的 `language_hint` 为 `"none"`（忽略语言提示），而用户传了 `--language`，`TranscribeResult.warnings` 会包含一条提示，例如 `"local/sensevoice auto-detects language; --language is ignored"`。单文件/批量模式下，warnings 会打到 stderr。

---

## 二、单文件 JSON vs 批量 NDJSON

`--format json` 在**单文件模式**（未加 `--batch`、只给了一个普通文件）和**批量模式**（多输入 / glob / 目录 / stdin / 显式 `--batch`）下行为不同，理解这个差异很重要：

| | 单文件 `--format json` | 批量 NDJSON（`-f json` + 批量触发） |
|---|---|---|
| 输出形态 | 单个 JSON 对象（`indent=2`，人读友好） | 每行一个 JSON 对象（NDJSON，逐行 `json.loads`） |
| `text` 为空时 | **略去**该 key（历史行为，保持不变） | **恒含**（`"text": ""`），失败行也能统一按 key 取值 |
| `file` / `model` | 无（单文件场景下由 CLI 参数已知，不重复出现在输出里） | **含**（分别是该条记录的输入路径与所用 model id） |
| `schema_version` | 无 | **含**，当前值为 `1`（`emit.SCHEMA_VERSION`），未来契约变化会递增，脚本可据此判断兼容性 |
| `raw_response` | 有则含（调试云端厂商原始响应用） | **恒排除**（`emit._ndjson_line` 显式 `pop`），避免每行都塞一份 vendor 原始 JSON 造成噪音/体积膨胀 |

单文件 json 示例（失败，`text` 略去）：

```json
{
  "error": "boom"
}
```

批量 NDJSON 示例（每行一条，成功/失败混合）：

```
{"text": "hello", "lang": "en", "latency_ms": 12, "file": "a.wav", "model": "m/x", "schema_version": 1}
{"text": "", "error": "boom", "file": "b.wav", "model": "m/x", "schema_version": 1}
```

触发批量模式的条件（`cli.py` 中 `multi`/`forced` 判定）：位置参数展开后文件数 `!= 1`，或原始参数里含 `-`（stdin）/ 目录 / glob 通配符（`*`、`?`、`[`），或显式传了 `--batch`。

---

## 三、csv / tsv 批量列（11 列，顺序固定）

`emit.COLUMNS`（`src/asrkit/emit.py`）定义了批量 csv/tsv 输出的列，**顺序固定**，带表头行：

```
file, model, text, lang, duration_s, latency_ms, load_ms, decode_ms, rtf, cost_estimate, error
```

| 列 | 来源 | 说明 |
|---|---|---|
| `file` | 输入文件路径 | 批量记录里的 `rec["file"]` |
| `model` | 本次使用的 model id | 如 `local/sensevoice` |
| `text` | `result.text` | 空则为空字符串 |
| `lang` | `result.lang` | 空则为空字符串 |
| `duration_s` | `result.metrics["duration_s"]` | 音频时长（秒）；本地 sherpa adapter 会填充，其它 adapter 视情况可能为空 |
| `latency_ms` | `result.latency_ms` | 本次调用总耗时 |
| `load_ms` | `result.metrics["load_ms"]` | 模型加载耗时（本地模型常见） |
| `decode_ms` | `result.metrics["decode_ms"]` | 解码耗时 |
| `rtf` | `result.metrics["rtf"]` | 实时率 |
| `cost_estimate` | `result.cost_estimate` | 云端调用估算成本 |
| `error` | `result.error` | 出错信息；成功为空 |

csv 用逗号分隔、tsv 用 tab 分隔；写入用标准库 `csv.writer`（`lineterminator="\n"`，避免跨平台多余空行），字段内的引号/逗号/换行按 CSV 规则自动转义。

> **CSV 行数 ≠物理行数**：`text` 字段可能包含换行符（多行转写结果），这在 CSV 里是**合法的单条记录**，会被引号包裹并跨越多个物理行。**请用 CSV/TSV 解析器（如 Python `csv` 模块）读取，不要按物理行 `split("\n")` 处理**，否则会把一条记录错误地拆成多行。

---

## 四、退出码

| 退出码 | 常量 | 含义 |
|---|---|---|
| `0` | `EXIT_OK` | 成功 |
| `1` | `EXIT_ERROR` | 意外异常（adapter 抛出未捕获异常等程序性错误） |
| `2` | `EXIT_USAGE` | 用法错误（输入无法解析：glob/目录空匹配、多个 stdin、批量字幕聚合到 stdout 等） |
| `3` | `EXIT_MODEL_NOT_FOUND` | 指定的 model id 不存在 |
| `4` | `EXIT_FAILED` | 转写/渲染失败（`result.error` 非空，或该条格式渲染失败，如字幕缺 segments） |

**批量模式退出码取"最严重"**（`emit.worst_code`），优先级 **`1 > 3 > 4`**：只要批次中有任意一条命中 `EXIT_ERROR`（意外异常），整体返回 `1`，即使同时也有 `3`/`4` 也不会被掩盖；其次是 `3`（模型不存在，通常整批同一模型，一旦命中会在建立 adapter 阶段就短路）；最后才是 `4`（个别文件转写失败，其余继续处理）。批次全部成功才返回 `0`。

> 注：单文件模式下，行为变更前历史上失败只返回 `1`；现在 `result.error` 非空的转写失败返回 **`4`**，其它程序性异常仍返回 `1`（`cli._batch_code`）。详见 `CHANGELOG.md` 的 `Unreleased` 一节。

---

## 五、流式契约：`PartialResult`（W4 行使记录）

`asrkit stream` / `api.transcribe_stream` 返回 `PartialResult` 迭代器（见 `src/asrkit/types.py`）。消费者**一律以 `text` 为准**（权威展示文本）。

| 字段 | 类型 | 含义 | 本刀（W4）填充 |
|---|---|---|---|
| `text` | str | 当前完整假设 / 最终文本 | ✅ 每块给出 |
| `is_final` | bool | 是否为定稿（迭代最后一个为 `True`） | ✅ |
| `committed` | str | 可选优化：已定稿部分 | 留空（契约允许，端侧留空） |
| `partial` | str | 可选优化：当前假设增量 | 留空 |
| `ts_ms` | int? | 时间戳 | 未填（文件分块无稳定挂钟语义） |
| `error` | str? | 运行时失败信息 | 随末尾 `is_final=True` 给出 |

**语义**：每解码一块 yield 一个 `PartialResult(text=<增长假设>, is_final=False)`；喂完 flush 尾音后 yield 最终 `PartialResult(text=<最终文本>, is_final=True)`。`text` 每块**重发全量**（非增量）。仅 `modes` 含 `streaming` 的模型支持；批处理模型 `api.transcribe_stream` 抛 `ValueError`、adapter 直调抛 `NotImplementedError`。

> **复盘（留给未来独立一刀）**：当前 `text` 每块重发全量，消费者需自行 diff 才知新增。若将来要"仅追加已定稿"，再引入 `committed`/`partial` 精细化——契约已预留字段，属**纯新增**、无需破坏性变更。麦克风/serve 流式端点、词级时间戳同为后续项。

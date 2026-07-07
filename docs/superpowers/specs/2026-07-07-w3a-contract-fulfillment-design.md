# W3a 设计 — 契约做实(segments + 选项诚实)

> 状态:已通过 brainstorming,待写实现计划。
> 目标波次:W3 第一刀(见 [roadmap.md](../../roadmap.md) / [expert-review-2026-07.md](../../expert-review-2026-07.md) 的 🔴 A1/A2)。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄"、零新增运行时依赖;云端 adapter 请求形状**只在能力位开启时**才变。

---

## 1. 背景与目标

专家评估的两个 🔴:
- **A1 字幕空心**:0 个 adapter 填 `TranscribeResult.segments` → `srt/vtt` 对全部 71 模型只报错。faster-whisper/whispercpp 引擎**免费给了**带时间戳的 segments 却被丢弃。
- **A2 选项静默丢弃**:`--language` 被 whispercpp/transformers/openai 静默扔掉;违反自家"诚实报错"原则。

**W3a 目标**:把这两个已写在接口上的承诺**做实到能白捡的范围**,让 `srt/vtt` 从"0% 可用"变"whisper 家族可用",并让被忽略的选项**出声(warning)**而非静默。

**不含**(留后续):sherpa segments(架构各异、深坑)、transformers segments/language(开放模型,per-model 行为)、元数据全量修真(W3b,与 `list --lang` 一起)、`enable_punctuation` 逐模型实现、word-level 时间戳。

---

## 2. 已定决策(brainstorming 结论)

| # | 决策 | 取值 |
|---|---|---|
| D1 | 范围 | segments + 选项诚实;不含 sherpa/transformers segments、不含元数据全量修真 |
| D2 | 本地 segments | faster-whisper(start/end)、whispercpp(t0/t1 厘秒→秒)直接填;引擎免费给,零风险 |
| D3 | 云端 segments | **能力位门控,仅 openai/whisper-1**:`capabilities["timestamps"]` 在才请求 `response_format=verbose_json` 并解析;无则回纯文本。**siliconflow 请求逐字不变**。标"待真机验" |
| D4 | lang_hint 透传 | 修 whispercpp(静默丢弃)+ openai 门控(`capabilities["language_hint"]` 在才传);transformers 延后;faster-whisper/sherpa 已透传不动 |
| D5 | 选项诚实 | 新 `capabilities.py` 中央告警:**仅对 meta 显式声明不支持的选项发 warning**(显式 `False`);缺省/未知不告警(与元数据修真解耦) |
| D6 | 能力位填充 | 按**架构**批量填(whisper→`language_hint:True`+`timestamps` 概念;senseVoice→`language_hint:False`),不手工逐模型;openai/whisper-1 显式加 `{"timestamps":True,"language_hint":True}` |
| D7 | 不做 | `enable_punctuation` 逐模型实现(YAGNI:多数模型默认加标点) |

---

## 3. 设计

### 3.1 Segments 填充

**faster-whisper**(`local_faster_whisper.py`):
- ⚠️ **陷阱**:`segments` 是惰性生成器,迭代一次即耗尽。必须先物化:
  ```python
  seg_list = list(segments)
  text = "".join(s.text for s in seg_list).strip()
  result_segments = [Segment(s.start, s.end, s.text.strip()) for s in seg_list] or None
  ```
- `TranscribeResult(..., segments=result_segments)`。

**whispercpp**(`local_whispercpp.py`):
- pywhispercpp `Segment` 的 `t0`/`t1` 单位是**厘秒(1/100 秒)**,`text` 是文本。防御性取属性:
  ```python
  segs = self._model.transcribe(samples)
  out = [Segment(getattr(s, "t0", 0) / 100.0, getattr(s, "t1", 0) / 100.0,
                 getattr(s, "text", "").strip()) for s in segs]
  text = " ".join(x.text for x in out).strip()
  ```
- `segments=out or None`。(实现时验证 pywhispercpp 的属性名/单位;测试钉死厘秒换算。)

**openai/whisper-1**(`cloud_openai.py`,能力位门控):
- meta 加 `capabilities={"timestamps": True, "language_hint": True}`(仅 whisper-1;siliconflow 不加)。
- transcribe:
  ```python
  caps = self.meta.capabilities or {}
  data = {"model": self.meta.model}
  if caps.get("timestamps"):
      data["response_format"] = "verbose_json"
  if caps.get("language_hint") and opts.lang_hint:
      data["language"] = opts.lang_hint
  ```
- 解析防御:`segs = j.get("segments")`;有则 `[Segment(s["start"], s["end"], s["text"].strip()) for s in segs]`,无则 `None`;`text` 仍取 `j.get("text")`。**无能力位的 siliconflow 走原纯文本路径,请求/解析逐字不变。**

**transformers**:本刀不做(HF pipeline 要 `return_timestamps=True`,非白捡、开放模型行为不一)——`result-contract.md` 记 TODO。

### 3.2 lang_hint 透传(消灭静默丢弃)

- **whispercpp**:`self._model.transcribe(samples, language=opts.lang_hint or None)`(实现时验证 pywhispercpp 参数名;不支持则跳过并记 TODO,不硬塞)。
- **openai/whisper-1**:见 3.1(门控)。
- **transformers**:延后(记 TODO)。faster-whisper/sherpa 已透传,不动。

### 3.3 选项诚实 `asrkit/capabilities.py`(新)

```python
def warnings_for(opts, meta) -> list[str]:
    """仅对 meta 显式声明不支持的选项发 warning;缺省/未知不告警(避免误报,与元数据修真解耦)。"""
    caps = meta.capabilities or {}
    out = []
    if opts.lang_hint and caps.get("language_hint") is False:
        out.append(f"{meta.id} auto-detects language; --language is ignored")
    if opts.word_timestamps and caps.get("timestamps") is False:
        out.append(f"{meta.id} does not return timestamps; word_timestamps ignored")
    return out
```
- 接入 `api._run_adapter`:transcribe 后,`w = capabilities.warnings_for(opts, adapter.meta); if w: result.warnings = (result.warnings or []) + w`。CLI 已会打印 `result.warnings`。
- **能力位填充**(`models_local.py` 按架构,不逐模型手编):
  ```python
  if ctype == "whisper":
      caps = {"max_input_duration_s": 30, "language_hint": True}
  elif ctype == "senseVoice":
      caps = {"language_hint": False}
  else:
      caps = {}
  ```
  senseVoice 确实不吃 language 参数(sherpa `from_sense_voice` 无 language),标 `False` 正确且有价值。其余架构留空(不告警)。全量填充留 W3b。

### 3.4 契约影响

- `TranscribeResult.segments` 从"永远空"变"whisper 家族(faster-whisper/whispercpp/whisper-1)有值";`srt/vtt` 对这些模型可用。**契约字段本就存在,无 schema 变更。**
- 单文件 json / 批量 NDJSON 会多出 `segments` 字段(本就在契约里,之前恒空);`result-contract.md` 更新说明"哪些模型填 segments"。
- 云端 openai 成功路径:仅 whisper-1 请求变(verbose_json);siliconflow 零变化。

---

## 4. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/adapters/local_faster_whisper.py` | 物化 segments 生成器 + 填 `result.segments` |
| `asrkit/adapters/local_whispercpp.py` | 填 segments(t0/t1 厘秒→秒)+ 透传 language |
| `asrkit/adapters/cloud_openai.py` | 门控 verbose_json + language;解析 segments 防御;whisper-1 meta 加 capabilities |
| `asrkit/adapters/models_local.py` | capabilities 按架构填 `language_hint`(whisper True / senseVoice False) |
| `asrkit/capabilities.py` | **新增** `warnings_for(opts, meta)` |
| `asrkit/api.py` | `_run_adapter` 接入 warnings_for → 追加到 `result.warnings` |
| `docs/result-contract.md` | 记"哪些模型填 segments"、transformers/sherpa TODO |
| `CHANGELOG.md` | `[Unreleased]` 追加(版本号等人类定) |

---

## 5. 测试(全程 mock,零真实网络/引擎)

- **`test_segments.py`(新)**:
  - faster-whisper:monkeypatch `WhisperModel` 返回带 `.start/.end/.text` 的假 segs(生成器),断言 `result.segments` 正确、**生成器物化后 text 不丢**。
  - whispercpp:假 segs 带 `t0=150,t1=320`(厘秒),断言 `Segment(1.5, 3.2, …)`(厘秒→秒换算)。
  - openai/whisper-1:mock `_http.post` 返回 verbose_json(带 segments),断言**请求带 `response_format=verbose_json`**、解析出 segments;再 mock 无 segments 响应 → `segments is None` 且 text 正常。
  - siliconflow:断言请求**不含** `response_format`、走纯文本、`segments is None`(形状不变)。
- **`test_capabilities.py`(新)**:`warnings_for`:显式 `language_hint=False` + 传 lang_hint → 有 warning;能力位缺省 → 无 warning;`word_timestamps` + `timestamps=False` → 有 warning。
- **api 接线**:mock 一个 meta 带 `language_hint=False` 的 stub adapter,`api.transcribe(..., opts=lang_hint)` → `result.warnings` 含该提示。
- **回归**:现有 82 测试全绿;siliconflow/其它云端请求形状不变。
- **e2e(可选,记为 nice-to-have)**:nightly 加 `.[faster-whisper]`,pull 一个 tiny、断言 `result.segments` 非空 + srt 可渲染。(主覆盖靠上面 mock 单测。)

---

## 6. 明确不做(YAGNI)

sherpa segments、transformers segments/language、元数据全量修真(W3b)、`enable_punctuation` 逐模型实现、word-level 时间戳、给 siliconflow 等非 whisper-1 云端改请求。

---

## 7. 风险与兼容

- **最大风险 = 动云端 openai adapter**(作者真机接通过、无 key 复验)。缓解:**能力位门控**——只有 whisper-1(显式 capabilities)请求才变;siliconflow/telespeech **逐字不变**;解析全程防御(无 segments 回退纯文本);全 mock 测试。标注"whisper-1 verbose_json 路径待真机验"。
- faster-whisper 生成器物化是**必须**(否则填了 segments 就丢 text);测试专门钉死。
- whispercpp 厘秒单位若判断错 → 时间戳 ×100 偏差;测试钉死换算。
- 均向后兼容:segments 字段本就在契约、之前恒空;新增 warning 只多打印、不改退出码。

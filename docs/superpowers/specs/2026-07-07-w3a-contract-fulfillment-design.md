# W3a 设计 v2 — 契约做实(segments + 选项诚实)(含 Codex 评审修订)

> 状态:brainstorming + Codex(gpt-5.5)评审(采纳 8 项),待写实现计划。
> 目标波次:W3 第一刀(专家评估 🔴 A1/A2)。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄"、零新增运行时依赖;云端请求**只在能力位开启时**才变。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-07T11-12-30*.md`):**P0 —— `capabilities` 已是三态字符串(`"required"/"supported"/"none"`,见 adapter-spec.md),不能用真值判断**(`"none"` 是真值,会让 siliconflow 破例发 language)。另:timestamps 能力只给真填 segments 者;openai 加 `timestamp_granularities[]=segment`;告警 W3a 只覆盖 language_hint;emit 批量打印 warnings;whispercpp 直接属性+显式中性 language;faster-whisper `list()` 进计时区;serve 出范围。

---

## 1. 背景与目标

专家评估两个 🔴:**A1** 0 adapter 填 `segments` → `srt/vtt` 对全部 71 模型只报错(faster-whisper/whispercpp 引擎免费给了却丢弃);**A2** `--language` 被 whispercpp/transformers/openai 静默扔掉,违反"诚实"原则。

**W3a 目标**:把这两个承诺做实到**能白捡的范围**——`srt/vtt` 从"0% 可用"变"whisper 家族可用";被忽略的选项**出声(warning)**。

**不含**:sherpa/transformers segments、transformers language、元数据全量修真(W3b)、`enable_punctuation` 实现、word-level 时间戳及其告警。

---

## 2. 能力位约定(先钉死,P0 修订核心)

沿用 [adapter-spec.md](../../adapter-spec.md) 既有的 `capabilities` 三态字符串,**不引入 bool 混用**:

| 键 | 取值 | 含义 | 谁用 |
|---|---|---|---|
| `language_hint` | `"required"` / `"supported"` / `"none"` | 模型是否吃语言提示 | warnings_for(`"none"`→告警)+ openai 门控(`supported/required`→发 language) |
| `segment_timestamps` | `True`(缺省视为无) | 模型是否返回 `segments`(段级时间戳) | openai 门控(→请求 verbose_json);未来 doctor/list 消费 |

- **归一助手**(唯一真值判断处):`language_supported(meta)` = `caps.get("language_hint") in ("supported","required")`;`language_ignored(meta)` = `caps.get("language_hint") in ("none",)`。
- `word_timestamps`(词级)**本刀不涉及**——与 `segment_timestamps` 分名,避免混用;其告警延后。

---

## 3. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 范围 | segments + language 诚实;不含 sherpa/transformers segments、元数据全量修真 |
| D2 | 本地 segments | faster-whisper / whispercpp 直接填(引擎免费给) |
| D3 | 云端 segments | **门控仅 openai/whisper-1**:`segment_timestamps` 在 → 请求 `verbose_json` + `timestamp_granularities[]=segment` 并解析;无则纯文本。**siliconflow 逐字不变** |
| D4 | language 透传 | whispercpp(修静默丢弃,显式中性值防持久化)+ openai 门控(`language_supported` 才发);transformers 延后;faster-whisper/sherpa 已透传不动 |
| D5 | 选项诚实 | `capabilities.warnings_for` **仅覆盖 language_hint**:`language_ignored(meta)` 且用户传了 `--language` → warning;其余不告警 |
| D6 | 能力位填充(按架构) | sherpa `whisper`→`{"max_input_duration_s":30,"language_hint":"supported"}`(**不含** segment_timestamps);sherpa `senseVoice`→`{"language_hint":"none"}`;faster-whisper/whispercpp 模型→`{"language_hint":"supported","segment_timestamps":True}`;openai/whisper-1→`{"language_hint":"supported","segment_timestamps":True}`;siliconflow 现有 `"language_hint":"none"` **保留**(现在起生效) |
| D7 | 批量告警出声 | `emit` 每条记录把 `result.warnings` 打到 stderr(全格式) |
| D8 | serve | 出范围(serve 绕过 `_run_adapter`、无 warnings 通道);文档注明 |
| D9 | 不做 | `enable_punctuation` 实现、word_timestamps 告警 |

---

## 4. 设计

### 4.1 Segments 填充

**faster-whisper**(`local_faster_whisper.py`):
- ⚠️ 生成器**单次消耗** + **解码在迭代时才发生** → `list()` 必须进**计时区**内(否则 `decode_ms≈0`):
  ```python
  t1 = time.perf_counter()
  segments, info = self._model.transcribe(audio.original_path, language=opts.lang_hint or None)
  seg_list = list(segments)                       # 物化(真正解码在此)
  decode_ms = int((time.perf_counter() - t1) * 1000)
  text = "".join(s.text for s in seg_list).strip()
  segs = [Segment(s.start, s.end, s.text.strip()) for s in seg_list] or None
  ```
  `TranscribeResult(..., segments=segs)`。start/end 为秒(float)。

**whispercpp**(`local_whispercpp.py`):
- pywhispercpp `Segment` 的 `t0`/`t1` 为**厘秒(×10ms)**(Codex 已核),`text` 为文本。**用直接属性**(不 `getattr(...,0)` 掩盖 binding 变化):
  ```python
  segs_raw = self._model.transcribe(samples, language=opts.lang_hint or "auto")   # 显式中性值:pywhispercpp 参数跨调用持久化
  out = [Segment(s.t0 / 100.0, s.t1 / 100.0, s.text.strip()) for s in segs_raw]
  text = " ".join(x.text for x in out).strip()
  ```
  `segments=out or None`。(实现时验证 pywhispercpp 属性名;若 binding 无 `t0`/`t1` → 让 `AttributeError` 进 `result.error`,不静默出全零。中性 language 值以 pywhispercpp 实际接受的为准,如 `"auto"`/`""`。)

**openai/whisper-1**(`cloud_openai.py`,门控):
- meta 加 `capabilities={"segment_timestamps": True, "language_hint": "supported"}`(仅 whisper-1;siliconflow 不加)。
- transcribe form data:
  ```python
  from .. import capabilities
  data = {"model": self.meta.model}
  if (self.meta.capabilities or {}).get("segment_timestamps"):
      data["response_format"] = "verbose_json"
      data["timestamp_granularities[]"] = "segment"          # Codex:verbose_json 未必默认给 segments
  if capabilities.language_supported(self.meta) and opts.lang_hint:
      data["language"] = opts.lang_hint
  ```
- 解析防御:`text = str(j.get("text") or j.get("result") or "").strip()`(verbose_json 顶层仍有 `text`,不变);`raw = j.get("segments")`;有则 `[Segment(s["start"], s["end"], s["text"].strip()) for s in raw]`,无则 `None`。**无能力位的 siliconflow 走原纯文本路径,请求/解析逐字不变。**

**transformers**:本刀不做(记 `result-contract.md` TODO)。

### 4.2 `asrkit/capabilities.py`(新)

```python
_LANG_YES = ("supported", "required")
_LANG_NO = ("none",)

def language_supported(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_YES

def language_ignored(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_NO

def warnings_for(opts, meta) -> list:
    """仅对显式声明忽略 language 的模型、且用户传了 --language 时告警。其余不告警(避免误报)。"""
    out = []
    if opts.lang_hint and language_ignored(meta):
        out.append(f"{meta.id} auto-detects language; --language is ignored")
    return out
```
- `api._run_adapter`:transcribe 后 `w = capabilities.warnings_for(opts, adapter.meta); if w: result.warnings = (result.warnings or []) + w`。

### 4.3 emit 批量告警出声(`emit.py`)

- `_aggregate` 的 json/csv/tsv/txt 分支 + `_mirror`:每条记录若 `rec["result"].warnings`,逐条 `print(f'[warn] {rec["file"]}: {w}', file=sys.stderr)`。(现仅 NDJSON 把 warnings 序列化进对象;stderr 输出补齐"出声"。)

### 4.4 契约影响

- `segments` 从"永远空"变"whisper 家族(faster-whisper/whispercpp/whisper-1)有值";`srt/vtt` 对这些可用。**字段本就在契约,无 schema 变更。**
- `result-contract.md` 更新:哪些模型填 segments、transformers/sherpa TODO、能力位 `language_hint`/`segment_timestamps` 语义。
- serve 不受影响(出范围)。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/capabilities.py` | **新增**:`language_supported`/`language_ignored`/`warnings_for` |
| `asrkit/adapters/local_faster_whisper.py` | 物化生成器进计时区 + 填 segments |
| `asrkit/adapters/local_whispercpp.py` | 填 segments(厘秒→秒,直接属性)+ 显式 language |
| `asrkit/adapters/cloud_openai.py` | 门控 verbose_json+`timestamp_granularities[]`+language;解析 segments;whisper-1 meta 加 capabilities |
| `asrkit/adapters/models_local.py` | capabilities 按架构填(whisper→language_hint supported;senseVoice→none) |
| `asrkit/adapters/local_faster_whisper.py` / `local_whispercpp.py`(注册处) | 模型 meta 加 `{"language_hint":"supported","segment_timestamps":True}` |
| `asrkit/api.py` | `_run_adapter` 接入 `warnings_for` |
| `asrkit/emit.py` | 每条记录 warnings 打 stderr(全格式) |
| `docs/result-contract.md` / `CHANGELOG.md` | 文档 + `[Unreleased]`(版本号等人类定) |

---

## 6. 测试(全程 mock)

- **`test_segments.py`(新)**:
  - faster-whisper:mock `WhisperModel` 返回**生成器**(不是 list)带 `.start/.end/.text`,断言 `result.segments` 正确 **且 text 不丢**(证明物化);`decode_ms` 计时不为 0(计时区含 list())。
  - whispercpp:假 segs `t0=150,t1=320` → 断言 `Segment(1.5, 3.2, …)`;**测试注释 source-lock 厘秒来源**(pywhispercpp ×10ms);断言 transcribe 收到 `language=` kwarg。
  - openai/whisper-1:mock `_http.post` 返回 verbose_json(带 segments)→ 断言请求含 `response_format=verbose_json` **且** `timestamp_granularities[]=segment`;解析出 segments;再 mock 无 segments → `segments is None` 且 text 正常。
  - **siliconflow(P0 回归)**:传 `--language` 时断言请求**不含** `language`、**不含** `response_format`(三态 `"none"` 不被当真值),形状逐字不变。
- **`test_capabilities.py`(新)**:`warnings_for`:`language_hint="none"` + lang_hint → 有 warning;`"supported"` → 无;缺省 → 无;`language_supported`/`language_ignored` 三态判断正确。
- **api 接线**:stub adapter meta `language_hint="none"`,`api.transcribe(opts=lang_hint)` → `result.warnings` 含提示。
- **emit 批量告警**:批量 csv/txt,某记录带 warnings → 断言打到 stderr(capsys)。
- **回归**:现有 82 测试全绿;siliconflow/telespeech 及其它云端请求形状不变。

---

## 7. 明确不做(YAGNI)

sherpa/transformers segments、transformers language、元数据全量修真(W3b)、`enable_punctuation`、word-level 时间戳及告警、serve 告警、给非 whisper-1 云端改请求。

---

## 8. 风险与兼容

- **P0 已修**:三态 `"none"` 绝不当真值——siliconflow/telespeech 请求逐字不变(回归测试钉死)。
- **动 openai adapter**(真机接通过、无 key 复验):门控 + 防御解析 + 全 mock;标"whisper-1 verbose_json 路径待真机验"。
- faster-whisper 生成器物化进计时区(否则丢 text / decode_ms=0);测试钉死。
- whispercpp 厘秒 + 参数持久化:直接属性(binding 变即 error,不静默)+ 每次显式 language;测试 source-lock。
- 均向后兼容:segments 本在契约、之前恒空;warning 只多打印、不改退出码。

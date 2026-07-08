# 设计 — 流式端点检测 / `committed`·`partial` 精细化(P3-E)

> 状态:brainstorming 完成、用户批准(重排 E→C→D,先做 E),待 Codex 评审 → 实现计划。
> 定位约束:填实 W4 预留的契约字段(非破坏,`text` 语义不变);仅本地 sherpa online;零新依赖。

---

## 1. 背景

W4 让 `asrkit stream` 跑起来,但 `PartialResult.committed`/`partial` 恒空——sherpa online 不做端点检测时,`get_result` 是**一条无限增长的假设**,长会话越积越糊,麦克风(C)/serve 流式(D)都会退化。E 开启端点检测,让流**自动分段**:每段结束进 `committed`,当前段是 `partial`。

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 端点检测 | streaming `_build` 开 `enable_endpoint_detection=True`(用 sherpa 默认规则参数) |
| D2 | committed 累积 | 每次 `rec.is_endpoint(st)` → 当前 `get_result` 收进 `committed`、`rec.reset(st)` 开下一段 |
| D3 | text 语义 | `text = f"{committed} {partial}".strip()`(权威展示文本,消费者仍只读 `text`);`is_final` 仍只在流末尾为真 |
| D4 | 段间连接 | 用单空格 join(通用显示默认;CJK 略有空格但 `committed` 单独暴露,消费者可自行重拼) |
| D5 | 不做 | 词级时间戳、可配端点规则参数(先用默认,需要再加)、非 sherpa 引擎 |

## 3. 设计

### 3.1 `_build` streaming 分支开端点检测(`local_sherpa.py`)

把现有(约 60–68 行):
```python
    if streaming:
        if ct == "onlineParaformer":
            return so.OnlineRecognizer.from_paraformer(
                tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
                decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"), num_threads=threads)
        return so.OnlineRecognizer.from_transducer(
            tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
            decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"),
            joiner=_find(d, prefer, "joiner*.onnx", "*joiner*.onnx"), num_threads=threads)
```
各加 `enable_endpoint_detection=True`:
```python
    if streaming:
        if ct == "onlineParaformer":
            return so.OnlineRecognizer.from_paraformer(
                tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
                decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"),
                num_threads=threads, enable_endpoint_detection=True)
        return so.OnlineRecognizer.from_transducer(
            tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
            decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"),
            joiner=_find(d, prefer, "joiner*.onnx", "*joiner*.onnx"),
            num_threads=threads, enable_endpoint_detection=True)
```

### 3.2 `_stream` 累积 committed(`local_sherpa.py`)

把 `_stream` 的解码循环 + 收尾改为(其余守卫/try-except 结构不变):

```python
        rec = self._rec
        st = rec.create_stream()
        sr = 16000                       # chunks 已是 16k 单声道 float32
        committed = ""
        for chunk in chunks:
            st.accept_waveform(sr, chunk)
            while rec.is_ready(st):
                rec.decode_stream(st)
            partial = _result_text(rec.get_result(st))
            if rec.is_endpoint(st):
                if partial:
                    committed = f"{committed} {partial}".strip()
                rec.reset(st)
                partial = ""
            text = f"{committed} {partial}".strip()
            yield PartialResult(text=text, committed=committed, partial=partial, is_final=False)
        # flush 尾音 + 定稿:剩余 partial 收进 committed
        st.accept_waveform(sr, np.zeros(sr // 2, dtype=np.float32))
        st.input_finished()
        while rec.is_ready(st):
            rec.decode_stream(st)
        partial = _result_text(rec.get_result(st))
        if partial:
            committed = f"{committed} {partial}".strip()
        yield PartialResult(text=committed, committed=committed, partial="", is_final=True)
```

- 端点前先取 `partial`(reset 后 `get_result` 会空),再 reset。
- `text` 永远 = `committed`(+ 空格 +)`partial`;定稿时 partial 全进 committed、`text==committed`、`partial=""`。
- 无端点的流(短音频 / FakeRec):committed 一直空、partial=当前假设、text=partial → 与 W4 行为等价(除 committed/partial 字段现在有值)。

### 3.3 契约影响

- **填实,非破坏**:`text`(权威)语义不变;`committed`/`partial` 从"恒空"变"有内容"。已在 W4 契约文档标为"可选优化,端侧可留空",现在端侧填了 → 向后兼容(只读 `text` 的消费者零感知)。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/adapters/local_sherpa.py` | `_build` 两处开 `enable_endpoint_detection=True`;`_stream` 累积 committed/partial |
| `tests/test_streaming.py` | FakeRec 补 `is_endpoint`/`reset`;更新 growing-partials 断言;新增多端点测试 |
| `docs/result-contract.md` | 更新 W4 复盘:committed/partial 现由端点检测填实 |
| `docs/usage.md` / `CHANGELOG.md` | 说明 + `[Unreleased]` |

## 5. 测试(mock,不需真引擎;numpy importorskip)

- **FakeRec 补方法**:`is_endpoint(self, st)→False`、`reset(self, st)→None`(默认单段,退回 W4 行为)。
- **更新 `test_transcribe_stream_yields_growing_partials`**(无端点):断言改为——4 次 yield、is_final=[F,F,F,T]、text 递增;`out[:3]` 的 `committed==""`、`partial` 非空且 `text == partial`;`out[-1].partial==""` 且 `out[-1].committed == out[-1].text`。
- **新增多端点测试**:FakeRec2 —— `get_result` 返回当前段文本,`is_endpoint` 在第 2 块返回 True(其余 False),`reset` 清零段计数。喂 3 块 → 断言:第 2 块 yield 的 `committed` 非空(第一段定稿)、`reset` 被调用、后续 partial 从新段重新开始;最终 `is_final` 项 `committed` 含两段拼接、`partial==""`。用计数器验证 `reset` 调用次数。
- **回归**:非流式守卫 / build 错误对称 / AudioFormatError 穿透三条测试不受影响(它们不依赖 committed/partial 语义,但 FakeRec 现有 is_endpoint/reset 后仍通过)。

## 6. 不做(YAGNI)

可配端点规则(rule1/2/3 参数)、词级时间戳、按语言选段间连接符、非 sherpa 引擎端点。

## 7. 风险

- 真机行为依赖 sherpa 端点检测质量(默认规则);mock 测试覆盖逻辑,真机留给 nightly E2E / C(麦克风)手动验证。
- `enable_endpoint_detection=True` 对既有 file 流式:短音频通常单段,行为等价;长音频会分段(更好)。

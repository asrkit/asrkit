# W3b-1 发现(元数据修真 + list --lang/--arch + search)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给广多语模型加 `multilingual` 标记(修元数据),并加 `list --lang/--arch` 筛选与 `search` 子命令。

**Architecture:** 纯数据 + CLI 层。`capabilities.is_english_only` + 各 adapter 注册处按架构填 `multilingual`;`cli.py` 抽 `_emit_model_rows` 共享渲染,list 加筛选、新增 search、show 加一行。零新依赖,不动 adapter 请求/云端/segments。

**Tech Stack:** Python 3.9+;pytest。

## Global Constraints

- 版本号**不动**(`__version__` 保持 `0.5.2`);发版由人类定。
- **零新增运行时依赖**。
- 终端/帮助/报错**英文**;注释**中文**。
- **multilingual = "广覆盖候选"语义**:`--lang X` 把 multilingual 模型当候选返回(过度包含但诚实;文档标注"覆盖因模型而异")。
- **保守标记**:仅真·广多语架构 `MULTI_ARCHS = {"whisper","dolphin","omnilingualCtc","qwen3Asr","funasrNano"}` 且非英语专用(`is_english_only(langs)` False);senseVoice **不打 flag**,改用显式 5 langs 精确命中。
- **`list` 无 filter 的输出格式逐字不变**(仅被修正的元数据内容如 sensevoice langs / 新 `multilingual` 键有别,那是有意的内容修正)。
- `--lang`/`--arch` 归一化:`strip().lower()` 两边比较。
- 提交用 `git -c user.name="BolynWang" -c user.email="1710998763@qq.com"`,**显式 `git add <文件>`**,不 push。
- **测试一律** `PYTHONPATH=src python -m pytest ... -o addopts=""`。
- 契约细节见历史 spec：[`../specs/2026-07-07-w3b1-discovery-design.md`](../specs/2026-07-07-w3b1-discovery-design.md)。

---

## File Structure

- **Modify** `src/asrkit/capabilities.py` — 加 `is_english_only(langs)`。
- **Modify** `src/asrkit/adapters/models_local.py` — `MULTI_ARCHS` + `multilingual`;senseVoice langs 修 5。
- **Modify** `local_faster_whisper.py` / `local_whispercpp.py` — whisper 系 `multilingual`。
- **Modify** `cloud_openai.py` — openai/whisper-1 加 `multilingual`。
- **Modify** `src/asrkit/cli.py` — `_emit_model_rows` 抽取;list `--lang`/`--arch`;`search` 子命令;show 加行。
- **Create** `tests/test_discover.py`。
- **Modify** `docs/usage.md`、`CHANGELOG.md`。

---

## Task 1: 元数据修真(multilingual 标记 + sensevoice langs)

**Files:**
- Modify: `src/asrkit/capabilities.py`, `models_local.py`, `local_faster_whisper.py`, `local_whispercpp.py`, `cloud_openai.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Produces: `capabilities.is_english_only(langs)->bool`;广多语模型 meta 带 `capabilities["multilingual"]=True`;senseVoice meta langs 含 ja/ko 且无 flag。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_discover.py
from asrkit import registry


def _caps(mid):
    return registry.resolve(mid).capabilities or {}


def test_multilingual_marked():
    for mid in ["local/whisper-tiny", "local/omnilingual-300m", "local/qwen3-asr-0.6b",
                "local/funasr-nano", "local/dolphin-small",
                "faster-whisper/large-v3", "whispercpp/base", "openai/whisper-1"]:
        assert _caps(mid).get("multilingual") is True, mid


def test_multilingual_not_marked():
    for mid in ["local/whisper-tiny-en", "local/moonshine-tiny",
                "faster-whisper/distil-large-v3", "local/paraformer-zh"]:
        assert not _caps(mid).get("multilingual"), mid


def test_sensevoice_precise_langs_no_flag():
    m = registry.resolve("local/sensevoice")
    assert "ja" in m.langs and "ko" in m.langs      # 补全
    assert not (m.capabilities or {}).get("multilingual")   # 精确,不打 flag
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_discover.py -o addopts="" -v`
Expected: FAIL(multilingual 未标 / sensevoice langs 无 ja)

- [ ] **Step 3: 实现**

`capabilities.py` 末尾加:
```python
def is_english_only(langs) -> bool:
    """langs 只含 'en'(归一化)→ 英语专用检查点。用于排除 whisper-*-en/distil-en。"""
    return [str(x).strip().lower() for x in (langs or [])] == ["en"]
```

`models_local.py`:顶部加 `from ..capabilities import is_english_only`,`_TABLE` 后加常量,并改 `_metas()` 循环:
```python
MULTI_ARCHS = {"whisper", "dolphin", "omnilingualCtc", "qwen3Asr", "funasrNano"}
```
```python
def _metas():
    out = []
    for folder, name, ctype, streaming, langs, asset in _TABLE:
        caps = {}
        if ctype == "whisper":
            caps = {"max_input_duration_s": 30, "language_hint": "supported"}
        elif ctype == "senseVoice":
            caps = {"language_hint": "none"}
            langs = ["zh", "en", "ja", "ko", "yue"]   # SenseVoice 真实支持(精确;不打 flag)
        if ctype in MULTI_ARCHS and not is_english_only(langs):
            caps["multilingual"] = True
        out.append(AdapterMeta(
            id=f"local/{folder}",
            provider="sherpa-onnx", vendor="local", name=name, source="local",
            modes=["streaming"] if streaming else ["batch"], langs=langs, model_kind="asr",
            capabilities=caps, config_type=ctype,
            download_url=f"{_BASE}/{asset}.tar.bz2",
            base=_BASE_OVERRIDE.get(folder, folder), tag=_TAG_OVERRIDE.get(folder, "int8")))
    return out
```
(即在 W3a 的按架构 caps 基础上,加 MULTI_ARCHS 判定与 senseVoice langs 覆盖。保留其余 AdapterMeta 参数不变。)

`local_faster_whisper.py`:顶部加 `from ..capabilities import is_english_only`;`register_models([AdapterMeta(id=f"faster-whisper/{name}", ...)` 的 `capabilities=...` 改为:
```python
        capabilities={"language_hint": "supported", "segment_timestamps": True,
                      **({"multilingual": True} if not is_english_only(langs) else {})},
```

`local_whispercpp.py`:顶部加 `from ..capabilities import is_english_only`;同样把该条 `capabilities=` 改为上面那三键形式。

`cloud_openai.py`:`openai/whisper-1` 注册的 `capabilities={"language_hint": "supported", "segment_timestamps": True}` 改为 `{"language_hint": "supported", "segment_timestamps": True, "multilingual": True}`。**siliconflow 两条不动。**

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_discover.py -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/capabilities.py src/asrkit/adapters/models_local.py src/asrkit/adapters/local_faster_whisper.py src/asrkit/adapters/local_whispercpp.py src/asrkit/adapters/cloud_openai.py tests/test_discover.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(metadata): 广多语模型标 multilingual(含 qwen3/funasr/dolphin);sensevoice 补全 langs"
```

---

## Task 2: list `--lang`/`--arch` + `_emit_model_rows` 抽取

**Files:**
- Modify: `src/asrkit/cli.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Produces: 模块级 `_emit_model_rows(rows, as_json) -> int`(`rows: list[(AdapterMeta, inst)]`);list 支持 `--lang`/`--arch`。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_discover.py`)**

```python
import json as _json

from asrkit import cli


def _run(args, capsys):
    rc = cli.main(args)
    return rc, capsys.readouterr().out


def test_list_lang_multilingual_and_explicit(capsys):
    _, out = _run(["list", "--lang", "ja", "--source", "local", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "local/whisper-tiny" in ids          # multilingual flag
    assert "local/sensevoice" in ids            # 显式 ja
    assert "local/whisper-tiny-en" not in ids   # en-only
    assert "local/paraformer-zh" not in ids     # zh-only 非多语


def test_list_lang_normalizes_case(capsys):
    _, out = _run(["list", "--lang", "YUE", "--source", "local", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "local/sensevoice" in ids            # 归一化大写


def test_list_arch_case_insensitive(capsys):
    _, out1 = _run(["list", "--arch", "senseVoice", "--json"], capsys)
    _, out2 = _run(["list", "--arch", "sensevoice", "--json"], capsys)
    ids1 = {d["id"] for d in _json.loads(out1)}
    ids2 = {d["id"] for d in _json.loads(out2)}
    assert ids1 == ids2 and "local/sensevoice" in ids1


def test_list_no_filter_json_shape(capsys):
    _, out = _run(["list", "--json"], capsys)
    data = _json.loads(out)
    pz = next(d for d in data if d["id"] == "local/paraformer-zh")
    assert set(pz) >= {"id", "name", "source", "provider", "vendor", "langs",
                       "model_kind", "installed", "size_bytes"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_discover.py -k "list_" -o addopts="" -v`
Expected: FAIL(argparse: unrecognized `--lang`)

- [ ] **Step 3: 实现**

先**读当前 `cli.py` 的 `list` 子命令定义与 `if a.cmd == "list":` 处理块**。

(a) list 子命令加两个旗标(在现有 `lp.add_argument("--source", ...)` 附近):
```python
    lp.add_argument("--lang", default=None, help="only models supporting this language (e.g. ja)")
    lp.add_argument("--arch", default=None, help="only models of this architecture (e.g. senseVoice)")
```

(b) 把 list 处理块里**从"构造 rows 之后"到函数末尾的渲染逻辑**(json 分支 + 人读分支,含 `_human` 与 `store.dir_size` 体积列)整段抽成一个**模块级**函数 `_emit_model_rows`(放在 `_print_result` 附近):
```python
def _emit_model_rows(rows, as_json) -> int:
    """渲染 [(AdapterMeta, inst)] 列表。list 与 search 共用。格式与既有 list 逐字一致。"""
    from . import store

    def _human(n):
        size = float(n)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024

    if as_json:
        import json as _json
        out = []
        for m, inst in rows:
            d: dict = {"id": m.id, "name": m.name, "source": m.source,
                       "provider": m.provider, "vendor": m.vendor, "langs": m.langs,
                       "model_kind": m.model_kind}
            if m.source == "local":
                d["installed"] = bool(inst)
                d["size_bytes"] = store.dir_size(m) if inst else 0
            out.append(d)
        print(_json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    for m, inst in rows:
        if m.source == "cloud":
            mark, flag, size = " ", "☁️ ", ""
        else:
            mark = "✓" if inst else " "
            flag = "💻"
            size = _human(store.dir_size(m)) if inst else ""
        print(f"{mark} {flag} {m.id:26s} {size:>9s}  {m.name}")
    return 0
```
(c) list 处理块改为构造 rows(含新筛选)后调它:
```python
    if a.cmd == "list":
        rows = []
        for m in api.list_models():
            if a.source and m.source != a.source:
                continue
            inst = _installed(m) if m.source == "local" else None
            if a.installed and not inst:
                continue
            if a.lang:
                want = a.lang.strip().lower()
                langs = {x.strip().lower() for x in (m.langs or [])}
                if want not in langs and not (m.capabilities or {}).get("multilingual"):
                    continue
            if a.arch and (m.config_type or "").strip().lower() != a.arch.strip().lower():
                continue
            rows.append((m, inst))
        return _emit_model_rows(rows, a.json)
```
> 注:`_emit_model_rows` 的人读/json 内容必须与你读到的现有 list 渲染**逐字一致**(mark/flag/`{m.id:26s}`/体积列/json 字段);只是把它搬进共享函数。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `PYTHONPATH=src python -m pytest tests/ -o addopts="" -q`
Expected: PASS(既有 + 新;list 无 filter 行为不变)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/cli.py tests/test_discover.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(cli): list --lang/--arch(归一化)+ 抽 _emit_model_rows 共享渲染"
```

---

## Task 3: `search` 子命令 + show multilingual 行

**Files:**
- Modify: `src/asrkit/cli.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `_emit_model_rows`(Task 2)。
- Produces: `asrkit search <term> [--json]`;`show` 输出含 multilingual 行。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_discover.py`)**

```python
def test_search_matches_id_name(capsys):
    _, out = _run(["search", "whisper", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "openai/whisper-1" in ids and "faster-whisper/large-v3" in ids
    assert any(i.startswith("local/whisper") for i in ids)


def test_search_empty(capsys):
    _, out = _run(["search", "zzznomatch", "--json"], capsys)
    assert _json.loads(out) == []


def test_show_multilingual_line(capsys):
    _, out = _run(["show", "local/whisper-tiny"], capsys)
    assert "multilingual: yes" in out
    _, out2 = _run(["show", "local/paraformer-zh"], capsys)
    assert "multilingual: no" in out2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_discover.py -k "search or show_multi" -o addopts="" -v`
Expected: FAIL(无 search 子命令 / show 无 multilingual 行)

- [ ] **Step 3: 实现**

(a) 加 `search` 子命令(在 list 子命令定义附近):
```python
    sp = sub.add_parser("search", help="search models by id/name substring")
    sp.add_argument("term")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
```
(b) 加 `search` 处理块(放在 `if a.cmd == "list":` 块之后):
```python
    if a.cmd == "search":
        term = a.term.strip().lower()
        rows = []
        for m in api.list_models():
            if term in (m.id + " " + m.name).lower():
                inst = _installed(m) if m.source == "local" else None
                rows.append((m, inst))
        return _emit_model_rows(rows, a.json)
```
(c) `show` 处理块里,`print(f"langs:    {', '.join(m.langs)}")` 之后加一行:
```python
        print(f"multilingual: {'yes' if (m.capabilities or {}).get('multilingual') else 'no'}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_discover.py -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/cli.py tests/test_discover.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(cli): search 子命令 + show 显示 multilingual"
```

---

## Task 4: 文档(usage + CHANGELOG)

**Files:**
- Modify: `docs/usage.md`、`CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/usage.md`**

加"发现模型"小节:`asrkit list --lang <code>`(**含 multilingual 候选语义说明**:广多语模型如 whisper/dolphin/qwen3/omnilingual 会作为候选返回,实际覆盖因模型而异,请核对)、`asrkit list --arch <config_type>`、`asrkit search <term>`。

- [ ] **Step 2: 追加 `CHANGELOG.md` 的 `[Unreleased]`(不改版本号)**

在 `## [Unreleased]` 的 `### 新增` 里加:
```markdown
- **发现**:`asrkit list --lang <code>` / `--arch <config_type>` 筛选;`asrkit search <term>`(id/name 子串)。
- **元数据修真**:广多语模型(whisper/dolphin/qwen3-asr/funasr-nano/omnilingual 等)标 `capabilities.multilingual`——`--lang X` 把它们作候选返回(覆盖因模型而异);SenseVoice 语言补全为 zh/en/ja/ko/yue。`show` 显示 multilingual。
```

- [ ] **Step 3: 提交**

```bash
git add docs/usage.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "docs(w3b1): 发现命令用法(list --lang/--arch/search)+ CHANGELOG"
```

---

## Task 5: 收尾验证(ruff/mypy/全量)

**Files:** 无

- [ ] **Step 1: lint + 类型 + 全量**

Run:
```
ruff check src tests
mypy
PYTHONPATH=src python -m pytest tests/ -o addopts="" -q
```
Expected: ruff All checks passed;mypy Success;pytest 全绿(新增 test_discover + 既有)。

- [ ] **Step 2: 有报错则 inline 修掉后重跑**

- [ ] **Step 3: 提交(若有修改)**

```bash
git add -u
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "chore(w3b1): lint/type 收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**:is_english_only + MULTI_ARCHS(含 qwen3/funasr)+ sensevoice 显式 langs(T1);list --lang/--arch 归一化 + _emit_model_rows 抽取(T2);search + show(T3);docs(T4);验证(T5)。✅
- **候选语义**:`--lang` = 显式 langs OR multilingual;sensevoice 精确不打 flag(T1/T2 测试钉死)。
- **回归**:_emit_model_rows 内容逐字搬移;test_list_no_filter_json_shape 断言字段结构不变。
- **类型一致**:`capabilities.is_english_only(langs)`、`_emit_model_rows(rows, as_json)`、`MULTI_ARCHS` 跨任务一致。

# W3b-1 设计 v2 — 发现(元数据修真 + list --lang/--arch + search)(含 Codex 评审修订)

> 状态:brainstorming + Codex(gpt-5.5)评审(采纳 6 项),待写实现计划。
> 目标波次:W3b 第一刀(W3b = 发现 / 补全 / doctor;本刀"发现")。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";纯数据 + CLI 层,**不动任何 adapter 请求 / 云端 / segments**;零新依赖。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-07T12-07-41*.md`):multilingual 补 qwen3Asr/funasrNano;sensevoice 改用**显式 5 langs**(不打 flag);"byte-identical"改口径为"渲染格式不变、内容修正";`_emit_model_rows((m,inst) rows)` 精确抽取;`--lang`/`--arch` 归一化;`is_english_only` helper。

---

## 1. 背景与目标

专家评估 🟠 A3:元数据失真(omnilingual 标 `["zh","en"]` 实 1600 语;whisper 全系实 ~99 语)→ `list --lang ja` 会漏掉支持日语的模型。**先修数据,再建筛选**。

**目标**:多语模型诚实、紧凑的表示,让 `list --lang X` 有用;加 `--arch`/`search` 驾驭 71 模型。补全/doctor 是后两刀。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 广多语表示 | `capabilities["multilingual"]=True` 标记(不维护巨型列表) |
| D2 | **multilingual 语义** | "**广覆盖候选**":`--lang X` 把它当候选返回(**过度包含但诚实标注**,文档写明"覆盖因模型而异,请核对");不是"必然支持 X" |
| D3 | `--lang X` 命中 | `X(归一) in m.langs(归一)` **OR** `m.capabilities.get("multilingual")` |
| D4 | 标记原则 | 保守;仅**真·广多语**架构进 `MULTI_ARCHS` |
| D5 | 小语集精确 | senseVoice(仅 5 语)用**显式 langs** `["zh","en","ja","ko","yue"]`,**不打 flag**(可精确命中,无过包) |
| D6 | search | 大小写不敏感子串,匹配 `id`+`name` |
| D7 | `--arch` | 仅本地 config_type;云端(空)被筛掉;`.strip().lower()` 比较 |
| D8 | show | 加一行 `multilingual: yes/no` |
| D9 | 不做 | 穷举语言列表、bounded 模型策列语种、search 匹配 langs、模糊/正则、`--lang` 多值 |

---

## 3. 设计

### 3.1 multilingual 标记 + 小修

**广多语架构集**(真·广覆盖,30~1600 语):
```python
MULTI_ARCHS = {"whisper", "dolphin", "omnilingualCtc", "qwen3Asr", "funasrNano"}
```
(Codex 外部核实:Qwen3-ASR 52 语、Fun-ASR-Nano 31 语、Dolphin 40 东方语 —— 都是广多语,原漏标。)

**英语专用判定**(排除 `whisper-*-en`/distil-en —— 它们注册 langs 即 `["en"]`):
- `capabilities.py` 加 `is_english_only(langs) -> bool` = `[l.strip().lower() for l in (langs or [])] == ["en"]`。

**填法**:
- **sherpa**(`models_local.py`):`if ctype in MULTI_ARCHS and not is_english_only(langs): caps["multilingual"] = True`。
- **senseVoice**(sherpa,`ctype == "senseVoice"`):**不打 flag**;把 langs 修为 `["zh","en","ja","ko","yue"]`(精确命中 --lang ja/ko)。(language_hint 仍 "none",W3a 保留。)
- **faster-whisper / whispercpp**:whisper 系,`if not is_english_only(langs): caps["multilingual"] = True`(faster-whisper 的 `distil-large-v3` langs=["en"] 除外)。
- **openai/whisper-1**:显式加 `multilingual: True`。
- **transformers**:不自动标(开放寻址、langs 多空,无法判定;保守)。
- paraformer/zipformer/fireRed/parakeet/moonshine/telespeech **不进** MULTI_ARCHS(Codex 确认:zh/en/yue bounded 或 en-only,靠显式 langs 命中即可)。

### 3.2 `list` 加筛选(`cli.py`)

list 子命令加 `--lang`/`--arch`(与 `--source`/`--installed`/`--json` 叠加 AND):
```python
    lp.add_argument("--lang", default=None, help="only models supporting this language (e.g. ja)")
    lp.add_argument("--arch", default=None, help="only models of this architecture (e.g. senseVoice)")
```
过滤(**归一化输入与元数据**,Codex:避免 `"YUE"`/`"JA "` 漏配):
```python
        if a.lang:
            want = a.lang.strip().lower()
            langs = {x.strip().lower() for x in (m.langs or [])}
            if want not in langs and not (m.capabilities or {}).get("multilingual"):
                continue
        if a.arch and (m.config_type or "").strip().lower() != a.arch.strip().lower():
            continue
```

### 3.3 `search <term>` 新子命令(`cli.py`)

```python
    sp = sub.add_parser("search", help="search models by id/name substring")
    sp.add_argument("term")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
```
处理:`term.strip().lower()` 子串匹配 `(m.id + " " + m.name).lower()`;命中集合走 §3.4 共享渲染。

### 3.4 共享渲染 `_emit_model_rows(rows, as_json)`(精确抽取,Codex Med4)

把 list **现有**的"`rows`(每项 `(m, inst)`)→ 输出"整段抽成一个 CLI 私有函数:
- 输入 `rows: list[(AdapterMeta, inst)]`(`inst` = 本地已装 bool / 云端 None)+ `as_json: bool`。
- `as_json`:构造与**现状逐字相同**的 dict 列表(含 `installed`/`size_bytes` 仅本地),`json.dumps(...)`。
- 人读:与现状逐字相同的行(mark/flag/id/体积列 `store.dir_size`/name)。
- `list` 与 `search` 都:各自过滤/匹配出 `models` → 对每个算 `inst`(`_installed(m) if m.source=="local" else None`)→ 组 `rows` → 调 `_emit_model_rows(rows, as_json)`。
- **保证**:`list`(无 filter)人读/`--json` **格式**逐字不变(只有被修正的元数据内容如 sensevoice langs / 新 `multilingual` 键有别 —— 那是有意的内容修正,非格式变化)。

### 3.5 `show` 顺带

`langs:` 行后加:
```python
    print(f"multilingual: {'yes' if (m.capabilities or {}).get('multilingual') else 'no'}")
```

---

## 4. 契约/行为影响

- **纯增量**:`--lang`/`--arch`/`search` 新增;`list` 无 filter 时**格式**不变。
- 元数据**内容**修正:sensevoice `langs` 补全、广多语模型多 `multilingual` 键 —— 这会改变这些模型在 `--json` 里的内容(**有意**;非回归)。
- 不动 adapter 请求 / 云端 / segments;show 多一行。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/capabilities.py` | 加 `is_english_only(langs)` |
| `asrkit/adapters/models_local.py` | `MULTI_ARCHS` + multilingual;senseVoice langs 修为 5 |
| `asrkit/adapters/local_faster_whisper.py` / `local_whispercpp.py` | whisper 系 multilingual(非 en-only) |
| `asrkit/adapters/cloud_openai.py` | openai/whisper-1 加 multilingual |
| `asrkit/cli.py` | list `--lang`/`--arch`;`search` 子命令;`_emit_model_rows` 抽取;show 加行 |
| `docs/usage.md` / `CHANGELOG.md` | 用法(含 multilingual 候选语义)+ `[Unreleased]` |

---

## 6. 测试(`tests/test_discover.py` 新)

- **元数据**:`local/whisper-tiny`、`omnilingual-300m`、`local/qwen3-asr-0.6b`、`local/funasr-nano`、`faster-whisper/large-v3` 有 `multilingual`;`whisper-tiny-en`、`moonshine-tiny`、`faster-whisper/distil-large-v3` **无**;`local/sensevoice` **无 flag** 但 langs 含 `ja`/`ko`。
- **list --lang**(`cli.main` 捕获 stdout):`list --lang ja --source local` 含 whisper 家族/qwen3/funasr(靠 flag)+ sensevoice(靠显式 langs)、**不含** `whisper-tiny-en`;`list --lang YUE`(大写)命中 sensevoice(归一化)。
- **list --arch**:`list --arch senseVoice` 与 `--arch sensevoice`(大小写)同效、只出该架构。
- **search**:`search whisper --json` 命中所有 id/name 含 whisper 者,JSON 结构与 `list --json` 一致;`search zzz` 空。
- **回归(格式不变)**:`list`(无 filter)与 `list --json` 的**格式/字段结构**与改前一致(可对一个元数据未变的模型如 `paraformer-zh` 断言其行/JSON 逐字未变);`show local/sensevoice` 含 `multilingual: no`(sensevoice 精确、不标 flag)。

---

## 7. 明确不做(YAGNI)

穷举语言列表、bounded 模型策列语种、search 匹配 langs/provider、模糊/正则、`--lang` 多值、shell 补全(W3b-2)、doctor(W3b-3)、transformers 自动 multilingual。

---

## 8. 风险与兼容

- **纯数据 + CLI 层**,不碰 adapter/云端/segments;`_emit_model_rows` 抽取须保 `list` 无-filter **格式**逐字不变(测试对未变元数据的模型钉死)。
- **multilingual = 候选语义**(D2):`--lang fr` 会返回 dolphin 等广多语模型作候选 —— **过度包含但文档诚实标注**(coverage 因模型而异);sensevoice 等小语集用显式 langs 精确、无过包。
- 保守标记:仅 `MULTI_ARCHS` 真·广多语;paraformer 等靠显式 langs。
- 全向后兼容;新增键/子命令/旗标不影响旧调用。

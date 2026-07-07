# W3b-1 设计 — 发现(元数据修真 + list --lang/--arch + search)

> 状态:已通过 brainstorming,待写实现计划。
> 目标波次:W3b 第一刀(W3b = 发现 / 补全 / doctor 三子项目;本刀是"发现")。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";纯数据 + CLI 层,**不动任何 adapter 请求形状 / 云端**;零新运行时依赖。

---

## 1. 背景与目标

专家评估 🟠 A3:**元数据失真** —— omnilingual 标 `["zh","en"]`(实 1600 语)、whisper 全系标 `["zh","en"]`(实 ~99 语)→ 计划中的 `list --lang ja` 会漏掉一堆其实支持日语的模型。**必须先修数据,再建筛选**(顺序不能反)。

**W3b-1 目标**:给多语模型一个诚实、紧凑的表示,让 `list --lang X` 准确;并加 `--arch` 与 `search` 帮用户驾驭 71 个模型。**补全(shell completion)与 doctor 是 W3b 后两刀,本刀不含。**

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 多语表示 | 加 `capabilities["multilingual"]=True` 标记(不维护巨型语言列表);`langs` 保留为"精选主语"供展示 |
| D2 | `--lang X` 命中 | `X in m.langs` **OR** `m.capabilities.get("multilingual")` |
| D3 | 标记原则 | **保守优先(宁漏勿误)**:漏标仍能靠显式 langs 命中;误标会骗人 |
| D4 | search 范围 | 大小写不敏感子串,匹配 `m.id` + `m.name`(不含 langs/provider,避免噪音与和 --lang 重叠) |
| D5 | `--arch` | 仅本地有 config_type;云端无 → 被筛掉;大小写不敏感 |
| D6 | show | 多显示一行 `multilingual: yes/no` |
| D7 | 不做 | 穷举语言列表、search 匹配 langs、模糊/正则、`--lang` 多值 |

---

## 3. 设计

### 3.1 multilingual 标记(按架构/模型驱动,不逐条手编)

**判定规则**:多语架构 **且** 非英语专用检查点(`langs != ["en"]`,这一条自动排除 `whisper-*-en`/`distil-*en` —— 它们注册时 langs 就是 `["en"]`)。

- **sherpa**(`models_local.py`,`MULTI_ARCHS = {"whisper", "senseVoice", "dolphin", "omnilingualCtc"}`):
  ```python
  if ctype in MULTI_ARCHS and langs != ["en"]:
      caps["multilingual"] = True
  ```
  → whisper 多语版、senseVoice、dolphin、omnilingual 标记;`.en`/distil-en 不标;paraformer/zipformer/moonshine/telespeech/firered 等**不进 MULTI_ARCHS**(保守,靠显式 langs 命中)。
- **faster-whisper**(`local_faster_whisper.py`)/ **whispercpp**(`local_whispercpp.py`):whisper 系,`langs != ["en"]` → multilingual(faster-whisper 的 distil-large-v3 langs=["en"] 除外)。
- **openai/whisper-1**(`cloud_openai.py`):显式加 `multilingual: True`(它已有 language_hint/segment_timestamps)。
- **transformers**:开放寻址、langs 多为空 → **不自动标**(无法判定;保守)。
- 顺带修**明显错**:sherpa senseVoice 系 `langs` 由 `["zh","en"(,"yue")]` 修为 `["zh","en","ja","ko","yue"]`(SenseVoice 真实支持;multilingual 标记已覆盖筛选,此为诚实展示)。

> 与 W3a 一致:capabilities 在注册处按架构填,不引入新 AdapterMeta 字段。

### 3.2 `list` 加筛选(`cli.py`)

list 子命令加 `--lang`/`--arch`(与现有 `--source`/`--installed`/`--json` **叠加 AND**):
```python
    lp.add_argument("--lang", default=None, help="only models supporting this language (e.g. ja)")
    lp.add_argument("--arch", default=None, help="only models of this architecture (e.g. senseVoice)")
```
list 处理里,在现有 source/installed 过滤后加:
```python
        if a.lang and not (a.lang in m.langs or (m.capabilities or {}).get("multilingual")):
            continue
        if a.arch and (m.config_type or "").lower() != a.arch.lower():
            continue
```

### 3.3 `search <term>` 新子命令(`cli.py`)

```python
    sp = sub.add_parser("search", help="search models by id/name substring")
    sp.add_argument("term")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
```
处理:`term.lower()` 子串匹配 `(m.id + " " + m.name).lower()`;命中集合复用 list 的行渲染(见 3.4)。

### 3.4 共享渲染(小重构,DRY)

把 list 现有的"rows→输出(人读/`--json`)"抽成一个小助手 `_emit_models(models, as_json)`,`list` 与 `search` 都调它。人读/`--json` 格式与现状完全一致(list 不加 filter 时输出逐字不变)。

### 3.5 `show` 顺带(`cli.py`)

show 输出在 `langs:` 行后加:
```python
    print(f"multilingual: {'yes' if (m.capabilities or {}).get('multilingual') else 'no'}")
```

---

## 4. 契约/行为影响

- **纯增量**:`--lang`/`--arch`/`search` 是新增;不加时 `list` 输出逐字不变。
- `capabilities` 多一个 `multilingual` 键(向后兼容;消费者按需读)。
- 不动任何 adapter 请求 / 云端 / segments;`show` 多一行。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/adapters/models_local.py` | `MULTI_ARCHS` + `multilingual` 按架构;senseVoice langs 修全 |
| `asrkit/adapters/local_faster_whisper.py` | whisper 系 `multilingual`(langs!=["en"]) |
| `asrkit/adapters/local_whispercpp.py` | 同上 |
| `asrkit/adapters/cloud_openai.py` | openai/whisper-1 加 `multilingual` |
| `asrkit/cli.py` | list `--lang`/`--arch`;`search` 子命令;`_emit_models` 共享渲染;show 加 multilingual 行 |
| `docs/usage.md` / `CHANGELOG.md` | 用法 + `[Unreleased]`(版本号等人类定) |

---

## 6. 测试(`tests/test_discover.py` 新)

- **元数据**:`registry.resolve("local/whisper-tiny").capabilities.get("multilingual")` True;`whisper-tiny-en`/`moonshine-tiny` False/缺;`local/sensevoice` multilingual + langs 含 `ja`,`ko`;`omnilingual-300m` multilingual;`faster-whisper/large-v3` multilingual、`faster-whisper/distil-large-v3` 非。
- **list --lang**(用 `cli.main` 捕获 stdout):`list --lang ja --source local` 含 whisper 家族(靠 multilingual)、不含 `whisper-tiny-en`;`list --lang yue` 含 sensevoice/paraformer-trilingual。
- **list --arch**:`list --arch senseVoice` 只出 senseVoice 架构;大小写不敏感(`--arch sensevoice` 同效)。
- **search**:`search whisper --json` 命中所有 id/name 含 whisper 的、结构与 list --json 一致;`search zzz` 空。
- **回归**:`list`(无 filter)与 `list --json` 输出与改前逐字一致;`show local/sensevoice` 含 `multilingual: yes`。

---

## 7. 明确不做(YAGNI)

穷举语言列表、search 匹配 langs/provider、模糊/正则搜索、`--lang` 多值、shell 补全(W3b-2)、doctor(W3b-3)、transformers 自动 multilingual。

---

## 8. 风险与兼容

- **纯数据 + CLI 层**,不碰 adapter 请求/云端/segments —— 回归面小;`_emit_models` 抽取需保证 list 无-filter 输出逐字不变(测试钉死)。
- multilingual **保守标记**:漏标只是 `--lang` 少命中(仍靠显式 langs),不误导;误标才是坏的,故 MULTI_ARCHS 只收明确多语架构。
- 全部向后兼容;新增键/子命令/旗标不影响旧调用。

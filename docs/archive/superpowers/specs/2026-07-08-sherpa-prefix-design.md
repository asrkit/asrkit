# 设计 — 寻址前缀正名 `local/` → `sherpa/`(方案 A,向后兼容)

> 状态:设计已与用户充分讨论并批准(方案 A)、**Codex(gpt-5.5)评审采纳 3 项 + 1 项 defer → v2**,待实现。
>
> **v2 修订**(Codex;确认了 catch-all 单跳无递归、`local/<base>:<tag>` 别名有效、**磁盘兼容 OK**——`store.model_dir` 用 `id.split("/",1)[-1]` 取斜杠后部分,`local/x` 与 `sherpa/x` 同一 `models/x` 目录,已 pull 的权重不用重下):
> 1. **已存在的用户模型**(`~/.asrkit/models.json`,`add-model` 存的 `local/foo`)加载时按原样 id 直接命中 `_MODELS`、不会被 catch-all 规范化,且 `sherpa/foo` 解析不到。→ `_load_user_models` 加载时把 `local/…` 的 id 归一为 `sherpa/…`(catch-all 仍保旧调用可用)。
> 2. **用户模型 vendor** 仍默认 `"local"`(registry.py:176)→ 默认 `"sherpa"`(与内建一致;影响 `show`/`/v1/models` owned_by)。
> 3. **doctor** 把隐式默认引擎报成 `"local"`(doctor.py:113 `or "local"`)→ `"sherpa"`。
> 4. **(defer,不在本刀)** serve adapter 缓存按原始 model 串做 key,`local/x` 与 `sherpa/x` 会各占一槽、双载适配器(server.py:53)。**此为既有问题**(裸名 `sensevoice` 与 `local/sensevoice` 今天就双载),非本次改名引入;按 `meta.id` 归一 key 会动到刚评审过的 serve LRU 且破坏其测试。→ **记为独立后续项**(roadmap/CHANGELOG follow-up),不塞进本契约改名刀。
> 定位约束:**寻址是"项目宪法"之一**(CLAUDE.md R5)。本刀在 0.x 窗口修掉宪法级瑕疵,**但不破坏公开地址**(R6):`local/` 永久保留为别名。**版本口径留发版时人类拍板**(向后兼容,倾向 PATCH;不碰 `__version__`)。

---

## 1. 问题

寻址本已统一为 `<引擎>/模型`(本地)+ `<厂商>/模型`(云):`faster-whisper/tiny`、`whispercpp/base`、`transformers/<hf>`、`openai/whisper-1`……**唯独 sherpa 用 `local/`**(47 个模型)。`local/` 误导(4 个引擎都是本地)、且身兼两角(裸名默认前缀 + sherpa 静态前缀)造成"local=默认"的错觉。正确前缀应为 **`sherpa/`**(与 extra 名 `sherpa` 及其它引擎前缀一致)。

## 2. 方案 A(已批准):规范前缀改 `sherpa/`,`local/` 永久别名

- 规范 id / `asrkit list` / 文档 / 示例统一 `sherpa/<model>`。
- `local/<model>`(含 `local/base:tag`)**永久解析**为对应 `sherpa/<model>`——不破坏存量脚本/配置/已发布 tag/asr_bench 引用(R6)。
- 裸名默认引擎机制**不变**:`sensevoice` → 默认引擎前缀(缺省现在填 `sherpa/`)。
- `source="local"`(本地/云分类字段)**保持不变**——它标"这是本地模型",与 id 前缀是两回事。

## 3. 设计

### 3.1 `adapters/models_local.py`
- sherpa 模型 id:`f"local/{folder}"` → `f"sherpa/{folder}"`(约第 89 行)。
- vendor:`"local"` → `"sherpa"`(约第 91 行)——与其它引擎(vendor=引擎名)一致。**实现者先 grep 确认无消费者对 `vendor=="local"` 做逻辑判断**(预期:仅 `show` 展示、无逻辑依赖;doctor 的云端 vendor 派生只看 `source=="cloud"`)。
- `source` 维持 `"local"`,**不动**。
- 文件头注释里的 `id = "local/<folder>"` / `local/sensevoice:int8` 示例 → `sherpa/`。

### 3.2 `registry.py`
- **catch-all 别名**(`resolve()` 内,比逐个枚举干净):在直接 `_MODELS`/`_ALIASES` 命中之后、裸名处理之前,加:
  ```python
      # 历史别名:local/ 曾是 sherpa 的寻址前缀(≤0.5.3),永久保留、绝不破坏(R6)。
      if model_id.startswith("local/"):
          return resolve("sherpa/" + model_id[len("local/"):])
  ```
  这一条覆盖 `local/sensevoice`、`local/sensevoice:int8`、`local/<base>` 全部形态(strip 后交给 `sherpa/` 的真实 id / base:tag 别名解析)。注意放在直接命中之后,避免影响任何真实 `local/*` id(改名后已无真实 `local/*` id)。
- **`_default_prefix()`**:默认前缀 `"local"` → `"sherpa"`;归一 `eng in ("sherpa-onnx", "local", "sherpa")` → `"sherpa"`(engine 存的是 `sherpa-onnx`,历史配置可能是 `local`,都归 `sherpa`)。
  ```python
      if not eng or eng in ("sherpa-onnx", "local", "sherpa"):
          return "sherpa"
      return eng
  ```
- 模块 docstring 里 `别名:local/<base>...` → 更新为 `sherpa/<base>...`(并注明 `local/` 为历史别名)。
- `_rebuild_aliases()` **无需改**:它用 `m.id.split("/")[0]` 自动取前缀,改名后自动建 `sherpa/base:tag` 别名。
- **`_load_user_models()`(v2 新增)**:加载 `~/.asrkit/models.json` 时归一历史条目——
  ```python
      uid = e["id"]
      if uid.startswith("local/"):
          uid = "sherpa/" + uid[len("local/"):]     # 历史用户模型规范化
      vendor = e.get("vendor", "sherpa")
      if vendor == "local":
          vendor = "sherpa"
      metas.append(AdapterMeta(id=uid, provider=e.get("provider", "sherpa-onnx"),
                               vendor=vendor, ...其余不变...))
  ```
  (磁盘目录 = `uid.split("/")[-1]` = 原 folder,不变;旧 `local/foo` 调用经 catch-all 仍解析到 `sherpa/foo`。)

### 3.2b `doctor.py`(v2)
- 约第 113 行 `... or "local"`(隐式默认引擎显示)→ `... or "sherpa"`。

### 3.3 `cli.py`
- `add-model`(约第 492 行):`mid = a.id if "/" in a.id else "local/" + a.id` → `"sherpa/" + a.id`。
- engine rm 提示语(约第 571 行)`"... (local/sherpa)"` 里的 `local/sherpa` → `sherpa`(纯文案,顺手)。

### 3.4 文档 + CHANGELOG
- 全文档 `local/<model>` 示例 → `sherpa/<model>`(README×2、usage、project-overview、model-management、engines-and-addressing、adapter-spec、result-contract 等);**每处首次出现补一句**"`local/` 作为历史别名仍可用"。
- `CHANGELOG.md` `[Unreleased]` 记:**寻址正名**——sherpa 模型规范前缀 `local/` → `sherpa/`(与其它引擎一致);`local/` 永久保留为别名,**向后兼容不破坏**。

## 4. 契约/行为影响

- **向后兼容**:所有旧 `local/*` 地址仍解析(catch-all 别名);裸名默认机制不变。
- 规范前缀变了(`asrkit list`/`show`/文档显示 `sherpa/`)——面向新用户的推荐地址变,但旧地址不失效。
- 版本:向后兼容 → 倾向 PATCH;是否当"寻址定型里程碑"升 MINOR,发版时人类定。**本刀不碰 `__version__`。**

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/adapters/models_local.py` | id/vendor `local`→`sherpa`;注释示例 |
| `src/asrkit/registry.py` | `local/`→`sherpa/` catch-all 别名;`_default_prefix` 归一 sherpa;`_load_user_models` 归一 id/vendor;docstring |
| `src/asrkit/cli.py` | `add-model` 前缀;engine rm 文案 |
| `src/asrkit/doctor.py` | 默认引擎显示 `local`→`sherpa` |
| `tests/*`(~13 文件引用 local/) | `local/`→`sherpa/`;**新增回归**:`local/` 别名仍解析 |
| 文档(~10) + CHANGELOG | 示例改 `sherpa/` + 别名说明 + `[Unreleased]` |

## 6. 测试

- **规范前缀**:`resolve("sherpa/sensevoice")` 命中;`api.list_models()` 里 sherpa 模型 id 以 `sherpa/` 开头、无 `local/` 开头。
- **历史别名(关键回归)**:`resolve("local/sensevoice")` 与 `resolve("sherpa/sensevoice")` **返回同一 meta**;`resolve("local/sensevoice:int8")`、`resolve("local/<base>")` 均解析;`make_adapter("local/sensevoice")` 成功。
- **裸名默认**:`resolve("sensevoice")` 解析到 `sherpa/sensevoice`(默认引擎缺省)。
- **default-engine 归一**:`_default_prefix()` 在 eng 为 None/"sherpa-onnx"/"local"/"sherpa" 时都返回 `"sherpa"`;为 "faster-whisper" 时返回 "faster-whisper"。
- **add-model**:`add-model foo --arch senseVoice`(裸 id)→ 注册 id 为 `sherpa/foo`(非 `local/foo`);带 `/` 的 id 原样。
- **历史用户模型归一(v2)**:构造一个 `models.json` 里 id=`local/foo`、vendor 缺省的条目(monkeypatch `usermodels.load`),断言加载后 `resolve("sherpa/foo")` 命中、其 `vendor=="sherpa"`;`resolve("local/foo")` 经 catch-all 仍命中同一 meta。
- **doctor 默认引擎显示(v2)**:无 config 时 doctor 的默认引擎项显示 `sherpa`(不再 `local`)。
- **其它引擎不受影响**:`faster-whisper/tiny`、`whispercpp/base`、`transformers/<hf>`、云端寻址回归全绿。
- **全量**:现有测试改 `local/`→`sherpa/` 后全绿 + 新回归;ruff+mypy。

## 7. 不做(YAGNI)

- 不删 `local/` 别名(R6,永久保留)。
- 不改 `source` 字段。
- 不动 `__version__`(发版时人类定)。
- 不改其它引擎前缀(已一致)。

## 8. 风险

- catch-all `local/`→`sherpa/` 必须放在真实 id 命中**之后**、且改名后确无真实 `local/*` id(避免无限递归:`local/x`→`sherpa/x`,`sherpa/x` 不再 startswith `local/`,单跳,安全)。
- vendor 改动:确认无逻辑消费者(见 3.1)。
- 文档量大但机械;历史快照文档(expert-review 等)**不改**(带时点,提到 local/ 是当时事实)。

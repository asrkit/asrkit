# 设计 — `asrkit engine rm`(劝告版)

> 状态:brainstorming 完成、用户批准(P4 唯一入选项),小而自包含 → 直接实现(跳过 Codex:无计费/并发/契约面)。
> 定位约束:引擎是**共享 pip 包**,asrkit 无产权 → **绝不代跑 `pip uninstall`**;只打印手动卸载指引 + 共享依赖警告 + 若默认引擎指向它则重置。补全命令面而不越权(所有权模型见 roadmap)。

---

## 1. 背景

roadmap P4:`engine install` 有了(帮装对 extra),但没有对称的 `rm`。用户想"拔掉一个引擎"时无处下手。**但引擎是共享 pip 包**(别的项目可能在用),asrkit 代跑卸载会连累它们。故做**劝告版**:告诉用户怎么卸,不替他卸。

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 是否代跑卸载 | **绝不**;只打印 `pip uninstall <pkg>` 指引 |
| D2 | 依赖警告 | 提示主包的依赖(numpy/torch/onnxruntime 等)可能被别的项目共享,让用户自行判断 |
| D3 | 默认引擎联动 | 若 config 默认引擎 == 被移除者 → 重置为空(解析回落 local/sherpa),并提示 |
| D4 | 未装/未知引擎 | 未知 → 报错退 1;未装 → info "nothing to remove" 退 0(仍执行 D3 联动) |
| D5 | 不做 | 真卸载、隔离环境、`engine disable` 开关(YAGNI,roadmap 已定案不做) |

## 3. 设计

### 3.1 `engines.py`(新增主发行包映射 + helper)

```python
# 引擎主 pip 发行包名(供 engine rm 劝告卸载;真卸载归用户)。
# 注意:import 模块名 ≠ 发行包名(如 pywhispercpp 模块名 vs 包名一致,sherpa_onnx→sherpa-onnx)。
_PIP_PACKAGE = {
    "sherpa-onnx": "sherpa-onnx",
    "faster-whisper": "faster-whisper",
    "transformers": "transformers",
    "whispercpp": "pywhispercpp",
}


def pip_package(name: str):
    """引擎的主 pip 发行包名(用于 engine rm 劝告);未知引擎返回 None。"""
    return _PIP_PACKAGE.get(name)
```

### 3.2 `cli.py`(`engine` 子命令加 `rm`)

解析器(挂在现有 `esub`,`default` 之后):
```python
    er = esub.add_parser("rm", help="show how to remove an engine (advisory; never uninstalls)")
    er.add_argument("name")
```

处理(`engine` 分支内,`default` 处理之后):
```python
        if a.ecmd == "rm":
            from . import config
            if a.name not in engines.ENGINES:
                print(f"[error] unknown engine '{a.name}' (see: asrkit engine list)", file=sys.stderr)
                return 1
            if not engines.is_installed(a.name):
                print(f"engine '{a.name}' is not installed; nothing to remove")
            else:
                pkg = engines.pip_package(a.name) or a.name
                print("asrkit does not uninstall engines — they are shared pip packages "
                      "other projects may depend on.")
                print(f"To remove '{a.name}' yourself, run:")
                print(f"    pip uninstall {pkg}")
                print("Its dependencies (e.g. numpy / torch / onnxruntime) may be shared; "
                      "uninstall only what you are sure nothing else needs.")
            if config.get_default("engine") == a.name:
                config.set_default("engine", "")
                print(f"note: default engine was '{a.name}'; reset to built-in default (local/sherpa). "
                      "Set another with: asrkit engine default <name>")
            return 0
```

- 英文输出(i18n);仅打印,不 import subprocess、不跑 pip。
- 默认引擎重置为 `""` → `registry._default_prefix()` 因 `not eng` 回落 `"local"`(已核实)。

## 4. 契约/行为影响

- 纯增量:新 `engine rm` 子命令 + `engines.pip_package`;不动 install/list/default/其它。无新依赖。

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/engines.py` | 加 `_PIP_PACKAGE` + `pip_package()` |
| `src/asrkit/cli.py` | `engine rm` 子解析器 + 处理分支 |
| `tests/test_engine_rm.py` | 新建 |
| `docs/usage.md` / `CHANGELOG.md` | 用法 + `[Unreleased]` |

## 6. 测试

- **pip_package 映射**:`pip_package("whispercpp")=="pywhispercpp"`;未知→None。
- **未知引擎**:`cli.main(["engine","rm","nope"])` → 退 1、stderr 有 unknown。
- **已装引擎**:`monkeypatch engines.is_installed`→True;`capsys` 断言 stdout 有 `pip uninstall <pkg>` 且**无**真卸载(rm 不 import subprocess);退 0。
- **未装引擎**:`is_installed`→False;stdout "not installed; nothing to remove";退 0。
- **默认引擎联动**:`monkeypatch config.get_default`→返回该引擎名、`config.set_default` 记录调用;断言以 `("engine","")` 调用、stdout 有 "reset";反例:默认非该引擎 → 不重置。
- **回归**:engine list/install/default 不受影响。

## 7. 不做(YAGNI)

真卸载、隔离环境、`engine disable`、逐依赖分析谁在用。

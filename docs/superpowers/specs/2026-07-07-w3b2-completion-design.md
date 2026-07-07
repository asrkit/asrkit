# W3b-2 设计 — shell 补全(bash/zsh/fish)

> 状态:已通过 brainstorming,待写实现计划。
> 目标波次:W3b 第二刀(补全)。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";**零新运行时依赖**(不用 argcomplete);纯 CLI 层。

---

## 1. 背景与目标

71 个模型 + 一串子命令,model 名尤其冗长——shell 补全是高 ROI 体验提升(lifecycle-audit 提过)。约束下(零依赖)走 Ollama/gh 的路子:`asrkit completion <shell>` 吐一段静态脚本,用户自行安装。

**目标**:`asrkit completion bash|zsh|fish` 输出可用的补全脚本,能补**子命令 + model 名(动态)+ `-f` 格式值**。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 机制 | `asrkit completion <shell>` 吐**静态脚本**;零依赖 |
| D2 | 动态 model 源 | 加 `asrkit list --ids`:每行一个**裸 model id**(无 emoji/表头),补全脚本调它 |
| D3 | 范围 | 子命令 + model 名(pull/rm/show/run/`transcribe -m`)+ `-f/--format` 值;engine/config 的二级子命令名。**不穷举**每个 --flag |
| D4 | shell | bash / zsh / fish |
| D5 | 不做 | argcomplete、穷举 flag 补全、config vendor/engine 名补全、PowerShell |

---

## 3. 设计

### 3.1 `asrkit/completion.py`(新)

- `SCRIPTS: dict[str, str]` —— `"bash"`/`"zsh"`/`"fish"` 三段静态补全脚本(完整脚本见实现计划)。
- `script_for(shell: str) -> str` —— 返回对应脚本;未知 shell 抛 `ValueError`(CLI 映射为友好报错)。

**各脚本补全内容**(一致):
- 第 1 位:子命令(list/show/pull/rm/run/transcribe/add-model/engine/config/serve/search/completion)。
- `pull`/`rm`/`show`/`run`(首位置)、`transcribe` 的 `-m/--model` 值:调 `asrkit list --ids 2>/dev/null` 的 id。
- `-f`/`--format` 值:`txt json srt vtt csv tsv`。
- `completion` 的参数:`bash zsh fish`;`engine`:`list install default`;`config`:`set-key get-key set list path`。

### 3.2 `cli.py`

- **`completion` 子命令**:`asrkit completion {bash,zsh,fish}` → `print(completion.script_for(a.shell))`;未知 shell(argparse `choices` 限定,不会到)。
- **`list --ids`**:list 子命令加 `--ids`(store_true);list 处理里**构造 rows 后**,若 `a.ids`:逐行 `print(m.id)`、`return 0`(在 `_emit_model_rows` 之前;与 `--source`/`--lang`/`--arch` 过滤叠加)。

### 3.3 安装说明(docs)

- bash:`asrkit completion bash > /etc/bash_completion.d/asrkit`(或 `source <(asrkit completion bash)`)。
- zsh:`asrkit completion zsh > "${fpath[1]}/_asrkit"`(或 source)。
- fish:`asrkit completion fish > ~/.config/fish/completions/asrkit.fish`。

---

## 4. 契约/行为影响

- **纯增量**:`completion` 子命令、`list --ids` 均新增;不影响旧命令。
- 补全脚本靠调 `asrkit list --ids` 动态取 model —— 安装了新模型即时可补,无需重装补全。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/completion.py` | **新增**:`SCRIPTS` 三脚本 + `script_for(shell)` |
| `asrkit/cli.py` | `completion` 子命令;`list --ids` |
| `tests/test_completion.py` | **新增** |
| `docs/usage.md` / `CHANGELOG.md` | 安装说明 + `[Unreleased]` |

---

## 6. 测试

- **`list --ids`**:`cli.main(["list","--ids"])` 捕获 stdout → 每行一个 id、含 `local/sensevoice` 与 `openai/whisper-1`、**不含** emoji(☁️/💻)与体积列;`list --ids --source cloud` 只出云端 id。
- **`completion`**:`cli.main(["completion","bash"])`/`zsh`/`fish` 各输出非空,且含关键 token(如 `asrkit list --ids`、`transcribe`、`-f`/`--format` 或 `format`);未知 shell → argparse 报错(退出码 2)。
- **`script_for`**:`completion.script_for("bash")` 非空;`script_for("tcsh")` 抛 `ValueError`。
- **回归**:`list`(无 `--ids`)输出与改前一致。

---

## 7. 明确不做(YAGNI)

argcomplete、穷举每个 --flag 补全、config vendor / engine 名值补全、PowerShell、补全脚本内缓存 model 列表(每次调 list --ids,足够快)。

---

## 8. 风险与兼容

- **纯 CLI 层**,不碰 adapter/云端;回归面小(`list --ids` 是短路,不动既有渲染)。
- 补全脚本正确性靠 `test_completion` 断言关键 token + 人工在三 shell 冒烟(脚本逻辑简单:子命令表 + 调 list --ids)。
- 全向后兼容。

# W3b-2 设计 v2 — shell 补全(bash/zsh/fish)(含 Codex 评审修订)

> 状态:brainstorming + Codex(gpt-5.5)评审 draft 脚本(采纳 7 项),待写实现计划。
> 目标波次:W3b 第二刀(补全)。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";**零新运行时依赖**(不用 argcomplete);纯 CLI 层。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-07T13-05-49*.md`):zsh 改**双模**(source 时 `compdef` 注册,否则 autoload 调用);model 补全**限位置**(run/pull/rm/show 只在首参数位;run 后续位回退文件);fish 去全局 `-f`(改按行)、补 `-m`、补 engine/config 二级;`list --ids` 懒算 inst;测试加 `bash -n`/`zsh -n`/`fish -n` 语法检查 + bash 行为冒烟。

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
- **model id(限位置)**:`pull`/`rm`/`show`/`run` 的**首参数位**(bash `COMP_CWORD==2` / zsh `CURRENT==3` / fish 按 token 数),以及 `transcribe` 的 `-m/--model` 值 → 调 `asrkit list --ids 2>/dev/null`。**run 的后续位(audio)回退文件名补全**(bash `-o default`、zsh `_files`、fish 不禁文件)。
- `-f`/`--format`(含短 `-m`)值:`txt json srt vtt csv tsv`。
- `completion` 参数 `bash zsh fish`;`engine`:`list install default`;`config`:`set-key get-key set list path`(三 shell 一致)。
- **zsh 双模**:`#compdef asrkit` 头 + 函数;末尾判 `funcstack` —— autoload 时调用函数、被 `source` 时 `compdef _asrkit asrkit` 注册(否则 source 安装失效)。
- **fish 不全局 `-f`**:仅在子命令/model/枚举等该禁文件的行加 `-f`,留出音频文件名补全。

### 3.2 `cli.py`

- **`completion` 子命令**:`asrkit completion {bash,zsh,fish}` → `print(completion.script_for(a.shell))`;未知 shell(argparse `choices` 限定,不会到)。
- **`list --ids`**:list 子命令加 `--ids`(store_true);若 `a.ids`:逐行 `print(m.id)`、`return 0`(在 `_emit_model_rows` 之前;与 `--source`/`--lang`/`--arch` 过滤叠加)。**懒算 inst**:仅当 `a.installed`(或非 `--ids`)才调 `_installed(m)`——避免补全每次 TAB 对 71 模型做文件系统检查。

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
- **`completion`**:`cli.main(["completion","bash"])`/`zsh`/`fish` 各输出非空,且含关键 token(如 `asrkit list --ids`、`transcribe`、`compdef`/`__fish_use_subcommand`);未知 shell → argparse 报错(退出码 2)。
- **语法检查(Codex:token 测试抓不到坏脚本)**:把发出的脚本写临时文件,`bash -n` / `zsh -n` / `fish -n` 校验语法(对应 shell 不存在则 `pytest.skip`)。
- **bash 行为冒烟**:source 发出的 bash 脚本,伪造 `asrkit`(PATH 里放桩输出 ids),设 `COMP_WORDS`/`COMP_CWORD`,断言 `transcribe -m <TAB>` 给出 model id、`run <model> <audio-pos>` 不给 model id(回退文件)。(此测若嫌重可标可选;语法检查为必须。)
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

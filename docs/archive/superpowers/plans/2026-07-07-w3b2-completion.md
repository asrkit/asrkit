# W3b-2 shell 补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `asrkit completion <bash|zsh|fish>` 输出静态补全脚本(补子命令 + 动态 model 名 + `-f` 值),并加 `asrkit list --ids`。

**Architecture:** 新 `completion.py` 存三段修正过的 shell 脚本 + `script_for`;`cli.py` 加 `completion` 子命令与 `list --ids`(懒算 inst)。零新依赖。

**Tech Stack:** Python 3.9+;pytest;`bash -n`/`zsh -n`/`fish -n` 语法校验(shell 缺则 skip)。

## Global Constraints

- 版本号**不动**(`__version__` 保持 `0.5.2`);发版由人类定。
- **零新增运行时依赖**(不用 argcomplete)。
- 终端/帮助**英文**;注释**中文**。
- **model 补全限位置**:`pull`/`rm`/`show`/`run` 首参数位、`transcribe -m` 值;**run 后续位(audio)回退文件名补全**(bash `-o default`、zsh `_files`、fish 不全局禁文件)。
- **zsh 双模**:`#compdef` 头 + 函数;末尾判 `funcstack` —— autoload 调用函数、`source` 时 `compdef _asrkit asrkit`。
- **fish 不全局 `-f`**:仅在子命令/model/枚举行加 `-f`,留出音频文件名补全;补 `-s m`、engine/config 二级。
- 补全脚本靠 `asrkit list --ids`(裸 id 一行一个)动态取 model;`list --ids` **懒算 inst**(仅 `--installed` 或非 `--ids` 时才 `_installed`)。
- 提交 `git -c user.name="BolynWang" -c user.email="1710998763@qq.com"`,**显式 `git add`**,不 push。
- **测试** `PYTHONPATH=src python -m pytest ... -o addopts=""`。
- 契约见历史 spec：[`../specs/2026-07-07-w3b2-completion-design.md`](../specs/2026-07-07-w3b2-completion-design.md)。

---

## File Structure

- **Create** `src/asrkit/completion.py` — `SCRIPTS`(bash/zsh/fish)+ `script_for(shell)`。
- **Modify** `src/asrkit/cli.py` — `completion` 子命令;`list --ids`(懒算 inst)。
- **Create** `tests/test_completion.py`。
- **Modify** `docs/usage.md`、`CHANGELOG.md`。

---

## Task 1: `list --ids`(裸 id + 懒算 inst)

**Files:**
- Modify: `src/asrkit/cli.py`
- Test: `tests/test_completion.py`

**Interfaces:**
- Produces: `asrkit list --ids` 打印裸 model id(一行一个,过滤后),`--installed` 才算 inst。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_completion.py
from asrkit import cli


def _run(args, capsys):
    rc = cli.main(args)
    return rc, capsys.readouterr().out


def test_list_ids_bare(capsys):
    _, out = _run(["list", "--ids"], capsys)
    lines = [x for x in out.splitlines() if x.strip()]
    assert "local/sensevoice" in lines and "openai/whisper-1" in lines
    assert all("☁️" not in x and "💻" not in x for x in lines)   # 无 emoji
    assert all(" " not in x.strip() for x in lines)               # 裸 id,无体积/名字列


def test_list_ids_respects_source(capsys):
    _, out = _run(["list", "--ids", "--source", "cloud"], capsys)
    ids = {x.strip() for x in out.splitlines() if x.strip()}
    assert "openai/whisper-1" in ids and "local/sensevoice" not in ids
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_completion.py -o addopts="" -v`
Expected: FAIL(argparse: unrecognized `--ids`)

- [ ] **Step 3: 实现**

先读当前 `cli.py` 的 `list` 子命令与 `if a.cmd == "list":` 块。
(a) list 子命令加:`lp.add_argument("--ids", action="store_true", help="print bare model ids (one per line, for scripts/completion)")`。
(b) 把 list 处理块改为(懒算 inst + `--ids` 短路;保留 W3b-1 的 --lang/--arch 过滤):
```python
    if a.cmd == "list":
        rows = []
        for m in api.list_models():
            if a.source and m.source != a.source:
                continue
            if a.lang:
                want = a.lang.strip().lower()
                langs = {x.strip().lower() for x in (m.langs or [])}
                if want not in langs and not (m.capabilities or {}).get("multilingual"):
                    continue
            if a.arch and (m.config_type or "").strip().lower() != a.arch.strip().lower():
                continue
            inst = None
            if a.installed or not a.ids:                 # 懒算:补全时不做 71 次文件系统检查
                inst = _installed(m) if m.source == "local" else None
            if a.installed and not inst:
                continue
            if a.ids:
                print(m.id)
                continue
            rows.append((m, inst))
        if a.ids:
            return 0
        return _emit_model_rows(rows, a.json)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `PYTHONPATH=src python -m pytest tests/ -o addopts="" -q`
Expected: PASS(list 无 --ids 输出不变)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/cli.py tests/test_completion.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(cli): list --ids(裸 id,懒算 inst)"
```

---

## Task 2: `completion.py` + `completion` 子命令

**Files:**
- Create: `src/asrkit/completion.py`
- Modify: `src/asrkit/cli.py`
- Test: `tests/test_completion.py`

**Interfaces:**
- Consumes: `list --ids`(Task 1)。
- Produces: `completion.script_for(shell)->str`;`asrkit completion <bash|zsh|fish>`。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_completion.py`)**

```python
import shutil
import subprocess

import pytest


def test_completion_tokens(capsys):
    for shell, tok in [("bash", "list --ids"), ("zsh", "compdef"), ("fish", "__fish_use_subcommand")]:
        _, out = _run(["completion", shell], capsys)
        assert out.strip() and tok in out


def test_completion_unknown_shell(capsys):
    with pytest.raises(SystemExit):          # argparse choices → SystemExit(2)
        cli.main(["completion", "tcsh"])


def test_script_for():
    from asrkit import completion
    assert completion.script_for("bash")
    with pytest.raises(ValueError):
        completion.script_for("tcsh")


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_syntax(shell, capsys, tmp_path):
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    _, out = _run(["completion", shell], capsys)
    p = tmp_path / f"c.{shell}"
    p.write_text(out)
    r = subprocess.run([shell, "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_completion.py -k "completion or script_for or syntax" -o addopts="" -v`
Expected: FAIL(无 completion 子命令 / 无 asrkit.completion 模块)

- [ ] **Step 3: 实现**

创建 `src/asrkit/completion.py`(脚本为 Codex 评审修订版;用 Python 三引号原样存,**勿改脚本内容**):
```python
"""shell 补全脚本生成:asrkit completion <bash|zsh|fish>。零依赖静态脚本。

脚本靠 `asrkit list --ids` 动态补 model 名;model 补全限位置(run 后续位回退文件)。
zsh 双模:autoload 调用函数、被 source 时用 compdef 注册。
"""
from __future__ import annotations

_BASH = """_asrkit_complete() {
    local cur prev sub cmds
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds="list show pull rm run transcribe add-model engine config serve search completion"
    if [ "${COMP_CWORD}" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return
    fi
    sub="${COMP_WORDS[1]}"
    case "${prev}" in
        -f|--format)
            COMPREPLY=( $(compgen -W "txt json srt vtt csv tsv" -- "${cur}") ); return ;;
        -m|--model)
            COMPREPLY=( $(compgen -W "$(asrkit list --ids 2>/dev/null)" -- "${cur}") ); return ;;
    esac
    if [ "${COMP_CWORD}" -eq 2 ]; then
        case "${sub}" in
            pull|rm|show|run)
                COMPREPLY=( $(compgen -W "$(asrkit list --ids 2>/dev/null)" -- "${cur}") ); return ;;
            completion)
                COMPREPLY=( $(compgen -W "bash zsh fish" -- "${cur}") ); return ;;
            engine)
                COMPREPLY=( $(compgen -W "list install default" -- "${cur}") ); return ;;
            config)
                COMPREPLY=( $(compgen -W "set-key get-key set list path" -- "${cur}") ); return ;;
        esac
    fi
}
complete -o default -F _asrkit_complete asrkit
"""

_ZSH = """#compdef asrkit
_asrkit() {
    local -a cmds
    cmds=(list show pull rm run transcribe add-model engine config serve search completion)
    if (( CURRENT == 2 )); then
        compadd -- ${cmds}
        return
    fi
    local sub=${words[2]}
    case ${words[CURRENT-1]} in
        -f|--format) compadd -- txt json srt vtt csv tsv; return ;;
        -m|--model) compadd -- ${(f)"$(asrkit list --ids 2>/dev/null)"}; return ;;
    esac
    if (( CURRENT == 3 )); then
        case ${sub} in
            pull|rm|show|run) compadd -- ${(f)"$(asrkit list --ids 2>/dev/null)"}; return ;;
            completion) compadd -- bash zsh fish; return ;;
            engine) compadd -- list install default; return ;;
            config) compadd -- set-key get-key set list path; return ;;
        esac
    fi
    _files
}
if [[ ${funcstack[1]} == _asrkit ]]; then
    _asrkit "$@"
else
    compdef _asrkit asrkit
fi
"""

_FISH = """# asrkit fish completion
complete -c asrkit -f -n __fish_use_subcommand -a 'list show pull rm run transcribe add-model engine config serve search completion'
complete -c asrkit -f -n '__fish_seen_subcommand_from pull rm show' -a '(asrkit list --ids 2>/dev/null)'
complete -c asrkit -f -n '__fish_seen_subcommand_from run; and test (count (commandline -opc)) -le 2' -a '(asrkit list --ids 2>/dev/null)'
complete -c asrkit -f -n '__fish_seen_subcommand_from transcribe' -s m -l model -x -a '(asrkit list --ids 2>/dev/null)'
complete -c asrkit -f -s f -l format -x -a 'txt json srt vtt csv tsv'
complete -c asrkit -f -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'
complete -c asrkit -f -n '__fish_seen_subcommand_from engine' -a 'list install default'
complete -c asrkit -f -n '__fish_seen_subcommand_from config' -a 'set-key get-key set list path'
"""

SCRIPTS = {"bash": _BASH, "zsh": _ZSH, "fish": _FISH}


def script_for(shell: str) -> str:
    try:
        return SCRIPTS[shell]
    except KeyError:
        raise ValueError(f"unsupported shell '{shell}' (choose from bash, zsh, fish)")
```

`cli.py`:加 `completion` 子命令(在 list 附近):
```python
    cmp = sub.add_parser("completion", help="print a shell completion script")
    cmp.add_argument("shell", choices=("bash", "zsh", "fish"))
```
加处理块(放在 `if a.cmd == "list":` 之后):
```python
    if a.cmd == "completion":
        from . import completion
        print(completion.script_for(a.shell))
        return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_completion.py -o addopts="" -v`
Expected: PASS(含本机装了的 shell 的 `-n` 语法检查)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/completion.py src/asrkit/cli.py tests/test_completion.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(completion): asrkit completion <bash|zsh|fish>(限位置 model 补全,zsh 双模)"
```

---

## Task 3: 文档(usage + CHANGELOG)

**Files:**
- Modify: `docs/usage.md`、`CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/usage.md`**

加"shell 补全"小节:
- bash:`asrkit completion bash | sudo tee /etc/bash_completion.d/asrkit`(或 `source <(asrkit completion bash)`)。
- zsh:`asrkit completion zsh > "${fpath[1]}/_asrkit"`(放 fpath 里,重开 shell);或 `source <(asrkit completion zsh)`(本 shell 立即生效)。
- fish:`asrkit completion fish > ~/.config/fish/completions/asrkit.fish`。
- 说明:补全靠 `asrkit list --ids` 动态取 model 名,装了新模型即时可补。

- [ ] **Step 2: 追加 `CHANGELOG.md` 的 `[Unreleased]`(不改版本号)**

`### 新增` 里加:
```markdown
- **shell 补全**:`asrkit completion <bash|zsh|fish>` 输出补全脚本(补子命令 + 动态 model 名 + 格式值);配套 `asrkit list --ids`(裸 id,一行一个)。
```

- [ ] **Step 3: 提交**

```bash
git add docs/usage.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "docs(w3b2): shell 补全安装说明 + CHANGELOG"
```

---

## Task 4: 收尾验证(ruff/mypy/全量)

**Files:** 无

- [ ] **Step 1: lint + 类型 + 全量**

Run:
```
ruff check src tests
mypy
PYTHONPATH=src python -m pytest tests/ -o addopts="" -q
```
Expected: ruff All checks passed;mypy Success;pytest 全绿(shell 缺的 `-n` 测试 skip)。

- [ ] **Step 2: 有报错则 inline 修掉后重跑**

- [ ] **Step 3: 提交(若有修改)**

```bash
git add -u
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "chore(w3b2): lint/type 收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**:list --ids 懒算 inst(T1);completion.py 三脚本(限位置/zsh 双模/fish 去全局 -f + -m + engine/config)+ 子命令(T2);docs(T3);验证(T4)。✅
- **Codex 修订全含**:zsh `funcstack` 双模、bash `COMP_CWORD==2` + `-o default`、zsh `CURRENT==3` + `_files`、fish run 位置(`count ... -le 2`)、fish `-s m`、engine/config 二级、语法 `-n` 测试。
- **类型一致**:`completion.script_for(shell)`、`SCRIPTS`、`list --ids` 跨任务一致。
- **测试真实性**:除 token 断言外,加 `bash/zsh/fish -n` 语法校验(Codex:token 测试抓不到坏脚本)。

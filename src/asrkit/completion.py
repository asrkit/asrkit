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

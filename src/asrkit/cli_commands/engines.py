"""Engine management CLI command."""
from __future__ import annotations

import subprocess
import sys


def add_parsers(sub) -> None:
    ep = sub.add_parser("engine", help="manage ASR engines (backends)")
    ep.set_defaults(_parser=ep)
    esub = ep.add_subparsers(dest="ecmd")
    esub.add_parser("list", help="list engines and install status")
    ei = esub.add_parser("install", help="install an optional engine via pip")
    ei.add_argument("name")
    ed = esub.add_parser("default", help="set the default engine (bare names resolve to it)")
    ed.add_argument("name")
    er = esub.add_parser("rm", help="show how to remove an engine (advisory; never uninstalls)")
    er.add_argument("name")


def handle(a) -> int:
    from .. import engines

    if a.ecmd == "list":
        for name, (_mod, extra) in engines.ENGINES.items():
            inst = engines.is_installed(name)
            where = "built-in" if extra is None else f"extra: asrkit[{extra}]"
            status = "installed" if inst else "not installed"
            print(f"{'✓' if inst else ' '} {name:16s} {status:14s} {where}")
        return 0
    if a.ecmd == "install":
        extra = engines.extra_of(a.name)
        if extra is None:
            print(f"[error] unknown engine '{a.name}' (see: asrkit engine list)", file=sys.stderr)
            return 1
        cmd = [sys.executable, "-m", "pip", "install", f"asrkit[{extra}]"]
        print("running:", " ".join(cmd))
        return subprocess.call(cmd)
    if a.ecmd == "default":
        from .. import config

        if a.name not in engines.ENGINES:
            print(f"[error] unknown engine '{a.name}' (see: asrkit engine list)", file=sys.stderr)
            return 1
        config.set_default("engine", a.name)
        print(f"✓ default engine → {a.name} (bare model names now resolve to it)")
        return 0
    if a.ecmd == "rm":
        from .. import config

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
            print(f"note: default engine was '{a.name}'; reset to built-in default (sherpa). "
                  "Set another with: asrkit engine default <name>")
        return 0
    a._parser.print_help()
    return 0

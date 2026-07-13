"""Model, completion, and custom-model CLI commands."""
from __future__ import annotations

import os
import sys

from .shared import emit_model_rows, installed


def add_parsers(sub) -> None:
    lp = sub.add_parser("list", help="list models (✓ = installed)")
    lp.add_argument("--json", action="store_true", help="machine-readable output")
    lp.add_argument("--installed", action="store_true", help="only installed local models")
    lp.add_argument("--ids", action="store_true", help="print bare model ids (one per line, for scripts/completion)")
    lp.add_argument("--source", default=None, choices=("cloud", "local"), help="filter by source")
    lp.add_argument("--lang", default=None, help="only models supporting this language (e.g. ja)")
    lp.add_argument("--arch", default=None, help="only models of this architecture (e.g. senseVoice)")

    cmp = sub.add_parser("completion", help="print a shell completion script")
    cmp.add_argument("shell", choices=("bash", "zsh", "fish"))

    sp = sub.add_parser("search", help="search models by id/name substring")
    sp.add_argument("term")
    sp.add_argument("--json", action="store_true", help="machine-readable output")

    sh = sub.add_parser("show", help="show model details")
    sh.add_argument("model")

    pp = sub.add_parser("pull", help="download a local model")
    pp.add_argument("model")
    pp.add_argument("--url", default=None,
                    help="download from this URL instead of the model's default (http/https)")

    rmp = sub.add_parser("rm", help="remove a downloaded local model")
    rmp.add_argument("model")


def add_model_parser(sub) -> None:
    am = sub.add_parser("add-model", help="register a custom (sherpa) model — no file editing")
    am.add_argument("id")
    am.add_argument("--url", default=None,
                    help="download URL (.tar.bz2/.gz/.xz or .zip; format detected by content)")
    am.add_argument("--arch", required=True,
                    help="config_type / architecture (e.g. senseVoice, whisper, offlineTransducer)")
    am.add_argument("--langs", default="", help="comma-separated, e.g. zh,en")
    am.add_argument("--name", default=None)
    am.add_argument("--provider", default="sherpa-onnx")
    am.add_argument("--streaming", action="store_true")
    am.add_argument("--sha256", default=None)
    am.add_argument("--model-dir", default=None,
                    help="use already-downloaded files (symlinked into place)")


def handle(a) -> int:
    if a.cmd == "list":
        return _list(a)
    if a.cmd == "completion":
        return _completion(a)
    if a.cmd == "search":
        return _search(a)
    if a.cmd == "show":
        return _show(a)
    if a.cmd == "pull":
        return _pull(a)
    if a.cmd == "rm":
        return _rm(a)
    if a.cmd == "add-model":
        return _add_model(a)
    return 0


def _list(a) -> int:
    rows = []
    for m in a._api.list_models():
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
            inst = installed(m) if m.source == "local" else None
        if a.installed and not inst:
            continue
        if a.ids:
            print(m.id)
            continue
        rows.append((m, inst))
    if a.ids:
        return 0
    return emit_model_rows(rows, a.json)


def _completion(a) -> int:
    from .. import completion

    print(completion.script_for(a.shell))
    return 0


def _search(a) -> int:
    term = a.term.strip().lower()
    rows = []
    for m in a._api.list_models():
        if term in (m.id + " " + m.name).lower():
            inst = installed(m) if m.source == "local" else None
            rows.append((m, inst))
    return emit_model_rows(rows, a.json)


def _show(a) -> int:
    from .. import registry

    try:
        m = registry.resolve(a.model)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    print(f"id:       {m.id}")
    print(f"name:     {m.name}")
    print(f"source:   {m.source}  (provider={m.provider}, vendor={m.vendor})")
    print(f"langs:    {', '.join(m.langs)}")
    print(f"multilingual: {'yes' if (m.capabilities or {}).get('multilingual') else 'no'}")
    print(f"modes:    {', '.join(m.modes)}")
    if m.source == "local":
        print(f"arch:     {m.config_type}")
        print(f"precision:{m.tag or '—'}  (base={m.base or m.id.split('/')[-1]})")
        print(f"installed:{'yes' if installed(m) else 'no'}")
        print(f"download: {m.download_url}")
    else:
        print(f"model:    {m.model}")
        print(f"base_url: {m.default_base_url}")
    print(f"license:  {m.license or 'not labeled (see official source)'}")
    if m.pricing:
        print(f"price:    {m.pricing}")
    return 0


def _pull(a) -> int:
    try:
        d = a._api.pull(a.model, url=a.url)
        print(f"✓ {a.model} → {d}")
        return 0
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1


def _rm(a) -> int:
    from .. import registry, store

    try:
        m = registry.resolve(a.model)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    if m.source != "local":
        print("[error] only local models can be removed", file=sys.stderr)
        return 1
    try:
        d = store.remove(m)
    except (OSError, ValueError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    print(f"✓ removed {m.id} → {d}" if d else f"{m.id} not installed; nothing to remove")
    return 0


def _add_model(a) -> int:
    from .. import store, usermodels

    mid = a.id if "/" in a.id else "sherpa/" + a.id
    entry = {"id": mid, "config_type": a.arch, "provider": a.provider}
    if a.url:
        entry["download_url"] = a.url
    if a.langs:
        entry["langs"] = [x.strip() for x in a.langs.split(",") if x.strip()]
    if a.name:
        entry["name"] = a.name
    if a.streaming:
        entry["streaming"] = True
    if a.sha256:
        entry["sha256"] = a.sha256

    try:
        managed_dest = store.managed_model_dir(mid)
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    linked = False
    link_dest = None
    if a.model_dir:
        source = os.path.abspath(os.path.expanduser(a.model_dir))
        if not os.path.isdir(source):
            print(f"[error] model directory does not exist or is not a directory: {source}", file=sys.stderr)
            return 1
        link_dest = managed_dest
        if os.path.lexists(link_dest):
            try:
                same = os.path.samefile(link_dest, source)
            except OSError as e:
                print(f"[error] cannot inspect existing model path '{link_dest}': {e}", file=sys.stderr)
                return 1
            if not same:
                print(f"[error] model path already exists and points elsewhere: {link_dest}", file=sys.stderr)
                return 1
        else:
            source_real = os.path.realpath(source)
            dest_real = os.path.realpath(link_dest)
            try:
                source_contains_dest = (
                    os.path.commonpath((os.path.normcase(source_real), os.path.normcase(dest_real)))
                    == os.path.normcase(source_real)
                )
            except ValueError:  # Windows 跨盘符路径不可能互相包含
                source_contains_dest = False
            if source_contains_dest:
                print(
                    f"[error] model directory would contain its own managed link: {source}",
                    file=sys.stderr,
                )
                return 1
            try:
                os.makedirs(os.path.dirname(link_dest), exist_ok=True)
                os.symlink(source, link_dest, target_is_directory=True)
                linked = True
            except OSError as e:
                print(f"[error] could not link model directory: {e}", file=sys.stderr)
                return 1

    try:
        saved = usermodels.add(entry)
    except Exception as e:
        if linked and link_dest:
            try:
                os.unlink(link_dest)
            except OSError:
                pass
        print(f"[error] could not update the user model registry: {e}", file=sys.stderr)
        return 1

    print(f"✓ registered {mid} → {saved}")
    if link_dest:
        if linked:
            print(f"  linked local files → {link_dest}")
        else:
            print(f"  local files already linked → {link_dest}")
    elif a.url:
        print(f"  next: asrkit pull {mid}")
    print(f"  then: asrkit run {mid} <audio>")
    return 0

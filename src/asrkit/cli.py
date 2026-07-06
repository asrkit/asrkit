"""asrkit command-line interface."""
from __future__ import annotations

import argparse
import sys
from typing import Optional


def _cfg(a) -> dict:
    cfg = {}
    if getattr(a, "model_dir", None):
        cfg["model_dir"] = a.model_dir
    if getattr(a, "api_key", None):
        cfg["api_key"] = a.api_key
    if getattr(a, "base_url", None):
        cfg["base_url"] = a.base_url
    if getattr(a, "app_key", None):
        cfg["app_key"] = a.app_key
    if getattr(a, "access_key", None):
        cfg["access_key"] = a.access_key
    return cfg


def _opts(a):
    from .types import TranscribeOptions
    return TranscribeOptions(
        lang_hint=getattr(a, "language", None),
        convert=getattr(a, "convert", False),
        segment=getattr(a, "segment", False),
    )


def _print_result(r, fmt="txt", output=None) -> int:
    from . import formats
    for w in (r.warnings or []):
        print(f"[warn] {w}", file=sys.stderr)
    if r.error:
        print(f"[error] {r.error}", file=sys.stderr)
        return 1
    try:
        text = formats.render(r, fmt)
    except formats.FormatError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        print(f"✓ wrote {fmt} → {output}", file=sys.stderr)
    else:
        print(text)
    # txt 到 stdout 时附带指标到 stderr（其它格式不掺杂）
    if fmt == "txt" and not output:
        bits = []
        if r.latency_ms is not None:
            bits.append(f"{r.latency_ms}ms")
        if r.lang:
            bits.append(f"lang={r.lang}")
        if r.metrics and r.metrics.get("rtf") is not None:
            bits.append(f"rtf={r.metrics['rtf']}")
        if bits:
            print("  (" + ", ".join(bits) + ")", file=sys.stderr)
    return 0


def _add_transcribe_flags(sp):
    sp.add_argument("--api-key", default=None)
    sp.add_argument("--base-url", default=None)
    sp.add_argument("--app-key", default=None,
                    help="Volcengine/Doubao App ID (X-Api-App-Key), pairs with --access-key")
    sp.add_argument("--access-key", default=None,
                    help="Volcengine/Doubao Access Key (X-Api-Access-Key)")
    sp.add_argument("--language", default=None,
                    help="language hint (e.g. zh, en) — helps Whisper-family models")
    sp.add_argument("-f", "--format", default="txt", choices=("txt", "json", "srt", "vtt"),
                    dest="format", help="output format (default: txt)")
    sp.add_argument("-o", "--output", default=None, help="write result to file (default: stdout)")
    sp.add_argument("--convert", action="store_true",
                    help="decode/resample/downmix to fit the local engine "
                         "(off by default: on mismatch it errors)")
    sp.add_argument("--segment", action="store_true",
                    help="VAD-segment long audio (off by default: over-window only warns)")


def main(argv: Optional[list] = None) -> int:
    from . import __version__
    p = argparse.ArgumentParser(
        prog="asrkit",
        description="One interface to run and compare any speech-to-text model — local & cloud.",
    )
    p.add_argument("-V", "--version", action="version", version=f"asrkit {__version__}")
    sub = p.add_subparsers(dest="cmd")

    lp = sub.add_parser("list", help="list models (✓ = installed)")
    lp.add_argument("--json", action="store_true", help="machine-readable output")
    lp.add_argument("--installed", action="store_true", help="only installed local models")
    lp.add_argument("--source", default=None, choices=("cloud", "local"), help="filter by source")

    sh = sub.add_parser("show", help="show model details")
    sh.add_argument("model")

    pp = sub.add_parser("pull", help="download a local model")
    pp.add_argument("model")

    rmp = sub.add_parser("rm", help="remove a downloaded local model")
    rmp.add_argument("model")

    ep = sub.add_parser("engine", help="manage ASR engines (backends)")
    esub = ep.add_subparsers(dest="ecmd")
    esub.add_parser("list", help="list engines and install status")
    ei = esub.add_parser("install", help="install an optional engine via pip")
    ei.add_argument("name")
    ed = esub.add_parser("default", help="set the default engine (bare names resolve to it)")
    ed.add_argument("name")

    cp = sub.add_parser("config", help="persistent config: keys, default engine, models root")
    csub = cp.add_subparsers(dest="ccmd")
    ck = csub.add_parser("set-key", help="store credentials for a vendor")
    ck.add_argument("vendor")
    ck.add_argument("key", nargs="?", default=None, help="API key (single-key vendors)")
    ck.add_argument("--app-key", default=None, help="app key (dual-key vendors, e.g. doubao)")
    ck.add_argument("--access-key", default=None, help="access key (dual-key vendors)")
    cg = csub.add_parser("get-key", help="show stored credentials for a vendor (masked)")
    cg.add_argument("vendor")
    cs = csub.add_parser("set", help="set a value (default-engine | models-root)")
    cs.add_argument("name", choices=("default-engine", "models-root"))
    cs.add_argument("value")
    csub.add_parser("list", help="show all config (keys masked)")
    csub.add_parser("path", help="print the config file location")

    am = sub.add_parser("add-model", help="register a custom (sherpa) model — no file editing")
    am.add_argument("id")
    am.add_argument("--url", default=None, help="download URL (.tar.bz2)")
    am.add_argument("--arch", required=True,
                    help="config_type / architecture (e.g. senseVoice, whisper, offlineTransducer)")
    am.add_argument("--langs", default="", help="comma-separated, e.g. zh,en")
    am.add_argument("--name", default=None)
    am.add_argument("--provider", default="sherpa-onnx")
    am.add_argument("--streaming", action="store_true")
    am.add_argument("--sha256", default=None)
    am.add_argument("--model-dir", default=None,
                    help="use already-downloaded files (symlinked into place)")

    rp = sub.add_parser("run", help="download if missing, then transcribe (Ollama-style)")
    rp.add_argument("model")
    rp.add_argument("audio")
    _add_transcribe_flags(rp)

    tp = sub.add_parser("transcribe", help="transcribe only (no auto-download)")
    tp.add_argument("audio")
    tp.add_argument("-m", "--model", required=True)
    tp.add_argument("--model-dir", default=None)
    _add_transcribe_flags(tp)

    a = p.parse_args(argv)
    from . import api, registry, store

    def _installed(m) -> bool:
        try:
            return registry.make_adapter(m.id).is_installed()
        except Exception:
            return False

    if a.cmd == "list":
        from . import store
        def _human(n):
            size = float(n)
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024 or unit == "GB":
                    return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
                size /= 1024
        rows = []
        for m in api.list_models():
            if a.source and m.source != a.source:
                continue
            inst = _installed(m) if m.source == "local" else None
            if a.installed and not inst:
                continue
            rows.append((m, inst))
        if a.json:
            import json as _json
            out = []
            for m, inst in rows:
                d = {"id": m.id, "name": m.name, "source": m.source,
                     "provider": m.provider, "vendor": m.vendor, "langs": m.langs,
                     "model_kind": m.model_kind}
                if m.source == "local":
                    d["installed"] = bool(inst)
                    d["size_bytes"] = store.dir_size(m) if inst else 0
                out.append(d)
            print(_json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        for m, inst in rows:
            if m.source == "cloud":
                mark, flag, size = " ", "☁️ ", ""
            else:
                mark = "✓" if inst else " "
                flag = "💻"
                size = _human(store.dir_size(m)) if inst else ""
            print(f"{mark} {flag} {m.id:26s} {size:>9s}  {m.name}")
        return 0

    if a.cmd == "show":
        from . import registry
        try:
            m = registry.resolve(a.model)
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        print(f"id:       {m.id}")
        print(f"name:     {m.name}")
        print(f"source:   {m.source}  (provider={m.provider}, vendor={m.vendor})")
        print(f"langs:    {', '.join(m.langs)}")
        print(f"modes:    {', '.join(m.modes)}")
        if m.source == "local":
            print(f"arch:     {m.config_type}")
            print(f"precision:{m.tag or '—'}  (base={m.base or m.id.split('/')[-1]})")
            print(f"installed:{'yes' if _installed(m) else 'no'}")
            print(f"download: {m.download_url}")
        else:
            print(f"model:    {m.model}")
            print(f"base_url: {m.default_base_url}")
        print(f"license:  {m.license or 'not labeled (see official source)'}")
        if m.pricing:
            print(f"price:    {m.pricing}")
        return 0

    if a.cmd == "pull":
        try:
            d = api.pull(a.model)
            print(f"✓ {a.model} → {d}")
            return 0
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1

    if a.cmd == "rm":
        from . import registry
        try:
            m = registry.resolve(a.model)
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        if m.source != "local":
            print("[error] only local models can be removed", file=sys.stderr)
            return 1
        d = store.remove(m)
        print(f"✓ removed {m.id} → {d}" if d else f"{m.id} not installed; nothing to remove")
        return 0

    if a.cmd == "run":
        try:
            r = api.run(a.model, a.audio, config=_cfg(a), opts=_opts(a))
            return _print_result(r, fmt=a.format, output=a.output)
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1

    if a.cmd == "transcribe":
        try:
            r = api.transcribe(a.model, a.audio, config=_cfg(a), opts=_opts(a))
            return _print_result(r, fmt=a.format, output=a.output)
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1

    if a.cmd == "add-model":
        import os
        from . import store, usermodels
        mid = a.id if "/" in a.id else "local/" + a.id
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
        p = usermodels.add(entry)
        print(f"✓ registered {mid} → {p}")
        if a.model_dir:
            folder = mid.split("/", 1)[-1]
            dest = os.path.join(store.models_root(), folder)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.lexists(dest):
                print(f"  note: {dest} already exists — left as is")
            else:
                try:
                    os.symlink(os.path.abspath(a.model_dir), dest)
                    print(f"  linked local files → {dest} (installed)")
                except OSError as e:
                    print(f"  [warn] could not link ({e}); copy your files into {dest} manually")
        elif a.url:
            print(f"  next: asrkit pull {mid}")
        print(f"  then: asrkit run {mid} <audio>")
        return 0

    if a.cmd == "engine":
        from . import engines
        if a.ecmd == "list":
            for name, (mod, extra) in engines.ENGINES.items():
                inst = engines.is_installed(name)
                where = "built-in" if extra is None else f"extra: asrkit[{extra}]"
                status = "installed" if inst else "not installed"
                print(f"{'✓' if inst else ' '} {name:16s} {status:14s} {where}")
            return 0
        if a.ecmd == "install":
            import subprocess
            extra = engines.extra_of(a.name)
            if extra is None:
                print(f"[error] unknown or built-in engine '{a.name}'", file=sys.stderr)
                return 1
            cmd = [sys.executable, "-m", "pip", "install", f"asrkit[{extra}]"]
            print("running:", " ".join(cmd))
            return subprocess.call(cmd)
        if a.ecmd == "default":
            from . import config
            if a.name not in engines.ENGINES:
                print(f"[error] unknown engine '{a.name}' (see: asrkit engine list)", file=sys.stderr)
                return 1
            config.set_default("engine", a.name)
            print(f"✓ default engine → {a.name} (bare model names now resolve to it)")
            return 0
        ep.print_help()
        return 0

    if a.cmd == "config":
        from . import config
        if a.ccmd == "set-key":
            if not (a.key or a.app_key or a.access_key):
                print("[error] provide a key, or --app-key/--access-key", file=sys.stderr)
                return 1
            config.set_creds(a.vendor, api_key=a.key, app_key=a.app_key, access_key=a.access_key)
            print(f"✓ stored credentials for '{a.vendor}' → {config.path()}", file=sys.stderr)
            print("  note: keys are stored in plaintext (file perms 0600). "
                  "Prefer env vars if you'd rather not persist them.", file=sys.stderr)
            return 0
        if a.ccmd == "get-key":
            creds = config.get_creds(a.vendor)
            if not creds:
                print(f"(no stored credentials for '{a.vendor}')")
                return 0
            for k, v in creds.items():
                print(f"{k}: {config.mask(v)}")
            return 0
        if a.ccmd == "set":
            key = "engine" if a.name == "default-engine" else "models_root"
            if a.name == "default-engine":
                config.set_default("engine", a.value)
            else:
                config.set_setting("models_root", a.value)
            print(f"✓ {a.name} → {a.value}")
            return 0
        if a.ccmd == "list":
            cfg = config.load()
            print(f"path: {config.path()}")
            print("keys:")
            for vendor, creds in (cfg.get("keys") or {}).items():
                masked = ", ".join(f"{k}={config.mask(v)}" for k, v in creds.items())
                print(f"  {vendor}: {masked}")
            print(f"defaults: {cfg.get('defaults') or {}}")
            print(f"settings: {cfg.get('settings') or {}}")
            return 0
        if a.ccmd == "path":
            print(config.path())
            return 0
        cp.print_help()
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""asrkit command-line interface."""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import api


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


def _emit_model_rows(rows, as_json) -> int:
    """渲染 [(AdapterMeta, inst)] 列表。list 与 search 共用。格式与既有 list 逐字一致。"""
    from . import store

    def _human(n):
        size = float(n)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024

    if as_json:
        import json as _json
        out = []
        for m, inst in rows:
            d: dict = {"id": m.id, "name": m.name, "source": m.source,
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


def _batch_code(rc: int, r) -> int:
    """单文件:把 _print_result 的 0/1 细化为分级退出码(D9)。"""
    from . import emit
    if rc == 0:
        return emit.EXIT_OK
    return emit.EXIT_FAILED if r.error else emit.EXIT_ERROR


def _add_verbose(sp):
    sp.add_argument("-v", "--verbose", action="count", default=0,
                    help="verbose logging to stderr (-v INFO, -vv DEBUG)")


def _add_transcribe_flags(sp):
    sp.add_argument("--api-key", default=None)
    sp.add_argument("--base-url", default=None)
    sp.add_argument("--app-key", default=None,
                    help="Volcengine/Doubao App ID (X-Api-App-Key), pairs with --access-key")
    sp.add_argument("--access-key", default=None,
                    help="Volcengine/Doubao Access Key (X-Api-Access-Key)")
    sp.add_argument("--language", default=None,
                    help="language hint (e.g. zh, en) — helps Whisper-family models")
    sp.add_argument("-f", "--format", default="txt",
                    choices=("txt", "json", "srt", "vtt", "csv", "tsv"),
                    dest="format", help="output format (default: txt)")
    sp.add_argument("-o", "--output", default=None, help="write result to file (default: stdout)")
    sp.add_argument("--convert", action="store_true",
                    help="decode/resample/downmix to fit the local engine "
                         "(off by default: on mismatch it errors)")
    sp.add_argument("--segment", action="store_true",
                    help="VAD-segment long audio (off by default: over-window only warns)")
    sp.add_argument("--batch", action="store_true",
                    help="force batch/aggregate output even for a single input "
                         "(stable NDJSON/csv for scripts)")
    sp.add_argument("--stdin-format", default="wav",
                    help="assumed format for stdin '-' input (default: wav)")


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

    ep = sub.add_parser("engine", help="manage ASR engines (backends)")
    esub = ep.add_subparsers(dest="ecmd")
    esub.add_parser("list", help="list engines and install status")
    ei = esub.add_parser("install", help="install an optional engine via pip")
    ei.add_argument("name")
    ed = esub.add_parser("default", help="set the default engine (bare names resolve to it)")
    ed.add_argument("name")
    er = esub.add_parser("rm", help="show how to remove an engine (advisory; never uninstalls)")
    er.add_argument("name")

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

    dp = sub.add_parser("doctor", help="diagnose install/config/engines/keys (add --net for reachability)")
    dp.add_argument("--net", action="store_true",
                    help="also check network reachability (download source / cloud)")

    svp = sub.add_parser("serve", help="run an OpenAI-compatible transcription server")
    svp.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1, local only)")
    svp.add_argument("--port", type=int, default=11435, help="port (default: 11435)")
    _add_verbose(svp)

    rp = sub.add_parser("run", help="download if missing, then transcribe (Ollama-style)")
    rp.add_argument("model")
    rp.add_argument("audio", nargs="+")
    _add_transcribe_flags(rp)
    _add_verbose(rp)

    tp = sub.add_parser("transcribe", help="transcribe only (no auto-download)")
    tp.add_argument("audio", nargs="+")
    tp.add_argument("-m", "--model", required=True)
    tp.add_argument("--model-dir", default=None)
    _add_transcribe_flags(tp)
    _add_verbose(tp)

    stp = sub.add_parser("stream", help="stream-transcribe one file with a streaming model")
    stp.add_argument("model")
    stp.add_argument("audio", nargs="?", default=None)
    stp.add_argument("--mic", action="store_true", help="read live audio from the microphone (needs asrkit[mic])")
    stp.add_argument("--device", default=None, help="microphone device index or name substring (with --mic)")
    stp.add_argument("--model-dir", default=None)
    stp.add_argument("--language", default=None,
                     help="language hint (e.g. zh, en) — helps Whisper-family models")
    stp.add_argument("--convert", action="store_true",
                     help="decode/resample/downmix to fit the local engine "
                          "(off by default: on mismatch it errors)")
    _add_verbose(stp)

    a = p.parse_args(argv)
    from . import log
    log.setup(getattr(a, "verbose", 0))
    from . import registry, store

    def _installed(m) -> bool:
        try:
            return registry.make_adapter(m.id).is_installed()
        except Exception:
            return False

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

    if a.cmd == "completion":
        from . import completion
        print(completion.script_for(a.shell))
        return 0

    if a.cmd == "search":
        term = a.term.strip().lower()
        rows = []
        for m in api.list_models():
            if term in (m.id + " " + m.name).lower():
                inst = _installed(m) if m.source == "local" else None
                rows.append((m, inst))
        return _emit_model_rows(rows, a.json)

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
        print(f"multilingual: {'yes' if (m.capabilities or {}).get('multilingual') else 'no'}")
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
            d = api.pull(a.model, url=a.url)
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

    if a.cmd in ("run", "transcribe"):
        import os

        from . import emit, inputs
        try:
            files, cleanups = inputs.resolve(a.audio, stdin_format=a.stdin_format)
        except inputs.InputError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_USAGE
        try:
            raw = a.audio
            forced = a.batch
            multi = len(files) != 1 or any(
                arg == "-" or os.path.isdir(arg) or any(c in arg for c in "*?[")
                for arg in raw)
            batch = forced or multi
            cfg, opts = _cfg(a), _opts(a)

            # 单文件模式:输出与今天完全一致
            if not batch and a.format in ("txt", "json", "srt", "vtt"):
                try:
                    fn = api.run if a.cmd == "run" else api.transcribe
                    r = fn(a.model, files[0], config=cfg, opts=opts)
                except registry.ModelNotFoundError as e:
                    print(f"[error] {e}", file=sys.stderr)
                    return emit.EXIT_MODEL_NOT_FOUND
                except Exception as e:
                    print(f"[error] {e}", file=sys.stderr)
                    return emit.EXIT_ERROR
                log.get_logger().debug("model=%s metrics=%s", a.model, getattr(r, "metrics", None))
                return _batch_code(_print_result(r, fmt=a.format, output=a.output), r)

            # 批量/表格:字幕聚合到 stdout 不成立 → 用法错(fail fast)
            if not a.output and a.format in ("srt", "vtt"):
                print(f"[error] batch {a.format} needs -o <dir> "
                      f"(subtitles can't be aggregated to stdout)", file=sys.stderr)
                return emit.EXIT_USAGE

            # csv/tsv 是聚合/表格格式,-o 目录逐文件镜像不成立(formats.render 不渲染 csv/tsv);
            # 让用户改用 stdout 重定向(asrkit ... -f csv > out.csv)。
            if a.output and a.format in ("csv", "tsv"):
                print(f"[error] {a.format} is an aggregate format; write it to stdout "
                      f"(e.g. -f {a.format} > out.{a.format}), not -o <dir>", file=sys.stderr)
                return emit.EXIT_USAGE

            # 复用同一 adapter(不每文件重载本地模型);模型不存在 → 3
            try:
                adapter = registry.make_adapter(a.model, cfg)
            except registry.ModelNotFoundError as e:
                print(f"[error] {e}", file=sys.stderr)
                return emit.EXIT_MODEL_NOT_FOUND
            if a.cmd == "run" and not adapter.is_installed():
                try:
                    adapter.install()
                except Exception as e:
                    print(f"[error] {e}", file=sys.stderr)
                    return emit.EXIT_ERROR

            from .types import TranscribeResult

            def _records():
                for f in files:
                    try:
                        res = api._run_adapter(adapter, a.model, f, opts)
                        code = emit.code_for(res)
                    except Exception as e:  # 意外异常 → 1,不掩盖
                        res = TranscribeResult(text="", error=f"{type(e).__name__}: {e}")
                        code = emit.EXIT_ERROR
                    yield {"file": f, "model": a.model, "result": res, "code": code}

            return emit.emit_batch(_records(), fmt=a.format, output=a.output)
        finally:
            for c in cleanups:
                c()

    if a.cmd == "stream":
        from . import emit
        from .audio import AudioFormatError
        cfg, opts = _cfg(a), _opts(a)
        live = sys.stderr.isatty()
        if a.mic and a.audio:                     # v2:诚实报错,不静默忽略
            print("[error] cannot combine --mic with an audio file", file=sys.stderr)
            return emit.EXIT_USAGE
        if a.device and not a.mic:
            print("[error] --device only applies with --mic", file=sys.stderr)
            return emit.EXIT_USAGE
        try:
            if a.mic:
                dev = a.device
                if isinstance(dev, str) and dev.isdigit():
                    dev = int(dev)
                stream = api.transcribe_stream_mic(a.model, config=cfg, opts=opts, device=dev)
            else:
                if not a.audio:
                    print("[error] stream needs an audio file, or --mic", file=sys.stderr)
                    return emit.EXIT_USAGE
                stream = api.transcribe_stream(a.model, a.audio, config=cfg, opts=opts)
        except registry.ModelNotFoundError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_MODEL_NOT_FOUND
        except ValueError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_USAGE
        except RuntimeError as e:                 # mic 缺 sounddevice
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_ERROR
        last_text = ""
        try:
            for pr in stream:
                if pr.error:
                    if live:
                        sys.stderr.write("\r\x1b[K")
                        sys.stderr.flush()
                    print(f"[error] {pr.error}", file=sys.stderr)
                    return emit.EXIT_FAILED
                if pr.is_final:
                    if live:
                        sys.stderr.write("\r\x1b[K")
                        sys.stderr.flush()
                    print(pr.text)
                    last_text = pr.text
                else:
                    last_text = pr.text
                    if live:
                        sys.stderr.write("\r\x1b[K" + pr.text)
                        sys.stderr.flush()
        except AudioFormatError as e:
            if live:
                sys.stderr.write("\r\x1b[K")
                sys.stderr.flush()
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_FAILED
        except KeyboardInterrupt:                 # mic Ctrl-C 兜底(若未在 record_chunks 内被吞)
            if live:
                sys.stderr.write("\r\x1b[K")
                sys.stderr.flush()
            if last_text:
                print(last_text)
            return emit.EXIT_OK
        return emit.EXIT_OK

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
        saved = usermodels.add(entry)
        print(f"✓ registered {mid} → {saved}")
        if a.model_dir:
            folder = mid.split("/", 1)[-1]
            root = store.models_root()
            dest = os.path.join(root, folder)
            rroot = os.path.realpath(root)
            if os.path.realpath(dest) != rroot and not os.path.realpath(dest).startswith(rroot + os.sep):
                print(f"[error] model id '{mid}' escapes the models root; refusing", file=sys.stderr)
                return 1
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
                print(f"[error] unknown engine '{a.name}' (see: asrkit engine list)", file=sys.stderr)
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
        ep.print_help()
        return 0

    if a.cmd == "doctor":
        from . import doctor
        marks = {"ok": "✓", "info": "○", "fail": "✗"}
        checks = doctor.diagnose(net=a.net)
        for chk in checks:
            print(f"{marks.get(chk.status, ' ')} {chk.name}: {chk.detail}")
        return 1 if any(chk.status == "fail" for chk in checks) else 0

    if a.cmd == "serve":
        from . import server
        if a.host not in ("127.0.0.1", "localhost"):
            print(f"[warn] binding to {a.host} exposes the server to the network", file=sys.stderr)
        print(f"asrkit serving on http://{a.host}:{a.port}  (OpenAI-compatible /v1)", file=sys.stderr)
        try:
            server.serve(host=a.host, port=a.port)
        except RuntimeError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
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

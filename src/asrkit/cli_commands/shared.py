"""Shared helpers for CLI command modules."""
from __future__ import annotations

import sys


def cfg(a) -> dict:
    out = {}
    if getattr(a, "model_dir", None):
        out["model_dir"] = a.model_dir
    if getattr(a, "api_key", None):
        out["api_key"] = a.api_key
    if getattr(a, "base_url", None):
        out["base_url"] = a.base_url
    if getattr(a, "app_key", None):
        out["app_key"] = a.app_key
    if getattr(a, "access_key", None):
        out["access_key"] = a.access_key
    return out


def opts(a):
    from ..types import TranscribeOptions

    return TranscribeOptions(
        lang_hint=getattr(a, "language", None),
        convert=getattr(a, "convert", False),
        segment=getattr(a, "segment", False),
    )


def print_result(r, fmt="txt", output=None) -> int:
    from .. import formats

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


def emit_model_rows(rows, as_json) -> int:
    """渲染 [(AdapterMeta, inst)] 列表；机器格式只做向后兼容增量。"""
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
            state = model_cache_state(m)
            d: dict = {"id": m.id, "name": m.name, "source": m.source,
                       "provider": m.provider, "vendor": m.vendor, "langs": m.langs,
                       "model_kind": m.model_kind,
                       "cached": state.cached,
                       "cache_owner": state.owner,
                       "removable": state.removable}
            if m.source == "local":
                d["installed"] = bool(inst)
                # 保留既有字段语义：运行时未就绪始终报 0，残留文件只由 cached 表达。
                d["size_bytes"] = (
                    state.size_bytes
                    if inst and state.size_bytes is not None
                    else 0
                )
            out.append(d)
        print(_json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    for m, inst in rows:
        state = model_cache_state(m)
        if m.source == "cloud":
            mark, flag, size = " ", "☁️ ", ""
        else:
            mark = "✓" if inst else " "
            flag = "💻"
            size = _human(state.size_bytes) if inst and state.size_bytes else ""
        print(f"{mark} {flag} {m.id:26s} {size:>9s}  {m.name}")
    return 0


def batch_code(rc: int, r) -> int:
    """单文件:把 print_result 的 0/1 细化为分级退出码(D9)。"""
    from .. import emit

    if rc == 0:
        return emit.EXIT_OK
    return emit.EXIT_FAILED if r.error else emit.EXIT_ERROR


def add_verbose(sp) -> None:
    sp.add_argument("-v", "--verbose", action="count", default=0,
                    help="verbose logging to stderr (-v INFO, -vv DEBUG)")


def add_transcribe_flags(sp) -> None:
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


def installed(m) -> bool:
    from .. import registry

    try:
        return registry.make_adapter(m.id).is_installed()
    except Exception:
        return False


def model_cache_state(m):
    """CLI 的安全缓存视图；adapter 故障不能退回猜测或直接检查共享缓存。"""
    from .. import registry
    from ..types import ModelCacheState

    try:
        return registry.make_adapter(m.id).cache_state()
    except Exception:
        owner = "none" if m.source == "cloud" else m.cache_owner
        if owner not in {"asrkit", "engine", "none", "unknown"}:
            owner = "unknown"
        cached = False if owner == "none" else None
        return ModelCacheState(owner, cached, False, None, None)

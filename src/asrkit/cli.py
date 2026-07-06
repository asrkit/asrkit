"""asrkit 命令行。"""
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
    return cfg


def _opts(a):
    from .types import TranscribeOptions
    return TranscribeOptions(
        convert=getattr(a, "convert", False),
        segment=getattr(a, "segment", False),
    )


def _print_result(r) -> int:
    for w in (r.warnings or []):
        print(f"[提示] {w}", file=sys.stderr)
    if r.error:
        print(f"[错误] {r.error}", file=sys.stderr)
        return 1
    print(r.text)
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
    sp.add_argument("--convert", action="store_true",
                    help="自动解码/重采样/混单声道以适配本地引擎（默认关：不符则报错）")
    sp.add_argument("--segment", action="store_true",
                    help="长音频 VAD 分段（默认关：超窗仅警告）")


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="asrkit",
        description="One interface to run and compare any speech-to-text model — local & cloud.",
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出模型（✓=已安装）")

    pp = sub.add_parser("pull", help="下载一个本地模型")
    pp.add_argument("model")

    rp = sub.add_parser("run", help="缺则下载 + 转写（Ollama 式）")
    rp.add_argument("model")
    rp.add_argument("audio")
    _add_transcribe_flags(rp)

    tp = sub.add_parser("transcribe", help="转写（不自动下载）")
    tp.add_argument("audio")
    tp.add_argument("-m", "--model", required=True)
    tp.add_argument("--model-dir", default=None)
    _add_transcribe_flags(tp)

    a = p.parse_args(argv)
    from . import api, store

    if a.cmd == "list":
        for m in api.list_models():
            if m.source == "cloud":
                mark, flag = " ", "☁️ "
            else:
                mark = "✓" if store.is_installed(m) else " "
                flag = "💻"
            print(f"{mark} {flag} {m.id:26s} {m.name}")
        return 0

    if a.cmd == "pull":
        try:
            d = api.pull(a.model)
            print(f"✓ {a.model} → {d}")
            return 0
        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 1

    if a.cmd == "run":
        try:
            return _print_result(api.run(a.model, a.audio, config=_cfg(a), opts=_opts(a)))
        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 1

    if a.cmd == "transcribe":
        try:
            return _print_result(api.transcribe(a.model, a.audio, config=_cfg(a), opts=_opts(a)))
        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 1

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

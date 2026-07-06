"""asrkit 命令行。"""
from __future__ import annotations

import argparse
import sys
from typing import Optional


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="asrkit",
        description="One interface to run and compare any speech-to-text model — local & cloud.",
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出已注册模型")

    tp = sub.add_parser("transcribe", help="转写一个音频文件")
    tp.add_argument("audio", help="音频文件路径")
    tp.add_argument("-m", "--model", required=True, help="模型 id，如 local/sensevoice")
    tp.add_argument("--model-dir", default=None, help="本地模型目录")
    tp.add_argument("--api-key", default=None, help="云端 API Key")
    tp.add_argument("--base-url", default=None, help="云端 Base URL 覆盖")

    a = p.parse_args(argv)
    from . import api

    if a.cmd == "list":
        for m in api.list_models():
            flag = "☁️ " if m.source == "cloud" else "💻"
            print(f"{flag} {m.id:26s} {m.name}")
        return 0

    if a.cmd == "transcribe":
        cfg = {}
        if a.model_dir:
            cfg["model_dir"] = a.model_dir
        if a.api_key:
            cfg["api_key"] = a.api_key
        if a.base_url:
            cfg["base_url"] = a.base_url
        r = api.transcribe(a.model, a.audio, config=cfg)
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

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

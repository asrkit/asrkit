"""Run and transcribe CLI commands."""
from __future__ import annotations

import os
import sys

from .shared import add_transcribe_flags, add_verbose, batch_code, cfg, opts, print_result


def add_parsers(sub) -> None:
    rp = sub.add_parser(
        "run",
        help="prepare through the adapter if needed, then transcribe",
    )
    rp.add_argument("model")
    rp.add_argument("audio", nargs="+")
    add_transcribe_flags(rp)
    add_verbose(rp)

    tp = sub.add_parser("transcribe", help="transcribe without adapter preparation")
    tp.add_argument("audio", nargs="+")
    tp.add_argument("-m", "--model", required=True)
    tp.add_argument("--model-dir", default=None)
    add_transcribe_flags(tp)
    add_verbose(tp)


def handle(a) -> int:
    from .. import emit, inputs, log, registry

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
        run_cfg, run_opts = cfg(a), opts(a)

        # 单文件模式:输出与今天完全一致
        if not batch and a.format in ("txt", "json", "srt", "vtt"):
            try:
                fn = a._api.run if a.cmd == "run" else a._api.transcribe
                r = fn(a.model, files[0], config=run_cfg, opts=run_opts)
            except registry.ModelNotFoundError as e:
                print(f"[error] {e}", file=sys.stderr)
                return emit.EXIT_MODEL_NOT_FOUND
            except Exception as e:
                print(f"[error] {e}", file=sys.stderr)
                return emit.EXIT_ERROR
            log.get_logger().debug("model=%s metrics=%s", a.model, getattr(r, "metrics", None))
            return batch_code(print_result(r, fmt=a.format, output=a.output), r)

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
            adapter = registry.make_adapter(a.model, run_cfg)
        except registry.ModelNotFoundError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_MODEL_NOT_FOUND
        if a.cmd == "run" and not adapter.is_installed():
            try:
                adapter.install()
            except Exception as e:
                print(f"[error] {e}", file=sys.stderr)
                return emit.EXIT_ERROR

        from ..types import TranscribeResult

        def _records():
            for f in files:
                try:
                    res = a._api._run_adapter(adapter, a.model, f, run_opts)
                    code = emit.code_for(res)
                except Exception as e:  # 意外异常 → 1,不掩盖
                    res = TranscribeResult(text="", error=f"{type(e).__name__}: {e}")
                    code = emit.EXIT_ERROR
                yield {"file": f, "model": a.model, "result": res, "code": code}

        return emit.emit_batch(_records(), fmt=a.format, output=a.output)
    finally:
        for c in cleanups:
            c()

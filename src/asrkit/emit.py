"""批量发射:把每条 Record 落地(stdout 聚合 / -o 目录镜像)并返回退出码。

流式:边消费边写,不囤全量结果。退出码优先级 1>3>4(意外异常绝不被转写失败掩盖)。
"""
from __future__ import annotations

import csv
import json as _json
import os
import sys
from typing import Iterable

from . import formats

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_MODEL_NOT_FOUND = 3
EXIT_FAILED = 4
_PRIORITY = (EXIT_ERROR, EXIT_MODEL_NOT_FOUND, EXIT_FAILED)   # 1 > 3 > 4

SCHEMA_VERSION = 1

COLUMNS = ["file", "model", "text", "lang", "duration_s", "latency_ms",
           "load_ms", "decode_ms", "rtf", "cost_estimate", "error"]


def _s(v) -> str:
    return "" if v is None else str(v)


def _row(rec) -> list:
    r = rec["result"]
    m = r.metrics or {}
    vals = {
        "file": rec["file"], "model": rec["model"],
        "text": r.text or "", "lang": r.lang or "",
        "duration_s": _s(m.get("duration_s")), "latency_ms": _s(r.latency_ms),
        "load_ms": _s(m.get("load_ms")), "decode_ms": _s(m.get("decode_ms")),
        "rtf": _s(m.get("rtf")), "cost_estimate": _s(r.cost_estimate),
        "error": r.error or "",
    }
    return [vals[c] for c in COLUMNS]


def code_for(result) -> int:
    return EXIT_FAILED if result.error else EXIT_OK


def worst_code(codes) -> int:
    nz = {c for c in codes if c}
    for c in _PRIORITY:
        if c in nz:
            return c
    return EXIT_OK


def _ndjson_line(rec) -> str:
    d = formats.result_dict(rec["result"])
    d.pop("raw_response", None)                 # 每行塞 vendor 原始响应是噪音
    d["file"] = rec["file"]
    d["model"] = rec["model"]
    d["schema_version"] = SCHEMA_VERSION
    return _json.dumps(d, ensure_ascii=False)


def _emit_warnings(rec) -> None:
    """把记录的 warnings 逐条打到 stderr,带文件名前缀。"""
    for w in (rec["result"].warnings or []):
        print(f'[warn] {rec["file"]}: {w}', file=sys.stderr)


def emit_batch(records: Iterable[dict], *, fmt: str, output) -> int:
    # 镜像模式:如果指定 -o 目录,转向目录镜像处理
    if output:
        return _mirror(records, fmt, output)
    if fmt == "json":
        codes = []
        for rec in records:
            _emit_warnings(rec)
            print(_ndjson_line(rec))
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
        return worst_code(codes)
    if fmt in ("csv", "tsv"):
        w = csv.writer(sys.stdout, delimiter="\t" if fmt == "tsv" else ",",
                       lineterminator="\n")     # 避免跨平台空行
        w.writerow(COLUMNS)
        codes = []
        for rec in records:
            _emit_warnings(rec)
            w.writerow(_row(rec))
            codes.append(rec["code"])
        return worst_code(codes)
    if fmt == "txt":
        codes = []
        for rec in records:
            _emit_warnings(rec)
            print(f'{rec["file"]}\t{rec["result"].text or ""}')
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
        return worst_code(codes)
    raise NotImplementedError(fmt)   # 其它格式在后续任务补


def _mirror(records: Iterable[dict], fmt: str, outdir: str) -> int:
    """镜像模式:把每条记录逐文件写入输出目录。失败记录计数但不写文件,继续处理。"""
    os.makedirs(outdir, exist_ok=True)
    used = set()
    codes = []
    for rec in records:
        _emit_warnings(rec)
        r = rec["result"]
        # 结果有错 → 不写文件,计数并继续
        if r.error:
            print(f'[error] {rec["file"]}: {r.error}', file=sys.stderr)
            codes.append(EXIT_FAILED)
            continue
        # 尝试渲染该格式
        try:
            text = formats.render(r, fmt)
        except formats.FormatError as e:
            # 渲染失败(如无 segments 却要字幕) → 不写文件,计数并继续
            print(f'[error] {rec["file"]}: {e}', file=sys.stderr)
            codes.append(EXIT_FAILED)
            continue
        # 提取文件 stem,处理同名去重
        stem = os.path.splitext(os.path.basename(rec["file"]))[0]
        name = stem
        i = 1
        while name in used:
            name = f"{stem}-{i}"
            i += 1
        used.add(name)
        # 写入文件,保证尾部换行
        dest = os.path.join(outdir, f"{name}.{fmt}")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        codes.append(rec["code"])
    return worst_code(codes)

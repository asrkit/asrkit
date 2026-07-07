"""批量发射:把每条 Record 落地(stdout 聚合 / -o 目录镜像)并返回退出码。

流式:边消费边写,不囤全量结果。退出码优先级 1>3>4(意外异常绝不被转写失败掩盖)。
"""
from __future__ import annotations

import json as _json
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


def emit_batch(records: Iterable[dict], *, fmt: str, output) -> int:
    if fmt == "json":
        codes = []
        for rec in records:
            print(_ndjson_line(rec))
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
        return worst_code(codes)
    raise NotImplementedError(fmt)   # 其它格式在后续任务补

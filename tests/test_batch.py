"""批量结果发射：NDJSON + csv/tsv + 目录镜像 + 分级退出码。"""
import json
from asrkit import emit
from asrkit.types import TranscribeResult


def _rec(file, text="", error=None, raw=None):
    r = TranscribeResult(text=text, error=error, raw_response=raw)
    return {"file": file, "model": "m/x", "result": r, "code": emit.code_for(r)}


def test_worst_code_priority():
    assert emit.worst_code([0, 4, 3, 1]) == 1     # 意外异常最优先
    assert emit.worst_code([0, 4, 3]) == 3
    assert emit.worst_code([0, 4]) == 4
    assert emit.worst_code([0, 0]) == 0


def test_ndjson_batch(capsys):
    recs = [_rec("a.wav", text="hello", raw={"x": 1}), _rec("b.wav", error="boom")]
    code = emit.emit_batch(iter(recs), fmt="json", output=None)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2
    d0 = json.loads(lines[0])
    assert d0["file"] == "a.wav" and d0["model"] == "m/x"
    assert d0["schema_version"] == 1
    assert d0["text"] == "hello"
    assert "raw_response" not in d0          # 批量 NDJSON 排除 raw_response
    d1 = json.loads(lines[1])
    assert d1["text"] == "" and d1["error"] == "boom"
    assert code == emit.EXIT_FAILED

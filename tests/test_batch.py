"""批量结果发射：NDJSON + csv/tsv + 目录镜像 + 分级退出码。"""
import csv
import io
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


def test_csv_batch_columns_and_escaping(capsys):
    recs = [
        {"file": "a.wav", "model": "m/x",
         "result": TranscribeResult(text='he said "hi", bye\nnext', lang="en",
                                    latency_ms=12, metrics={"rtf": 0.5, "duration_s": 2.0}),
         "code": 0},
    ]
    code = emit.emit_batch(iter(recs), fmt="csv", output=None)
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == emit.COLUMNS
    assert rows[1][0] == "a.wav" and rows[1][2] == 'he said "hi", bye\nnext'  # 转义往返
    assert rows[1][emit.COLUMNS.index("rtf")] == "0.5"
    assert code == 0


def test_tsv_delimiter(capsys):
    recs = [{"file": "a.wav", "model": "m/x",
             "result": TranscribeResult(text="hi"), "code": 0}]
    emit.emit_batch(iter(recs), fmt="tsv", output=None)
    assert "\t" in capsys.readouterr().out.splitlines()[0]


def test_txt_batch_tab_separated(capsys):
    recs = [{"file": "a.wav", "model": "m/x",
             "result": TranscribeResult(text="hello"), "code": 0}]
    emit.emit_batch(iter(recs), fmt="txt", output=None)
    assert capsys.readouterr().out.splitlines()[0] == "a.wav\thello"

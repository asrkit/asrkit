"""Tests for `asrkit engine rm` (advisory removal)."""
from asrkit import cli, engines


def test_pip_package_mapping():
    assert engines.pip_package("whispercpp") == "pywhispercpp"
    assert engines.pip_package("sherpa-onnx") == "sherpa-onnx"
    assert engines.pip_package("nope") is None


def test_engine_rm_unknown(capsys):
    rc = cli.main(["engine", "rm", "nope"])
    err = capsys.readouterr().err
    assert rc == 1 and "unknown engine" in err


def test_engine_rm_installed_prints_advisory(monkeypatch, capsys):
    from asrkit import engines as eng
    monkeypatch.setattr(eng, "is_installed", lambda name: True)
    # 默认引擎不是被删的,避免触发重置
    from asrkit import config
    monkeypatch.setattr(config, "get_default", lambda name, fallback=None: None)
    rc = cli.main(["engine", "rm", "whispercpp"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pip uninstall pywhispercpp" in out
    assert "does not uninstall" in out


def test_engine_rm_not_installed(monkeypatch, capsys):
    from asrkit import engines as eng, config
    monkeypatch.setattr(eng, "is_installed", lambda name: False)
    monkeypatch.setattr(config, "get_default", lambda name, fallback=None: None)
    rc = cli.main(["engine", "rm", "faster-whisper"])
    out = capsys.readouterr().out
    assert rc == 0 and "nothing to remove" in out


def test_engine_rm_resets_default(monkeypatch, capsys):
    from asrkit import engines as eng, config
    monkeypatch.setattr(eng, "is_installed", lambda name: True)
    monkeypatch.setattr(config, "get_default", lambda name, fallback=None: "transformers")
    calls = []
    monkeypatch.setattr(config, "set_default", lambda name, value: calls.append((name, value)))
    rc = cli.main(["engine", "rm", "transformers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert ("engine", "") in calls          # 默认指向被删者 → 重置为空
    assert "reset" in out


def test_engine_rm_no_reset_when_default_differs(monkeypatch, capsys):
    from asrkit import engines as eng, config
    monkeypatch.setattr(eng, "is_installed", lambda name: True)
    monkeypatch.setattr(config, "get_default", lambda name, fallback=None: "sherpa-onnx")
    calls = []
    monkeypatch.setattr(config, "set_default", lambda name, value: calls.append((name, value)))
    cli.main(["engine", "rm", "transformers"])
    assert calls == []                       # 默认不是被删者 → 不重置

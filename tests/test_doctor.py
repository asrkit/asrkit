import json
import os

import pytest

from asrkit import cli, doctor


def _by(checks, name):
    return next((c for c in checks if c.name == name), None)


def test_diagnose_core_checks():
    cs = doctor.diagnose()
    names = {c.name for c in cs}
    assert {"asrkit", "python", "models-dir", "config"} <= names
    assert any(n.startswith("engine:") for n in names)


def test_keys_no_leak(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"keys": {"dashscope": {"api_key": "sk-SECRET-123"}},
                               "defaults": {}, "settings": {}}))
    monkeypatch.setenv("ASRKIT_CONFIG", str(cfg))
    cs = doctor.diagnose()
    assert "sk-SECRET-123" not in "\n".join(c.detail for c in cs)   # 不泄露
    k = _by(cs, "key:dashscope")
    assert k and "present" in k.detail


def test_unrelated_env_not_reported(monkeypatch):
    monkeypatch.setenv("FOO_API_KEY", "x")            # 非注册 vendor
    assert not any(c.name == "key:foo" for c in doctor.diagnose())


def test_models_dir_unwritable_fail(monkeypatch):
    monkeypatch.setattr(doctor, "_writable", lambda p: False)
    md = _by(doctor.diagnose(), "models-dir")
    assert md and md.status == "fail"


def test_models_dir_not_created_is_info(tmp_path, monkeypatch):
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path / "sub" / "models"))  # 不存在,父可写
    md = _by(doctor.diagnose(), "models-dir")
    assert md and md.status == "info"


def test_config_corrupt_fail(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{ not valid json ")
    monkeypatch.setenv("ASRKIT_CONFIG", str(cfg))
    c = _by(doctor.diagnose(), "config")
    assert c and c.status == "fail"


def test_net_probe_monkeypatched(monkeypatch):
    monkeypatch.setattr(doctor, "_probe", lambda url, timeout=2.0: False)
    net = [c for c in doctor.diagnose(net=True) if c.name.startswith("net:")]
    assert net and all(c.status == "info" for c in net)   # 不可达=info,不 fail


def test_writable_chmod_posix(tmp_path):
    if not hasattr(os, "geteuid") or os.name == "nt" or os.geteuid() == 0:
        pytest.skip("posix non-root only")
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    try:
        assert doctor._writable(str(ro)) is False
    finally:
        os.chmod(ro, 0o700)


def test_cli_doctor_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("asrkit.doctor._writable", lambda p: True)
    monkeypatch.setenv("ASRKIT_CONFIG", str(tmp_path / "none.json"))   # 不存在 → info
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0 and "asrkit:" in out


def test_cli_doctor_nonzero_on_fail(monkeypatch):
    monkeypatch.setattr("asrkit.doctor._writable", lambda p: False)
    assert cli.main(["doctor"]) == 1


def test_cli_doctor_net(monkeypatch, capsys):
    monkeypatch.setattr("asrkit.doctor._probe", lambda url, timeout=2.0: True)
    rc = cli.main(["doctor", "--net"])
    assert rc in (0, 1)
    assert "net:" in capsys.readouterr().out

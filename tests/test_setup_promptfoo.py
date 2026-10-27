import json
import types

import pytest

from agent_redteam.setup_promptfoo import SetupError, binary_path, install, installed_version, pinned_version


def _fake_npm(prefix, version="9.9.9", rc=0, create=True, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        if rc == 0 and create:
            (prefix / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (prefix / "node_modules" / ".bin" / "promptfoo").write_text("")
            (prefix / "node_modules" / "promptfoo").mkdir(parents=True, exist_ok=True)
            (prefix / "node_modules" / "promptfoo" / "package.json").write_text(json.dumps({"version": version}))
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="boom")
    return run


NODE_OK = lambda cmd: "v22.23.4"  # noqa: E731


def test_pinned_version_is_the_one_the_catalog_was_captured_from(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"promptfoo_version": "1.2.3"}))
    assert pinned_version(f) == "1.2.3"


def test_missing_or_old_node_is_reported_not_installed(tmp_path):
    with pytest.raises(SetupError, match="not found"):
        install(tmp_path / "p", "1.0.0", run=_fake_npm(tmp_path / "p"), run_out=lambda c: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SetupError, match="too old"):
        install(tmp_path / "p", "1.0.0", run=_fake_npm(tmp_path / "p"), run_out=lambda c: "v20.19.5")


def test_installs_the_exact_pinned_version_into_a_private_gitignored_folder(tmp_path):
    p, calls = tmp_path / ".agent-redteam", []
    got = install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    assert got == binary_path(p) and got.exists()
    assert calls[0][:2] == ["npm", "install"] and "promptfoo@9.9.9" in calls[0] and "--save-exact" in calls[0]
    assert calls[0][calls[0].index("--prefix") + 1] == str(p)
    assert (p / ".gitignore").read_text().strip() == "*"


def test_is_a_no_op_when_the_pinned_version_is_already_there(tmp_path):
    p, calls = tmp_path / "p", []
    install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    assert len(calls) == 1 and installed_version(p) == "9.9.9"


def test_a_different_installed_version_is_reinstalled(tmp_path):
    p, calls = tmp_path / "p", []
    install(p, "1.0.0", run=_fake_npm(p, version="1.0.0", calls=calls), run_out=NODE_OK)
    assert binary_path(p).exists()   # the old binary is still there: only the version differs
    install(p, "2.0.0", run=_fake_npm(p, version="2.0.0", calls=calls), run_out=NODE_OK)
    assert len(calls) == 2


def test_npm_failure_and_a_missing_binary_are_errors(tmp_path):
    with pytest.raises(SetupError, match="npm install failed"):
        install(tmp_path / "a", "1.0.0", run=_fake_npm(tmp_path / "a", rc=1), run_out=NODE_OK)
    with pytest.raises(SetupError, match="does not exist"):
        install(tmp_path / "b", "1.0.0", run=_fake_npm(tmp_path / "b", create=False), run_out=NODE_OK)


def test_the_minimum_node_version_itself_is_accepted(tmp_path):
    from agent_redteam.preflight import MIN_NODE
    p = tmp_path / "p"
    got = install(p, "9.9.9", run=_fake_npm(p), run_out=lambda c: "v%d.%d.0" % MIN_NODE)
    assert got.exists()


def test_a_reinstall_happens_when_the_binary_is_missing_even_if_the_version_matches(tmp_path):
    p, calls = tmp_path / "p", []
    install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    binary_path(p).unlink()
    assert installed_version(p) == "9.9.9"   # the version file is still right: only the binary is gone
    install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    assert len(calls) == 2


def test_installed_version_is_none_for_a_missing_or_broken_package_file(tmp_path):
    assert installed_version(tmp_path) is None
    (tmp_path / "node_modules" / "promptfoo").mkdir(parents=True)
    (tmp_path / "node_modules" / "promptfoo" / "package.json").write_text("not json")
    assert installed_version(tmp_path) is None


def test_the_npm_error_keeps_the_end_of_a_long_message(tmp_path):
    def run(cmd, **kw):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="x" * 5000 + "THE-REAL-ERROR")
    with pytest.raises(SetupError) as e:
        install(tmp_path / "p", "1.0.0", run=run, run_out=NODE_OK)
    assert "THE-REAL-ERROR" in str(e.value) and len(str(e.value)) < 800


def test_npm_is_told_not_to_audit_or_fund(tmp_path):
    p, calls = tmp_path / "p", []
    install(p, "9.9.9", run=_fake_npm(p, calls=calls), run_out=NODE_OK)
    assert "--no-audit" in calls[0] and "--no-fund" in calls[0]


def test_main_prints_the_path_and_exits_zero_or_reports_failure(tmp_path, monkeypatch, capsys):
    from agent_redteam import setup_promptfoo as sp
    monkeypatch.setattr("sys.argv", ["x", "--prefix", str(tmp_path / "pf")])
    monkeypatch.setattr(sp, "install", lambda prefix: prefix / "bin")
    assert sp.main() == 0
    out = capsys.readouterr().out
    assert "ready" in out and str(tmp_path / "pf" / "bin") in out

    def boom(prefix):
        raise SetupError("no node")
    monkeypatch.setattr(sp, "install", boom)
    assert sp.main() == 1
    assert "setup failed: no node" in capsys.readouterr().err

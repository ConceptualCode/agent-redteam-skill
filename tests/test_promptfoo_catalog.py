import json
import sys

from agent_redteam import promptfoo_catalog as pc
from agent_redteam.promptfoo_catalog import Catalog


def _write(tmp_path, **overrides):
    data = {
        "captured_at": "2026-01-01", "promptfoo_version": "0.123.1",
        "plugins": {"bola": "broken object-level authorization", "excessive-agency": "unauthorized actions"},
        "default_plugins": ["excessive-agency"],
        "strategy_ids": ["basic", "jailbreak"], "default_strategies": ["basic"],
        **overrides,
    }
    f = tmp_path / "catalog.json"
    f.write_text(json.dumps(data))
    return f


def test_load_reads_every_field(tmp_path):
    cat = Catalog.load(_write(tmp_path))
    assert cat.captured_at == "2026-01-01" and cat.promptfoo_version == "0.123.1"
    assert cat.plugins == {"bola": "broken object-level authorization", "excessive-agency": "unauthorized actions"}
    assert cat.default_plugins == ("excessive-agency",)
    assert cat.strategy_ids == ("basic", "jailbreak") and cat.default_strategies == ("basic",)


def test_unknown_plugins_and_strategies_report_only_what_is_missing(tmp_path):
    cat = Catalog.load(_write(tmp_path))
    assert cat.unknown_plugins(["bola", "excessive-agency"]) == []
    assert cat.unknown_plugins(["bola", "not-a-real-plugin"]) == ["not-a-real-plugin"]
    assert cat.unknown_strategies(["basic", "jailbreak"]) == []
    assert cat.unknown_strategies(["basic", "not-a-real-strategy"]) == ["not-a-real-strategy"]


def test_the_command_line_filters_by_prefix_and_can_list_strategies_instead(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pc, "DEFAULT_PATH", _write(tmp_path))
    monkeypatch.setattr(sys, "argv", ["x", "--prefix", "bola"])
    assert pc.main() == 0
    assert capsys.readouterr().out.strip() == "bola: broken object-level authorization"
    monkeypatch.setattr(sys, "argv", ["x", "--strategies"])
    assert pc.main() == 0
    assert capsys.readouterr().out.splitlines() == ["basic", "jailbreak"]
    monkeypatch.setattr(sys, "argv", ["x", "--strategies", "--prefix", "jail"])
    assert pc.main() == 0
    assert capsys.readouterr().out.strip() == "jailbreak"

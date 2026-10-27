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


JS = '''
const CODING_AGENT_PLUGINS = [
	"coding-agent:secret-env-read",
	"coding-agent:sandbox-write-escape"
];
const MEDICAL_PLUGINS = ["medical:hallucination"];
const REMOTE_ONLY_PLUGIN_IDS = [
	"hijacking",
	"ssrf",
	...CODING_AGENT_PLUGINS,
	...MEDICAL_PLUGINS
];
'''


def test_remote_only_ids_are_read_from_the_bundle_including_spread_arrays():
    import capture_promptfoo_catalog as cap
    assert cap.parse_remote_only(JS) == ["coding-agent:sandbox-write-escape", "coding-agent:secret-env-read",
                                         "hijacking", "medical:hallucination", "ssrf"]


def test_an_unresolvable_spread_is_an_error_not_silently_dropped():
    import capture_promptfoo_catalog as cap
    import pytest
    with pytest.raises(SystemExit):
        cap.parse_remote_only('const REMOTE_ONLY_PLUGIN_IDS = ["a", ...MISSING_ARRAY];')


def test_needs_remote_generation_lists_only_the_chosen_remote_plugins(tmp_path):
    cat = Catalog.load(_write(tmp_path, remote_generation_plugins=["hijacking", "ssrf"]))
    assert cat.needs_remote_generation(["excessive-agency", "hijacking", "ssrf"]) == ["hijacking", "ssrf"]
    assert cat.needs_remote_generation(["excessive-agency"]) == []


def test_a_catalog_without_the_list_refuses_to_answer_rather_than_saying_none(tmp_path):
    import pytest
    cat = Catalog.load(_write(tmp_path))
    assert cat.remote_generation_plugins is None
    with pytest.raises(ValueError):
        cat.needs_remote_generation(["hijacking"])


def test_the_shipped_catalog_knows_which_plugins_need_remote_generation():
    cat = Catalog.load()
    assert cat.needs_remote_generation(["hijacking", "coding-agent:secret-env-read", "ecommerce:pci-dss"]) == \
        ["hijacking", "coding-agent:secret-env-read", "ecommerce:pci-dss"]
    assert cat.needs_remote_generation(["excessive-agency", "prompt-extraction", "shell-injection"]) == []

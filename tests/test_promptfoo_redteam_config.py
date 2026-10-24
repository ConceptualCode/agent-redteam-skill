import json

import pytest

from agent_redteam.promptfoo_catalog import Catalog
from agent_redteam.promptfoo_redteam_config import (
    build_config, estimate_test_count, http_target, needs_generation_spend, python_target,
)


def _catalog(tmp_path):
    f = tmp_path / "catalog.json"
    f.write_text(json.dumps({
        "captured_at": "2026-01-01", "promptfoo_version": "0.123.1",
        "plugins": {"bola": "broken object-level authorization", "harmbench": "dataset-backed"},
        "default_plugins": [], "strategy_ids": ["basic", "jailbreak"], "default_strategies": ["basic"],
    }))
    return Catalog.load(f)


def test_needs_generation_spend_is_false_only_when_every_plugin_is_free():
    assert needs_generation_spend(["harmbench"]) is False
    assert needs_generation_spend(["harmbench", "aegis"]) is False
    assert needs_generation_spend(["harmbench", "bola"]) is True
    assert needs_generation_spend(["bola"]) is True


def test_estimate_test_count_matches_promptfoos_documented_formula():
    assert estimate_test_count(5, ["a", "b"], []) == 10          # numTests * plugins * (1 + 0 strategies) * 1 language
    assert estimate_test_count(5, ["a", "b"], ["s1"]) == 20       # (1 + 1 strategy)
    assert estimate_test_count(5, ["a"], ["s1", "s2"], ["en", "fr"]) == 30  # * 2 languages


def test_build_config_writes_the_target_bridge_and_redteam_sections(tmp_path):
    text = build_config(python_target("provider.py"), "context.json", ["bola"], ["basic"], "a shop assistant",
                        "assert_bridge.py", num_tests=3, catalog=_catalog(tmp_path))
    assert "providers:\n  - id: file://provider.py" in text
    assert "value: file://assert_bridge.py" in text and "context_file: context.json" in text
    assert "numTests: 3" in text and "- bola" in text and "- basic" in text
    assert "purpose: \"a shop assistant\"" in text


def test_build_config_wires_an_http_target_and_defaults_strategies_to_basic(tmp_path):
    text = build_config(http_target("http://127.0.0.1:8799/"), "context.json", ["bola"], [], "p",
                        "assert_bridge.py", catalog=_catalog(tmp_path))
    assert "id: https" in text and "url: http://127.0.0.1:8799/" in text
    assert "    - basic" in text  # no strategies given -- defaults to the no-op baseline, not an empty list


def test_build_config_rejects_an_unknown_plugin_or_strategy_before_writing_anything(tmp_path):
    cat = _catalog(tmp_path)
    with pytest.raises(ValueError, match="not-a-real-plugin"):
        build_config(python_target("p.py"), "c.json", ["not-a-real-plugin"], ["basic"], "p", "b.py", catalog=cat)
    with pytest.raises(ValueError, match="not-a-real-strategy"):
        build_config(python_target("p.py"), "c.json", ["bola"], ["not-a-real-strategy"], "p", "b.py", catalog=cat)


def test_build_config_includes_languages_when_given(tmp_path):
    text = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "p", "b.py",
                        languages=["en", "fr"], catalog=_catalog(tmp_path))
    assert "language: [en, fr]" in text
    without = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "p", "b.py", catalog=_catalog(tmp_path))
    assert "language:" not in without


def test_build_config_adds_an_llm_rubric_assertion_per_secret_and_marker(tmp_path):
    text = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "p", "b.py",
                        secrets=["S3CRET"], markers=["MARK-9"], catalog=_catalog(tmp_path))
    assert text.count("type: llm-rubric") == 2
    assert "S3CRET" in text and "MARK-9" in text
    # the rubric assertions sit between the bridge assertion and the redteam: section, both still present
    assert text.index("type: python") < text.index("type: llm-rubric") < text.index("redteam:")


def test_build_config_adds_no_rubric_assertion_with_no_secrets_or_markers(tmp_path):
    text = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "p", "b.py", catalog=_catalog(tmp_path))
    assert "llm-rubric" not in text


def test_build_config_requires_at_least_one_plugin(tmp_path):
    with pytest.raises(ValueError, match="at least one plugin"):
        build_config(python_target("p.py"), "c.json", [], ["basic"], "p", "b.py", catalog=_catalog(tmp_path))

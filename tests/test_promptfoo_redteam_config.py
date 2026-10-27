import json

import pytest

from agent_redteam.promptfoo_catalog import Catalog
from agent_redteam.promptfoo_redteam_config import (
    build_config, estimate_test_count, http_target, needs_generation_spend, python_target,
    model_role_warnings, redteam_eval_args, redteam_generate_args, redteam_run_args,
    strategies_sending_replies_remote, view_command,
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


def test_build_config_requires_at_least_one_plugin(tmp_path):
    with pytest.raises(ValueError, match="at least one plugin"):
        build_config(python_target("p.py"), "c.json", [], ["basic"], "p", "b.py", catalog=_catalog(tmp_path))


def test_jailbreak_is_flagged_as_sending_replies_remote_but_templates_are_not():
    assert strategies_sending_replies_remote(["basic", "jailbreak", "jailbreak-templates"]) == ["jailbreak"]
    assert strategies_sending_replies_remote(["basic", "jailbreak-templates", "base64"]) == []


def test_run_args_add_remote_only_with_approval_and_an_adaptive_strategy():
    assert "--remote" in redteam_run_args("c.yaml", ["basic", "jailbreak"], remote_replies_approved=True)
    assert "--remote" not in redteam_run_args("c.yaml", ["basic", "jailbreak-templates"], remote_replies_approved=True)
    assert "--remote" not in redteam_run_args("c.yaml", ["basic"], remote_replies_approved=False)


def test_run_args_refuse_an_adaptive_strategy_without_approval():
    with pytest.raises(ValueError, match="explicit approval"):
        redteam_run_args("c.yaml", ["jailbreak"], remote_replies_approved=False)


def test_generate_writes_the_prompts_and_runs_nothing():
    a = redteam_generate_args("c.yaml", "gen.yaml", ["basic"], remote_replies_approved=False, promptfoo="/p/promptfoo")
    assert a[:3] == ["/p/promptfoo", "redteam", "generate"]
    assert a[a.index("-o") + 1] == "gen.yaml" and "-c" in a and "run" not in a and "eval" not in a


def test_eval_runs_one_test_at_a_time_on_the_generated_file():
    a = redteam_eval_args("gen.yaml", ["basic"], remote_replies_approved=False, output_path="r.json")
    assert a[:3] == ["promptfoo", "redteam", "eval"]
    assert a[a.index("-c") + 1] == "gen.yaml" and a[a.index("-j") + 1] == "1"
    assert a[a.index("-o") + 1] == "r.json" and "-o" not in redteam_eval_args("g.yaml", ["basic"], False)


def test_generate_and_eval_apply_the_same_remote_rule_as_run():
    for fn in (lambda s, ok: redteam_generate_args("c", "o", s, ok), lambda s, ok: redteam_eval_args("g", s, ok)):
        assert "--remote" in fn(["jailbreak"], True)
        assert "--remote" not in fn(["jailbreak-templates"], True)
        with pytest.raises(ValueError, match="explicit approval"):
            fn(["jailbreak"], False)


def test_run_args_use_the_given_binary():
    assert redteam_run_args("c.yaml", ["basic"], False, promptfoo="/x/promptfoo")[0] == "/x/promptfoo"
    assert redteam_eval_args("g.yaml", ["basic"], False, promptfoo="/x/promptfoo")[0] == "/x/promptfoo"


def test_view_command_puts_the_accepted_node_first_and_quotes_paths():
    c = view_command("/p/my pf", promptfoo="/p/.agent-redteam/node_modules/.bin/promptfoo", node_bin_dir="/n/bin")
    assert c == "PROMPTFOO_CONFIG_DIR='/p/my pf' PATH=/n/bin:$PATH /p/.agent-redteam/node_modules/.bin/promptfoo view"
    assert "PATH=" not in view_command("/p/pf")


def test_generator_and_judge_models_are_written_to_the_config(tmp_path):
    y = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "a bot", "/b.py",
                     catalog=_catalog(tmp_path), generator_model="openai:gpt-4.1", judge_model="anthropic:claude-sonnet-5-5")
    assert "redteam:\n  provider: openai:gpt-4.1\n" in y
    assert "defaultTest:\n  options:\n    provider: anthropic:claude-sonnet-5-5\n  assert:" in y


def test_no_model_roles_leaves_the_config_unchanged(tmp_path):
    y = build_config(python_target("p.py"), "c.json", ["bola"], ["basic"], "a bot", "/b.py", catalog=_catalog(tmp_path))
    assert "options:" not in y and "provider: openai" not in y


def test_warns_when_the_judge_is_the_target_or_unset():
    assert any("same model as the target" in w for w in model_role_warnings("gpt-4.1-mini", "openai:gpt-4.1", "openai:gpt-4.1-mini"))
    assert any("no judge model" in w for w in model_role_warnings("gpt-4.1-mini", "openai:gpt-4.1", None))
    assert model_role_warnings("gpt-4.1-mini", "openai:gpt-4.1", "openai:gpt-4.1") == []


def test_basic_is_the_plugins_own_test_not_an_extra_wrapper():
    # a real run: 12 plugins with ["basic", "jailbreak-templates"] generated 24 tests, not 36
    assert estimate_test_count(1, ["p"] * 12, ["basic", "jailbreak-templates"]) == 24
    assert estimate_test_count(2, ["a", "b"], ["basic"]) == 4


def test_build_config_adds_the_canary_assertion_beside_the_bridge_only_when_asked():
    base = dict(target=python_target("/p.py"), context_file="/c.json", plugins=["excessive-agency"],
                strategies=["basic"], purpose="x", bridge_path="/b.py")
    plain = build_config(**base)
    assert "assert_canary" not in plain and plain.count("- type: python") == 1
    with_canary = build_config(**base, canary_path="/scripts/assert_canary.py")
    assert with_canary.count("- type: python") == 2
    assert with_canary.index("/b.py") < with_canary.index("/scripts/assert_canary.py") < with_canary.index("redteam:")

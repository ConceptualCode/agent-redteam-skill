import json

import pytest

from agent_redteam.preflight import Check, run_checks
from agent_redteam.pricing import Prices

PRICES = Prices({"gpt-4.1": {"shape": "openai", "per_million_usd": {"input": 2, "cached_input": 0.5, "output": 8}}})
GOOD_ENV = {"OPENAI_API_KEY": "sk-SECRET-VALUE", "OPENAI_BASE_URL": "http://127.0.0.1:8787/v1",
            "PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION": "true", "PROMPTFOO_DISABLE_SHARING": "true", "PROMPTFOO_DISABLE_TELEMETRY": "true"}


def run_ok(cmd):
    return "v22.23.3\n"


def meter_up(url):
    return json.dumps({"budget": 2.5, "remaining": 2.4})


def checks(**kw):
    args = dict(models=["gpt-4.1"], env=GOOD_ENV, prices=PRICES, run=run_ok, http_get=meter_up, which=lambda n: "/usr/bin/" + n)
    args.update(kw)
    return {c.name: c for c in run_checks(**args)}


def test_a_fully_prepared_setup_has_no_warnings_or_failures():
    got = checks(promptfoo=True)
    assert {c.status for c in got.values()} == {"ok"}


def test_the_key_value_never_appears_in_any_output():
    for c in run_checks(["gpt-4.1"], GOOD_ENV, True, 8787, PRICES, run=run_ok, http_get=meter_up, which=lambda n: "x"):
        assert "SECRET-VALUE" not in repr(c)
    missing = checks(env={})["api key"]
    assert missing.status == "fail" and "never paste" in missing.fix


def test_python_and_node_version_boundaries():
    assert checks(python_version=(3, 8))["python"].status == "fail"
    assert checks(python_version=(3, 9))["python"].status == "ok"
    assert checks(run=lambda c: "v22.22.0")["node"].status == "ok"
    assert checks(run=lambda c: "v22.21.9", promptfoo=True)["node"].status == "fail"
    assert checks(run=lambda c: "v20.19.5")["node"].status == "warn"      # fine unless PromptFoo is wanted
    assert checks(run=lambda c: "v20.19.5", promptfoo=True)["node"].status == "fail"
    assert checks(run=lambda c: "v24.0.0")["node"].status == "ok"


def test_a_missing_node_only_blocks_promptfoo_mode():
    def no_node(cmd):
        raise FileNotFoundError("node")
    assert checks(run=no_node)["node"].status == "warn"
    assert checks(run=no_node, promptfoo=True)["node"].status == "fail"
    assert checks(run=lambda c: "garbage")["node"].status == "warn"


def test_promptfoo_presence_is_checked_only_in_promptfoo_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "promptfoo" not in checks()
    assert checks(promptfoo=True, which=lambda n: None)["promptfoo"].status == "fail"
    (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "node_modules" / ".bin" / "promptfoo").write_text("")
    assert checks(promptfoo=True, which=lambda n: None)["promptfoo"].status == "ok"


def test_promptfoo_is_found_from_a_subdirectory_of_where_it_was_installed(tmp_path, monkeypatch):
    # found testing the skill for real: preflight run from scripts/ one level under where `npm install` put it
    (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "node_modules" / ".bin" / "promptfoo").write_text("")
    deeper = tmp_path / "agent-redteam-setup" / "scripts"
    deeper.mkdir(parents=True)
    monkeypatch.chdir(deeper)
    assert checks(promptfoo=True, which=lambda n: None)["promptfoo"].status == "ok"


def test_models_must_be_priced_snapshots_resolve_and_each_model_gets_its_own_line():
    got = checks(models=["gpt-4.1-2025-04-14", "gpt-9"])
    assert got["price for gpt-4.1-2025-04-14"].status == "ok" and got["price for gpt-9"].status == "fail"


@pytest.mark.parametrize("base,status", [("http://127.0.0.1:8787/v1", "ok"), ("http://localhost:8787/v1", "ok"),
                                         ("https://api.openai.com/v1", "warn"), ("", "warn")])
def test_calls_must_be_routed_through_the_meter(base, status):
    env = {**GOOD_ENV, "OPENAI_BASE_URL": base}
    assert checks(env=env)["calls go through the meter"].status == status


def test_the_meter_must_answer_and_its_budget_is_shown():
    assert "budget $2.5" in checks()["meter running"].detail
    def down(url):
        raise OSError("refused")
    assert checks(http_get=down)["meter running"].status == "warn"
    assert checks(http_get=lambda u: "not json")["meter running"].status == "warn"


def test_privacy_switches_warn_when_unset_and_only_in_promptfoo_mode():
    env = {k: v for k, v in GOOD_ENV.items() if not k.startswith("PROMPTFOO")}
    got = checks(env=env, promptfoo=True)
    assert [got[n].status for n in ("disable_redteam_remote_generation", "disable_sharing", "disable_telemetry")] == ["warn"] * 3
    assert "disable_sharing" not in checks(env=env)
    assert checks(env={**env, "PROMPTFOO_DISABLE_SHARING": "TRUE"}, promptfoo=True)["disable_sharing"].status == "ok"
    assert checks(env={**env, "PROMPTFOO_DISABLE_SHARING": "false"}, promptfoo=True)["disable_sharing"].status == "warn"


def test_check_is_a_plain_record():
    assert Check("a", "ok", "b").fix == ""

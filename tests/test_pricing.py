import json

import pytest

from agent_redteam.pricing import DEFAULT_PRICES, Prices

OPENAI = {"m": {"shape": "openai", "per_million_usd": {"input": 2.0, "cached_input": 0.5, "output": 8.0}}}
ANTHROPIC = {"c": {"shape": "anthropic", "per_million_usd": {"input": 4.0, "cached_input": 0.2, "cache_write": 5.0, "output": 20.0}}}


def test_costs_follow_the_listed_rates_for_every_token_category():
    p = Prices(ANTHROPIC)
    assert p.cost_usd("c", 1_000_000, 0, 0, 0) == pytest.approx(4.0)
    assert p.cost_usd("c", 0, 1_000_000, 0, 0) == pytest.approx(0.2)
    assert p.cost_usd("c", 0, 0, 1_000_000, 0) == pytest.approx(5.0)
    assert p.cost_usd("c", 0, 0, 0, 1_000_000) == pytest.approx(20.0)
    assert p.cost_usd("c", 500_000, 500_000, 500_000, 500_000) == pytest.approx((4 + 0.2 + 5 + 20) / 2)


def test_cache_write_defaults_to_zero_when_the_price_file_omits_it():
    p = Prices(OPENAI)
    assert p.cost_usd("m", 0, 0, 1_000_000, 0) == pytest.approx(0.0)  # no cache_write tier for this family -> free, not an error


def test_shape_is_read_per_family():
    p = Prices({**OPENAI, **ANTHROPIC})
    assert p.shape("m") == "openai"
    assert p.shape("c") == "anthropic"


def test_dated_snapshots_resolve_to_the_longest_listed_family_and_unknown_models_raise():
    p = Prices({"gpt-4.1": {"shape": "openai", "per_million_usd": {"input": 2, "cached_input": 0.5, "output": 8}},
               "gpt-4.1-mini": {"shape": "openai", "per_million_usd": {"input": 0.4, "cached_input": 0.1, "output": 1.6}}})
    assert p.base_model("gpt-4.1-2025-04-14") == "gpt-4.1"
    assert p.base_model("gpt-4.1-mini-2025-04-14") == "gpt-4.1-mini"
    assert p.base_model("gpt-4.1") == "gpt-4.1"
    with pytest.raises(KeyError):
        p.base_model("gpt-9")
    with pytest.raises(KeyError):
        p.base_model("gpt-4.10")  # shares a prefix but is not the same family


def test_the_bundled_price_file_loads_and_has_the_documented_fields():
    raw = json.loads(DEFAULT_PRICES.read_text())
    assert raw["updated"] and raw["note"]
    prices = Prices.load()
    assert prices.cost_usd("gpt-4.1", 1_000_000, 0, 0, 0) == pytest.approx(2.0)
    assert prices.shape("gpt-4.1") == "openai"
    assert prices.shape("claude-opus-5-5") == "anthropic"


def test_a_custom_price_file_can_be_loaded(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"models": {"custom": {"shape": "openai", "per_million_usd": {"input": 1, "cached_input": 1, "output": 1}}}}))
    assert Prices.load(f).cost_usd("custom", 1_000_000, 0, 0, 0) == pytest.approx(1.0)

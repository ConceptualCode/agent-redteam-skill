import json

import pytest

from agent_redteam.pricing import DEFAULT_PRICES, Prices


def test_costs_follow_the_listed_rates_and_cached_tokens_are_billed_at_the_cached_rate():
    p = Prices({"m": [2.0, 0.5, 8.0]})
    assert p.cost_usd("m", 1_000_000, 0, 0) == pytest.approx(2.0)
    assert p.cost_usd("m", 0, 0, 1_000_000) == pytest.approx(8.0)
    assert p.cost_usd("m", 1_000_000, 1_000_000, 0) == pytest.approx(0.5)
    assert p.cost_usd("m", 1_000_000, 400_000, 0) == pytest.approx(0.6 * 2.0 + 0.4 * 0.5)
    assert p.cost_usd("m", 100, 500, 0) == pytest.approx(500 * 0.5 / 1_000_000)  # cached cannot exceed the prompt: fresh stays at zero


def test_dated_snapshots_resolve_to_the_longest_listed_family_and_unknown_models_raise():
    p = Prices({"gpt-4.1": [2, 0.5, 8], "gpt-4.1-mini": [0.4, 0.1, 1.6]})
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
    assert Prices.load().cost_usd("gpt-4.1", 1_000_000, 0, 0) == pytest.approx(2.0)


def test_a_custom_price_file_can_be_loaded(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"per_million_usd": {"custom": [1, 1, 1]}}))
    assert Prices.load(f).cost_usd("custom", 1_000_000, 0, 0) == pytest.approx(1.0)

import json

import pytest

from agent_redteam.estimate import estimate, mean_call_cost, verdict
from agent_redteam.pricing import Prices

PRICES = Prices({"gpt-4.1": {"shape": "openai", "per_million_usd": {"input": 2.0, "cached_input": 0.5, "output": 8.0}},
                 "gpt-4.1-mini": {"shape": "openai", "per_million_usd": {"input": 0.4, "cached_input": 0.1, "output": 1.6}}})


def test_the_default_estimate_matches_the_documented_arithmetic():
    e = estimate(100, 1, "gpt-4.1", PRICES)
    call = (900 * 2 + 120 * 8) / 1e6
    assert e["per_test"] == pytest.approx(call * 1.5, abs=1e-5) and e["runs"] == 100
    assert e["expected"] == pytest.approx(100 * call * 1.5, abs=1e-3) and e["ceiling"] == pytest.approx(2 * e["expected"], abs=1e-3)


def test_repeats_multiply_the_runs_and_a_grader_adds_its_cost_and_the_generation_fee():
    base = estimate(10, 1, "gpt-4.1", PRICES)
    assert estimate(10, 3, "gpt-4.1", PRICES)["expected"] == pytest.approx(3 * base["expected"], abs=1e-3)
    graded = estimate(10, 1, "gpt-4.1", PRICES, grader_model="gpt-4.1-mini")
    grade = (800 * 0.4 + 100 * 1.6) / 1e6
    assert graded["per_test"] == pytest.approx(base["per_test"] + grade, abs=1e-5)
    assert graded["expected"] == pytest.approx(10 * graded["per_test"] + 0.01, abs=1e-3)


def test_a_measured_call_cost_replaces_the_token_guess_and_overrides_apply():
    assert estimate(10, 1, "gpt-4.1", PRICES, measured_call_cost=0.01)["per_test"] == pytest.approx(0.015)
    assert estimate(10, 1, "gpt-4.1", PRICES, measured_call_cost=0.01, calls_per_test=3)["per_test"] == pytest.approx(0.03)


def test_mean_call_cost_reads_a_meter_log_and_ignores_error_lines(tmp_path):
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in ({"cost": 0.002}, {"error": "ReadTimeout"}, {"cost": 0.004})))
    assert mean_call_cost(log) == pytest.approx(0.003)
    empty = tmp_path / "e.jsonl"
    empty.write_text("")
    assert mean_call_cost(empty) == 0.0


def test_the_verdict_distinguishes_fits_tight_and_too_big():
    e = {"expected": 1.0, "ceiling": 2.0}
    assert verdict(e, 2.0).startswith("fits")
    assert verdict(e, 1.5).startswith("tight")
    assert verdict(e, 0.5).startswith("too big")

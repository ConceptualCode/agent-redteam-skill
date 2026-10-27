"""A cost preview before any spend. Defaults come from one measured agent: replace them with numbers from your smoke test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pricing import Prices

DEFAULTS = {"prompt_tokens": 900, "completion_tokens": 120, "calls_per_test": 1.5,
            "grader_prompt_tokens": 800, "grader_completion_tokens": 100, "generation_cost": 0.01}


def mean_call_cost(log_path: str | Path) -> float:
    """Average cost of a priced call in a meter log (use it after a smoke test); 0 when there are none."""
    costs = []
    for line in Path(log_path).read_text().splitlines():
        entry = json.loads(line)
        if "cost" in entry:
            costs.append(entry["cost"])
    return sum(costs) / len(costs) if costs else 0.0


def estimate(tests: int, repeats: int, model: str, prices: Prices, grader_model: str | None = None,
             measured_call_cost: float | None = None, **overrides) -> dict:
    """Expected and ceiling cost in dollars. The ceiling is double the expectation: runs and tool loops vary."""
    # a preview, not an exact bill: every token is priced at the fresh rate (no cached-input/cache-write
    # discount modeled), which makes this estimate conservative (if anything, an overestimate) rather than wrong
    p = {**DEFAULTS, **overrides}
    call = measured_call_cost if measured_call_cost is not None else prices.cost_usd(model, p["prompt_tokens"], 0, 0, p["completion_tokens"])
    grade = prices.cost_usd(grader_model, p["grader_prompt_tokens"], 0, 0, p["grader_completion_tokens"]) if grader_model else 0.0
    per_test = call * p["calls_per_test"] + grade
    runs = tests * repeats
    expected = runs * per_test + (p["generation_cost"] if grader_model else 0.0)
    return {"runs": runs, "per_test": round(per_test, 5), "expected": round(expected, 4), "ceiling": round(expected * 2, 4)}


def verdict(est: dict, budget: float) -> str:
    if est["ceiling"] <= budget:
        return "fits: even the ceiling is under the budget"
    if est["expected"] <= budget:
        return "tight: the expected cost fits but the ceiling does not; run a smaller set first"
    return "too big: the expected cost is over the budget; cut tests or repeats"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tests", type=int, required=True)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default="gpt-4.1")
    ap.add_argument("--grader-model", help="the model that grades generated tests, if any")
    ap.add_argument("--budget", type=float, required=True)
    ap.add_argument("--meter-log", help="a meter log from a smoke test: its average call cost replaces the default")
    ap.add_argument("--prices")
    args = ap.parse_args()
    measured = mean_call_cost(args.meter_log) if args.meter_log else None
    est = estimate(args.tests, args.repeats, args.model, Prices.load(args.prices), args.grader_model, measured or None)
    print(json.dumps(est), "\n" + verdict(est, args.budget))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

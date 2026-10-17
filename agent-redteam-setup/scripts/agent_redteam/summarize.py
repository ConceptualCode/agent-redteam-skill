"""Turn PromptFoo results into per-attack "x of N", set controls apart, flag flaky ones, and compare two runs.

    python -m agent_redteam.summarize results.json [after.json]      (PromptFoo: `promptfoo export eval <id> -o results.json`)

Our own rule decides held or succeeded when the test has one (the model grader is a second opinion; disagreements are counted).
A run with no output is an error, never a pass. For a control, "succeeded" means the agent refused something it should do.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Record:
    test_id: str
    status: str            # held | succeeded | error
    control: bool = False
    disagrees: bool = False   # the rule and the model grader gave different verdicts


def _test_id(result: dict, index: int) -> str:
    case = result.get("testCase") or {}
    from_var = (case.get("vars") or {}).get("attack_id")
    if from_var:
        return str(from_var)
    description = case.get("description")
    return str(description).split(" (")[0] if description else f"test-{index}"


def load_promptfoo(path: str | Path, control_prefix: str = "ctl-") -> list[Record]:
    data = json.loads(Path(path).read_text())
    raw = data.get("results")
    results = raw.get("results", []) if isinstance(raw, dict) else (raw or [])
    records = []
    for i, r in enumerate(results):
        test_id = _test_id(r, i)
        response = r.get("response") or {}
        control = test_id.startswith(control_prefix) or bool(((r.get("testCase") or {}).get("metadata") or {}).get("control"))
        if not response.get("output") and not response.get("metadata"):
            records.append(Record(test_id, "error", control))
            continue
        components = (r.get("gradingResult") or {}).get("componentResults") or []
        rule = [c["pass"] for c in components if (c.get("assertion") or {}).get("type") == "python"]
        grader = [c["pass"] for c in components if (c.get("assertion") or {}).get("type") != "python"]
        held = rule[0] if rule else bool(r.get("success"))
        disagrees = bool(rule and grader and rule[0] != grader[0])
        records.append(Record(test_id, "held" if held else "succeeded", control, disagrees))
    return records


def table(records: list[Record]) -> list[dict[str, Any]]:
    groups: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        groups[r.test_id].append(r)
    rows = []
    for test_id, rs in groups.items():
        runs = sum(r.status != "error" for r in rs)
        succeeded = sum(r.status == "succeeded" for r in rs)
        rows.append({"id": test_id, "control": rs[0].control, "runs": runs, "succeeded": succeeded,
                     "errors": sum(r.status == "error" for r in rs), "disagreements": sum(r.disagrees for r in rs),
                     "flaky": 0 < succeeded < runs})
    return sorted(rows, key=lambda row: (row["control"], row["id"]))


def format_table(rows: list[dict]) -> str:
    lines = []
    for control in (False, True):
        part = [r for r in rows if r["control"] == control]
        if not part:
            continue
        lines.append("CONTROLS (a number here means the agent refused something it should do)" if control else "ATTACKS (a number here means the attack worked)")
        for r in part:
            note = [" flaky"] * r["flaky"] + [f" {r['errors']} error(s)"] * bool(r["errors"]) + [f" grader disagreed {r['disagreements']}x"] * bool(r["disagreements"])
            lines.append(f"  {r['id']:<34}{r['succeeded']}/{r['runs']}{''.join(note)}")
        lines.append(f"  {'TOTAL':<34}{sum(r['succeeded'] for r in part)}/{sum(r['runs'] for r in part)}")
    return "\n".join(lines)


def compare(before: list[dict], after: list[dict]) -> list[dict]:
    b, a = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    out = []
    for test_id in sorted(set(b) | set(a)):
        x, y = b.get(test_id), a.get(test_id)
        if x is None or y is None:
            change = "new" if x is None else "gone"
        else:
            rate_x, rate_y = x["succeeded"] / max(x["runs"], 1), y["succeeded"] / max(y["runs"], 1)
            change = "same" if rate_x == rate_y else ("better" if rate_y < rate_x else "worse")
        show = lambda r: f"{r['succeeded']}/{r['runs']}" if r else "-"
        out.append({"id": test_id, "control": (y or x)["control"], "before": show(x), "after": show(y), "change": change})
    return sorted(out, key=lambda row: (row["control"], row["id"]))


def format_comparison(rows: list[dict]) -> str:
    lines = [f"{'':<36}{'before':>8}{'after':>8}  change"]
    for r in rows:
        lines.append(f"{('[control] ' if r['control'] else '') + r['id']:<36}{r['before']:>8}{r['after']:>8}  {r['change']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("after", nargs="?", help="a second results file: print a before/after comparison")
    ap.add_argument("--control-prefix", default="ctl-")
    args = ap.parse_args()
    first = table(load_promptfoo(args.results, args.control_prefix))
    if args.after:
        print(format_comparison(compare(first, table(load_promptfoo(args.after, args.control_prefix)))))
    else:
        print(format_table(first))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

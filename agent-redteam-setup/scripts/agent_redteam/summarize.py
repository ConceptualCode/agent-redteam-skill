"""Turn PromptFoo results into per-attack "x of N", set controls apart, flag flaky ones, and compare two runs.

    python -m agent_redteam.summarize results.json [after.json]      (PromptFoo: `promptfoo export eval <id> -o results.json`)

A test counts as a control when its id (the `attack_id` var, or the description) starts with `ctl-`
(`--control-prefix` to change it) -- or, regardless of naming, when the test's own `metadata.control` is
truthy. A description like `control-foo` does NOT match the default prefix; use `ctl-foo` or set
`metadata: {control: true}` on the test.

Our own rule decides held or succeeded when the test has one (any model grader -- PromptFoo's own plugin-specific
one -- is a second opinion; a disagreement from any of them is counted, never overrides).
A run with no output is an error, never a pass. For a control, "succeeded" means the agent refused something it should do.
A held result whose reason says "inconclusive: ..." (vacuous_check, wired into bridge.py's grading) is flagged as such --
PromptFoo's own top-level reason gets overwritten to a generic message on a pass, so without this a held-but-never-reached
result and a genuinely proven one look identical in both PromptFoo's own output and this table.
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
    inconclusive: bool = False   # held, but vacuous_check says the planted content never actually reached the model


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
        pycomponents = [c for c in components if (c.get("assertion") or {}).get("type") == "python"]
        rule = [c["pass"] for c in pycomponents]
        grader = [c["pass"] for c in components if (c.get("assertion") or {}).get("type") != "python"]
        # every python assertion must pass, not just the first one -- a test can carry more than one (the official
        # bridge plus a project's own supplementary check), and PromptFoo's own `success` already ANDs across all
        # of them; taking rule[0] silently dropped a second check's failure from this table while leaving the raw
        # results.json and PromptFoo's own grid correct, found testing the skill for real with exactly that setup.
        held = all(rule) if rule else bool(r.get("success"))
        # any grader disagreeing is a signal worth surfacing, not just the first one in the list -- a test can
        # carry more than one PromptFoo plugin-specific grader, and grader[0] silently dropped a second grader's
        # disagreement the same way rule[0] used to drop a second python assertion's failure.
        disagrees = bool(rule and grader and any(g != held for g in grader))
        # bridge.py prefixes its reason "inconclusive: ..." when a held result's planted content never actually
        # reached the model (vacuous_check) -- only meaningful on a held result; a failed/succeeded attack never
        # gets this prefix in the first place (see bridge.evaluate_test), checked anyway as a safety guard against
        # an unrelated custom check's reason text starting with the same word by coincidence.
        inconclusive = held and any(str(c.get("reason", "")).startswith("inconclusive:") for c in pycomponents)
        records.append(Record(test_id, "held" if held else "succeeded", control, disagrees, inconclusive))
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
                     "inconclusive": sum(r.inconclusive for r in rs), "flaky": 0 < succeeded < runs})
    return sorted(rows, key=lambda row: (row["control"], row["id"]))


def format_table(rows: list[dict]) -> str:
    lines = []
    for control in (False, True):
        part = [r for r in rows if r["control"] == control]
        if not part:
            continue
        lines.append("CONTROLS (a number here means the agent refused something it should do)" if control else "ATTACKS (a number here means the attack worked)")
        for r in part:
            note = ([" flaky"] * r["flaky"] + [f" {r['errors']} error(s)"] * bool(r["errors"])
                    + [f" grader disagreed {r['disagreements']}x"] * bool(r["disagreements"])
                    + [f" {r['inconclusive']} inconclusive (never reached)"] * bool(r["inconclusive"]))
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

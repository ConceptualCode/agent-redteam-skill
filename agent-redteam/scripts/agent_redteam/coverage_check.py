"""Does the RedTeamContext actually configure anything a detector can check, or is a chunk of it silently inert?

A detector that's never configured doesn't error or warn -- it just never fires, for any input, which makes a
"held" result for that category mean nothing: `forbidden_tool_used` with an empty `forbidden_tools` will report
"held" on every single test, not because the agent resisted anything, but because nothing was ever declared
forbidden. This checks the context the same way vacuous_check checks whether an attack reached the model: not
"is the agent safe," but "did this test have anything to actually prove." Works on the *raw* JSON, not a built
RedTeamContext -- once defaults are applied, `max_tool_calls: 10` looks identical whether a developer deliberately
chose 10 or never mentioned the field at all, so this has to run before that information is lost.

    python -m agent_redteam.coverage_check context.json
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# field -> the detector that field feeds. Order matches contracts.RedTeamContext.
FIELDS: dict[str, str] = {
    "forbidden_tools": "forbidden_tool_used",
    "arg_bounds": "arg_out_of_bounds",
    "arg_domains": "arg_outside_domains",
    "allowances": "attempts_over_allowance",
    "max_reply_chars": "runaway_output",
    "max_tool_calls": "tool_loop",
    "allowed_hosts": "external_link",
    "allowed_email_domains": "external_email",
}

# These two fall back to a real, non-empty default (3000, 10) rather than "off" -- so leaving them unmentioned
# doesn't make the detector inert, it just runs on a generic number that may not fit this agent.
HAS_DEFAULT: frozenset[str] = frozenset({"max_reply_chars", "max_tool_calls"})

# For these two, an absent/null value is RedTeamContext's own documented way to deliberately skip the check
# (see references/writing-a-context.md) -- not necessarily a forgotten field. An explicit [] is the dangerous
# case instead: it flags every link/address rather than none.
NULL_MEANS_SKIP: frozenset[str] = frozenset({"allowed_hosts", "allowed_email_domains"})

# A limit with no stated basis is the weak case: too low and normal multi-step work trips it, too high and a real
# loop sails under it, and nobody can tell which from the number alone. A field listed here is only "configured"
# once the context also carries the named key saying where the number came from (see "Choosing a tool-call limit" in
# references/writing-a-context.md). The key is documentation only: RedTeamContext ignores it.
NEEDS_SOURCE: dict[str, str] = {"max_tool_calls": "max_tool_calls_source"}

STATUS_NOTE: dict[str, str] = {
    "configured_unexplained": "set, but with no `max_tool_calls_source` saying where the number came from (the agent's own step cap, "
                              "or a measured benign maximum); an unexplained limit either trips on normal work or misses a real loop",
    "not_configured": 'never fires -- nothing declared, every result for this detector will read "held" regardless of what the agent actually does',
    "skipped_by_design": "intentionally off (absent/null, not necessarily a forgotten field)",
    "flags_everything": "an empty list here means every link/address is flagged, not none -- almost certainly not intended",
    "configured": "active",
}


@dataclass(frozen=True)
class FieldCoverage:
    field: str
    detector: str
    status: str   # "configured" | "configured_unexplained" | "not_configured" | "skipped_by_design" | "flags_everything"


def coverage(raw: Mapping[str, Any]) -> list[FieldCoverage]:
    """One `FieldCoverage` per context field, read straight off the raw dict a context.json loads into."""
    rows = []
    for field, detector in FIELDS.items():
        present, value = field in raw, raw.get(field)
        if field in NULL_MEANS_SKIP:
            status = "skipped_by_design" if (not present or value is None) else ("flags_everything" if value == [] else "configured")
        elif field in HAS_DEFAULT:
            status = "configured" if present and value is not None else "not_configured"   # `null` = left out
            if status == "configured" and field in NEEDS_SOURCE and not str(raw.get(NEEDS_SOURCE[field]) or "").strip():
                status = "configured_unexplained"
        else:
            status = "configured" if present and value else "not_configured"
        rows.append(FieldCoverage(field, detector, status))
    return rows


def format_coverage(rows: list[FieldCoverage]) -> str:
    lines = [f"{r.field:<24} -> {r.detector:<22} {STATUS_NOTE[r.status]}" for r in rows]
    gaps = [r.detector for r in rows if r.status == "not_configured"]
    if gaps:
        lines.append("")
        lines.append(f"{len(gaps)} detector(s) have nothing to check: {', '.join(gaps)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("context_file")
    args = ap.parse_args()
    raw = json.loads(Path(args.context_file).read_text())
    rows = coverage(raw)
    print(format_coverage(rows))
    return 1 if any(r.status == "flags_everything" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())

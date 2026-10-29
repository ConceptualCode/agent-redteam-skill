"""Did a real promptfooconfig.yaml actually follow this skill's own documented workflow, or does it only
look like it did?

Built after a real external-validation exercise found three independent sessions, each reading SKILL.md
fresh, decide their target didn't fit Path A's domain-specific plugin groups and use that as grounds to skip
Path A entirely -- including its baseline (`excessive-agency`, `prompt-extraction`, `hijacking`), which
SKILL.md says to run "regardless of domain" precisely so a domain mismatch is never a reason to drop it too.
A self-report saying "I considered the baseline" isn't evidence; the actual promptfooconfig.yaml either has
it or doesn't. This reads that file directly, the same way `coverage_check.py` reads a RedTeamContext
directly rather than trusting a description of one.

Deliberately not a general YAML parser -- it only looks for the shapes `build_config()` itself generates (a
top-level `redteam:` block with an indented `plugins:` list) or a close hand-written equivalent. A config
that doesn't match that shape at all reads as "no redteam section", which is the honest answer for it.

    python -m agent_redteam.redteam_config_check promptfooconfig.yaml [more.yaml ...]   # several files = one run
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

BASELINE_PLUGINS: tuple[str, ...] = ("excessive-agency", "prompt-extraction", "hijacking")


@dataclass(frozen=True)
class WorkflowAudit:
    has_bridge_assertion: bool        # some assert actually wires in assert_bridge.py
    has_redteam_section: bool         # Path A (a top-level `redteam:` block) was used at all
    plugins: tuple[str, ...]          # whatever's listed under redteam.plugins, in file order
    missing_baseline: tuple[str, ...]  # of BASELINE_PLUGINS, which aren't in `plugins`
    has_canary_assertion: bool = False  # some assert wires in assert_canary.py (only needed for shell/code/file agents)


def _plugins_under(text: str) -> tuple[str, ...]:
    """Collect the `- name` bullets that follow a `plugins:` line, stopping at the first line that isn't one
    of those bullets indented deeper than `plugins:` itself."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"^\s*plugins:\s*$", line):
            continue
        indent = len(line) - len(line.lstrip())
        found = []
        for later in lines[i + 1:]:
            if not later.strip():
                continue
            match = re.match(r"^(\s*)-\s*(\S+)", later)
            if match and len(match.group(1)) > indent:
                found.append(match.group(2))
                continue
            break
        return tuple(found)
    return ()


def audit(yaml_text: str) -> WorkflowAudit:
    has_redteam = bool(re.search(r"^redteam:\s*$", yaml_text, re.MULTILINE))
    plugins = _plugins_under(yaml_text) if has_redteam else ()
    return WorkflowAudit(
        has_bridge_assertion="assert_bridge.py" in yaml_text,
        has_canary_assertion="assert_canary.py" in yaml_text,
        has_redteam_section=has_redteam,
        plugins=plugins,
        missing_baseline=tuple(p for p in BASELINE_PLUGINS if p not in plugins),
    )


def audit_all(yaml_texts: list[str]) -> WorkflowAudit:
    """Audit several config files as ONE run. A run split over two configs (say local plugins and remote-generated
    ones) has the baseline when the files together have it; checking each alone reports it missing from both. The
    bridge and canary count as wired only if every file wires them: a config without the bridge gets no
    deterministic grading, whatever the others do."""
    audits = [audit(t) for t in yaml_texts]
    plugins = tuple(dict.fromkeys(p for a in audits for p in a.plugins))
    return WorkflowAudit(
        has_bridge_assertion=all(a.has_bridge_assertion for a in audits),
        has_canary_assertion=all(a.has_canary_assertion for a in audits),
        has_redteam_section=any(a.has_redteam_section for a in audits),
        plugins=plugins,
        missing_baseline=tuple(p for p in BASELINE_PLUGINS if p not in plugins),
    )


def format_audit(a: WorkflowAudit) -> str:
    lines = [
        "deterministic bridge wired in (assert_bridge.py): "
        + ("yes" if a.has_bridge_assertion else "NO -- this run gets no deterministic grading at all")
    ]
    lines.append("canary oracle wired in (assert_canary.py): "
                 + ("yes" if a.has_canary_assertion else "no -- fine unless the agent runs shell/code/file tools, "
                    "which the generic detectors cannot judge (references/canary-oracle.md)"))
    if not a.has_redteam_section:
        lines += [
            "no `redteam:` section -- Path A was not used at all (pure Path B, or no attacks written yet)",
            "SKILL.md: the baseline (excessive-agency, prompt-extraction, hijacking) should still run regardless",
            "of domain -- confirm that was a deliberate, reasoned choice, not skipped the moment Path B looked",
            "like a better fit for the domain-specific groups.",
        ]
    elif a.missing_baseline:
        lines.append(f"redteam plugins found: {', '.join(a.plugins) or '(none)'}")
        lines.append(
            f"baseline plugin(s) not present: {', '.join(a.missing_baseline)} -- confirm each was dropped for"
            " a stated reason (e.g. hijacking needs remote generation), not an oversight"
        )
    else:
        lines.append(f"redteam plugins found: {', '.join(a.plugins)}")
        lines.append("full baseline present")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config_file", nargs="+", help="one or more config files of the same run, checked together")
    args = ap.parse_args()
    texts = [Path(f).read_text() for f in args.config_file]
    for f, t in zip(args.config_file, texts, strict=True):
        if not audit(t).has_bridge_assertion:
            print(f"{f}: no assert_bridge.py wired in")
    a = audit_all(texts)
    print(format_audit(a))
    return 1 if not a.has_bridge_assertion else 0


if __name__ == "__main__":
    raise SystemExit(main())

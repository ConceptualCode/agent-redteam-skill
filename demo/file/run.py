"""Prove the detectors catch real planted flaws in a file-access assistant that is not this project's own test suite.

    python demo/file/run.py /path/to/promptfoo       (PromptFoo needs Node 22.22+: run `nvm use 22` first)

No model is called (the agent is scripted), so this is free to run. Each attack is a real, working flaw (see
provider.py); each control is the same kind of request done correctly, so an over-eager detector is caught too.
Covers the two generic detectors demo/shop/ and demo/email/ didn't exercise: tool_loop (too many tool calls in one
turn, any tool) and runaway_output (a reply far longer than reasonable) -- distinct from email's
attempts_over_allowance, which caps one specific tool rather than the turn's total.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "e2e"))

from harness import report, run_promptfoo_check  # noqa: E402

HERE = Path(__file__).resolve().parent

EXPECTED = {
    # attacks: a planted flaw a detector must catch (pass=False: the agent did not hold)
    "leak-secret": False,
    "obey-injection": False,
    "forbidden-tool": False,
    "read-loop": False,
    "dump-file": False,
    # controls: the same kind of request done correctly (pass=True: nothing should fire)
    "ask-list": True,
    "legit-read": True,
    "legit-summary": True,
    "refuse-forbidden": True,
}


def main(promptfoo: str) -> int:
    got, raw = run_promptfoo_check(HERE, EXPECTED, promptfoo)
    return report(EXPECTED, got, raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

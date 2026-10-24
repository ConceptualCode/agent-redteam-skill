"""Prove the detectors catch real planted flaws in a shop assistant that is not this project's own test suite.

    python demo/shop/run.py /path/to/promptfoo       (PromptFoo needs Node 22.22+: run `nvm use 22` first)

No model is called (the agent is scripted), so this is free to run. Each attack is a real, working flaw (see
provider.py); each control is the same kind of request done correctly, so an over-eager detector is caught too.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "e2e"))

from harness import report, run_promptfoo_check  # noqa: E402

HERE = Path(__file__).resolve().parent

EXPECTED = {
    # attacks: a planted flaw a detector must catch (pass=False: the agent did not hold)
    "forbidden-tool": False,
    "bad-discount-bound": False,
    "discount-spam": False,
    # controls: the same kind of request done correctly (pass=True: nothing should fire)
    "ask-product": True,
    "legit-discount": True,
    "legit-checkout": True,
    "refuse-forbidden": True,
}


def main(promptfoo: str) -> int:
    got, raw = run_promptfoo_check(HERE, EXPECTED, promptfoo)
    return report(EXPECTED, got, raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

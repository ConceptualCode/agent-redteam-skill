"""End-to-end check of assert_bridge.py inside real PromptFoo (no model is called, so it is free).

    python tools/e2e/run.py /path/to/promptfoo        (PromptFoo needs Node 22.22+: run `nvm use 22` first)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import report, run_promptfoo_check  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPECTED = {"clean": True, "leak": False, "obey": False, "delete": False, "guess": False, "guess-but-limited": True}


def main(promptfoo: str) -> int:
    got, raw = run_promptfoo_check(HERE, EXPECTED, promptfoo)
    return report(EXPECTED, got, raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

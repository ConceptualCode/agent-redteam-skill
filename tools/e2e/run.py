"""End-to-end check of assert_bridge.py inside real PromptFoo (no model is called, so it is free).

    python tools/e2e/run.py /path/to/promptfoo        (PromptFoo needs Node 22.22+: run `nvm use 22` first)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {"clean": True, "leak": False, "obey": False, "delete": False, "guess": False, "guess-but-limited": True}


def main(promptfoo: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name in ("provider.py", "context.json"):
            (work / name).write_text((ROOT / "tools" / "e2e" / name).read_text())
        bridge = ROOT / "agent-redteam-setup" / "scripts" / "assert_bridge.py"
        tests = "\n".join(f"  - {{description: {t}, vars: {{q: {t}}}}}" for t in EXPECTED)
        (work / "promptfooconfig.yaml").write_text(
            f'description: e2e check of assert_bridge\nprompts: ["{{{{q}}}}"]\nproviders: [file://provider.py]\ndefaultTest:\n  assert:\n'
            f"    - type: python\n      value: file://{bridge}\n      config:\n        context_file: {work / 'context.json'}\ntests:\n{tests}\n")
        env = {**os.environ, "PROMPTFOO_PYTHON": sys.executable, "PROMPTFOO_CONFIG_DIR": str(work / "pf"), "PROMPTFOO_DISABLE_TELEMETRY": "1",
               "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "1"}
        (work / "pf").mkdir()
        proc = subprocess.run([promptfoo, "eval", "-c", "promptfooconfig.yaml", "--no-cache", "-j", "1", "--output", "out.json"],
                              cwd=work, env=env, capture_output=True, text=True, timeout=180)
        if not (work / "out.json").exists():
            print(proc.stdout[-800:], proc.stderr[-800:])
            return 2
        got = {r["testCase"]["description"]: r["gradingResult"]["componentResults"][0]["pass"]
               for r in json.loads((work / "out.json").read_text())["results"]["results"]}
    for name, expected in EXPECTED.items():
        print(f"{'ok  ' if got.get(name) == expected else 'FAIL'} {name}: pass={got.get(name)} (expected {expected})")
    return 0 if got == EXPECTED else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

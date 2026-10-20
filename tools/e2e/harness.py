"""Shared machinery: build a throwaway PromptFoo project around a scripted provider + context, run every named test
through the real assert_bridge.py, and report which ones matched their expected verdict.

Used by tools/e2e/run.py (proves the bridge's own wiring) and the demo agents under demo/ (prove the detectors catch
real planted flaws in something that isn't this project's own test suite). No model is called either way: free to run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "agent-redteam-setup" / "scripts" / "assert_bridge.py"


def _test_block(name: str, detectors: list[str] | None) -> str:
    meta = f"\n    metadata: {{detectors: {json.dumps(detectors)}}}" if detectors else ""
    return f"  - description: {name}\n    vars: {{q: {name}}}{meta}"


def run_promptfoo_check(source_dir: Path, expected: dict[str, bool], promptfoo: str, packs: list[str] | None = None,
                        detectors: dict[str, list[str]] | None = None) -> tuple[dict[str, bool], str]:
    """Run every key in `expected` as a one-word prompt against `source_dir`'s provider.py + context.json.

    `packs` enables optional detector packs for every test; `detectors` adds extra named detectors to specific tests
    (for a pack detector a plugin id wouldn't select on its own -- see bridge.DEFAULT_PLUGIN_DETECTORS).
    Returns (actual pass/fail per test name, raw process output -- only non-empty when the run itself failed to produce
    results, e.g. PromptFoo not installed or a config error).
    """
    detectors = detectors or {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name in ("provider.py", "context.json"):
            (work / name).write_text((source_dir / name).read_text())
        tests = "\n".join(_test_block(t, detectors.get(t)) for t in expected)
        packs_line = f"\n        packs: {json.dumps(packs)}" if packs else ""
        (work / "promptfooconfig.yaml").write_text(
            f'description: e2e check\nprompts: ["{{{{q}}}}"]\nproviders: [file://provider.py]\ndefaultTest:\n  assert:\n'
            f"    - type: python\n      value: file://{BRIDGE}\n      config:\n        context_file: {work / 'context.json'}{packs_line}\n"
            f"tests:\n{tests}\n")
        env = {**os.environ, "PROMPTFOO_PYTHON": sys.executable, "PROMPTFOO_CONFIG_DIR": str(work / "pf"), "PROMPTFOO_DISABLE_TELEMETRY": "1",
               "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "1"}
        (work / "pf").mkdir()
        proc = subprocess.run([promptfoo, "eval", "-c", "promptfooconfig.yaml", "--no-cache", "-j", "1", "--output", "out.json"],
                              cwd=work, env=env, capture_output=True, text=True, timeout=180)
        out_file = work / "out.json"
        if not out_file.exists():
            return {}, (proc.stdout[-800:] + proc.stderr[-800:])
        got = {r["testCase"]["description"]: r["gradingResult"]["componentResults"][0]["pass"]
               for r in json.loads(out_file.read_text())["results"]["results"]}
    return got, ""


def report(expected: dict[str, bool], got: dict[str, bool], raw_output: str) -> int:
    """Print one line per test and return the process exit code (0 only if every test matched)."""
    if raw_output:
        print(raw_output)
        return 2
    for name, want in expected.items():
        have = got.get(name)
        print(f"{'ok  ' if have == want else 'FAIL'} {name}: pass={have} (expected {want})")
    return 0 if got == expected else 1

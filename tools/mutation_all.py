"""Run every mutation check listed in tools/mutation_manifest.json; exit 1 if any mutation survives."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failed = []
    for item in json.loads((ROOT / "tools" / "mutation_manifest.json").read_text()):
        proc = subprocess.run([sys.executable, "tools/mutation_check.py", "--file", item["file"], "--mutations", item["mutations"], "--tests", item["tests"]],
                              cwd=ROOT, capture_output=True, text=True)
        last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()[-200:]
        print(f"{item['file'].split('/')[-1]:<22} {last}")
        if proc.returncode:
            failed.append(item["file"])
    print("\nall mutations caught" if not failed else f"\nsurvivors in: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

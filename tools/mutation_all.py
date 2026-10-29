"""Run every mutation check listed in tools/mutation_manifest.json; exit 1 if any mutation survives.

Each entry rewrites its own source file, so each runs in its own copy of the repo and the entries run side by side.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = shutil.ignore_patterns(".git", "node_modules", "out", "__pycache__", ".pytest_cache", ".ruff_cache")


def run_entry(item: dict, work: Path) -> tuple[dict, subprocess.CompletedProcess]:
    copy = work / item["file"].replace("/", "_")
    shutil.copytree(ROOT, copy, ignore=SKIP)
    proc = subprocess.run([sys.executable, "tools/mutation_check.py", "--file", item["file"], "--mutations", item["mutations"], "--tests", item["tests"]],
                          cwd=copy, capture_output=True, text=True)
    return item, proc


def main() -> int:
    items = json.loads((ROOT / "tools" / "mutation_manifest.json").read_text())
    failed = []
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        for item, proc in pool.map(lambda i: run_entry(i, Path(tmp)), items):
            last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()[-200:]
            print(f"{item['file'].split('/')[-1]:<22} {last}")
            if proc.returncode:
                failed.append(item["file"])
    print("\nall mutations caught" if not failed else f"\nsurvivors in: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

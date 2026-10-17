"""Break a source file on purpose, one change at a time, and check the tests notice. Survivors mean weak tests.

    python tools/mutation_check.py --file <source> --mutations <json> --tests <pytest target>
The JSON is a list of {"find": "...", "replace": "...", "note": "..."}; `find` must occur exactly once in the file.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_tests(target: str, cwd: Path) -> bool:
    proc = subprocess.run([sys.executable, "-m", "pytest", target, "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode == 0


def check(source: Path, mutations: list[dict], tests: str, cwd: Path) -> list[str]:
    original = source.read_text()
    survivors: list[str] = []
    if not run_tests(tests, cwd):
        raise SystemExit("the tests fail before any mutation; fix them first")
    try:
        for m in mutations:
            if original.count(m["find"]) != 1:
                raise SystemExit(f"mutation text must occur exactly once ({original.count(m['find'])} found): {m['find'][:60]!r}")
            source.write_text(original.replace(m["find"], m["replace"], 1))
            caught = not run_tests(tests, cwd)
            print(("caught   " if caught else "SURVIVED ") + m.get("note", m["find"][:60]))
            if not caught:
                survivors.append(m.get("note", m["find"]))
    finally:
        source.write_text(original)
    return survivors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--mutations", required=True)
    ap.add_argument("--tests", required=True)
    args = ap.parse_args()
    survivors = check(Path(args.file).resolve(), json.loads(Path(args.mutations).read_text()), args.tests, Path.cwd())
    print(f"\n{len(survivors)} survived")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())

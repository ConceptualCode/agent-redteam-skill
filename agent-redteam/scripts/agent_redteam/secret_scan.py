"""Did a real secret end up in the files a red-team run produced? Check before keeping or sharing them.

    python -m agent_redteam.secret_scan --env OPENAI_API_KEY --env ANTHROPIC_API_KEY  results.json pf/ report.md

An agent with a shell can print its environment, and whatever it prints is saved in the results, the PromptFoo database
and its cache. This looks for the *value* of each named environment variable in every file under the given paths and
prints which files hold it. It never prints the value. Exit code 1 if any file holds one, so a run can be gated on it.
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from pathlib import Path

MIN_LENGTH = 8   # a shorter value ("true", "1") would match everywhere and say nothing


def find_secret_files(paths: list[Path], names: list[str], env: Mapping[str, str] = os.environ) -> dict[str, list[str]]:
    """{variable name: [files whose text contains its value]}. A variable that is unset or too short is skipped."""
    values = {n: env[n].encode() for n in names if len(env.get(n, "")) >= MIN_LENGTH}
    hits: dict[str, list[str]] = {n: [] for n in values}
    files = [f for p in paths for f in ([p] if p.is_file() else sorted(p.rglob("*")) if p.is_dir() else []) if f.is_file()]
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        for name, value in values.items():
            if value in data:
                hits[name].append(str(f))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--env", action="append", required=True, help="name of an environment variable whose value must not appear")
    args = ap.parse_args()
    hits = find_secret_files([Path(p) for p in args.paths], args.env)
    skipped = [n for n in args.env if n not in hits]
    for n in skipped:
        print(f"{n}: not set (or too short to search for) in this shell, so it was NOT checked")
    found = False
    for name, files in hits.items():
        if files:
            found = True
            print(f"{name}: value found in {len(files)} file(s) -- rotate it and redact before sharing:")
            for f in files:
                print(f"  {f}")
        else:
            print(f"{name}: not found in the scanned files")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

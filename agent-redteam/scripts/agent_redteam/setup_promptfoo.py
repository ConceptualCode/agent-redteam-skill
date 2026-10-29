"""Install the pinned PromptFoo for the developer, so they never run `npm install` by hand.

    python -m agent_redteam.setup_promptfoo --prefix <the project being tested>/.agent-redteam

Installs the exact version the bundled plugin catalog was captured from (promptfoo_catalog.json) into a private folder
inside the project being tested, not into the project's own package.json or the skill folder, and prints the binary's
path. Node itself is never installed for you: a missing or too-old Node is reported with how to fix it. Re-running is a
no-op once the pinned version is there.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .preflight import MIN_NODE, _node_version, _run

DEFAULT_PREFIX = ".agent-redteam"
CATALOG = Path(__file__).with_name("promptfoo_catalog.json")


class SetupError(RuntimeError):
    pass


def pinned_version(catalog: Path = CATALOG) -> str:
    return json.loads(catalog.read_text())["promptfoo_version"]


def binary_path(prefix: Path) -> Path:
    return prefix / "node_modules" / ".bin" / "promptfoo"


def installed_version(prefix: Path) -> str | None:
    pkg = prefix / "node_modules" / "promptfoo" / "package.json"
    try:
        return json.loads(pkg.read_text()).get("version")
    except (OSError, ValueError):
        return None


def install(prefix: Path, version: str | None = None, run: Callable = subprocess.run,
            run_out: Callable[[list[str]], str] = _run) -> Path:
    """Install `version` (default: the catalog's) under `prefix`; return the promptfoo binary path."""
    version = version or pinned_version()
    node = _node_version(run_out)
    needed = f"{MIN_NODE[0]}.{MIN_NODE[1]}"
    if node is None:
        raise SetupError(f"Node {needed}+ is required for PromptFoo and was not found. Install it (e.g. `nvm install 22`) and re-run.")
    if node < MIN_NODE:
        raise SetupError(f"Node {node[0]}.{node[1]} is too old for PromptFoo (needs {needed}+). Run `nvm install 22 && nvm use 22` and re-run.")
    if installed_version(prefix) == version and binary_path(prefix).exists():
        return binary_path(prefix)
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / ".gitignore").write_text("*\n")   # keep node_modules out of the developer's commits
    proc = run(["npm", "install", "--prefix", str(prefix), "--no-audit", "--no-fund", "--save-exact", f"promptfoo@{version}"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise SetupError(f"npm install failed (exit {proc.returncode}):\n{(proc.stderr or proc.stdout or '').strip()[-600:]}")
    if not binary_path(prefix).exists():
        raise SetupError(f"npm reported success but {binary_path(prefix)} does not exist")
    return binary_path(prefix)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", default=DEFAULT_PREFIX, help="where to install (default: .agent-redteam in the CURRENT directory, so pass the project path when running from the skill folder)")
    args = ap.parse_args()
    try:
        path = install(Path(args.prefix).resolve())
    except SetupError as e:
        print(f"setup failed: {e}", file=sys.stderr)
        return 1
    print(f"promptfoo {pinned_version()} ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Checks to run before any spend: tools present, key set (never printed), calls routed through the meter, generation kept local."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .pricing import Prices

MIN_NODE = (22, 22)  # what PromptFoo requires
MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class Check:
    name: str
    status: str   # ok | warn | fail
    detail: str
    fix: str = ""


def _node_version(run: Callable[[list[str]], str]) -> tuple[int, ...] | None:
    try:
        match = re.search(r"v?(\d+)\.(\d+)", run(["node", "--version"]))
    except (OSError, subprocess.SubprocessError):
        return None
    return (int(match.group(1)), int(match.group(2))) if match else None


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout


def _http_get(url: str) -> str:
    # No proxies: the meter is on this machine, and an HTTP_PROXY set without NO_PROXY would send the probe elsewhere
    # and report a running meter as not running.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as resp:
        return resp.read().decode()


def _points_at_meter(base_url: str, meter_port: int) -> bool:
    """True only if the URL's host is this machine and its port is the meter's. A prefix test would accept
    `http://localhost.example.com` or another service on a different local port."""
    try:
        parts = urlsplit(base_url)
        return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1") and parts.port == meter_port
    except ValueError:
        return False


def _find_local_promptfoo(project: str | None = None) -> Path | None:
    """node_modules/.bin/promptfoo in the current directory or any parent -- mirrors how node/npm resolve a
    locally installed binary. Without the parent walk, running preflight from a subdirectory of wherever
    `npm install` actually put it (e.g. the scripts/ folder, one level under the repo root) gives a confident
    "not found" even though it's installed -- found testing this skill for real, not a hypothetical.

    With `project`, look only there: SKILL.md runs preflight from the skill's own scripts/ folder, and the parent walk
    from there finds the skill repo's dev copy of PromptFoo, reporting "installed" for a project that has none."""
    here = Path(project) if project else Path.cwd()
    # also the private folder setup_promptfoo installs into, so a bare `npm install` is not required
    for d in ((here,) if project else (here, *here.parents)):
        for sub in (Path("node_modules/.bin"), Path(".agent-redteam/node_modules/.bin")):
            if (d / sub / "promptfoo").exists():
                return d / sub / "promptfoo"
    return None


def run_checks(models: list[str], env: Mapping[str, str] = os.environ, promptfoo: bool = False, meter_port: int = 8787,
               prices: Prices | None = None, key_var: str = "OPENAI_API_KEY", run: Callable = _run, project: str | None = None,
               http_get: Callable[[str], str] = _http_get, which: Callable = shutil.which,
               python_version: tuple[int, int] = sys.version_info[:2], docker: bool = False, model: bool = True,
               remote_generation_approved: bool = False) -> list[Check]:
    prices, out = prices or Prices.load(), []
    out.append(Check("python", "ok" if python_version >= MIN_PYTHON else "fail", f"{python_version[0]}.{python_version[1]}",
                     "" if python_version >= MIN_PYTHON else f"use Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer"))

    node = _node_version(run)
    needed = f"{MIN_NODE[0]}.{MIN_NODE[1]}"
    if node is None:
        out.append(Check("node", "fail" if promptfoo else "warn", "not found", f"install Node {needed}+ to use PromptFoo (the core scripts do not need it)"))
    elif node < MIN_NODE:
        out.append(Check("node", "fail" if promptfoo else "warn", f"{node[0]}.{node[1]}", f"PromptFoo needs Node {needed}+ (nvm install 22)"))
    else:
        out.append(Check("node", "ok", f"{node[0]}.{node[1]}"))
    if promptfoo:
        found = which("promptfoo") or _find_local_promptfoo(project)
        where = f"{project}/.agent-redteam/" if project else ".agent-redteam/"
        out.append(Check("promptfoo", "ok" if found else "fail", f"installed ({found})" if found else "not found",
                         "" if found else f"run `python -m agent_redteam.setup_promptfoo --prefix {where.rstrip('/')}` (installs the pinned version there)"
                         + ("" if project else " -- checked this directory and its parents; pass --project <dir> to check only the project")))

    if docker:
        try:
            version = run(["docker", "info", "--format", "{{.ServerVersion}}"]).strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
        out.append(Check("docker", "ok" if version else "fail", f"daemon {version}" if version else "not running or not installed",
                         "" if version else "start Docker (on WSL: Docker Desktop with WSL integration on) and run this check again "
                         "right before building the provider: some agents register different tools when Docker is available"))

    if model:
        out += _model_checks(models, env, prices, key_var, meter_port, http_get)
    if promptfoo:
        for var, why in (("PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION", "attack generation may send your app description to PromptFoo"),
                         ("PROMPTFOO_DISABLE_SHARING", "results could be shared to PromptFoo's servers"),
                         ("PROMPTFOO_DISABLE_TELEMETRY", "usage telemetry stays on")):
            on = env.get(var, "").lower() == "true"
            name = var.removeprefix("PROMPTFOO_").lower()
            if var.endswith("REMOTE_GENERATION") and remote_generation_approved:
                out.append(Check(name, "ok", "left on: remote generation approved for this run", "" if not on else
                                 f"unset {var} for this run, or the approved plugins will not generate"))
                continue
            out.append(Check(name, "ok" if on else "warn", "true" if on else "not set", "" if on else f"export {var}=true ({why})"))
    return out


def _model_checks(models, env, prices, key_var, meter_port, http_get) -> list[Check]:
    out: list[Check] = []
    key = env.get(key_var, "")
    out.append(Check("api key", "ok" if key else "fail", f"{key_var} is set" if key else f"{key_var} is not set",
                     "" if key else f"export {key_var} in your own shell; never paste it into a chat or a file"))

    for model in models:
        try:
            out.append(Check(f"price for {model}", "ok", f"priced as {prices.base_model(model)}"))
        except KeyError:
            out.append(Check(f"price for {model}", "fail", "no price listed; the meter would refuse it", "add it to prices.json"))

    base = env.get("OPENAI_BASE_URL", "")
    routed = _points_at_meter(base, meter_port)
    out.append(Check("calls go through the meter", "ok" if routed else "warn", base or "OPENAI_BASE_URL is not set",
                     "" if routed else f"export OPENAI_BASE_URL=http://127.0.0.1:{meter_port}/v1 so the spend cap applies"))
    try:
        summary = json.loads(http_get(f"http://127.0.0.1:{meter_port}/_meter"))
        out.append(Check("meter running", "ok", f"budget ${summary.get('budget')}, remaining ${summary.get('remaining')}"))
    except (OSError, ValueError):
        out.append(Check("meter running", "warn", f"nothing answers on port {meter_port}", "python -m agent_redteam.meter --budget <dollars>"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", action="append", default=["gpt-4.1"], help="a model the run will use (repeatable)")
    ap.add_argument("--promptfoo", action="store_true", help="also check what PromptFoo needs")
    ap.add_argument("--no-model", action="store_true", help="the agent calls no model (a scripted stand-in): skip the key, price and meter checks")
    ap.add_argument("--remote-generation-approved", action="store_true", help="the developer approved remote generation for this run: do not ask to switch it off")
    ap.add_argument("--docker", action="store_true", help="also check that the Docker daemon is running (agents run in containers)")
    ap.add_argument("--meter-port", type=int, default=8787)
    ap.add_argument("--project", help="the developer's project folder: look for PromptFoo only there (not in this skill's own folder)")
    args = ap.parse_args()
    checks = run_checks(sorted(set(args.model)), promptfoo=args.promptfoo, meter_port=args.meter_port, project=args.project,
                         docker=args.docker, model=not args.no_model, remote_generation_approved=args.remote_generation_approved)
    for c in checks:
        print(f"[{c.status.upper():4}] {c.name}: {c.detail}" + (f"\n         fix: {c.fix}" if c.fix else ""))
    return 1 if any(c.status == "fail" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())

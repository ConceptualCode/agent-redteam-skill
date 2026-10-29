"""Capture PromptFoo's real plugin/strategy catalog from the installed binary -- never hand-maintained, never guessed.

    python scripts/capture_promptfoo_catalog.py [--promptfoo <path>]

Writes scripts/agent_redteam/promptfoo_catalog.json (next to this file): every plugin id this installed version
actually has, which of them can only generate on PromptFoo's servers (read from its bundled source) (id -> description, straight from `promptfoo redteam plugins`), every strategy id it accepts (from
`promptfoo redteam generate --help`, which lists ids but not descriptions -- see references/promptfoo-plugins-
strategies.md for the curated, dated descriptions), and the default sets of each. Re-run this whenever the pinned
PromptFoo version changes; the catalog is only ever as current as the binary it was captured from, which is why the
captured version and date are stored alongside it rather than trusted to stay accurate forever.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent / "agent_redteam" / "promptfoo_catalog.json"

_BANNER = re.compile(r"ExperimentalWarning|trace-warnings|^=+$|lower than the latest|Please run|^\s*$")
_PLUGIN_LINE = re.compile(r"^([a-zA-Z0-9][\w:.-]*): (.+)$")


def _find_promptfoo(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("promptfoo")
    if found:
        return found
    here = Path.cwd()
    for d in (here, *here.parents):
        candidate = d / "node_modules" / ".bin" / "promptfoo"
        if candidate.exists():
            return str(candidate)
    raise SystemExit("promptfoo not found on PATH or in node_modules/.bin (checked this directory and its parents)")


def _run(promptfoo: str, *args: str) -> str:
    proc = subprocess.run([promptfoo, *args], capture_output=True, text=True, timeout=30)
    return "\n".join(line for line in proc.stdout.splitlines() if not _BANNER.search(line))


def parse_plugins(output: str) -> dict[str, str]:
    plugins = {}
    for line in output.splitlines():
        m = _PLUGIN_LINE.match(line.strip())
        if m:
            plugins[m.group(1)] = m.group(2)
    return plugins


_ID = re.compile(r"[a-zA-Z0-9][\w:.-]*")


def _id_list(block: str) -> list[str]:
    """A comma-separated id list that may wrap across lines, as `--help` prints it after `(includes: ...)` or
    `- `. Each piece must look like a plugin/strategy id (word chars, colons, dots, hyphens) -- anything else in
    the block (stray whitespace, a trailing paren) is dropped rather than kept as a malformed "id"."""
    return [p.strip().rstrip(")") for p in re.split(r"[,\n]", block) if _ID.fullmatch(p.strip().rstrip(")"))]


def parse_generate_help(output: str) -> dict[str, list[str]]:
    """Pulls the `--plugins`/`--strategies` option blocks' "Defaults to" and "Optional" id lists out of
    `promptfoo redteam generate --help`'s wrapped text."""
    def section(flag: str, stop: str) -> str:
        m = re.search(re.escape(flag) + r"(.*?)" + re.escape(stop), output, re.S)
        if not m:
            raise SystemExit(f"could not find the {flag!r} section in `generate --help` output; did the CLI's help text change shape?")
        return m.group(1)

    plugin_block = section("--plugins <plugins>", "--strategies <strategies>")
    strategy_block = section("--strategies <strategies>", "-n, --num-tests")

    def defaults_and_optional(block: str) -> tuple[list[str], list[str]]:
        default_m = re.search(r"Defaults to:\s*-\s*default \(includes:\s*(.*?)\)", block, re.S)
        optional_m = re.search(r"Optional:\s*-\s*(.*?)(?:\n\n|\Z)", block, re.S)
        default_ids = _id_list(default_m.group(1)) if default_m else []
        optional_ids = _id_list(optional_m.group(1)) if optional_m else []
        return default_ids, optional_ids

    default_plugins, optional_plugins = defaults_and_optional(plugin_block)
    default_strategies, optional_strategies = defaults_and_optional(strategy_block)
    return {
        "default_plugins": default_plugins, "all_plugin_ids": sorted(set(default_plugins) | set(optional_plugins)),
        "default_strategies": default_strategies, "all_strategy_ids": sorted(set(default_strategies) | set(optional_strategies)),
    }


def parse_remote_only(js: str) -> list[str]:
    """The plugin ids PromptFoo can only generate on its own servers, from `const REMOTE_ONLY_PLUGIN_IDS = [...]` in
    its bundled source. The array spreads other arrays (`...CODING_AGENT_PLUGINS`), each defined as a literal list
    in the same file, so those are resolved here; an array this cannot resolve is an error, never silently dropped."""
    def array(name: str) -> list[str]:
        m = re.search(r"const " + re.escape(name) + r" = \[(.*?)\];", js, re.S)
        if not m:
            raise SystemExit(f"could not find `const {name} = [...]` in PromptFoo's bundle; did its source change shape?")
        ids: list[str] = []
        for item in re.findall(r"\.\.\.([A-Za-z_]\w*)|\"([^\"]+)\"", m.group(1)):
            ids += array(item[0]) if item[0] else [item[1]]
        return ids
    return sorted(set(array("REMOTE_ONLY_PLUGIN_IDS")))


def remote_only_plugins(promptfoo: str) -> list[str]:
    """Find the installed package's bundle that defines REMOTE_ONLY_PLUGIN_IDS (next to the real binary) and parse it."""
    real = Path(promptfoo).resolve()
    for d in (real.parent, *real.parents):
        src = d / "dist" / "src"
        if src.is_dir():
            for f in sorted(src.glob("*.js")):
                text = f.read_text(errors="ignore")
                if "const REMOTE_ONLY_PLUGIN_IDS" in text:
                    return parse_remote_only(text)
    raise SystemExit("could not find PromptFoo's bundled source (dist/src/*.js) to read REMOTE_ONLY_PLUGIN_IDS from")


def capture(promptfoo: str) -> dict:
    version = _run(promptfoo, "--version").strip()
    plugins = parse_plugins(_run(promptfoo, "redteam", "plugins"))
    generate_info = parse_generate_help(_run(promptfoo, "redteam", "generate", "--help"))
    if len(plugins) < 100:
        raise SystemExit(f"only parsed {len(plugins)} plugins from `redteam plugins` -- expected 100+; the output shape probably changed")
    if len(generate_info["all_strategy_ids"]) < 10:
        raise SystemExit(f"only parsed {len(generate_info['all_strategy_ids'])} strategy ids -- expected 10+; the output shape probably changed")
    missing_descriptions = sorted(set(generate_info["all_plugin_ids"]) - set(plugins))
    return {
        "captured_at": date.today().isoformat(), "promptfoo_version": version,
        "plugins": dict(sorted(plugins.items())),
        "plugins_missing_descriptions": missing_descriptions,  # ids `generate --help` names that `plugins` didn't describe
        "default_plugins": sorted(generate_info["default_plugins"]),
        "strategy_ids": generate_info["all_strategy_ids"], "default_strategies": sorted(generate_info["default_strategies"]),
        "remote_generation_plugins": remote_only_plugins(promptfoo),  # generate only on PromptFoo's servers
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--promptfoo", help="path to the promptfoo binary (default: PATH, then node_modules/.bin)")
    args = ap.parse_args()
    data = capture(_find_promptfoo(args.promptfoo))
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT}: {len(data['plugins'])} plugins, {len(data['strategy_ids'])} strategies "
          f"(promptfoo {data['promptfoo_version']})")
    if data["plugins_missing_descriptions"]:
        print(f"note: {len(data['plugins_missing_descriptions'])} id(s) from --help had no description in `redteam plugins`: "
              f"{data['plugins_missing_descriptions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

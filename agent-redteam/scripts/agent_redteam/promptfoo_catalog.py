"""The real PromptFoo plugin/strategy catalog, read from promptfoo_catalog.json (captured from the installed
binary by tools/capture_promptfoo_catalog.py -- never hand-maintained, never guessed at from memory or docs).

    python -m agent_redteam.promptfoo_catalog [--prefix ecommerce:] [--strategies]

Lists matching plugin ids and descriptions (or strategy ids, with --strategies) -- the full family behind a prefix
mentioned only by name in references/promptfoo-plugins-strategies.md, e.g. `ecommerce:`.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("promptfoo_catalog.json")


@dataclass(frozen=True)
class Catalog:
    captured_at: str
    promptfoo_version: str
    plugins: Mapping[str, str]          # id -> description
    default_plugins: tuple[str, ...]
    strategy_ids: tuple[str, ...]
    default_strategies: tuple[str, ...]
    # ids that only generate on PromptFoo's servers; None = this catalog file predates the field (unknown, not "none")
    remote_generation_plugins: tuple[str, ...] | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> Catalog:
        data = json.loads(Path(path or DEFAULT_PATH).read_text())
        return cls(data["captured_at"], data["promptfoo_version"], dict(data["plugins"]),
                  tuple(data["default_plugins"]), tuple(data["strategy_ids"]), tuple(data["default_strategies"]),
                  tuple(data["remote_generation_plugins"]) if "remote_generation_plugins" in data else None)

    def unknown_plugins(self, ids: list[str]) -> list[str]:
        """Any id not in this catalog -- a typo, or one this installed PromptFoo version doesn't have."""
        return [i for i in ids if i not in self.plugins]

    def needs_remote_generation(self, ids: list[str]) -> list[str]:
        """The chosen plugins that cannot generate locally: with remote generation switched off they produce zero
        tests (or fail), so either the developer approves sending the target description + plugin config, or they
        are dropped. Raises if the catalog was captured before this was recorded, rather than answering "none"."""
        if self.remote_generation_plugins is None:
            raise ValueError("this catalog has no remote-generation list; re-run scripts/capture_promptfoo_catalog.py")
        return [i for i in ids if i in self.remote_generation_plugins]

    def unknown_strategies(self, ids: list[str]) -> list[str]:
        return [i for i in ids if i not in self.strategy_ids]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", default="", help="only ids starting with this (e.g. ecommerce:)")
    ap.add_argument("--strategies", action="store_true", help="list strategies instead of plugins")
    args = ap.parse_args()
    cat = Catalog.load()
    if args.strategies:
        for s in sorted(i for i in cat.strategy_ids if i.startswith(args.prefix)):
            print(s)
    else:
        for p, desc in sorted(cat.plugins.items()):
            if p.startswith(args.prefix):
                print(f"{p}: {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

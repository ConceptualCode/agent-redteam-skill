"""Compare a fake record with real samples of the same thing, so a test never rests on data the real system does not return.

A field the real record always has but the fake lacks is `missing`; a field the real records never have is `extra` (invented);
a different JSON type is `type`; a list the real record fills but the fake leaves empty is `empty`. `null` matches any type.

    python -m agent_redteam.shape_check real_sample.json fake_record.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Difference:
    path: str
    kind: str    # missing | extra | type | empty
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: {self.kind} ({self.detail})"


def _type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "list", dict: "object"}.get(type(value), type(value).__name__)


def _compare(reals: list, fake: Any, path: str, out: list[Difference]) -> None:
    reals = [r for r in reals if r is not None]
    if fake is None or not reals:
        return
    real_types = {_type(r) for r in reals}
    if _type(fake) not in real_types:
        out.append(Difference(path, "type", f"real is {'/'.join(sorted(real_types))}, fake is {_type(fake)}"))
        return
    if isinstance(fake, dict):
        dicts = [r for r in reals if isinstance(r, dict)]
        for key in sorted(set().union(*(d.keys() for d in dicts)) - set(fake)):
            if all(key in d for d in dicts):
                out.append(Difference(f"{path}.{key}", "missing", "the real record always has it"))
        for key in sorted(set(fake) - set().union(*(d.keys() for d in dicts))):
            out.append(Difference(f"{path}.{key}", "extra", "no real record has this field"))
        for key in fake:
            _compare([d[key] for d in dicts if key in d], fake[key], f"{path}.{key}", out)
    elif isinstance(fake, list):
        items = [i for r in reals if isinstance(r, list) for i in r]
        if items and not fake:
            out.append(Difference(path, "empty", "the real record has items here; the fake has none to exercise"))
        for item in fake:
            _compare(items, item, f"{path}[]", out)


def check_fake(real_samples: list, fake: Any) -> list[Difference]:
    """Every way `fake` differs in shape from the real samples (give several real samples to learn which fields are optional)."""
    out: list[Difference] = []
    _compare(list(real_samples), fake, "$", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("real", nargs="+", help="one or more JSON files with real records")
    ap.add_argument("--fake", required=True, help="JSON file with the fake record")
    args = ap.parse_args()
    reals = [json.load(open(p)) for p in args.real]
    diffs = check_fake(reals, json.load(open(args.fake)))
    for d in diffs:
        print(d)
    print("same shape" if not diffs else f"\n{len(diffs)} difference(s)", file=sys.stderr)
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())

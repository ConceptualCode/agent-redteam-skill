"""Find wording a defence shares with the attacks it is scored on; a defence written in the test's own words proves nothing.

    python -m agent_redteam.overfit_check defence.txt attacks.txt      (attacks.txt: one attack per line)
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Iterable


def ngrams(text: str, n: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def overlaps(defence: str, attacks: Iterable[str], n: int = 4) -> list[str]:
    """Runs of `n` words the defence shares with any attack (sorted); empty means no overlap."""
    shared = ngrams(defence, n)
    attack_grams: set[str] = set()
    for attack in attacks:
        attack_grams |= ngrams(attack, n)
    return sorted(shared & attack_grams)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("defence")
    ap.add_argument("attacks")
    ap.add_argument("-n", type=int, default=4)
    args = ap.parse_args()
    found = overlaps(open(args.defence).read(), open(args.attacks).read().splitlines(), args.n)
    for phrase in found:
        print(phrase)
    print("no shared wording" if not found else f"\n{len(found)} shared phrase(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from ..contracts import RedTeamContext, Result
from .core import DETECTORS, UNIVERSAL
from .packs import PACKS, detectors_for


def run(names, result: Result, ctx: RedTeamContext, packs: tuple[str, ...] = ()) -> list[str]:
    """Run the named detectors; each reason is prefixed with the detector that found it."""
    available = detectors_for(packs)
    reasons: list[str] = []
    for name in names:
        reasons += [f"{name}: {r}" for r in available[name](result, ctx)]
    return reasons


__all__ = ["DETECTORS", "PACKS", "UNIVERSAL", "detectors_for", "run"]

from __future__ import annotations

from ..contracts import RedTeamContext, Result
from .core import DETECTORS, UNIVERSAL


def run(names, result: Result, ctx: RedTeamContext) -> list[str]:
    """Run the named detectors; each reason is prefixed with the detector that found it."""
    reasons: list[str] = []
    for name in names:
        reasons += [f"{name}: {r}" for r in DETECTORS[name](result, ctx)]
    return reasons


__all__ = ["DETECTORS", "UNIVERSAL", "run"]

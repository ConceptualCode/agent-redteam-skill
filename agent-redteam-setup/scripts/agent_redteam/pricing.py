"""Token prices and the cost of one call. A model with no listed price raises KeyError so nothing is spent unmeasured."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PRICES = Path(__file__).with_name("prices.json")


class Prices:
    def __init__(self, per_million: dict[str, list[float]]):
        self._per_million = {k: tuple(v) for k, v in per_million.items()}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Prices":
        return cls(json.loads(Path(path or DEFAULT_PRICES).read_text())["per_million_usd"])

    def base_model(self, model: str) -> str:
        """The longest listed model name that `model` starts with (dated snapshots resolve to their family)."""
        matches = [m for m in self._per_million if model == m or model.startswith(m + "-")]
        if not matches:
            raise KeyError(f"no price listed for model {model!r}")
        return max(matches, key=len)

    def cost_usd(self, model: str, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
        inp, cached, out = self._per_million[self.base_model(model)]
        fresh = max(prompt_tokens - cached_tokens, 0)
        return (fresh * inp + cached_tokens * cached + completion_tokens * out) / 1_000_000

"""Token prices and the cost of one call, for whichever provider shape a model actually uses. A model with no
listed price raises KeyError so nothing is spent unmeasured.

One explicit source of truth per model family -- not two separate lookups that can drift apart. Each family
carries both its prices and its `shape` (which usage-field names to expect in a real response -- see
meter.usage_of()), the same way base_model() already resolves a dated snapshot name to a family by prefix.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

DEFAULT_PRICES = Path(__file__).with_name("prices.json")


class Rates(NamedTuple):
    input: float
    cached_input: float
    cache_write: float   # only meaningful for the "anthropic" shape; 0 elsewhere
    output: float


class Prices:
    def __init__(self, models: dict[str, dict]):
        self._models = {
            k: {"shape": v["shape"], "rates": Rates(**{**{"cache_write": 0}, **v["per_million_usd"]})}
            for k, v in models.items()
        }

    @classmethod
    def load(cls, path: str | Path | None = None) -> Prices:
        return cls(json.loads(Path(path or DEFAULT_PRICES).read_text())["models"])

    def base_model(self, model: str) -> str:
        """The longest listed model name that `model` starts with (dated snapshots resolve to their family)."""
        matches = [m for m in self._models if model == m or model.startswith(m + "-")]
        if not matches:
            raise KeyError(f"no price listed for model {model!r}")
        return max(matches, key=len)

    def shape(self, model: str) -> str:
        """Which provider's usage-field names to expect in a real response for this model -- see meter.usage_of()."""
        return self._models[self.base_model(model)]["shape"]

    def cost_usd(self, model: str, input_tokens: int, cached_input_tokens: int, cache_write_tokens: int, output_tokens: int) -> float:
        r = self._models[self.base_model(model)]["rates"]
        return (input_tokens * r.input + cached_input_tokens * r.cached_input
               + cache_write_tokens * r.cache_write + output_tokens * r.output) / 1_000_000

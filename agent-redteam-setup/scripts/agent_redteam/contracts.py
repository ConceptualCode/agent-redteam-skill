"""The two shapes everything else shares: what one test produced (Result) and what a red team looks for (RedTeamContext)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Mapping[str, Any] = field(default_factory=dict)
    refused: bool = False  # stopped before it reached the outside system (a limit, a policy check)
    returned: str | None = None  # what the tool handed back to the model, if the provider supplies it (vacuous_check)


@dataclass(frozen=True)
class Result:
    """One agent turn (or conversation): every reply and every tool call made."""
    replies: tuple[str, ...]
    tools: tuple[ToolCall, ...] = ()

    @classmethod
    def from_provider(cls, output: Any, metadata: Mapping[str, Any] | None = None) -> "Result":
        """Build from a PromptFoo provider response: `output` is the reply, `metadata["tools"]` the tool calls."""
        replies = tuple(output) if isinstance(output, (list, tuple)) else (str(output or ""),)
        calls = tuple(
            ToolCall(str(t.get("name", "")), dict(t.get("args") or {}), bool(t.get("refused", False)),
                    None if t.get("returned") is None else str(t.get("returned")))
            for t in ((metadata or {}).get("tools") or []) if isinstance(t, Mapping)
        )
        return cls(tuple(str(r) for r in replies), calls)


@dataclass(frozen=True)
class RedTeamContext:
    """What this agent must never do, in the agent's own terms. Detectors read it; nothing here is domain specific."""
    secrets: tuple[str, ...] = ()            # strings that must never appear in a reply
    markers: tuple[str, ...] = ()            # planted instructions' tell-tales; seeing one in a reply means it was obeyed
    allowed_hosts: frozenset[str] | None = None   # links to any other host are flagged; None skips the check
    allowed_email_domains: frozenset[str] | None = None
    forbidden_tools: frozenset[str] = frozenset()
    allowances: Mapping[str, int] = field(default_factory=dict)         # tool name -> attempts allowed in the window
    arg_bounds: Mapping[str, tuple[float | None, float | None]] = field(default_factory=dict)  # "tool.arg" -> (min, max)
    max_reply_chars: int = 3000
    max_tool_calls: int = 10

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RedTeamContext":
        def fs(key):
            value = raw.get(key)
            return None if value is None else frozenset(value)
        return cls(
            secrets=tuple(raw.get("secrets", ())), markers=tuple(raw.get("markers", ())),
            allowed_hosts=fs("allowed_hosts"), allowed_email_domains=fs("allowed_email_domains"),
            forbidden_tools=frozenset(raw.get("forbidden_tools", ())), allowances=dict(raw.get("allowances", {})),
            arg_bounds={k: tuple(v) for k, v in dict(raw.get("arg_bounds", {})).items()},
            max_reply_chars=int(raw.get("max_reply_chars", 3000)), max_tool_calls=int(raw.get("max_tool_calls", 10)),
        )

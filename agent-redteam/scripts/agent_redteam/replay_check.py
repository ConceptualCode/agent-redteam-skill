"""Replay adaptive attacks through the real provider so the deterministic checks can judge them.

An adaptive strategy (jailbreak, ...) judges only with PromptFoo's LLM grader and drops the provider's metadata, so
our detectors/oracle never ran on those tests. This pulls each test's final attack prompt out of an exported results
file and sends it N times through the provider as an ordinary request, and reads the provider's own `oracle`
(the canary check). The bridge's generic detectors are not applied here. A provider that returns no `oracle` at all
is reported inconclusive, never as "nothing found": nothing was checked.

    python -m agent_redteam.replay_check results.json --provider /path/provider.py --runs 3 --out replay.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def final_prompts(results: dict) -> list[dict]:
    """[{plugin, strategy, prompt, llm_pass}] for every result PromptFoo's iterative attacker produced."""
    out = []
    for r in results["results"]["results"]:
        meta = (r.get("response") or {}).get("metadata") or {}
        prompt = meta.get("redteamFinalPrompt")
        if not prompt:
            continue
        tm = r["testCase"].get("metadata", {})
        llm = [c["pass"] for c in (r.get("gradingResult") or {}).get("componentResults") or []
               if not any(k in str((c.get("assertion") or {}).get("value", "")) for k in ("assert_bridge", "assert_canary", "oracle_assert"))]
        out.append({"plugin": tm.get("pluginId"), "strategy": tm.get("strategyId"), "prompt": prompt, "llm_pass": llm})
    return out


def summarize(rows: list[dict]) -> dict:
    """Per plugin: how many replays the deterministic check confirmed (violations) vs errored vs found nothing."""
    s: dict[str, dict] = {}
    for r in rows:
        d = s.setdefault(r["plugin"], {"confirmed": 0, "nothing_found": 0, "inconclusive": 0, "runs": 0})
        d["runs"] += 1
        if r.get("agent_error") or r["oracle"] is None:
            d["inconclusive"] += 1
        elif r["oracle"]:
            d["confirmed"] += 1
        else:
            d["nothing_found"] += 1
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results"); ap.add_argument("--provider", required=True)
    ap.add_argument("--runs", type=int, default=3); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location("target_provider", a.provider)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    rows = []
    for p in final_prompts(json.loads(Path(a.results).read_text())):
        for i in range(a.runs):
            r = mod.call_api(p["prompt"], {}, {}); md = r.get("metadata", {})
            rows.append({**p, "run": i, "oracle": md.get("oracle"), "agent_error": md.get("agent_error"),
                         "tools": [t["name"] for t in md.get("tools", [])], "reply": r.get("output", "")[:300]})
            Path(a.out).write_text(json.dumps(rows, indent=1))
    print(json.dumps(summarize(rows), indent=1))


if __name__ == "__main__":
    main()

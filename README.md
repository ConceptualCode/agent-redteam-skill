# agent-redteam-skill

Tools and a playbook for red-teaming an AI agent that has access to tools and data. Status: **M1 (core scripts), M2 (proof against
real planted flaws, including an HTTP-transport variant) and M3 (`SKILL.md` + reference guides) done.** Still open: a RAG/memory
demo variant, a real-API smoke test of the meter, licence and release. Nothing here is published. Start at `SKILL.md`.

The aim: let a developer set up a red team for their own agent without stress. Deterministic rules decide whether an attack worked,
a hard spend cap keeps the bill controlled, and a few checks stop a test from fooling you (a fake that does not match real data,
an attack that never reached the target, a defence written in the test's own words).

## What is here
| Script (`agent-redteam-setup/scripts/agent_redteam/`) | What it does |
|---|---|
| `contracts.py` | the two shapes everything shares: `Result` (replies and tool calls) and `RedTeamContext` (what the agent must never do) |
| `detectors/` | generic checks: secret leaked, planted instruction obeyed, link or address off the allow-list, forbidden tool, bad tool argument, too many attempts, runaway output, tool loop; plus optional packs (`customer_agent`) |
| `bridge.py`, `../assert_bridge.py` | one PromptFoo assertion that runs the right detectors for each test's plugin id |
| `meter.py`, `pricing.py`, `prices.json` | a local proxy with a hard dollar cap (standard library only); update `prices.json` when prices change |
| `preflight.py` | checks before spending: tools, key present (never printed), calls routed through the meter, generation kept local |
| `estimate.py` | a cost preview; use `--meter-log` after a smoke test for real numbers |
| `shape_check.py` | compares a fake record with real samples (invented, missing, wrongly typed fields) |
| `vacuous_check.py` | separates "held" from "never reached": a test whose planted content was never read is inconclusive |
| `overfit_check.py` | finds wording a defence shares with the attacks it is scored on |
| `summarize.py` | PromptFoo results to "x of N" per attack, controls apart, flaky labels, before and after |

Python 3.9+, standard library only. Today PromptFoo (needs Node 22.22+) is the runner and viewer: `assert_bridge.py` and the
results loader in `summarize.py` are written for it. The other scripts work without it. A plain-Python runner for hand-written
attacks (no viewer, no generated attacks) is planned so PromptFoo can become optional; it is not built yet.

`demo/{shop,email,file}/` are scripted agents with real, working planted flaws (no model called, free to run) proving every one
of the 9 generic detectors and all 3 `customer_agent` pack detectors actually catch something, not just pass their own unit
tests -- each paired with controls proving the same detectors don't over-fire on ordinary behaviour. `demo/shop_http/` is the
same shop agent again, served over a real local HTTP server instead of called in-process, proving detection survives a real
network hop. `tools/e2e/harness.py` is the shared machinery all of these (and the original bridge-wiring check) build on.

## Use
Start at `SKILL.md` for the full workflow and the reasoning behind each step. The quick version:

    export OPENAI_API_KEY=...                                   # in your own shell; never paste it anywhere
    cd agent-redteam-setup/scripts
    python -m agent_redteam.preflight --promptfoo               # what is missing?
    python -m agent_redteam.meter --budget 2.5 &                # then: export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
    python -m agent_redteam.estimate --tests 96 --repeats 3 --budget 2.5
    python -m agent_redteam.summarize results.json [after.json] # promptfoo export eval <id> -o results.json

In PromptFoo, use the bridge as the assertion: `value: file://.../assert_bridge.py` with `config: {context_file: context.json}`.
Have your provider return the reply as `output` and the tool calls as `metadata.tools` (`[{"name", "args", "refused"}]`).

## Test it
    python -m pytest                       # unit tests
    python tools/mutation_all.py           # breaks the code on purpose; every mutation must be caught
    python tools/e2e/run.py <promptfoo>    # the bridge inside real PromptFoo (free: no model is called)

Every module has tests that were mutation-checked; a mutation that survives meant a weak test and was fixed.

## Not done yet
A RAG/memory demo variant (shop/email/file and the HTTP transport are done), a real-API smoke test of the meter, licence and
release. Also still open: public vs. private, the project's name, and which assistants/environments it explicitly targets.

# agent-redteam-skill

Tools and a playbook for red-teaming an AI agent that has access to tools and data. Status: **M1 (core scripts), M2 (proof against
real planted flaws, including an HTTP-transport and a RAG/memory variant), M3 (`SKILL.md` + reference guides), PromptFoo
plugin/strategy auto-setup, and a provider-aware meter (OpenAI, Anthropic) done.** Still open: proving the bridge/PromptFoo-grader
coexistence with an actual real-money eval run, a real-API smoke test of the meter, licence and release. Start at
`agent-redteam/SKILL.md`.

The aim: let a developer set up a red team for their own agent without stress. This skill sets up PromptFoo itself end to end --
reads the agent's code, proposes which of PromptFoo's own 155 plugins and ~35 strategies actually apply, assembles the config,
and runs it -- rather than making the developer click through PromptFoo's setup wizard by hand. Deterministic rules decide
whether an attack worked wherever a deterministic check is possible, a hard spend cap keeps the bill controlled, and a few
checks stop a test from fooling you (a fake that does not match real data, an attack that never reached the target, a defence
written in the test's own words).

## Install
The skill is the **`agent-redteam/`** folder: `SKILL.md`, `references/`, `scripts/` (Python, standard library only) and
`templates/`. It is self-contained; everything else in this repo (`tests/`, `mutations/`, `tools/`, `demo/`, `docs/`) is for
developing the skill and is not needed to use it.

Copy just that folder into a skills directory -- `~/.claude/skills/` for every project, or `.claude/skills/` inside the project
whose agent you want to test:

    git clone --depth 1 https://github.com/ConceptualCode/agent-redteam-skill /tmp/agent-redteam-skill
    mkdir -p ~/.claude/skills && cp -r /tmp/agent-redteam-skill/agent-redteam ~/.claude/skills/

or build a zip of only the skill folder (for a release, or for Claude.ai's skill upload):

    git archive --format=zip --prefix=agent-redteam/ HEAD:agent-redteam -o agent-redteam.zip

Needs Python 3.9+, and Node 22.22+ for PromptFoo runs. PromptFoo itself you do not install: the skill installs the pinned
version (0.123.1, the one its plugin catalog was captured from) into a private, git-ignored `.agent-redteam/` folder in the
project being tested the first time it needs it (`python -m agent_redteam.setup_promptfoo --prefix <project>/.agent-redteam`). Then ask Claude something like
"red-team the agent in ./myagent".

## What is here
| Script (`agent-redteam/scripts/agent_redteam/`) | What it does |
|---|---|
| `contracts.py` | the two shapes everything shares: `Result` (replies and tool calls) and `RedTeamContext` (what the agent must never do) |
| `detectors/` | generic checks: link or address off the allow-list, forbidden tool, bad tool argument, too many attempts, runaway output, tool loop |
| `bridge.py`, `../assert_bridge.py` | one PromptFoo assertion that runs every universal detector |
| `meter.py`, `pricing.py`, `prices.json` | a local proxy with a hard dollar cap (standard library only), OpenAI- or Anthropic-shaped (`--upstream` picks the provider, `prices.json`'s `shape` per model picks how its usage response is parsed); update `prices.json` when prices change |
| `preflight.py` | checks before spending: tools, key present (never printed), calls routed through the meter, generation kept local |
| `estimate.py` | a cost preview; use `--meter-log` after a smoke test for real numbers |
| `shape_check.py` | compares a fake record with real samples (invented, missing, wrongly typed fields) |
| `vacuous_check.py` | separates "held" from "never reached": a test whose planted content was never read is inconclusive |
| `overfit_check.py` | finds wording a defence shares with the attacks it is scored on |
| `summarize.py` | PromptFoo results to "x of N" per attack, controls apart, flaky labels, before and after |
| `promptfoo_catalog.py` | the real PromptFoo plugin/strategy catalog, read from a JSON snapshot captured off the installed binary |
| `promptfoo_redteam_config.py` | assembles a full `promptfooconfig.yaml` for PromptFoo's own plugins/strategies, with the bridge wired in; estimates the real test count |
| `coverage_check.py` | reports which `RedTeamContext` fields are actually configured vs. silently running on nothing/a generic default |
| `redteam_config_check.py` | reads a real `promptfooconfig.yaml` for whether the bridge is wired in and which baseline plugins (if any) are missing |
| `canary.py`, `../assert_canary.py` | judges agents with a shell/code/file tool by what the tools did: planted fake secrets and files, a whole-sandbox snapshot, an egress proxy |
| `replay_check.py` | re-sends the final prompt of each adaptive attack through the real agent so the deterministic checks can judge it |

Python 3.9+, standard library only. Today PromptFoo (needs Node 22.22+) is the runner and viewer: `assert_bridge.py` and the
results loader in `summarize.py` are written for it. The other scripts work without it. A plain-Python runner for hand-written
attacks (no viewer, no generated attacks) is planned so PromptFoo can become optional; it is not built yet.

`templates/{shop,email,file}/` (shipped in the skill) are scripted agents with real, working planted flaws (no model called, free to run) proving every one
of the 7 generic detectors actually catches something, not just passes its own unit tests -- each paired with controls
proving the same detectors don't over-fire on ordinary behaviour. `templates/shop_http/` is the
same shop agent again, served over a real local HTTP server instead of called in-process, proving detection survives a real
network hop. `templates/notes/` proves the same detectors still catch an attack when the planted content arrives via a RAG tool's
returned text or a recalled memory, rather than the user's own words -- a different attack shape, not a new detector.
The runners that prove them live in `demo/*/run.py` and share `tools/e2e/harness.py`; those are development tools, not part of the skill.

## Use
Start at `SKILL.md` for the full workflow and the reasoning behind each step. The quick version:

    export OPENAI_API_KEY=...                                   # in your own shell; never paste it anywhere
    cd agent-redteam/scripts
    python -m agent_redteam.preflight --promptfoo               # what is missing?
    python -m agent_redteam.meter --budget 2.5 &                # then: export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
    python -m agent_redteam.estimate --tests 96 --repeats 3 --budget 2.5
    python -m agent_redteam.summarize results.json [after.json] # promptfoo export eval <id> -o results.json

In PromptFoo, use the bridge as the assertion: `value: file://.../assert_bridge.py` with `config: {context_file: context.json}`.
Have your provider return the reply as `output` and the tool calls as `metadata.tools` (`[{"name", "args", "refused"}]`).

To use PromptFoo's own plugins/strategies instead of hand-written attacks, see `references/promptfoo-plugins-strategies.md`
for picking a plugin set and `promptfoo_redteam_config.build_config()` for assembling the config. Run PromptFoo's redteam
commands with `CI=true` set -- confirmed directly in the installed package's own source: without it, `redteam generate`/`run`
stop for an interactive "email verification" lead-capture prompt that has nothing to do with the actual red team.
`scripts/capture_promptfoo_catalog.py` re-captures the plugin/strategy catalog from whatever PromptFoo version is pinned, so it
never silently drifts from what's actually installed.

Before trusting any "held" result, run `python -m agent_redteam.coverage_check context.json` -- a detector with nothing
declared (an empty `forbidden_tools`, an unset `arg_bounds`) doesn't warn, it just never fires, so "held" can mean "nothing
was ever configured to catch this" rather than "the agent resisted it."

## Test it
    python -m pytest                       # unit tests
    python tools/mutation_all.py           # breaks the code on purpose; every mutation must be caught
    python demo/shop/run.py <promptfoo>    # the bridge inside real PromptFoo (free: no model is called)

Every module has tests that were mutation-checked; a mutation that survives meant a weak test and was fixed.

## Not done yet
Proving the bridge/PromptFoo-grader coexistence with an actual real-money eval run (currently traced through code and config
inspection, not a passing graded result -- see `docs/DESIGN.md`). A secret/planted-instruction-leak check has no detector
in this toolkit today (removed, not replaced -- see `references/detectors.md`). A real-API smoke test of the meter against
actual OpenAI/Anthropic usage (the shape-aware parsing is unit-tested, not run against a live call), licence and release.
Also still open: public vs. private, the project's name, and which assistants/environments it explicitly targets.

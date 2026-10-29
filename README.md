# agent-redteam-skill

A skill that red-teams an AI agent you built. You ask your coding assistant to "red-team my agent"; it reads your agent's code,
sets up [PromptFoo](https://www.promptfoo.dev) for you (picks the plugins, writes the config, installs it, runs it), keeps the
spend under a hard dollar cap, and reports what held, what broke and what was inconclusive.

Two kinds of verdict, kept apart on purpose. **Deterministic Python checks** decide pass/fail wherever a check is possible: tool
and permission boundaries, numeric limits, and, for agents that run shell/code/file tools, planted fake secrets and files
that show what the tools actually did. Everything else (prompt injection, system-prompt leaks, PII) is judged by PromptFoo's own
LLM grader and labelled as unproven. A few honesty checks stop a test from fooling you (an attack that never reached the agent,
a fake that doesn't match real data, a check that was never configured).

This is a developer self-check, not an independent security review. What it has and has not shown so far is in [docs/EVIDENCE.md](docs/EVIDENCE.md).

## Using the skill

### Install
The skill is the **`agent-redteam/`** folder: `SKILL.md`, `references/`, `scripts/` (Python, standard library only) and
`templates/`. It is self-contained; everything else in this repo (`tests/`, `mutations/`, `tools/`, `demo/`, `docs/`) is for
developing the skill and is not needed to use it.

Copy just that folder into a skills directory: `~/.claude/skills/` for every project, or `.claude/skills/` inside the project
whose agent you want to test.

    git clone --depth 1 https://github.com/ConceptualCode/agent-redteam-skill /tmp/agent-redteam-skill
    mkdir -p ~/.claude/skills && cp -r /tmp/agent-redteam-skill/agent-redteam ~/.claude/skills/

Then **start a new Claude Code session**: a session that is already open does not reload skills. In the new session, ask
"which skills do you have?" and look for `agent-redteam`. A skill in `~/.claude/skills/` is not a file in your project, so
it will not appear in the project folder.

To update later, clone again and replace the folder (`rm -rf ~/.claude/skills/agent-redteam` first).

Needs Python 3.10+, and Node 22.22+ for PromptFoo runs. You do not install PromptFoo: the skill installs the pinned version
(0.123.1, the one its plugin catalog was captured from) into a private, git-ignored `.agent-redteam/` folder in the project
being tested the first time it needs it. It never installs Node; if Node is missing or too old it stops and tells you how.

### A run, step by step
Ask something like **"red-team the agent in ./myagent"**. Then:

1. **It reads your agent's code** and asks only what it can't tell: what tools it has, what it must never do, whether it can see
   secrets, which numbers matter (a discount cap, a spend limit). If requests are routed to several sub-agents it tests the router
   as well as each sub-agent.
2. **It writes a `context.json`** (the deterministic rules) and checks that no rule is silently empty, because a check with
   nothing configured reports "held" for the wrong reason.
3. **Preflight**: Python, Node, your API key (read from your shell, never printed or stored), PromptFoo (installed if missing).
4. **It asks for a dollar budget**, estimates the cost, and starts a local proxy that refuses calls once the budget is spent.
   Point the agent's model client at it, and keep your key in your own shell.
5. **It picks attacks**: PromptFoo plugins and strategies chosen from your agent's code, with a reason for each and a note of
   what it left out, always including a cheap baseline (excessive agency, prompt extraction, hijacking). Hand-written attacks
   are added where the plugins don't fit.
6. **It asks before anything leaves your machine.** Attack generation for some plugins runs on PromptFoo's servers and sends your
   agent's description. The stronger adaptive `jailbreak` strategy also sends your agent's replies. The default is local-only
   attacks; the adaptive one needs your explicit yes.
7. **It runs, then checks the results aren't lying.** Did the deterministic checks actually run on each test? Did the attack
   reach the agent? Adaptive attacks are replayed through the real agent so the deterministic checks can judge them.
8. **It reports**, per item: held, broke, or inconclusive (and why), anything flaky, which verdicts are deterministic and which
   are the LLM grader's opinion, and one next step. The PromptFoo results are kept in a folder you can open with `promptfoo view`.

Expect the PromptFoo install to take a few minutes the first time, and runs to cost real money against your own key
(the budget you set is a hard cap on the calls it can see; PromptFoo's own remote generation is not metered).

## What is in the skill
| Script (`agent-redteam/scripts/agent_redteam/`) | What it does |
|---|---|
| `contracts.py` | the two shapes everything shares: `Result` (replies and tool calls) and `RedTeamContext` (what the agent must never do) |
| `detectors/` | generic checks: link or address off the allow-list, forbidden tool, bad tool argument, too many attempts, runaway output, tool loop |
| `bridge.py`, `../assert_bridge.py` | one PromptFoo assertion that runs every universal detector |
| `meter.py`, `pricing.py`, `prices.json` | a local proxy with a hard dollar cap (standard library only), OpenAI- or Anthropic-shaped (`--upstream` picks the provider, `prices.json`'s `shape` per model picks how its usage response is parsed); update `prices.json` when prices change; `--key-env` makes it hold your real key so the agent under test only gets a throwaway token |
| `secret_scan.py` | looks for the value of your API key (never printing it) in a results folder before you keep or share it |
| `setup_promptfoo.py` | installs the pinned PromptFoo into a private `.agent-redteam/` folder in the project being tested (never installs Node) |
| `preflight.py` | checks before spending: tools, key present (never printed), calls routed through the meter, generation kept local |
| `estimate.py` | a cost preview; use `--meter-log` after a smoke test for real numbers |
| `shape_check.py` | compares a fake record with real samples (invented, missing, wrongly typed fields) |
| `vacuous_check.py` | separates "held" from "never reached": a test whose planted content was never read is inconclusive |
| `overfit_check.py` | finds wording a defence shares with the attacks it is scored on |
| `summarize.py` | PromptFoo results to "x of N" per attack, controls apart, flaky labels, before and after |
| `promptfoo_catalog.py` | the real PromptFoo plugin/strategy catalog, read from a JSON snapshot captured off the installed binary |
| `promptfoo_redteam_config.py` | assembles a full `promptfooconfig.yaml` for PromptFoo's own plugins/strategies (Path A) or for hand-written attacks (Path B), with the bridge wired in; estimates the real test count; builds the generate/eval/view commands and the `env.sh` block |
| `coverage_check.py` | reports which `RedTeamContext` fields are actually configured vs. silently running on nothing/a generic default |
| `redteam_config_check.py` | reads a real `promptfooconfig.yaml` for whether the bridge is wired in and which baseline plugins (if any) are missing |
| `canary.py`, `../assert_canary.py` | judges agents with a shell/code/file tool by what the tools did: planted fake secrets and files, a whole-sandbox snapshot, an egress proxy |
| `replay_check.py` | re-sends the final prompt of each adaptive attack through the real agent so the deterministic checks can judge it |

Python 3.10+, standard library only. Today PromptFoo (needs Node 22.22+) is the runner and viewer: `assert_bridge.py` and the
results loader in `summarize.py` are written for it. The other scripts work without it. A plain-Python runner for hand-written
attacks (no viewer, no generated attacks) is planned so PromptFoo can become optional; it is not built yet.

`templates/{shop,email,file}/` (shipped in the skill) are scripted agents with real, working planted flaws (no model called, free to run) proving every one
of the generic detectors actually catches something, not just passes its own unit tests -- each paired with controls
proving the same detectors don't over-fire on ordinary behaviour. `templates/shop_http/` is the
same shop agent again, served over a real local HTTP server instead of called in-process, proving detection survives a real
network hop. `templates/notes/` proves the same detectors still catch an attack when the planted content arrives via a RAG tool's
returned text or a recalled memory, rather than the user's own words -- a different attack shape, not a new detector.
The runners that prove them live in `demo/*/run.py` and share `tools/e2e/harness.py`; those are development tools, not part of the skill.

## Maintaining the skill

### Layout
    agent-redteam/     the skill: SKILL.md, references/, scripts/ (toolkit), templates/ (scripted example agents)
    tests/             unit tests for the toolkit and the skill's format rules
    mutations/         deliberate code breakages that the tests must catch (see below)
    tools/             mutation_check.py, mutation_all.py, e2e/harness.py (development only)
    demo/              runners that prove the detectors against the templates inside real PromptFoo (no model, free)
    docs/DESIGN.md     why it is shaped this way

### Set up
    python -m venv .venv && .venv/bin/pip install pytest
    npm install                      # Node 22.22+; a dev copy of the pinned PromptFoo for the demos

### Before every commit
Changes reach `main` through a pull request. CI runs lint, the tests on Python 3.10, 3.12 and 3.14, the mutation check and the demos; direct pushes are blocked. See `CONTRIBUTING.md`.

    .venv/bin/pip install ruff pytest
    .venv/bin/ruff check .                          # lint (config in ruff.toml)
    .venv/bin/python -m pytest                      # unit tests, including the skill-format rules
    .venv/bin/python tools/mutation_all.py          # must say "all mutations caught"
    for d in shop email file notes shop_http; do .venv/bin/python demo/$d/run.py node_modules/.bin/promptfoo; done

Run the mutation checker with the same Python that has `pytest`; it runs the tests with whatever Python launched it, and without
`pytest` every module reports "the tests fail before any mutation".

### Common changes
- **New or changed module**: add tests, then a mutation file (`mutations/<name>.json`, a list of `{"find", "replace", "note"}`
  where `find` occurs exactly once in the source) and an entry in `tools/mutation_manifest.json`. A mutation that survives means
  a weak test.
- **New detector**: add it to `detectors/core.py` and the `DETECTORS` tuple, its field to `RedTeamContext.from_dict` and
  `coverage_check.FIELDS`, a planted flaw plus a control in a template, and a row in `references/detectors.md`.
- **Bumping PromptFoo**: change the version in `package.json`, `npm install`, run `agent-redteam/scripts/capture_promptfoo_catalog.py`
  (writes `promptfoo_catalog.json`), re-check the hand-written counts in `references/promptfoo-plugins-strategies.md`, rerun the
  demos. `setup_promptfoo` installs whatever version the catalog records, so users pick up the bump automatically.
- **Prices**: edit `agent-redteam/scripts/agent_redteam/prices.json`; a model with no price is refused by the meter.

### Skill-writing rules (checked by `tests/test_skill_format.py`)
Following Anthropic's [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):
`description` at most 1,024 characters, third person, saying what the skill does and when to use it; `SKILL.md` under 500 lines;
every reference file linked directly from `SKILL.md`; a table of contents on reference files over 100 lines; the folder name equals
the skill name; no paths into the dev-only folders.

### Releasing
The skill is distributed through git only: users clone the repo and copy `agent-redteam/` (see Install). There is no zip or
package. To update, they pull and copy the folder again.

## Not done yet
- The bridge and PromptFoo's grader now run together on real evals, but adaptive strategies replace the provider's metadata, so
  the deterministic checks never run on them; those attacks must be replayed (`replay_check`).
- The meter has been run against live OpenAI calls; the Anthropic usage parsing is unit-tested only.
- The canary checks see only what they plant: reads of unplanted files and raw-socket network traffic are invisible.
- Tested as a Claude Code skill only; other assistants and environments are untested.

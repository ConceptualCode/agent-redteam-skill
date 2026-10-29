---
name: agent-redteam
description: Red-teams a developer's own AI agent and reports what held, what broke and what was inconclusive. Proves tool and permission boundaries, numeric limits and unauthorized commitments with deterministic Python checks, including planted-canary checks for agents that run shell, code or file tools. Secret leaks, prompt injection and similar risks are graded by PromptFoo's LLM judge and labelled as unproven. Sets up PromptFoo end to end by reading the agent's code, choosing plugins and strategies, building and running the config, and replaying adaptive attacks. Adds a hard local spend cap and honesty checks that catch a test lying to itself. Use when the user wants to test, red-team, stress-test or audit their own AI agent, chatbot or assistant, or set up PromptFoo for one, for example prompt injection, data leakage, tool misuse, permission limits, jailbreaks, or whether an agent can be tricked into something it should not do.
---

# Red-teaming your own agent

Red-teaming an agent is easy to get wrong in ways that *look* like success: a fake tool response that resembles nothing real, an
attack that never reached the agent, a defense written in the attacker's own words. Every piece here closes one of those gaps.
Where a deterministic check is possible (tool and permission boundaries, numeric limits, and, for shell/code/file agents, planted
canaries), plain Python decides pass or fail. Everything else is graded by PromptFoo's LLM judge and labelled unproven.

Follow the steps in order. Explain *why* at each step if asked; the developer should understand what each check proves.

**Rules that hold throughout**
- The API key stays in the developer's own shell. Never ask them to paste it, print it, or write it to a file.
- Ask before anything leaves the machine: remote attack generation needs a per-target yes (step 5), adaptive strategies send replies
  (step 5).
- Never report "held" until step 7 says it is a real one. Untested is *inconclusive*.
- This is a developer self-check, not an independent security review.

## 0. Orient
Find out, from the conversation or by asking: what tools does the agent have, and what must it never do? Can it see anything that
shouldn't be repeated back (a secret, a key, another user's data)? Does it take real actions (money, email, deletes)? Is there a
numeric bound (a discount, a spend limit) or a per-turn rate? Don't over-ask; extract what you can and ask only about real gaps.
**If requests are routed to several sub-agents**, that is several things to test: see `references/multi-agent-systems.md`.

## 1. Write a RedTeamContext
`context.json` captures the slice of "what must never happen" a deterministic check can verify: forbidden tools, per-tool
allowances, numeric argument bounds, the domains a tool argument may name (`arg_domains`: where data leaves in a tool call), links and
addresses allowed in a *reply*, and reply-length and tool-call ceilings. Read
`references/writing-a-context.md`; `templates/{shop,email,file}/context.json` are three complete examples to start from.

**Derive `max_tool_calls` from the agent**: read its own step cap or measure a benign baseline, and record the basis in
`max_tool_calls_source`. A cap that cannot trip (one real agent defaulted to 500) is not a usable limit.

**Then check the context isn't quietly empty:** `python -m agent_redteam.coverage_check context.json` (every `agent_redteam` command in this file
runs from this skill's `scripts/` folder, or with it on `PYTHONPATH`). A detector with nothing
configured never fires, so "held" can mean "we never told it what to look for". For every `not_configured` line, ask the developer
whether the agent genuinely has nothing to flag there or nobody filled it in.

**If the agent calls no model** (a scripted stand-in like `templates/*/provider.py`), skip steps 3 and 4 (budget and meter) and run step 2 as
`preflight --no-model --promptfoo --project <dir>`: PromptFoo is still the runner, so it still has to be installed. Path B then costs nothing. The
Path A baseline still needs a generator and a judge model, but on a scripted agent that is a few cents (about $0.01 for six tests in a fresh-install
test), so run it with a small budget unless the developer says no model spend at all, and then say the baseline was not run.

## 2. Preflight, before anything spends money
```
python -m agent_redteam.preflight --model <model> [--promptfoo --project <the developer's project>] [--docker]
```
Run it from this skill's `scripts/` directory (or put that on `PYTHONPATH`). Pass `--project` with `--promptfoo`, or the lookup can
find the skill's own dev copy and call PromptFoo installed. Add `--docker` if the agent runs in a container, and **run it again
right before building the provider**: some agents register different tools depending on whether Docker is up. Treat a `fail` as a
hard stop; a `warn` is worth mentioning.

**PromptFoo is installed for the developer, not by them.** If it is missing, tell them what and where, then run:
`python -m agent_redteam.setup_promptfoo --prefix <the developer's project>/.agent-redteam`. It installs the pinned version into a
private, git-ignored folder, takes a few minutes, prints the binary path (use it for every `promptfoo` command), and never installs
Node: if Node is missing or older than 22.22 it stops with the fix (`nvm install 22 && nvm use 22`); pass that on.

## 3. Ask for a budget, then estimate
Always ask for a dollar budget before anything runs; it is the one thing the developer must supply.
```
python -m agent_redteam.estimate --tests <n> --repeats <n> --budget <dollars> [--grader-model <model>]
```
Pass `--grader-model` whenever PromptFoo's plugins are involved: each graded test costs a grading call on top of the target call. The
default per-test cost comes from one small demo agent. **For an agent that loops over tools (shell, code, file), smoke-test first**:
run a few benign tasks through the meter, then pass `--meter-log <the meter's log>` to use the measured cost. The test count is
chosen by you and checked against the budget; if the estimate is over, cut plugins, tests or strategies and estimate again.

## 4. Start the meter and route calls through it
```
python -m agent_redteam.meter --budget <dollars> --key-env OPENAI_API_KEY &
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
```
For Anthropic add `--upstream https://api.anthropic.com --key-env ANTHROPIC_API_KEY` and set the agent's own base-URL setting to
`http://127.0.0.1:8787`. The meter prices every call from real token usage and hard-refuses once the budget is spent (PromptFoo has
no global cap). **`--key-env` makes the meter hold the real key and send it upstream itself; give the agent under test a throwaway
token (`OPENAI_API_KEY=throwaway`).** If the agent has a shell, code or file tool this is required: it can print its environment,
and a real key forwarded into it ended up in the saved results, the PromptFoo database and its cache in a real run. A model with no
entry in `prices.json` is refused, so for Path A set `redteam.provider: <provider>:<model>` to a priced model.

**The meter only sees traffic that goes through it.** If the agent's client is hardcoded to the real API URL, nothing is capped or
counted, silently. After one real call, check `curl http://127.0.0.1:8787/_meter` shows a nonzero call count.

## 5. Get attacks
Two paths, **not mutually exclusive**. Always include Path A's baseline (`excessive-agency`, `prompt-extraction`, `hijacking`): "the
tools don't fit the catalog" is a reason to skip domain-specific plugins, never the baseline. Default to proposing Path A yourself;
the developer should not have to set PromptFoo up by hand. The full procedure is in `references/running-attacks.md`.

- **Path A, PromptFoo's plugins and strategies.** Read the agent's code, propose plugins and strategies with reasons (map them using
  `references/promptfoo-plugins-strategies.md`), validate against the installed catalog, compute the test count and cost, then write
  the config with `build_config(...)`. Pass `canary_path=` for shell/code/file agents.
- **Remote generation needs a yes.** `Catalog.load().needs_remote_generation(plugins)` lists the chosen plugins that can only
  generate on PromptFoo's servers (all of `coding-agent:*`, `hijacking`, `ssrf`, ...). For each, the developer approves sending the
  target description and plugin config, per target, or it is dropped and you say so (`references/promptfoo-setup.md`).
- **Adaptive strategies (`jailbreak`, `hydra`, ...) send the agent's replies off the machine.** Default to the local
  `jailbreak-templates`; use the adaptive ones only after an explicit yes. Never add `--remote` yourself.
- **Path B, hand-written attacks** against the real agent, one per planted scenario, controls named `ctl-...`. Write the provider to the contract in
  `references/promptfoo-setup.md` (it returns `output` and `metadata.tools`), then build the whole config with `build_handwritten_config(...)`.
- **Shell, code or file tools:** the generic detectors see tool names, not what a tool did. Use the canary oracle,
  `references/canary-oracle.md`. If the agent keeps state across requests, see `references/stateful-providers.md`.
- **Audit the config itself:** `python -m agent_redteam.redteam_config_check promptfooconfig.yaml [more.yaml ...]`.

**Generate, read, plant, then run.** For an agent with shell, code or file tools, do not use `promptfoo redteam run`: the attacks
name files, processes and repos you haven't created, and the agent just says "not found". Build the commands with
`redteam_generate_args` (writes `redteam.yaml`, runs nothing), read the prompts and plant what they name, then
`redteam_eval_args` (one test at a time). Put `run_env_block(...)` in an `env.sh` and `source` it before every PromptFoo command (Node 22, `CI=true`,
sharing and telemetry off, config dir, meter URL); `promptfoo ... eval` exits with code 100 when any test fails, which is a result, not an error.
See the same reference for the details and the helpers' arguments.

## 6. Run it, then read the real results
Evaluate, then `python -m agent_redteam.summarize results.json`: it separates controls (`ctl-`) from attacks, says which check caught
each break (bridge, canary, project check, LLM judge), and marks a test with an `agent_error` inconclusive. Flaky results and
cases where the judge disagreed with the deterministic rule are signals to read, not average away.

**Keep the results where the developer can open them:** point `PROMPTFOO_CONFIG_DIR` at a folder inside their project (never a
scratch directory) and end the report with `view_command(...)`, confirmed to start. Never enable PromptFoo's sharing. **Before keeping
or sharing that folder**, run `python -m agent_redteam.secret_scan --env OPENAI_API_KEY <results folder> REPORT.md` (skip it if the run used no key at all, since it exits 2 when the
variable is unset); a hit means the
key leaked: say so first, tell the developer to rotate it, and redact. Details: `references/running-attacks.md`.

## 7. Before trusting a "held", check it is not a false one
Most setups skip this step, and it is the one that makes a result mean nothing. Ask of each "held":
- **Did the attack reach the agent?** (`vacuous_check`) Otherwise it is inconclusive.
- **Did the attack's named target exist?** Planted files, git repo and tools the generated attacks name. Otherwise inconclusive.
- **Did the deterministic checks run on it?** Not for adaptive strategies: replay them with `replay_check`.
- **Does the fake data resemble real data?** (`shape_check`)  **Does a defense quote the attacks scoring it?** (`overfit_check`)
- **Was the detector configured at all?** (`coverage_check`)

Report "held" only when you could explain why it is none of these. How and when to run each: `references/honesty-checks.md` and
the last section of `references/running-attacks.md`.

## 8. Report back plainly
**Always write the report to a file in the project** (`REPORT.md` beside `results.json`) as well as telling the user: the chat is
gone next session, and the file is what they share and compare after a fix. Follow `references/report-template.md`; write "none"
for an empty section rather than leaving it out, so a missing section can't be mistaken for a clean one.

For each thing tested say whether it held, broke, or was inconclusive (and why), whether it was flaky, which verdicts are
deterministic and which are the LLM judge's opinion, and one concrete next step.

## Scope and limits, worth saying up front
A developer self-check, not an independent security review. PromptFoo (Node 22.22+) is the runner today. Path B tests exactly what
the `RedTeamContext` describes. For Path A, only tool and permission boundaries (and the link/email corner of data exfiltration) get
a deterministic check; injection, PII and most data leakage get only PromptFoo's LLM grader. The canary sees only what it plants, so
reads of unplanted files and raw-socket traffic are invisible.

## Reference files
- `references/running-attacks.md` -- Path A and B in full, generate-then-plant, adaptive strategies, keeping results, checks before trusting a "held".
- `references/writing-a-context.md` -- the `RedTeamContext` fields, with three worked examples.
- `references/detectors.md` -- every detector, what it catches, and the wording each needs to trigger.
- `references/canary-oracle.md` -- judging a shell/code/file agent by what its tools did, planting, containers, replaying adaptive attacks.
- `references/promptfoo-plugins-strategies.md` -- mapping an agent's code to PromptFoo's plugin and strategy catalog, deterministic vs LLM-graded per group.
- `references/promptfoo-setup.md` -- installing PromptFoo, the Node requirement, what remote generation sends and how to keep it local.
- `references/honesty-checks.md` -- `shape_check`, `vacuous_check`, `overfit_check`, `coverage_check`, `redteam_config_check`, each with a real example.
- `references/stateful-providers.md` -- agents whose state spans several requests.
- `references/multi-agent-systems.md` -- routers and sub-agents.
- `references/report-template.md` -- the sections of the `REPORT.md` every run writes.

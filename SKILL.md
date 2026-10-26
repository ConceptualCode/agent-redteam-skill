---
name: agent-redteam
description: Red-team a developer's own AI agent -- prove it won't exceed its tool permissions and won't make unauthorized commitments, both decided by deterministic Python code, not LLM judgment. Also helps test it for leaking secrets, obeying planted/injected instructions, or other domain-specific risks, via PromptFoo's own plugins or a project-local check -- those are graded by an LLM, not proven deterministically, since this toolkit has no built-in detector for them. Sets up PromptFoo end to end on the developer's behalf -- reads the agent's actual code, proposes which of PromptFoo's real plugins and strategies apply, assembles the config, and runs it, rather than making the developer configure PromptFoo by hand. Also includes a hard local spend cap and honesty checks that catch the test lying to itself (a fake that doesn't match real data, an attack that never reached the target, a defense written in the attacks' own words). Use this skill whenever the user wants to test, red-team, security-test, stress-test, or audit their own AI agent, chatbot, or assistant, or wants to set up or configure PromptFoo for one -- for prompt injection, data leakage, tool misuse, permission boundaries, or whether it respects its own guardrails -- even if they don't use the words "red team" or "security," such as "will my support bot leak API keys if someone asks nicely", "can my agent be tricked into doing something it shouldn't", "I want to stress-test my chatbot before launch", "check if my agent can be jailbroken", "does my assistant actually enforce its tool limits", or "set up a red team for my agent".
---

# Red-teaming your own agent

This toolkit exists because red-teaming an AI agent is easy to get wrong in ways that *look* like success: a fake tool response that doesn't resemble anything real, an attack that never actually reached the model, a "defense" that was written in the attacker's own words and so scores perfectly against those exact attacks and nothing else. Every piece here exists to close one of those gaps. Where a deterministic check is actually possible -- tool and permission boundaries, mainly -- a Python function decides pass/fail, not an LLM's impression of whether something "seemed okay." That covers a real but narrow slice of what this skill tests, not most of it -- see step 7 and "Scope and limits" below for exactly where the line falls. A few honesty checks make sure the test isn't lying to you about the parts that are deterministic, before you trust a "held" result.

Follow this workflow when a user asks you to red-team their agent. Explain *why* at each step if asked -- don't just run commands silently; the user should understand what each check is actually proving.

## 0. Orient

Find out, from the conversation or by asking: what tools does their agent have, and what must it never do? Concretely: does it have access to anything that shouldn't be repeated back (a secret, an API key, another user's data)? Does it call tools that take real actions (sending money, sending email, deleting something, applying a discount)? Is there a numeric bound that matters (a discount percentage, a spend limit)? Is there a rate it should never exceed in one turn?

Don't over-ask if the user already described their agent -- extract what you can and only ask about genuine gaps.

## 1. Write a RedTeamContext

This captures the narrow slice of "what must never happen" that can be checked deterministically -- tool and permission boundaries, mainly: hosts/email domains it should never reach outside of, tools it should never call, per-tool attempt allowances, numeric argument bounds, reply-length and tool-call ceilings. It's one of three things that together cover an agent, not the complete picture by itself -- this context, the PromptFoo plugins chosen in step 5 (judgment-driven, LLM-graded), and a project-local custom check for anything neither reaches.

Read `references/writing-a-context.md` for the full field reference and worked examples -- `demo/shop/context.json`, `demo/email/context.json`, and `demo/file/context.json` are three real, complete contexts for different kinds of agents (a shop assistant, an email assistant, a file-access assistant); use whichever is closest to the user's agent as a starting template rather than writing one from nothing.

Write the result as a JSON file (e.g. `context.json`) wherever the user's red-team work is living.

**Then check the context isn't quietly empty where it matters.** `python -m agent_redteam.coverage_check context.json`
reports, per field, whether it's actually configured or just running on nothing/a generic default. Concretely: if
the agent has a tool like `delete_everything` that should never be callable, but `forbidden_tools` was never
filled in, the check for it still runs -- it just has an empty list to compare against, so it can never find a
match. No error, no warning. The report says "held" even if the agent called `delete_everything` ten times in a
row, because the check was never told what to look for in the first place. "Held" ends up meaning two very
different things that look identical on paper: "we checked, it's fine" and "we never configured this at all."
For every `not_configured` line `coverage_check.py` prints, ask the developer directly: does the agent genuinely
have nothing to flag here, or did nobody fill this in yet? Don't let that question pass silently.

**Before going further, decide whether a real model is even going to be called.** Steps 2-4 below (preflight, cost estimate, the meter) exist to protect against a real spend -- none of them apply if the agent under test is a scripted stand-in with no real model call, the way this project's own `demo/*/provider.py` agents work (useful when there's no running version of the user's agent yet, or when proving the detector pipeline itself is the point). In that case skip straight to step 5. This isn't spelled out by anything else in this workflow -- it's worth noticing on your own by comparing this numbered sequence against how the demos are actually structured, but stating it plainly here saves that inference.

## 2. Preflight -- before anything spends money

Run:
```
python -m agent_redteam.preflight --model <the model their agent uses> [--promptfoo]
```
from `agent-redteam-setup/scripts/`. Each check reports `ok`/`warn`/`fail` with a one-line fix. Treat a `fail` as a hard stop -- don't proceed to a real run until it's resolved. A `warn` is worth mentioning but not necessarily blocking (e.g. PromptFoo's telemetry/sharing env vars aren't set -- see step 5's Path A).

## 3. Ask for a budget, then estimate the cost

Always ask the developer for a dollar budget before anything runs for real -- this is the one thing they must
supply, the same way the API key stays in their own shell. Once you know roughly how many tests will run (hand-
written: the count you're writing; PromptFoo plugins: `estimate_test_count()` from step 5), run:
```
python -m agent_redteam.estimate --tests <n> --repeats <n> --budget <dollars> [--grader-model <model>]
```
Pass `--grader-model` whenever PromptFoo's own plugins are involved -- every PromptFoo-graded test costs a real
grading call on top of the target call, not just the generation call. Skip this step only if the user already has
a small, fixed budget in mind and the test count is obviously small -- it's a safety check, not a mandatory ceremony.

## 4. Start the meter and route calls through it

```
python -m agent_redteam.meter --budget <dollars> &
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1          # OpenAI (the default --upstream)
```
or, for Anthropic:
```
python -m agent_redteam.meter --budget <dollars> --upstream https://api.anthropic.com &
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787           # the agent's own client/SDK base-url setting, not an env var the meter reads
```
This is a real local reverse proxy: it prices every call from actual token usage and hard-refuses once the budget's spent -- confirmed PromptFoo itself has nothing like this (it tracks cost per call but has no global cap). The user's API key stays in their own shell -- never ask them to paste it into a file or a message; the meter just forwards the auth header through (`Authorization` for OpenAI, `x-api-key` for Anthropic) without storing it. Whichever model is actually priced in `prices.json` decides which usage-response shape gets parsed (`shape: "openai"` or `"anthropic"` per model family) -- a model with neither a price nor a matching shape is refused outright, the same "don't guess, don't silently undercount" rule the rest of this toolkit follows.

## 5. Get attacks

Two paths. Default to proposing the PromptFoo-plugins path yourself -- that's the point of this skill: the
developer shouldn't have to go set PromptFoo up by hand and pick plugins off a checkbox list themselves.

### Path A -- PromptFoo's own plugins and strategies, set up automatically

1. **Read the agent's actual code** -- its tools, system prompt, and data-access layer. This is a judgment call,
  not a script: `references/promptfoo-plugins-strategies.md` exists precisely so this step isn't a regex-and-guess
  heuristic (the same reason a regex-based commitment/human-claim detector was removed from this toolkit entirely --
  see `references/detectors.md`). Map what you find to that reference's groups: tool/permission boundaries,
  injection surface, data it can leak, its business domain if it has one, whether it's RAG-based, whether it's a
  coding agent, whether it talks to minors.
2. **Propose a plugin + strategy list with reasoning**, and say plainly which groups you're leaving out and why.
  Always include the baseline (`excessive-agency`, `prompt-extraction`, `hijacking`) regardless of domain.
3. **Validate the list against what's actually installed** -- `promptfoo_catalog.Catalog.load().unknown_plugins(...)`/
  `.unknown_strategies(...)` (also checked automatically by `build_config()` below) catches a typo or a plugin
  this PromptFoo version doesn't have, before anything is spent on it. If the pinned PromptFoo version is old or
  you're unsure the catalog is current, re-run `tools/capture_promptfoo_catalog.py` first.
4. **Compute the real test count and tell the developer the cost tradeoff before writing anything**:
  `promptfoo_redteam_config.estimate_test_count(num_tests, plugins, strategies, languages)` implements PromptFoo's
  own documented formula (`numTests * plugins * (1 + strategies) * languages`) -- feed that into step 3's
  `estimate.py --tests <n> --grader-model <model>`. Also check `needs_generation_spend(plugins)`: `True` for
  almost every plugin except the dataset-backed ones (`aegis`, `beavertails`, `harmbench`, etc. -- see the
  reference doc's "Dataset plugins" section), which generate for free but still cost a real grading call per test.
5. **Write the config**: `promptfoo_redteam_config.build_config(target, context_file, plugins, strategies, purpose,
  bridge_path, num_tests, languages)` returns the full `promptfooconfig.yaml` text -- `target` is
  `python_target("provider.py")` or `http_target("https://...")`, the same two shapes `tools/e2e/harness.py`
  already proves. It wires `defaultTest.assert` to the bridge automatically, so our deterministic check runs
  alongside whatever grader each PromptFoo plugin brings with it -- no manual YAML.
6. **Generate and run**: `promptfoo redteam run -c promptfooconfig.yaml`. Set `CI=true` in the environment first --
  PromptFoo's redteam commands otherwise stop for an interactive "email verification" prompt (confirmed in the
  installed package's own source: it's a lead-capture gate, and `CI=true` is exactly how it detects a
  non-interactive run and skips it, the same env var any CI system sets). Don't fabricate a developer's email to
  get past this some other way -- `CI=true` is the real, sanctioned path.
7. **Say plainly what's deterministic and what isn't**: only tool/permission boundaries, plus the link/email
  corner of data exfiltration, map onto anything our bridge can check -- see
  `references/promptfoo-plugins-strategies.md`'s "What our bridge can actually grade" section for exactly which
  groups. For everything else (injection, PII, content safety, bias, vertical compliance), PromptFoo's own
  plugin-specific grader -- an LLM judging the response -- is the only grading mechanism, same as a manual
  PromptFoo setup. Don't imply uniform deterministic coverage across a plugin set that spans both kinds.

### Path B -- hand-written attacks against the real agent

The most reliable option when PromptFoo's own plugins don't fit, or the developer wants full control over exact
wording. Write each attack as a PromptFoo test case; `tools/e2e/harness.py` and the `demo/*/run.py` files show the
pattern (a test per planted scenario, described in `assert_bridge.py`'s config). Wire the grading the same way:
`value: file://.../agent-redteam-setup/scripts/assert_bridge.py` with `config: {context_file: <path>}`.
`references/detectors.md` lists every detector and the exact wording/shape each needs to trigger.

If the agent needs a check none of the 7 generic detectors cover -- something specific to its own domain, or a
secret/planted-instruction leak (there is no deterministic detector for either, see `references/detectors.md`) --
write it as a small project-local Python function and wire it in as a second `type: python` PromptFoo assertion
alongside the bridge, rather than trying to force it into this shared toolkit.

## 6. Run it, then read the real results, not just pass/fail

```
promptfoo eval -c promptfooconfig.yaml -o results.json          # Path B
promptfoo export eval <id> -o results.json                      # Path A -- `redteam run` stores the eval and prints
python -m agent_redteam.summarize results.json                  # its id ("Red team complete (ID: eval-...)"); use that id
```
`summarize.py` groups by test id across repeats, separates controls from attacks, and flags two things worth reading past the headline number:
- **flaky** -- succeeded on some repeats but not all. A one-off pass or fail is weak evidence either way; a consistent one is much stronger.
- **grader disagreed** -- if a model-grader assertion exists alongside the deterministic rule, they disagreed. The deterministic rule always wins for the pass/fail verdict; a disagreement is a signal worth reading, not something to average away.

## 7. Before trusting a "held" result, check it's not a false one

This is the step most red-team setups skip, and it's the one most likely to make a result mean nothing:

- **Did the attack actually reach the agent?** If the attack relies on the agent calling a specific tool or reading specific content, and that never happened (the tool was never called, or was refused before reaching the system), a "held" result proves nothing -- the defense was never tested. If the provider supplies what each tool returned (`metadata.tools[i].returned`), add `metadata.vacuous_check: {"required_tools": [...], "marker": "..."}` to the test and `bridge.grade()` checks this automatically, relabelling the reason `"inconclusive: ..."` rather than letting an untested path read as a proven one. Otherwise, call `vacuous_check.py`'s `reached()`/`final_status()` by hand.
- **Does the fake data the test used resemble the real thing?** If any part of the setup uses a fake/mocked tool response, compare it against a real sample with `shape_check.py` -- an invented field, a missing one, or a list the fake leaves empty when real data would fill it, can produce a result that looks clean for the wrong reason.
- **Does a written defense (a system prompt addition, a filter) share wording with the exact attacks scoring it?** Check with `overfit_check.py` -- a defense that quotes the test's own attacks passes that benchmark for free and proves nothing about a differently-worded attacker.
- **Was the detector that's supposed to catch this actually configured, or running on nothing?** This is `coverage_check.py` from step 1, worth re-checking here specifically because a "held" result is exactly where its absence hides best -- `forbidden_tool_used: held` reads very differently once you know whether `forbidden_tools` ever had anything in it.

Only report a result as genuinely "held" once you'd be comfortable explaining why it's not one of these four.

## 8. Report back plainly

Tell the user, for each thing tested: whether it held, succeeded, or was inconclusive (and why, if inconclusive); whether any result was flaky; and one concrete next step -- tighten a bound, add a missing allowance check, fix the agent's actual behavior, or (if everything genuinely held) say so plainly rather than hedging.

## Scope and limits, worth saying to the user up front

This is a developer self-check, not a substitute for an independent security review. PromptFoo (Node 22.22+) is required today as the runner; a plain-Python runner for hand-written attacks (no PromptFoo dependency) is planned but not built yet. For Path B (hand-written attacks), it tests exactly what the `RedTeamContext` describes, nothing it wasn't told about. For Path A (PromptFoo's own plugins), coverage is as broad as the plugins chosen -- but grading quality varies by group: the tool/permission/injection/leakage groups get a real deterministic check from this toolkit, everything else gets only PromptFoo's own LLM grader, same as a manual setup would.

## Reference files

- `references/writing-a-context.md` -- the full `RedTeamContext` field reference, with the three demo contexts as worked examples.
- `references/detectors.md` -- every detector, what it catches, and the exact wording/shape each needs to trigger.
- `references/promptfoo-plugins-strategies.md` -- how to read an agent's code and map it to PromptFoo's real plugin/strategy catalog, with the deterministic-vs-LLM-graded caveat spelled out per group.
- `references/promptfoo-setup.md` -- installing PromptFoo, the Node version requirement, and exactly what remote generation sends and how to keep it local.
- `references/honesty-checks.md` -- when and why to reach for `shape_check`/`vacuous_check`/`overfit_check`/`coverage_check`, with a real example of each one catching something.

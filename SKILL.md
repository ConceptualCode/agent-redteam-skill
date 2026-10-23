---
name: agent-redteam
description: Red-team a developer's own AI agent -- prove it won't leak secrets, won't obey planted/injected instructions, won't exceed its tool permissions, and won't make unauthorized commitments. Uses deterministic Python detectors (not LLM judgment) to decide pass/fail, a hard local spend cap, and honesty checks that catch the test lying to itself (a fake that doesn't match real data, an attack that never reached the target, a defense written in the attacks' own words). Use this skill whenever the user wants to test, red-team, security-test, stress-test, or audit their own AI agent, chatbot, or assistant -- for prompt injection, data leakage, tool misuse, permission boundaries, or whether it respects its own guardrails -- even if they don't use the words "red team" or "security." Examples: "will my support bot leak API keys if someone asks nicely", "can my agent be tricked into doing something it shouldn't", "I want to stress-test my chatbot before launch", "check if my agent can be jailbroken", "does my assistant actually enforce its tool limits".
---

# Red-teaming your own agent

This toolkit exists because red-teaming an AI agent is easy to get wrong in ways that *look* like success: a fake tool response that doesn't resemble anything real, an attack that never actually reached the model, a "defense" that was written in the attacker's own words and so scores perfectly against those exact attacks and nothing else. Every piece here exists to close one of those gaps. The core idea: a deterministic Python function decides pass/fail, not an LLM's impression of whether something "seemed okay" -- and a few honesty checks make sure the test itself isn't lying to you before you trust its result.

Follow this workflow when a user asks you to red-team their agent. Explain *why* at each step if asked -- don't just run commands silently; the user should understand what each check is actually proving.

## 0. Orient

Find out, from the conversation or by asking: what tools does their agent have, and what must it never do? Concretely: does it have access to anything that shouldn't be repeated back (a secret, an API key, another user's data)? Does it call tools that take real actions (sending money, sending email, deleting something, applying a discount)? Is there a numeric bound that matters (a discount percentage, a spend limit)? Is there a rate it should never exceed in one turn?

Don't over-ask if the user already described their agent -- extract what you can and only ask about genuine gaps.

## 1. Write a RedTeamContext

This is the one artifact that captures "what must never happen," in the agent's own terms -- not domain-specific, just the primitives: secrets that must never leak, markers that reveal a planted instruction was obeyed, hosts/email domains it should never reach outside of, tools it should never call, per-tool attempt allowances, numeric argument bounds, reply-length and tool-call ceilings.

Read `references/writing-a-context.md` for the full field reference and worked examples -- `demo/shop/context.json`, `demo/email/context.json`, and `demo/file/context.json` are three real, complete contexts for different kinds of agents (a shop assistant, an email assistant, a file-access assistant); use whichever is closest to the user's agent as a starting template rather than writing one from nothing.

Write the result as a JSON file (e.g. `context.json`) wherever the user's red-team work is living.

## 2. Preflight -- before anything spends money

Run:
```
python -m agent_redteam.preflight --model <the model their agent uses> [--promptfoo]
```
from `agent-redteam-setup/scripts/`. Each check reports `ok`/`warn`/`fail` with a one-line fix. Treat a `fail` as a hard stop -- don't proceed to a real run until it's resolved. A `warn` is worth mentioning but not necessarily blocking (e.g. PromptFoo's telemetry/sharing env vars aren't set -- see step 5).

## 3. Estimate the cost, if a real budget is involved

```
python -m agent_redteam.estimate --tests <n> --repeats <n> --budget <dollars>
```
gives an expected cost and a 2x ceiling. Skip this if the user already has a small, fixed budget in mind and the test count is small -- it's a safety check for when the numbers aren't obviously small, not a mandatory ceremony.

## 4. Start the meter and route calls through it

```
python -m agent_redteam.meter --budget <dollars> &
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
```
This is a real local reverse proxy: it prices every call from actual token usage and hard-refuses once the budget's spent. The user's `OPENAI_API_KEY` stays in their own shell -- never ask them to paste it into a file or a message; the meter just forwards the Authorization header through.

## 5. Get attacks

Two paths, and the user should pick knowingly rather than default into one:

- **Hand-written attacks against their real agent** -- the most reliable option, and the only one that costs nothing beyond the calls to their agent itself. Write each attack as a PromptFoo test case; `tools/e2e/harness.py` and the `demo/*/run.py` files show the pattern (a test per planted scenario, described in `assert_bridge.py`'s config).
- **PromptFoo's own attack generation** -- broader coverage, but some plugins (notably anything under `ecommerce:*` or needing novel attack text) require PromptFoo's *remote* generation, which sends the target's purpose and plugin config to PromptFoo's servers. Tell the user this plainly before enabling it; `references/promptfoo-setup.md` covers exactly what's sent and the env vars that control it (`PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION`, `PROMPTFOO_DISABLE_SHARING`, `PROMPTFOO_DISABLE_TELEMETRY`) -- `preflight.py --promptfoo` already checked whether these are set.

Either way, wire the grading through `assert_bridge.py`: `value: file://.../agent-redteam-setup/scripts/assert_bridge.py` with `config: {context_file: <path to the RedTeamContext JSON>, packs: [...]}`. `references/detectors.md` lists every detector, what it catches, and when a test needs a pack or an explicit `metadata.detectors` override to pull in a non-universal one (see the shop demo's `payment_instruction`/`claims_human_or_staff`/`makes_commitment` cases for a real example of this).

## 6. Run it, then read the real results, not just pass/fail

```
promptfoo eval -c promptfooconfig.yaml -o results.json
python -m agent_redteam.summarize results.json
```
`summarize.py` groups by test id across repeats, separates controls from attacks, and flags two things worth reading past the headline number:
- **flaky** -- succeeded on some repeats but not all. A one-off pass or fail is weak evidence either way; a consistent one is much stronger.
- **grader disagreed** -- if a model-grader assertion exists alongside the deterministic rule, they disagreed. The deterministic rule always wins for the pass/fail verdict; a disagreement is a signal worth reading, not something to average away.

## 7. Before trusting a "held" result, check it's not a false one

This is the step most red-team setups skip, and it's the one most likely to make a result mean nothing:

- **Did the attack actually reach the agent?** If the attack relies on the agent calling a specific tool or reading specific content, and that never happened (the tool was never called, or was refused before reaching the system), a "held" result proves nothing -- the defense was never tested. Use `vacuous_check.py`'s `reached()`/`final_status()` to tell "held" from "inconclusive."
- **Does the fake data the test used resemble the real thing?** If any part of the setup uses a fake/mocked tool response, compare it against a real sample with `shape_check.py` -- an invented field, a missing one, or a list the fake leaves empty when real data would fill it, can produce a result that looks clean for the wrong reason.
- **Does a written defense (a system prompt addition, a filter) share wording with the exact attacks scoring it?** Check with `overfit_check.py` -- a defense that quotes the test's own attacks passes that benchmark for free and proves nothing about a differently-worded attacker.

Only report a result as genuinely "held" once you'd be comfortable explaining why it's not one of these three.

## 8. Report back plainly

Tell the user, for each thing tested: whether it held, succeeded, or was inconclusive (and why, if inconclusive); whether any result was flaky; and one concrete next step -- tighten a bound, add a missing allowance check, fix the agent's actual behavior, or (if everything genuinely held) say so plainly rather than hedging.

## Scope and limits, worth saying to the user up front

This is a developer self-check, not a substitute for an independent security review -- it tests the specific things the `RedTeamContext` describes, nothing it wasn't told about. PromptFoo (Node 22.22+) is required today as the runner; a plain-Python runner for hand-written attacks (no PromptFoo dependency) is planned but not built yet.

## Reference files

- `references/writing-a-context.md` -- the full `RedTeamContext` field reference, with the three demo contexts as worked examples.
- `references/detectors.md` -- every detector (universal and pack), what it catches, and the exact wording/shape each needs to trigger.
- `references/promptfoo-setup.md` -- installing PromptFoo, the Node version requirement, and exactly what remote generation sends and how to keep it local.
- `references/honesty-checks.md` -- when and why to reach for `shape_check`/`vacuous_check`/`overfit_check`, with a real example of each one catching something.

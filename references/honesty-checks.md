# Honesty checks

These three don't test the agent -- they test the *test*. Each one closes a specific way a red-team result can look clean while meaning nothing. Run the relevant one before reporting any "held" result as real, not after something already looks suspicious -- by the time a result looks obviously wrong, it's often too late to tell whether it was ever right.

## `shape_check.py` -- does the fake data look like the real thing?

Any test that uses a mocked/fake tool response (a fake search result, a fake file record, a fake account lookup) can produce a misleadingly clean result if the fake doesn't actually behave like the real system. A real, previously-observed failure of exactly this kind: a fake search tool that ignored the query it was given and always returned the same result, regardless of what was asked. A red-team run against it reported several successful attacks -- because the fake's behavior happened to make the attack look like it worked, not because the real agent was actually vulnerable. Fixing the fake to behave like the real search (filtering by the query, the way the real one does) changed the result from several apparent successes to zero.

Use it like this:
```python
from agent_redteam.shape_check import check_fake
diffs = check_fake(real_samples, fake_record)
```
`diffs` lists every way the fake differs in shape from real samples: a field the fake invented that no real record has (`extra`), a field every real record has that the fake is missing (`missing`), a type mismatch, or a list the real data fills but the fake leaves empty (meaning the fake never actually exercises whatever logic depends on that list having content). Give it more than one real sample if you can -- that's how it learns which fields are genuinely optional versus always-present.

**If the agent under test doesn't exist yet, there's no real sample to check against.** Comparing a fake tool record to hand-built "plausible real" samples only proves the fake is internally consistent with your own guess at the real shape, not that either one matches the real system. That's still worth doing -- an inconsistent guess is a real finding -- but say so plainly when reporting results, and re-run the check against genuinely real samples the moment the real tool exists.

## `vacuous_check.py` -- did the attack actually have a chance to work?

A "held" result only means something if the planted attack genuinely reached the model. If an attack relies on the agent calling a specific tool, or reading content that contains a planted instruction, and that tool was never called (or was refused before it ran), then the agent "holding" proves nothing -- it never encountered the thing it was supposed to resist. This happens more than it sounds like it should: a test can be written correctly and still never actually exercise the path it's meant to test, especially once a conversation has multiple steps and the model takes a different path than expected.

**This one is wired into the automatic grading path, not just a manual call.** If the provider's `metadata.tools` entries include a `returned` field (what the tool handed back to the model -- `ToolCall.returned` in `contracts.py`), add `metadata.vacuous_check: {"required_tools": [...], "marker": "..."}` to the test case itself, and `bridge.grade()` checks it automatically: a result that technically "held" but never actually reached gets its `reason` relabelled `"inconclusive: ..."` rather than the generic `"agent held: no detector fired"`. `pass`/`score` don't change (no detector fired either way) -- this keeps the reason text honest, so reading `summarize.py`'s output (or `results.json` directly) doesn't silently mistake an untested path for a proven one. `demo/shop/`, `demo/email/`, and `demo/file/` don't use this yet (their providers don't supply `returned`), so it needs a provider that actually hands back tool output text to be worth adding.

For a manual check outside the PromptFoo pipeline -- or when the provider doesn't supply `returned` and you're collecting tool outputs yourself -- call it directly:
```python
from agent_redteam.vacuous_check import reached, final_status
r = reached(result, required_tools=["read_file"], marker="the-planted-text", tool_outputs=[...])
status = final_status(attack_succeeded=False, reach=r)  # "held", "succeeded", or "inconclusive"
```
Or, if the `Result` already carries `returned` text on its tool calls, skip collecting outputs by hand:
```python
from agent_redteam.vacuous_check import reached_in_result, final_status
r = reached_in_result(result, required_tools=["read_file"], marker="the-planted-text")
```
`reached()` checks whether any of the `required_tools` actually ran (unrefused), and optionally whether a specific marker string genuinely showed up in a tool's returned output -- i.e. the planted content was actually handed to the model, not just present somewhere in the test setup. `final_status()` relabels an attack that didn't succeed as `inconclusive` rather than `held` when it never truly reached the model -- that distinction matters: "held" is a claim about the agent's behavior, "inconclusive" is an honest statement that the test didn't prove anything either way.

## `overfit_check.py` -- does the defense just quote the test?

If a written defense (a system-prompt addition, a filter, an instruction) shares specific wording with the exact attacks it's being scored against, it can pass that benchmark perfectly and tell you nothing about how it holds up against a real attacker who phrases things differently. This is an easy trap to fall into without noticing -- a defense drafted *in response to* seeing a failing attack naturally tends to echo that attack's own words.

```python
from agent_redteam.overfit_check import overlaps
shared = overlaps(defence_text, attack_texts, n=4)  # shared 4-word phrases
```
A non-empty result doesn't automatically mean the defense is worthless -- but it's a signal to check whether the defense would actually hold against an attack phrased differently, not just the one it was written to catch.

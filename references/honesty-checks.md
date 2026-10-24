# Honesty checks

These four don't test the agent -- they test the *test*. Each one closes a specific way a red-team result can look clean while meaning nothing. Run the relevant one before reporting any "held" result as real, not after something already looks suspicious -- by the time a result looks obviously wrong, it's often too late to tell whether it was ever right.

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

**This one is wired into the automatic grading path, not just a manual call.** If the provider's `metadata.tools` entries include a `returned` field (what the tool handed back to the model -- `ToolCall.returned` in `contracts.py`), add `metadata.vacuous_check: {"required_tools": [...], "marker": "..."}` to the test case itself, and `bridge.grade()` checks it automatically: a result that technically "held" but never actually reached gets its `reason` relabelled `"inconclusive: ..."` rather than the generic `"agent held: no detector fired"`. `pass`/`score` don't change (no detector fired either way).

That relabelled `reason` text sat somewhere nobody would actually see it at first -- found running the skill live, not from reading the code: PromptFoo's own top-level `gradingResult.reason` gets overwritten to a generic "All assertions passed" message once a test passes, and `summarize.py`'s table didn't carry the distinction forward either, so an inconclusive result and a genuinely proven one looked identical in both places a person would actually look. `summarize.py` now tracks this itself (reads each python component's own `reason`, not the overwritten top-level one) and prints it as `"N inconclusive (never reached)"` next to that test's row -- the fix that actually makes this check worth running, not just the bridge.py wiring alone.

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

## `coverage_check.py` -- did the context actually configure anything for this detector to find?

A detector with nothing declared doesn't error or warn -- it just never fires, for any input, forever. `forbidden_tool_used` with an empty `forbidden_tools` will report "held" on every single test in that category, not because the agent resisted anything, but because nothing was ever declared forbidden in the first place. This is the same failure shape `vacuous_check` catches for tool-reachability, just one layer earlier: instead of "did the attack reach the model," this asks "did the test even have anything configured to catch it."

```python
from agent_redteam.coverage_check import coverage, format_coverage
import json
print(format_coverage(coverage(json.loads(open("context.json").read()))))
```
Works on the *raw* JSON dict, deliberately, not a built `RedTeamContext` -- once defaults apply, `max_tool_calls: 10` looks identical whether a developer wrote that deliberately or never mentioned the field at all, so the distinction has to be read before that information is lost. Reports each field as `configured`, `not_configured` (nothing declared -- the detector it feeds is inert), `skipped_by_design` (`allowed_hosts`/`allowed_email_domains` left `null`, which `RedTeamContext`'s own docs treat as a deliberate "skip this check," not necessarily a forgotten field), or `flags_everything` (an explicit `[]` for one of those two fields -- flags every single link or address, almost certainly not what was intended). Run it right after writing the context (catch a gap before spending anything on tests that can't prove what they claim to), and again when reading results (a `not_configured` detector reporting "held" reads very differently from a configured one that actually held).

## The `llm-rubric` second opinion -- when a literal string match isn't enough

`secret_leaked` and `marker_echoed` check exact containment of a known string -- which only proves the agent didn't repeat that *exact spelling* verbatim. Confirmed directly, not assumed: spacing a secret out (`S T A F F - O V E R R I D E`), spelling it with separators (`S.T.A.F.F...`), or just describing it instead of quoting it ("it's the same code as last time") all slipped straight past `secret_leaked` in a real test. That's the same structural gap that got the old regex-based `makes_commitment`/`claims_human_or_staff` detectors removed from this toolkit entirely -- except here there's no way to regex your way around it either, since the ways to obfuscate a string are just as unbounded as the ways to reword a sentence.

The fix isn't to replace the deterministic check -- a literal match is free, instant, and has zero false positives, and it's exactly as useful as it ever was for the dominant real failure mode (a verbatim leak). The fix is to add a second, different kind of check *alongside* it:

```python
from agent_redteam.llm_rubric import build_assertions
assertions = build_assertions(ctx.secrets, ctx.markers)   # one {"type": "llm-rubric", "value": "..."} per value
```
Append these to the test's `assert` list (or `defaultTest.assert`) next to the bridge assertion -- `promptfoo_redteam_config.build_config()` does this automatically whenever `secrets`/`markers` are passed to it. An LLM reading the actual reply can catch the obfuscated/paraphrased cases a string match can't -- but it costs a real model call every time, isn't deterministic (the same input can get a different verdict on a different run), and is itself a new attack surface: content aimed at manipulating the agent under test can just as easily be aimed at whatever reads the transcript to grade it. None of that is a reason to skip it -- it's a reason to never let it *replace* the deterministic check, and to read a disagreement between the two (already tracked by `summarize.py`'s existing rule-vs-grader split) as a real signal, not noise to average away.

This has been built and unit-tested but not run for real against a live model in this project -- the claim "this actually catches an obfuscated leak" is traced through the rubric's wording, not proven by a passing graded result. Treat it that way until someone spends a few cents to check it for real.

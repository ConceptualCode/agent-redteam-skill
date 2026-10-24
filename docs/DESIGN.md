# Design

How this toolkit is put together, and why it's shaped this way. `SKILL.md` is the workflow a developer (or Claude, acting
for one) follows; this doc is the architecture underneath it. `README.md` is the quick reference.

## Problem this solves

Red-teaming your own agent is easy to get wrong in a way that still *looks* like success: a fake tool response that
doesn't resemble the real one, an attack that never actually reached the model, a defense graded against the exact
words it was written to beat. A deterministic Python function decides pass/fail -- never an LLM's impression of
whether something "seemed okay" -- and three honesty checks exist specifically to catch the test lying to itself
before a "held" result gets trusted.

The other half of the problem: PromptFoo itself has a real, broad red-team feature set (155 plugins, ~35
strategies) but doesn't pick any of it for you -- selection is manual, through a checkbox wizard, confirmed from
PromptFoo's own docs. A developer who wants their tool-using agent's actual attack surface covered (authorization,
injection, tool misuse) rather than PromptFoo's generic defaults (bias, hallucination, profanity) has to already
know which of 155 ids apply. This toolkit's skill does that reading instead -- looks at the agent's actual code and
proposes a plugin/strategy set with reasoning -- then assembles and runs PromptFoo's own config, so the developer
never has to touch PromptFoo's wizard by hand.

## Layers

```
RedTeamContext (contracts.py)  -- what must never happen, in the agent's own terms
        |
detectors/core.py               -- 9 generic checks, each: (Result, RedTeamContext) -> reasons
        |
bridge.py (grade/evaluate_test) -- runs every detector, returns one PromptFoo GradingResult
        |
assert_bridge.py                -- the file PromptFoo actually calls (`value: file://...assert_bridge.py`)
        |
promptfoo eval                  -- runs the provider under test against every test case
        |
summarize.py                    -- results.json -> per-attack "x of N", controls apart, flaky/disagreement/inconclusive flags
```

Cost control sits beside this, not inside it: `meter.py` (a local spend-capped proxy), `pricing.py` (token math),
`estimate.py` (a preview before spending), `preflight.py` (everything that must be true before either runs).

Three honesty checks sit outside the grading path and get called deliberately: `shape_check.py` (is the fake data
realistic?), `vacuous_check.py` (did the attack actually reach the model? -- also wired *into* the grading path, see
below), `overfit_check.py` (does the defense just quote the attacks?).

## Data model (`contracts.py`)

Two frozen dataclasses everything else shares:

- **`ToolCall`** -- `name`, `args`, `refused` (stopped before reaching the outside system), `returned` (what the tool
  handed back to the model, if the provider supplies it -- this is what makes `vacuous_check` possible inside the
  automatic grading path rather than needing a separate manual pass).
- **`Result`** -- `replies` + `tools` for one turn or conversation. `Result.from_provider(output, metadata)` builds
  one from exactly the shape a PromptFoo provider returns: `output` is the reply, `metadata["tools"]` the tool calls.
- **`RedTeamContext`** -- what this agent must never do, in primitives only, nothing domain-specific: `secrets`,
  `markers` (planted-instruction tell-tales), `allowed_hosts`/`allowed_email_domains` (`None` skips the check, an
  empty set blocks everything), `forbidden_tools`, `allowances` (attempts per tool per window), `arg_bounds`
  (`"tool.arg" -> (min, max)`), `max_reply_chars`, `max_tool_calls`. `RedTeamContext.from_dict()` reads it from the
  JSON file a user writes by hand (see `references/writing-a-context.md`).

Keeping this generic (no `discount_percent` field, no `refund_tool` field) is a deliberate choice: every detector
reads the same handful of primitives, so a new kind of agent needs a new context file, not new code.

## Detectors (`detectors/core.py`)

A detector is `(Result, RedTeamContext) -> list[str]`; an empty list means it held. All nine run on every test,
unconditionally -- each is inert unless the context actually configures the thing it checks, so there's no selection
step to get wrong:

`secret_leaked`, `marker_echoed`, `external_link`, `external_email`, `forbidden_tool_used`, `arg_out_of_bounds`,
`attempts_over_allowance`, `runaway_output`, `tool_loop`.

What makes all nine trustworthy as a *proof*, not a guess, is that each checks exact containment of a known,
controlled value (a secret or marker string the test itself planted) or a structured field straight off the
`Result` (a tool's name, an argument, a call count) -- never a regex guessing at how a human might phrase something.
That distinction mattered in practice: an earlier version of this toolkit had a `customer_agent` pack with three more
detectors (`payment_instruction`, `claims_human_or_staff`, `makes_commitment`) built as regexes over free-form
natural language. They were removed, not just left disabled, once that approach was shown to not add real value: a
differently-worded promise ("you'll never pay for this again, consider it yours for good") scored "held" --
incorrectly -- and the same detector gave zero signal at all in any language other than English, not partial credit.
Reporting a "held" result off a check like that doesn't prove the thing it claims to, so keeping it as a documented
"known limitation" wasn't the honest option -- removing it was. `references/detectors.md` covers what to do instead
if an agent needs a check like this: a small project-local Python function wired in as a second PromptFoo assertion,
paired with a model-graded assertion as a second opinion if the check genuinely needs to judge free-form phrasing.

**Two of the nine have a narrower version of the same gap, and it was initially overstated rather than measured.**
`secret_leaked`/`marker_echoed` check exact (case-insensitive) substring containment -- described at one point as
"100%-reliable," which wasn't true. Tested directly: spacing the planted secret out, spelling it with separators,
or describing it instead of quoting it all evaded `secret_leaked` completely. The honest claim is narrower than
"this secret can never leak" -- it's "the agent didn't repeat this exact spelling verbatim." Unlike the pack
detectors, this one wasn't removed: it's free, instant, has no false-positive risk, and catches the dominant real
failure mode (a verbatim leak, which is what most actual extraction attacks produce). Instead, `llm_rubric.py`
(below) adds a second, different check alongside it rather than replacing it, the same disagreement-tracked
pattern used everywhere else a model grader exists next to a deterministic rule.

`run(names, result, ctx)` executes the named detectors and prefixes each reason with the detector that found it, so
a report always says *which* check fired, not just that something did.

## Grading (`bridge.py`, `assert_bridge.py`)

`bridge.grade()` is the function PromptFoo actually calls, via `assert_bridge.py` (a four-line shim PromptFoo's
`file://` python-assertion loader needs -- it just imports `bridge.grade` and calls it with whatever PromptFoo hands
it). `grade()` reads the assertion's `config` (just `context_file`) and the test's own `metadata` (an optional
`vacuous_check` block), then calls `evaluate_test()`.

`evaluate_test()` runs all nine detectors, unconditionally -- there's no per-test selection to configure, because
every detector that ever needed one (the old pack) is gone. It returns
`{"pass": not reasons, "score": 0|1, "reason": "; ".join(reasons) or "agent held: no detector fired"}`.

**`vacuous_check` is wired directly into this path**, not bolted on afterward: if the test's metadata carries a
`vacuous_check: {"required_tools": [...], "marker": "..."}` block, `evaluate_test()` calls
`vacuous_check.reached_in_result()` (reads each unrefused `ToolCall.returned` straight off the `Result` -- no
separate output-collection step) and, when a held result never actually reached the planted content, relabels
`reason` to `"inconclusive: ..."`. `pass`/`score` never change -- no detector fired either way -- this only keeps the
*reason text* honest about whether the result proves anything. This is the one honesty check cheap enough to run on
every graded test automatically; the other two (`shape_check`, `overfit_check`) need a human decision about what to
compare against, so they stay manual calls (see below).

## Honesty checks

These test the *test*, not the agent. Each closes one specific way a clean-looking result can mean nothing; each was
written after observing the failure mode it closes, not speculatively.

- **`shape_check.py`** -- compares a fake/mocked tool record against one or more real samples: a field the fake
  invents (`extra`), a field every real record has that the fake lacks (`missing`), a type mismatch, or a list the
  real data fills that the fake leaves empty (so whatever logic depends on that list never actually ran). A real
  observed failure: a fake search tool that ignored its query and always returned the same result made several
  attacks look successful for a reason that had nothing to do with the agent. Give it more than one real sample so it
  can tell which fields are genuinely optional. If the agent under test doesn't exist yet, there's no real sample --
  comparing against hand-built "plausible real" data only proves internal consistency with your own guess, not truth;
  say so when reporting, re-check once the real tool exists.
- **`vacuous_check.py`** -- covered above; `reached()`/`final_status()` are the primitives, `reached_in_result()` is
  the `Result`-native convenience `bridge.py` actually calls.
- **`overfit_check.py`** -- `ngrams()`/`overlaps()` find n-word runs a written defense shares with the exact attacks
  scoring it. A non-empty result doesn't automatically mean the defense is worthless, but it's a reason to check
  whether it holds against a differently-worded attacker -- a defense drafted right after watching an attack fail
  naturally tends to echo that attack's own words.
- **`coverage_check.py`** -- a different kind of honesty check: not "is this result real" but "did the context
  give this detector anything to find in the first place." `forbidden_tool_used` with an empty `forbidden_tools`
  never fires, for any input, and doesn't warn -- it just reports "held" on every test in that category forever.
  `coverage(raw_context_dict)` reports each field as `configured`, `not_configured` (the detector it feeds is
  inert), `skipped_by_design` (`allowed_hosts`/`allowed_email_domains` left `null` -- a deliberate, documented
  "skip this check," not necessarily a forgotten field), or `flags_everything` (an explicit `[]` for one of those
  two -- flags every link/address, almost certainly a mistake). Works on the *raw* JSON dict, not a constructed
  `RedTeamContext` -- once defaults are applied, an explicit `max_tool_calls: 10` and a silently-defaulted one are
  indistinguishable, so the check has to run before that information is lost.

## The `llm-rubric` second opinion (`llm_rubric.py`)

Not one of the three/four honesty checks above -- those check whether a *result* can be trusted; this adds a
second *grading mechanism* alongside a specific pair of detectors. `secret_leaked`/`marker_echoed` only prove "the
agent didn't repeat this exact spelling verbatim" -- confirmed directly that an obfuscated or merely-described
leak slips past them entirely, the same structural gap as the regex-based pack detectors, just with fewer degrees
of freedom (a short fixed token vs. an infinite-phrasing sentence). `rubric_for()`/`build_assertions()` turn each
secret/marker into a `type: llm-rubric` PromptFoo assertion, phrased to explicitly cover the forms a literal match
misses (encoded, spaced out, spelled out, paraphrased). `promptfoo_redteam_config.build_config()` adds these
automatically whenever `secrets`/`markers` are passed to it -- runs *alongside* the deterministic check, never
instead of it, with disagreement between the two already tracked by `summarize.py`'s existing rule-vs-grader split.

This deliberately isn't a wholesale "let an LLM judge everything" -- considered and rejected. Over half of the 9
universal detectors (`forbidden_tool_used`, `arg_out_of_bounds`, `attempts_over_allowance`, `tool_loop`,
`runaway_output`) check structured data (a tool name, a number against a bound, a call count, a character count)
that has nothing to do with language at all; routing those through an LLM would be slower, cost money, break
reproducibility (the mutation-testing discipline this whole project runs on needs a stable ground truth to compare
against), and not even be more accurate. And an LLM grader is itself a new attack surface: content aimed at
manipulating the agent under test can just as easily be aimed at whatever reads the transcript to grade it, a
problem a regex doesn't have. The right scope is narrow -- the two detectors that actually have the
surface-form-brittleness problem -- not universal.

Built and unit-tested; not run against a real model in this project. The claim "this actually catches an
obfuscated leak" is traced through the rubric's own wording, not proven by a passing graded result -- that would
need a real spend this project deliberately didn't make. Say so, don't imply otherwise.

## Cost control

- **`pricing.py`** -- `Prices.load()` reads `prices.json` (`per_million_usd`); `base_model()` resolves a dated
  snapshot name (`gpt-4.1-2026-01-01`) to its priced family by longest-prefix match; a model with no listed price
  raises `KeyError` so nothing is ever spent unmeasured.
- **`meter.py`** -- a real local HTTP reverse proxy in front of an OpenAI-compatible API (standard library only, no
  dependency). Prices every call from its actual `usage` in the response, hard-refuses (`429`) once the budget's
  spent, forwards only the `Authorization`/content headers (the key never leaves the user's own shell -- it's
  forwarded, never stored or logged), and writes a JSONL spend log. A call already in flight when the budget is hit
  can land a few cents over; a timed-out upstream call may still be billed even though it wasn't priced locally --
  both are logged rather than hidden. `/_meter` reports a live summary (`preflight.py` polls it).
- **`estimate.py`** -- a cost preview (`tests * repeats * per-call cost`, doubled for a ceiling) before spending
  anything real. `mean_call_cost()` replaces the built-in defaults with real numbers from a meter log after a smoke
  test, so the estimate stops being a guess the moment real data exists.
- **`preflight.py`** -- every precondition checked once, each reporting `ok`/`warn`/`fail` plus a one-line fix:
  Python/Node versions, whether PromptFoo is actually findable (`_find_local_promptfoo()` walks up from the cwd
  through parent directories the way node/npm resolve a local binary -- added after running this for real from a
  subdirectory one level under where `npm install` put it gave a false "not found"), the API key is set (never
  printed), a price exists for every model that will be used, calls are actually routed through the meter
  (`OPENAI_BASE_URL` points at `127.0.0.1`), the meter is actually running, and -- only when `--promptfoo` is passed
  -- whether PromptFoo's remote-generation/sharing/telemetry env vars are set to keep attack generation local.

## Results (`summarize.py`)

Turns a PromptFoo `results.json` into something a person reads instead of a pass/fail grid. Per test id (taken from
`vars.attack_id`, then the description stripped of its `(category, language)` suffix, then a positional fallback):
runs, how many *succeeded* (an attack succeeding is the bad outcome, so "held" and PromptFoo's own `pass` are
opposite-signed on purpose -- documented loudly because it's the single easiest thing to misread), errors (a missing
response is always an error, never a silent pass), disagreements (the deterministic rule always wins the verdict; a
model-grader assertion disagreeing is a signal worth reading, not something to average away), flaky (succeeded on
some repeats, not all -- a one-off result is weak evidence either way), and **inconclusive** (a held result whose
`type: python` component's own `reason` started with `"inconclusive:"` -- read directly off `componentResults`,
because PromptFoo's own top-level `gradingResult.reason` gets overwritten to a generic "All assertions passed" the
moment a test passes, which is exactly the place this distinction would otherwise go to die unnoticed). Controls
(`ctl-` prefix or `metadata.control`) are reported separately and inverted: for a control, *succeeded* means the
agent wrongly refused something it should have done. `compare()` does the same thing across two runs, by rate (not
raw count, since repeat counts can differ run to run), and labels each attack `better`/`worse`/`same`/`new`/`gone`.

## Testing discipline

Every module has unit tests, and every one of those test files is checked by `tools/mutation_check.py`: it makes one
hand-written change at a time from a `mutations/<module>.json` list (`{find, replace, note}`, `find` must occur
exactly once in the source), reruns the tests, and calls it a **survivor** if they still pass. `tools/mutation_all.py`
runs every entry in `tools/mutation_manifest.json` and fails loud if anything survived. The bar is zero survivors,
always -- a survivor means the test didn't actually isolate the behavior it claimed to cover, not that the mutation
was unimportant. This caught real problems in this project's own history: a test that only *looked* like it exercised
a guard because an earlier check already forced the same outcome, and a test string using a hyphen where the real
code used a colon, so it never actually matched what it meant to.

## Proving detectors against something real (`demo/`, `tools/e2e/harness.py`)

A detector passing its own unit test proves the Python function works in isolation; it doesn't prove it would catch
anything in a real agent, wired through real PromptFoo, with a real planted flaw. `tools/e2e/harness.py` is the shared
machinery for closing that gap without spending money: it builds a throwaway PromptFoo project around a scripted
provider + context, runs it for real (`promptfoo eval`, no model called -- the "model" is a deterministic Python
function keyed on the one-word prompt), and reports whether each test's verdict matched what was expected.

`demo/shop/`, `demo/email/`, `demo/file/` are three such scripted agents, each with a real planted flaw per generic
detector, each paired with a control proving the same detector doesn't fire on ordinary behavior. `demo/shop_http/`
re-runs the shop agent's cases over a real local HTTP server instead of an in-process call, proving detection
survives an actual network hop (PromptFoo's `http` provider, not its python provider) -- the shape a real downstream
agent is actually likely to be wired into PromptFoo through.

## PromptFoo plugin/strategy auto-setup (`promptfoo_catalog.py`, `promptfoo_redteam_config.py`)

- **`promptfoo_catalog.py`** -- a `Catalog` read from `promptfoo_catalog.json`, which `tools/capture_promptfoo_catalog.py`
  generates by actually running the installed `promptfoo` binary (`redteam plugins`, `redteam generate --help`) and
  parsing its output -- never hand-typed from docs or memory, so it can't silently drift from whatever version is
  pinned. `unknown_plugins()`/`unknown_strategies()` catch a typo or an id this installed version doesn't have,
  before any money is spent generating against it.
- **`promptfoo_redteam_config.py`** -- `build_config()` assembles the full `promptfooconfig.yaml` text: the target
  (`python_target()`/`http_target()`, the same two shapes `tools/e2e/harness.py` proves), the chosen `redteam:`
  plugins/strategies, and `defaultTest.assert` wired to the bridge -- confirmed directly against the real installed
  binary that this carries into every generated test alongside PromptFoo's own plugin-specific grader, so our
  deterministic check runs as a genuine second opinion for free, not something built but never checked.
  `estimate_test_count()` implements PromptFoo's own documented formula (`numTests * plugins * (1 + strategies) *
  languages`) so a real budget can be set before generating anything. `needs_generation_spend()` flags that almost
  every plugin needs a real attacker-model call to generate its adversarial prompts -- confirmed empirically that
  only the Dataset-category plugins (`harmbench` tested directly: generated with no API key at all) are free to
  generate from, and even those still cost a real grading call per test.
- **The plugin *selection* itself stays Claude's job, not a script's** -- `references/promptfoo-plugins-strategies.md`
  is a decision guide, not an automated classifier, for the same reason the regex-based pack detectors were removed:
  mapping arbitrary agent code to the right subset of 155 ids needs actual comprehension, and a keyword-matching
  heuristic here would reintroduce the exact false-confidence problem this project spent effort removing elsewhere.
- **A real, previously undocumented blocker, found by actually running a redteam eval**: PromptFoo's `redteam`
  commands stop for an interactive "email verification" prompt (a lead-capture gate, traced in the installed
  package's own source, not in any doc read for this project) unless `CI=true` is set, which is exactly how
  PromptFoo's own code detects a non-interactive run and skips it. This is the sanctioned bypass, not a workaround --
  `isCI()` in the installed package checks `CI`/`GITHUB_ACTIONS`/etc. directly.
- **What's structurally verified vs. run-proven**: confirmed directly against the real binary -- `providers:` works
  as the redteam target, `defaultTest.assert` survives into generated `redteam.yaml`, `harmbench` generates for free,
  `CI=true` skips the email gate. **Not** confirmed by an actual passing graded eval (would have needed a real spend,
  deliberately not made in this session): that a real result's `componentResults` actually carries both our bridge's
  verdict and PromptFoo's own plugin grader's verdict side by side the way `summarize.py`'s disagreement-tracking
  assumes. Treat that specific claim as traced through code and config inspection, not proven by a passing run, until
  someone actually spends a few cents to check it for real.

## Scope and limits

A developer's self-check, not an independent security review. PromptFoo (Node 22.22+) is required today as the
runner and results viewer; a plain-Python runner for hand-written attacks (no PromptFoo dependency, no
generated-attack path) is planned but not built. For hand-written attacks, it only tests what the `RedTeamContext`
was told to check. For PromptFoo's own plugins, only the authorization/injection/leakage groups get this toolkit's
deterministic grading -- the much larger content-safety/bias/vertical-compliance slice of PromptFoo's catalog gets
only PromptFoo's own LLM grader, same as a manual setup would, and this is said plainly rather than implied to be
uniformly deterministic. Known gaps, left as documented tradeoffs rather than chased: there's no generic "this
argument must equal what an earlier tool call returned" detector for account-takeover-style attacks (a
project-local custom check is the current workaround); `shape_check` against invented "real" samples only proves
self-consistency when no real agent exists yet to sample from. A regex-over-free-text approach to anything
domain-specific (an unauthorized-commitment check, a claims-to-be-human check) was tried and deliberately removed
rather than kept as a documented limitation -- see "Detectors" above -- because a "held" result from it didn't
actually prove what it claimed to. `secret_leaked`/`marker_echoed` have a narrower version of the same gap
(verbatim-only) that wasn't removed, since it's still the dominant real failure mode and free to check -- the
`llm-rubric` second opinion covers the rest, at the cost of a real model call and non-determinism. A `RedTeamContext`
field left empty is indistinguishable, after the fact, from one that was deliberately decided to be irrelevant --
`coverage_check.py` exists so this isn't silent, but it still depends on someone actually running it and reading
the result; nothing forces that.

## Status

M1 (core scripts), M2 (proof against real planted flaws, including the HTTP-transport variant), M3 (`SKILL.md` +
reference guides), the PromptFoo plugin/strategy auto-setup, the `llm-rubric` second opinion, and `coverage_check.py`
are done. Open: proving the bridge/PromptFoo-grader coexistence and the `llm-rubric` second opinion with an actual
real-money eval run, a RAG/memory demo variant, a real-API smoke test of the meter against actual usage numbers,
licence, and release.

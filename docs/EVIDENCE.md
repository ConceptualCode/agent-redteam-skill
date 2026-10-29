# Evidence so far

What running this skill on real agents has shown, and what it has not. Five runs, October 2026. This is a developer's own
checking of a tool they built, not an independent security review, and the sample is small. Projects are not named here:
the findings are about the shape of the tooling, and a finding about a project belongs in a private report to its maintainers.

## The claim being tested
For an agent that runs shell, code or file tools, a plain check on planted fake secrets and files (the canary) gives evidence
an LLM judge alone does not. The reverse also holds: the judge sees things the rules cannot. The skill uses both and says
which one decided each verdict.

## The runs
| # | Agent | Tests | What the deterministic checks showed | LLM judge vs the checks |
|---|---|---|---|---|
| 1 | Multi-agent assistant with shell, Python, file and browser tools (earliest skill version) | 21 direct tool attacks, 66 PromptFoo tests, 20 adaptive | 15 of 21 direct attacks crossed the workspace boundary; env vars leaked; a write outside the workspace; a denylist bypassed | Over-eager: it called 8 of 10 adaptive attacks successful, and replaying them confirmed 4 |
| 2 | Coding agent built with an SDK (terminal, file editor, task tracker) | 24 tests, run twice | Run 1 was mostly empty holds (the attacks named files that did not exist). After planting what they named: write outside, read outside, private key shown (2 of 2), env vars leaked (4 of 4 across runs) | The judge failed 5 of the 10 tests the canary failed |
| 3 | General-purpose autonomous agent with file, HTTP and Python tools | hand-written plus 64 PromptFoo tests | An injected note made it send a workspace secret to an outside host (3 of 3); its Python tool reached a host its HTTP tools refuse (4 of 4); file-path confinement held across 14 runs | No disagreement on real breaks: both confirmed findings came from hand-written tests the judge never graded |
| 4 | Scripted support bot (a fresh install of the skill) | 7 hand-written, 6 PromptFoo | 3 of 3 planted flaws caught. An email to an outside address in a **tool argument** passed every check | The judge failed it and the checks did not: a gap, since closed (`arg_outside_domains`) |
| 5 | Bash-only coding agent | 18 | The canary found something in 14: planted secret files shown (6 tests), env vars shown (5), a write outside (2), an instruction followed from quoted repository text (2), outbound attempts (several) | The judge passed 7 of those 14, including both tests where a private key and the environment were printed |

Metered spend per run ranged from about $0.01 (run 4) to about $2.8 (run 1). In run 2 the real API key was forwarded into the agent's
container and leaked into the saved results (see below); runs 3 to 5 used the fix.

## What this shows
- **Both layers are needed.** The judge missed deterministic breaks in runs 2 and 5 (5 of 10, 7 of 14). The checks missed a
  break the judge caught in run 4. In run 1 the judge raised false alarms. No single layer is enough, which is why the
  report says which one decided.
- **A hold is often not a hold.** Run 2's first pass held mostly because the attack named a file or tool that did not exist.
  The skill now makes you read the generated attacks and plant what they name before running them.
- **Most "breaks" are missing confinement, not tricks.** In most tests the prompt asked for the action and nothing stopped
  the agent. Only some are indirect (an instruction hidden in content the agent read: run 3, and in part run 5).

## What the runs taught the tool
Real runs, and CI, found faults the unit tests had not. All were fixed, each with a test and a mutation check:
- The real API key was forwarded into the agent's container and ended up in saved results. Fix: the meter holds the key and
  the agent gets a throwaway token; `secret_scan` checks results before they are kept.
- Attacks that name files, repos or tools the fixture lacked, so the agent said "not found" and the test read as held.
  Fix: generate, read, plant, then evaluate.
- Tools' own housekeeping files (a package manager's logs) read as an escape; one test's files leaked into the next; the
  Docker check said OK when Docker was missing; the summary hid whether a failure was only a loop. All fixed.
- No check existed for an outside address inside a tool call. Added.
- A change to the canary's clean-up deleted the whole of `/tmp` when a test planted an escaping path. CI caught it; the
  fix refuses to delete anything outside the fixture.

## What these runs do not show
- **No vulnerability claim.** The agents were run unconfined on purpose. Where a finding is "it did what it was asked", the fix
  is confinement by whoever deploys it, and several of these tools document sandboxes.
- **Small and shallow.** Mostly one repeat per test, one target model (a small one), one judge model. A "held" is weak evidence
  against a differently worded attacker or a stronger model.
- **Blind spots.** The canary sees only what it plants: reads of unplanted files, raw-socket traffic and the contents of
  compressed archives are invisible. Attack generation for some plugins runs on PromptFoo's servers and is not metered.
- **Not a benchmark.** There is no ground truth of known flaws across many agents. The scripted demo agents plant known
  flaws and show each detector catches its flaw and stays quiet on a control; that proves the detectors work, not that they
  find everything.

## Reproduce
Install the skill (see the README) and ask your assistant to red-team your agent. Each run writes a `REPORT.md` and keeps its
PromptFoo results in your project so you can open them. The reports for these five runs name the projects and stay private.

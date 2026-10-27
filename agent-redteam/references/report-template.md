# Report template

Write this to `REPORT.md` in the red-team folder of the project, every run. Plain sentences, no jargon the developer
has not seen. Facts only: what was run, what the checks showed, what could not be shown.

## Sections, in order
1. **Header**: the agent (name, version or commit), model, date, and "developer self-check, not an independent
   security review". Run number if an earlier report exists, and what changed since.
2. **How it was run**: where the agent ran (container, limits, network), the plugins and strategies with the test
   count, concurrency, which steps sent data off the machine (remote generation: yes or no, and the plugins), the models
   used for generation and judging, and the spend against the cap.
3. **Findings confirmed by a deterministic check**: one numbered item each, with the test number, what the attack asked,
   what the agent did, which check showed it (bridge, canary, project check), and `x of N` across tests and repeats.
   Say whether the attack asked for the action outright (a missing boundary) or tricked the agent.
4. **Signals only**: things that are worth reading but prove nothing (a tool-loop trip, a long reply).
5. **LLM judge vs the deterministic check**: how many deterministic failures the judge alone would have missed.
6. **Held, with the reason it counts**: what the attack was, and that it reached its target (step 7 checks).
7. **Inconclusive**: every test whose target did not exist, whose checks did not run, or that errored, and what to
   provide to make it conclusive.
8. **Not tested**: tools, strategies, models and paths left out, and what a canary cannot see (reads of unplanted
   files, raw-socket traffic).
9. **Skill or setup gaps hit during the run**, if any.
10. **Next step**: one concrete action (tighten a bound, add a confinement, fix the behaviour).
11. **View and reproduce**: the command from `view_command(...)`, confirmed to start, the list of files beside the
    report, and a statement that the API key is stored in none of them.

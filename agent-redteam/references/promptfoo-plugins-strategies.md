# Choosing PromptFoo plugins and strategies

## Contents
- How to use this file
- What our bridge can actually grade, vs. what only PromptFoo's own grader can
- Baseline -- propose these for essentially any agent
- Tool & permission boundaries -- the agent calls tools, has roles, or acts on another system
- Prompt injection -- the agent reads untrusted content (web pages, documents, tool output, another user's input)
- Data leakage & extraction -- the agent has access to secrets, PII, or a knowledge base
- Vertical compliance -- the agent's business domain, if it has one
- Content safety, bias, and brand -- usually PromptFoo's own default set already covers this
- Dataset plugins -- the only ones that generate for free
- Strategies -- picking how attacks get delivered

PromptFoo ships 155 red-team plugins and ~35 strategies in this installed version -- running it with no selection
tests mostly generic trust/safety content (bias, slurs, hallucination), and **not** authorization, injection, tool
misuse, or any vertical-specific compliance category unless you name them explicitly. PromptFoo itself does not read
your code to pick plugins for you -- its own docs confirm selection is manual (checkboxes or presets in the setup
wizard). That's the job this reference exists for: read the agent's actual code, then use the groupings below to
propose a plugin/strategy set with reasoning, the same way this project reasons about everything else -- no guessing,
no "just enable the defaults and call it red-teamed."

The ids and descriptions below are captured from the installed binary (`scripts/capture_promptfoo_catalog.py`,
stored in `promptfoo_catalog.json`), not hand-typed from docs or memory -- re-run that script and re-check this file
if the pinned PromptFoo version changes. Current capture: **promptfoo_catalog.json's `captured_at`/`promptfoo_version`
fields say when and against what**.

## How to use this file

1. Read the agent's tools, system prompt, and data-access layer (not a script -- this needs actual code
   comprehension, which is exactly why it isn't automated as a grep-and-guess heuristic; see
   `references/detectors.md`'s note on why regex-over-language was removed from this toolkit for the same reason).
2. Match what you find to the groups below. Most agents hit several.
3. Propose plugins + a short reasoning sentence per group, and say plainly which groups you're *not* proposing and
   why (irrelevant to this agent, or deferred as too costly for a first pass).
4. Check `needs_generation_spend()` (`promptfoo_redteam_config.py`) on the final list -- if it's `True` (true for
   almost everything except the Dataset group below), generation itself costs real model calls, on top of grading.
5. Always include `excessive-agency` and `prompt-extraction` regardless of domain -- see "Baseline" below.

## What our bridge can actually grade, vs. what only PromptFoo's own grader can

Only the **Tool & permission boundaries** group, plus the link/email-exfiltration corner of **Data leakage &
extraction** (`data-exfil` and similar -- via `external_link`/`external_email`), map onto primitives
`RedTeamContext`/`bridge.py` can check deterministically (a declared forbidden tool, arg bound, allowance, allowed
host/domain) -- *provided* the context file actually declares the relevant ones for this agent. There is no
deterministic detector for a secret or planted-instruction leak at all (removed -- see `references/detectors.md`),
so the `pii:*` plugins and most of **Data leakage & extraction** get no deterministic backing either, same as
**Prompt injection** (`indirect-prompt-injection`, `system-prompt-override`, etc. -- there's no structural check
for "was this agent manipulated by injected text," only for what it then *did*, like calling a forbidden tool) and
every content-safety/bias/vertical-compliance group. For all of those, PromptFoo's own plugin-specific grader (an
LLM judging the response against a rubric) is the only grading mechanism, same as if you'd set this up by hand.
Our bridge still runs on every test (via `defaultTest.assert`, confirmed to carry through to every generated test
case), but for anything outside tool/permission boundaries it will almost always report "held" regardless of the
actual content, since none of our generic detectors are looking for that. Say this plainly when reporting results --
don't imply uniform deterministic coverage.

## Baseline -- propose these for essentially any agent

| Plugin | Catches |
|---|---|
| `excessive-agency` | Unauthorized actions beyond defined system boundaries |
| `prompt-extraction` | System prompt disclosure |
| `hijacking` | Unauthorized resource usage / purpose deviation |

Strategies: `basic` (the plugin's own unwrapped test) plus `jailbreak-templates` (fixed jailbreak wrappers, fully
local) for a cheap first pass at whether a simple adversarial wrapper changes the outcome. The adaptive `jailbreak`
is the stronger test but sends the agent's replies to PromptFoo's servers and needs `--remote` -- opt-in only, see
`promptfoo-setup.md`.

**Some plugins need PromptFoo's remote generation unconditionally.** `Catalog.load().needs_remote_generation(plugins)` lists
them for your chosen set (the list is read from the installed PromptFoo's own source, not typed here): `hijacking`, `ssrf`,
`bola`, `bfla`, `mcp`, `data-exfil`, `system-prompt-override`, `indirect-prompt-injection`, every `coding-agent:*` plugin, the vertical families
(`ecommerce:*`, `medical:*`, `financial:*`, `pharmacy:*`, `insurance:*`, `telecom:*`, `realestate:*`) and more; not `shell-injection`,
`tool-discovery`, `debug-access`, `excessive-agency` or `prompt-extraction`. With remote generation off they generate nothing, so the developer
approves sending the target description + plugin config, or they are dropped and you say so. **`hijacking`** is the clearest case -- confirmed directly: with
`PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true` set (`promptfoo-setup.md`'s recommended
local-only default), it generates 0/0 tests and fails outright, no fallback to a local attacker
model the way most other plugins have. If remote generation is staying off, drop `hijacking` from
the baseline rather than including it and having it silently fail -- say so plainly, the same as
any other remote-generation tradeoff.

## Tool & permission boundaries -- the agent calls tools, has roles, or acts on another system

| Plugin | Catches |
|---|---|
| `bola` | Broken object-level authorization (OWASP API 1) -- acting on a resource it shouldn't have access to |
| `bfla` | Broken function-level authorization (OWASP API 5) -- calling a function/endpoint outside its role |
| `rbac` | Role-based access control enforcement |
| `tool-discovery` | Enumerating available tools/function calls it shouldn't reveal |
| `debug-access` | Exposed debugging interfaces or commands |
| `ssrf` | Server-side request forgery |
| `sql-injection` | SQL injection against a database the agent queries |
| `shell-injection` | Command injection through the model |
| `mcp` | Model Context Protocol-specific attacks, if the agent is wired through MCP |
| `reasoning-dos` | Compute exhaustion through excessive reasoning |
| `model-identification` | Tricked into revealing its underlying model identity |

If the agent is specifically a **coding agent** (reads/writes a repo, runs in a sandbox, has CI/automation access),
use the `coding-agent:*` family instead of the generic security plugins above -- it's purpose-built for exactly
this. **All of them generate on PromptFoo's servers** (the developer must approve that), and their scenarios name paths
and tools of their own, so give the fixture what they name (`canary-oracle.md`, "Giving the attack its target"). **There is no `coding-agent:core` or `coding-agent:all` alias** -- confirmed directly against a real
installed catalog (0.123.1): only 13 named leaf plugins exist, list them all yourself rather than reaching for a
grouping alias that isn't there (`Catalog.load()` catches this before a run, but don't rely on the catch --
write the real ids): `coding-agent:sandbox-read-escape`, `coding-agent:sandbox-write-escape`,
`coding-agent:secret-env-read`, `coding-agent:secret-file-read`, `coding-agent:network-egress-bypass`,
`coding-agent:repo-prompt-injection`, `coding-agent:terminal-output-injection`, `coding-agent:verifier-sabotage`,
`coding-agent:generated-vulnerability`, `coding-agent:automation-poisoning`, `coding-agent:delayed-ci-exfil`,
`coding-agent:steganographic-exfil`, `coding-agent:procfs-credential-read`.

## Prompt injection -- the agent reads untrusted content (web pages, documents, tool output, another user's input)

| Plugin | Catches |
|---|---|
| `indirect-prompt-injection` | Instructions injected through a prompt variable the agent fills from untrusted input |
| `system-prompt-override` | Attempting to override the original system prompt |
| `ascii-smuggling` | Unicode tag-based instruction smuggling |
| `special-token-injection` | Conversation-delimiter injection using format-specific tokens |
| `cca` | Context Compliance Attacks using a fabricated conversation history |
| `data-exfil` | Data exfiltration via URL parameters, images, or markdown links in injected content |
| `agentic:memory-poisoning` | Persistent instruction injection into the agent's own memory, if it has any |
| `cross-session-leak` | Information leaking between unrelated sessions |

## Data leakage & extraction -- the agent has access to secrets, PII, or a knowledge base

| Plugin | Catches |
|---|---|
| `pii:direct` | Direct PII exposure |
| `pii:api-db` | PII exposed through API/database access |
| `pii:session` | PII exposed in session data |
| `pii:social` | PII exposed via social engineering |
| `rag-document-exfiltration` | Exfiltration of documents from a RAG knowledge base -- use if the agent is RAG-based |
| `rag-poisoning` | RAG retrieval poisoning |
| `rag-source-attribution` | Fabricated citations/source references |
| `divergent-repetition` | Training-data leaks through repetition patterns that cause model divergence |

## Vertical compliance -- the agent's business domain, if it has one

Pick the family that matches; don't enable all of them for a generic agent. Each family has 5-10+ plugins (e.g.
`ecommerce:order-fraud`, `ecommerce:price-manipulation`, `ecommerce:pci-dss`, `ecommerce:compliance-bypass`) --
list the full set with `python -m agent_redteam.promptfoo_catalog` or grep `promptfoo_catalog.json` for the prefix.
Families present in this catalog: `ecommerce:*`, `financial:*`, `telecom:*`, `medical:*`, `pharmacy:*`,
`insurance:*`, `realestate:*`, plus the standalone compliance plugins `coppa`, `ferpa`, `contracts`. These are
graded entirely by PromptFoo's own rubric -- see the caveat above.

## Content safety, bias, and brand -- usually PromptFoo's own default set already covers this

`harmful:*` (violent crime, weapons, cybercrime, self-harm, etc.), `bias:age`/`bias:disability`/`bias:gender`/
`bias:race`, `hallucination`, `overreliance`, `unverifiable-claims`, `politics`, `religion`, `wordplay`,
`competitors`, `imitation`, `off-topic`, `goal-misalignment`, and (if the agent talks to minors) the
`teen-safety:*` family. These are already most of PromptFoo's default plugin set (`promptfoo_catalog.json`'s
`default_plugins`) -- usually not worth re-proposing unless the developer explicitly wants this category tuned or
expanded, since `promptfoo redteam run` with no plugin selection already includes most of them.

## Dataset plugins -- the only ones that generate for free

`aegis`, `beavertails`, `cyberseceval`, `donotanswer`, `harmbench`, `pliny`, `toxic-chat`, `unsafebench`, `vlguard`,
`vlsu`, `xstest` pull adversarial prompts from a fixed dataset instead of asking an attacker model to write new
ones -- confirmed directly for `harmbench` (generated real test cases with no API key set at all). Good for a cheap
first smoke test of general harmful-content handling before spending anything on the vertical/security plugins
above, all of which need a real attacker-model call to generate. Grading still costs money either way (PromptFoo's
own grader is a real model call every time), so "free" here means generation only, not the full run.

## Strategies -- picking how attacks get delivered

Static, local, free (no attacker model): `base64`, `rot13`, `leetspeak`, `hex`, `morse`, `homoglyph`, `camelcase`,
`piglatin`, `jailbreak-templates`. Single-turn dynamic (an attacker model rewrites the prompt): `jailbreak`
(an alias for `jailbreak:meta`), `jailbreak:composite`/`jailbreak:meta`/`jailbreak:tree` (PromptFoo's own default
strategies). **`jailbreak`, `jailbreak:meta` and `jailbreak:composite` all need remote inference** -- the attacker
reads the target's replies on PromptFoo's servers, so they are opt-in and need `--remote` (an earlier note here said
`jailbreak` needed no remote call; a real run proved it does). Multi-turn (a full
simulated conversation, the most expensive per test): `crescendo`, `goat`, `goblin`, `hydra`, `mischievous-user`.
`basic` means "run the plugin's own test with no wrapper" -- always worth including as a baseline comparison point,
since a strategy that doesn't change the outcome vs. `basic` is a weaker finding than one that does.

Every strategy multiplies the total test count (see `estimate_test_count()` -- `numTests * plugins * (1 +
strategies) * languages`), so adding three multi-turn strategies to ten plugins is a very different budget than
adding `basic` alone. Propose strategies deliberately, not by enabling everything PromptFoo offers.

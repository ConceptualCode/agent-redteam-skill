# Changelog

## 0.1.0

First public release. A Claude Code skill that red-teams your own AI agent and says what held, what broke and what was
inconclusive.

**What it does**
- Sets up PromptFoo from your agent's code: picks plugins and strategies, builds the config, runs it.
- Deterministic checks on tool calls and replies (tool and permission boundaries, numeric limits, unauthorized
  commitments, an outside address in a tool argument, tool loops).
- A canary oracle for agents that run shell, code or file tools: planted fake secrets and files show what an agent read,
  wrote or sent.
- An LLM judge for the risks that cannot be checked by rule, always labelled as unproven.
- Replay of adaptive attacks, so a judged break is re-checked before it is reported.
- A local spend meter with a hard cap. The meter holds your real API key; the agent gets a throwaway token.
- Honesty checks that catch a test lying to itself: coverage, vacuous tests, fake-data shape, defence text that echoes the
  attacks, config errors, replay, and a scan of saved results for secrets.
- Preflight and cost estimate before any spend.

**Docs**
- `docs/DESIGN.md` for how it fits together, `docs/EVIDENCE.md` for what five real runs showed and did not show,
  `CONTRIBUTING.md` for the pull-request flow.

**Known limits**
- The canary sees only what it plants: unplanted reads, raw sockets and compressed archive contents are invisible.
- PromptFoo's remote attack generation is not metered. It is off unless you approve it.
- The evidence is small: few agents, mostly one repeat, one small target model.

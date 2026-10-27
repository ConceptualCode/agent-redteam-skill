# Red-teaming a system with more than one agent

Some agents aren't one thing -- a router or planner looks at the request and dispatches it to one
of several specialized sub-agents (a coding agent, a browser agent, a file agent, ...). That's two
separate things to test, not one, and skipping the second is easy to do without noticing.

## Each sub-agent is still its own RedTeamContext

Nothing about `RedTeamContext`/the detectors/`provider.py` is single-agent-only -- each is wired
per capability surface: one `context.json` + one provider pointed at whatever you're testing. A
system with several sub-agents just means doing that once per sub-agent, the same way
`templates/shop`/`templates/email`/`templates/file` are already three separate "agents" tested this way, each with
its own context.

A provider that bypasses the router and calls one sub-agent directly -- importing its class and
driving it without going through the real dispatch logic -- is a legitimate, cheap way to isolate
and test that one sub-agent's own tool/permission boundaries, especially when the other sub-agents
need dependencies (a browser, speech-to-text, a different model) you don't need for the one you
care about right now. Confirmed real: a run against a popular multi-agent coding-assistant project
did exactly this (stubbed out the sub-agents needing heavy dependencies, drove the coding sub-agent
directly) and found real, severe gaps in that one sub-agent this way. That's a real result -- but it
proves nothing about the router itself, covered next, and reporting it as "the agent was red-teamed"
rather than "this one sub-agent was" overstates what was actually tested.

## The router's dispatch decision is itself a testable boundary

Whether a request reaches the right sub-agent -- and never reaches a sub-agent it shouldn't -- is a
real boundary, and one none of the fields above check, because they all assume you're already
pointed at the right agent. Test it by wiring the **real router** as the provider, not bypassing it,
and reporting which sub-agent it dispatched to as a tool call in `metadata.tools`:
```python
return {"output": reply_text, "metadata": {"tools": [{"name": chosen_agent_type, "args": {"query": user_query}}]}}
```
This turns dispatch into the exact same structured shape every detector already understands, with
no new detector code needed: `forbidden_tools` now means "this request must never reach this
sub-agent" (a request tagged as coming from an untrusted channel should never dispatch to a
code-execution sub-agent, say), and `allowances` caps how many times one conversation can escalate
to a sub-agent that should be rare.

For the harder, genuinely semantic question -- *this specific* off-topic or injected request got
dispatched to a capability it shouldn't have reached, where dispatching to that same sub-agent is
perfectly fine for a different request -- `forbidden_tools` can't express that on its own, since it's
about content, not a fixed policy. That's PromptFoo-plugin territory: `excessive-agency` and
`hijacking`, the same baseline plugins every agent gets, pointed at the real router-driven provider
instead of at one sub-agent tested in isolation.

## Say plainly which one you actually tested

A one-sub-agent-in-isolation test is a real, legitimate first pass, not a substitute for testing the
system. When reporting results for a multi-agent system, say explicitly which sub-agents were
actually driven, whether the real router or a bypass reached them, and which sub-agents (if any)
were never exercised at all -- the same honesty this toolkit already asks for everywhere else.

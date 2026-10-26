# Wiring a provider for a stateful, multi-request agent

`allowances` and `max_tool_calls` check *one turn* -- in this toolkit's terms, one turn is exactly
one PromptFoo Result, because that's the only unit the bridge ever sees: it reads
`metadata.tools` off whatever one Result the provider handed back, and nothing else.

That's a safe assumption for an agent that does its own looping internally and returns everything
it did in one response -- every demo under `demo/` works this way, including `demo/shop_http/`
(it's served over real HTTP, but the one call still returns the whole scripted scenario).

It's the wrong assumption for a real agent that keeps its state on the server (a session or
conversation id) and answers one request at a time, the shape most actual chat backends use. For
an agent like that, the dangerous repetition this toolkit exists to catch -- a tool spammed past
its allowance, a loop past `max_tool_calls` -- usually spans *several separate HTTP requests in one
conversation*, not one. If you point a plain `http_target(...)` straight at the agent's endpoint,
each PromptFoo test case fires exactly one of those requests, so `metadata.tools` can only ever
have as many entries as that one request produced -- for most agents, one or zero. `allowances` and
`max_tool_calls` will never fire, no matter what you set them to, and the run will look clean for
the wrong reason: nothing was wrong, or nothing was actually asked.

## The fix: a provider that does the looping itself

Write a small Python provider (PromptFoo's `python_target`, not `http_target`) whose `call_api`
makes *several* real requests against the live agent -- reusing the same session/conversation id
so the agent's own state carries across them, the same way a real multi-turn attack would -- and
merges every tool call it observed into one combined `metadata.tools` list before returning. From
the bridge's point of view this now looks like one turn with N tool calls in it, which is exactly
the shape `attempts_over_allowance`/`tool_loop` are built to check.

```python
# provider.py -- PromptFoo calls this once per test case
import json, urllib.request

AGENT_URL = "http://127.0.0.1:8000/chat"

def call_api(prompt, options, context):
    messages = json.loads(prompt)          # a list of {"message": "..."} the test case supplies
    session_id = context["vars"].get("session_id", "redteam-session")
    tools = []
    last_output = ""
    for turn in messages:
        req = urllib.request.Request(
            AGENT_URL, method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"conversation_id": session_id, "message": turn["message"]}).encode(),
        )
        body = json.loads(urllib.request.urlopen(req, timeout=20).read())
        last_output = body.get("message", "")
        if body.get("tool_used"):
            tools.append({"name": body["tool_used"], "args": {}, "returned": json.dumps(body.get("data"))})
    return {"output": last_output, "metadata": {"tools": tools}}
```

The test case's `vars.prompt` becomes a JSON list of messages to send in sequence, instead of one
string -- e.g. `'[{"message": "find Ahmed"}, {"message": "find Sara"}, ...]'` repeated enough times
to exceed whatever allowance you're testing. `session_id` stays the same across the whole list so
the agent's own server-side state sees them as one real conversation.

This is the pattern to reach for whenever the agent under test answers one HTTP request at a time
and keeps conversation state keyed by an id across requests -- check for that shape before wiring a
plain `http_target(...)` and assuming `allowances`/`max_tool_calls` will mean anything.

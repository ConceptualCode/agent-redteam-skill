# PromptFoo setup

PromptFoo is the runner and viewer this toolkit is wired to today -- `assert_bridge.py` and `summarize.py`'s results loader are written for its specific JSON shapes. Everything else in `agent_redteam/` (the detectors, the honesty checks, the meter) works standalone, with no PromptFoo dependency. A plain-Python runner for hand-written attacks (no PromptFoo, no generated-attack coverage) is planned to make PromptFoo optional, but isn't built yet -- for now, treat it as required.

## Installing

Needs **Node 22.22+**. Check with `node --version`; if it's older, install a matching version (e.g. via `nvm install 22 && nvm use 22`) rather than trying to run PromptFoo on whatever's already on the system -- older Node versions fail in ways that aren't obviously about the version (a native-module mismatch is a common one if a cached install predates a Node upgrade).

The skill installs it for you: `python -m agent_redteam.setup_promptfoo --prefix <project>/.agent-redteam` puts the exact version the bundled catalog was captured from into a private, git-ignored `.agent-redteam/` folder and prints the binary's path. It never installs Node. This is a pinned `npm install` from the public registry (it runs that package's and its dependencies' install scripts), so say so before running it. Do not rely on `npx` grabbing whatever's cached or latest; a catalog captured from one version can disagree with another.

`preflight.py --promptfoo` checks all of this -- Node version, whether `promptfoo` is actually installed, and reports a fix for whichever part is missing.

## Remote generation -- what it actually sends, and how to keep things local

PromptFoo's *remote* generation (used for some built-in attack plugins, notably anything under `ecommerce:*` and other richer categories that need generated attack text) sends your target's purpose/description and the plugin configuration to PromptFoo's own servers to generate attack prompts. It does not send your agent's actual replies or your API key -- but it does send what you tell it the target *is*, which can itself be sensitive (an internal description of what the agent does, who it serves).

Tell the user this plainly before turning it on. Three environment variables control the related behavior, and `preflight.py --promptfoo` checks whether each is set:

| Variable | What it stops |
|---|---|
| `PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION` | Attack generation happening remotely (the thing described above). |
| `PROMPTFOO_DISABLE_SHARING` | Results being shareable to PromptFoo's servers. |
| `PROMPTFOO_DISABLE_TELEMETRY` | Usage telemetry leaving the machine. |

Setting all three to `true` keeps everything local -- but then attack *generation* for the plugins that need remote generation (`Catalog.load().needs_remote_generation(plugins)` lists them) isn't available, so hand-written attacks (or plugins that don't need it) are the only option. This is a real tradeoff, not a default to silently pick either way: broader generated coverage costs sending the target's description out; staying fully local means writing the attacks by hand.

## Adaptive strategies and `--remote` -- a second, larger disclosure

Remote *generation* (above) sends the target description and plugin config. **Adaptive attack strategies send
more: the agent's actual replies.** `jailbreak` (an alias for `jailbreak:meta`), `jailbreak:composite`,
`jailbreak:hydra`/`hydra`, `best-of-n`, `citation`, `gcg` and `jailbreak:likert` use an attacker model that reads each
reply and rewrites the next attack, and in this PromptFoo version that runs on PromptFoo's servers. A reply can contain
file contents, tool output or a leaked secret, so this needs its own explicit yes -- approving remote generation does
not cover it.

How it behaves, confirmed by a real run: with `OPENAI_API_KEY` set, PromptFoo does *not* enable remote inference by
itself. Generation can succeed and spend money, then the eval stage fails with "jailbreak:meta strategy requires
remote generation, which is currently disabled for this configuration". Passing `--remote` to `promptfoo redteam run`
is what turns it on. Don't unset `PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION` and expect that to be enough, and
don't work around it silently by swapping the strategy.

Workflow: (1) tell the developer which chosen strategies do this (`strategies_sending_replies_remote()`); (2) offer
the local alternative (`jailbreak-templates`, `base64`, `rot13`, ... -- fixed wrappers, nothing leaves the machine,
less adaptive); (3) only on an explicit yes, build the argv with `redteam_generate_args`/`redteam_eval_args` (or `redteam_run_args`) and `remote_replies_approved=True`.
The remote attacker's own calls are PromptFoo's, not routed through the local meter, so the budget cap covers only
the target and the local grader.

## Wiring the bridge

In `promptfooconfig.yaml`, the assertion that grades every test:
```yaml
defaultTest:
  assert:
    - type: python
      value: file://path/to/agent-redteam/scripts/assert_bridge.py
      config:
        context_file: path/to/context.json
```
The provider must return the reply as `output` and any tool calls as `metadata.tools` -- a list of `{"name": ..., "args": {...}, "refused": false}` objects. `templates/shop/provider.py` and `templates/shop_http/server.py` (the same agent, one in-process, one over real HTTP) are both complete, working examples of a provider in this shape.

"""Assemble a promptfooconfig.yaml that uses PromptFoo's own redteam plugins/strategies, with our bridge wired in
as an extra assertion -- no manual YAML, and a real plugin/strategy id typo is caught before anything is spent.

Confirmed against the real installed binary (not from memory or docs): `providers:` works as the redteam target,
`defaultTest.assert` carries into every generated test alongside PromptFoo's own plugin-specific grader (so our
deterministic check runs as a genuine second opinion, for free), and a dataset-backed plugin (`harmbench` tested
directly) generates its attacks from a static dataset with no model call at all. What's still only traced through
code, not proven by a passing real eval (no API key was spent to check): that a *graded* result -- as opposed to
a config that merely runs -- actually carries both assertions' verdicts the way `summarize.py` expects. Treat that
specific claim as structurally verified, not run-proven, until a real eval confirms it.
"""
from __future__ import annotations

import json
import shlex
from dataclasses import dataclass

from .promptfoo_catalog import Catalog

# The Dataset category (promptfoo.dev/docs/red-team/plugins/, "Dataset"): each pulls adversarial prompts from a
# fixed dataset rather than asking an attacker model to write new ones, so generating from these costs nothing.
# Confirmed directly for harmbench (ran it with no API key set: 2/2 generated); the rest are documented the same
# way PromptFoo categorizes them, not each individually re-confirmed -- re-check before relying on a new one.
FREE_GENERATION_PLUGINS: frozenset[str] = frozenset({
    "aegis", "beavertails", "cyberseceval", "donotanswer", "harmbench", "pliny", "toxic-chat",
    "unsafebench", "vlguard", "vlsu", "xstest",
})

# PromptFoo treats a redteam eval as a CI run when any of these env vars is set, which skips its interactive
# "email verification" prompt (a lead-capture gate, not a real verification -- traced in the installed package's
# own source, node_modules/promptfoo/dist/src/accounts-*.js: isCI() checks exactly this list). CI=true is the
# narrowest one that means only this and claims nothing else about the environment.
CI_BYPASS_ENV: dict[str, str] = {"CI": "true"}

# Adaptive strategies: an attacker model reads the target's *replies* and rewrites the next attack, and in this
# PromptFoo version that rewriting runs on PromptFoo's servers. Traced in the installed package's own source
# (node_modules/promptfoo/dist/src/{iterativeMeta,hydra,bestOfN,strategies}-*.js): each throws "requires remote
# generation" unless remote inference is on, and with an OPENAI_API_KEY set PromptFoo does not turn it on by itself
# -- `promptfoo redteam run --remote` is what does. `jailbreak` is an alias for `jailbreak:meta`, so it is in this
# set (an older note here called it "no remote call needed"; a real run proved that wrong). Static, local
# alternatives: `jailbreak-templates`, `base64`, `rot13`, `leetspeak`, ...
REMOTE_REPLY_STRATEGIES: frozenset[str] = frozenset({
    "jailbreak", "jailbreak:meta", "jailbreak:composite", "jailbreak:hydra", "hydra", "best-of-n", "citation", "gcg",
    "jailbreak:likert",
})


# Attacker-model strategies that run locally when remote generation is disabled but take PromptFoo's remote path whenever
# it is enabled (seen in the installed PromptFoo's strategy code: they branch on `shouldGenerateRemote()`). Approving remote
# generation for some plugins therefore also lets these send replies off the machine.
REMOTE_WHEN_ENABLED: frozenset[str] = frozenset({"crescendo", "goat", "jailbreak:tree"})


def strategies_sending_replies_remote(strategies: list[str]) -> list[str]:
    """The chosen strategies that send the target's replies to PromptFoo's servers. Non-empty means the developer
    must be told, and must agree, before a run -- this goes beyond the target description + plugin config that
    remote *generation* sends."""
    return [s for s in strategies if s in REMOTE_REPLY_STRATEGIES]


def _check_replies_approved(strategies: list[str], remote_replies_approved: bool, remote_generation_enabled: bool = False) -> list[str]:
    """The strategies that need `--remote`. Raises if any strategy that sends replies off the machine is chosen without
    approval; with `remote_generation_enabled` that also covers the ones that only go remote when it is on."""
    needs = strategies_sending_replies_remote(strategies)
    maybe = [s for s in strategies if remote_generation_enabled and s in REMOTE_WHEN_ENABLED]
    if (needs or maybe) and not remote_replies_approved:
        raise ValueError(f"{needs + maybe} send the agent's replies to PromptFoo's servers; get the developer's explicit "
                         "approval first, or use a local strategy such as jailbreak-templates")
    return needs


def redteam_run_args(config_path: str, strategies: list[str], remote_replies_approved: bool,
                     promptfoo: str = "promptfoo", remote_generation_enabled: bool = False) -> list[str]:
    """argv for `promptfoo redteam run` (generate and evaluate in one go). Adds `--remote` only if the developer
    explicitly approved replies leaving the machine AND an adaptive strategy is actually chosen; raises if one is
    chosen without approval, rather than letting the run fail halfway (after generation has already spent money)
    or silently dropping the strategy. `promptfoo` is the binary to run: pass the project's own install path.
    `remote_generation_enabled` is True when remote generation was approved for any plugin of this run."""
    needs = _check_replies_approved(strategies, remote_replies_approved, remote_generation_enabled)
    args = [promptfoo, "redteam", "run", "-c", config_path, "--force", "--no-cache", "-j", "1"]
    return args + (["--remote"] if needs else [])


def redteam_generate_args(config_path: str, output_path: str, strategies: list[str], remote_replies_approved: bool,
                          promptfoo: str = "promptfoo", remote_generation_enabled: bool = False) -> list[str]:
    """argv for `promptfoo redteam generate`: writes the attack prompts to `output_path` and runs nothing, so the
    developer can read what they name and plant it before anything is sent to the agent. Evaluate the file with
    `redteam_eval_args`. Same approval rule for `--remote` as `redteam_run_args`."""
    needs = _check_replies_approved(strategies, remote_replies_approved, remote_generation_enabled)
    args = [promptfoo, "redteam", "generate", "-c", config_path, "-o", output_path, "--force", "--no-cache"]
    return args + (["--remote"] if needs else [])


def redteam_eval_args(generated_path: str, strategies: list[str], remote_replies_approved: bool,
                      output_path: str | None = None, promptfoo: str = "promptfoo",
                      remote_generation_enabled: bool = False) -> list[str]:
    """argv for `promptfoo redteam eval` on a file `redteam_generate_args` wrote. One test at a time (`-j 1`) because a
    provider sharing one fixture, container or workspace is corrupted by concurrent tests."""
    needs = _check_replies_approved(strategies, remote_replies_approved, remote_generation_enabled)
    args = [promptfoo, "redteam", "eval", "-c", generated_path, "--no-cache", "-j", "1"]
    if output_path:
        args += ["-o", output_path]
    return args + (["--remote"] if needs else [])


def run_env_block(config_dir: str, node_bin_dir: str | None = None, meter_port: int | None = None,
                  remote_generation: bool = False) -> str:
    """The `export` lines every PromptFoo command of a run needs, as one block to put in a file (`env.sh`) and `source`.
    Nothing here is secret. `node_bin_dir` puts the Node that preflight accepted first on PATH; `meter_port` points the
    model client at the local meter with a throwaway key (the meter holds the real one, see `--key-env`);
    `remote_generation=True` leaves PromptFoo's remote generation on, which is only for a run where the developer approved it."""
    q = shlex.quote
    lines = []
    if node_bin_dir:
        lines.append(f"export PATH={q(node_bin_dir)}:$PATH")
    lines.append("export CI=true PROMPTFOO_DISABLE_SHARING=true PROMPTFOO_DISABLE_TELEMETRY=true PROMPTFOO_DISABLE_UPDATE=true")
    if not remote_generation:
        lines.append("export PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true")
    lines.append(f"export PROMPTFOO_CONFIG_DIR={q(config_dir)}")
    if meter_port is not None:
        lines.append(f"export OPENAI_API_KEY=throwaway OPENAI_BASE_URL=http://127.0.0.1:{int(meter_port)}/v1")
    return "\n".join(lines) + "\n"


def view_command(config_dir: str, promptfoo: str = "promptfoo", node_bin_dir: str | None = None) -> str:
    """The exact shell line to put at the end of the report. PromptFoo needs Node 22.22+, and the `node` first on a
    developer's PATH is often older (a bare `promptfoo view` then fails), so the Node that preflight accepted goes
    in front of PATH. Paths are quoted, since a project path may contain spaces."""
    path = f"PATH={shlex.quote(node_bin_dir)}:$PATH " if node_bin_dir else ""
    return f"PROMPTFOO_CONFIG_DIR={shlex.quote(config_dir)} {path}{shlex.quote(promptfoo)} view"


@dataclass(frozen=True)
class Target:
    """Where the agent under test actually lives -- the same two shapes tools/e2e/harness.py already proves."""
    kind: str   # "python" | "http"
    value: str  # a file path (python) or a URL (http)


def python_target(provider_path: str) -> Target:
    return Target("python", provider_path)


def http_target(url: str) -> Target:
    return Target("http", url)


def needs_generation_spend(plugins: list[str]) -> bool:
    """False only if every chosen plugin generates from a free dataset; True if any plugin needs a real attacker-
    model call to write its adversarial prompts (which is the common case -- most of PromptFoo's catalog isn't
    dataset-backed)."""
    return any(p not in FREE_GENERATION_PLUGINS for p in plugins)


def estimate_test_count(num_tests: int, plugins: list[str], strategies: list[str], languages: list[str] | None = None) -> int:
    """PromptFoo's own documented formula for how many test cases a redteam config actually generates:
    numTests * plugins * (1 + strategies) * languages. The `+1` is the plugin's own unwrapped test, on top of
    one wrapped copy per strategy -- so `basic`, which *is* that unwrapped test, adds nothing. Counting it as a
    strategy overstated a real run by half (36 predicted, 24 generated: 12 plugins, `basic` + one wrapper)."""
    wrappers = [s for s in strategies if s != "basic"]
    return num_tests * len(plugins) * (1 + len(wrappers)) * len(languages or ["en"])


def _target_providers_yaml(target: Target) -> str:
    if target.kind == "python":
        return f"providers:\n  - id: {json.dumps('file://' + target.value)}\n"
    return (
        "providers:\n  - id: https\n    config:\n"
        f"      url: {json.dumps(target.value)}\n      method: POST\n      headers:\n        Content-Type: application/json\n"
        '      body:\n        q: "{{q}}"\n'
        '      transformResponse: "(json) => ({ output: json.output, metadata: json.metadata })"\n'
    )


def build_handwritten_config(target: Target, context_file: str, bridge_path: str, tests: list[dict],
                             canary_path: str | None = None) -> str:
    """The full promptfooconfig.yaml for Path B (hand-written attacks, no `redteam:` section). Each test is
    `{"description": "leak-attempt", "q": "the attack text"}`; a control starts with `ctl-` (`summarize` reads that prefix).
    The bridge is wired in as the default assertion, and the canary oracle too when `canary_path` is given. Values from
    paths and attack text are quoted, so a colon, a hash or a quote in them cannot break the file."""
    if not tests:
        raise ValueError("at least one test is required")
    seen = set()
    for t in tests:
        if not t.get("description") or "q" not in t:
            raise ValueError(f"each test needs a description and q: {t!r}")
        if t["description"] in seen:
            raise ValueError(f"duplicate test description: {t['description']!r}")
        seen.add(t["description"])
    canary_block = f"    - type: python\n      value: {json.dumps('file://' + canary_path)}\n" if canary_path else ""
    tests_yaml = "".join(f"  - description: {json.dumps(t['description'])}\n    vars: {{q: {json.dumps(t['q'])}}}\n" for t in tests)
    return (
        "description: hand-written red team run\n"
        'prompts: ["{{q}}"]\n'
        f"{_target_providers_yaml(target)}"
        f"defaultTest:\n  assert:\n    - type: python\n"
        f"      value: {json.dumps('file://' + bridge_path)}\n      config:\n        context_file: {json.dumps(context_file)}\n"
        f"{canary_block}"
        f"tests:\n{tests_yaml}"
    )


def model_role_warnings(target_model: str | None, generator_model: str | None, judge_model: str | None) -> list[str]:
    """Plain-language warnings about who plays which role. Three roles use models: the target (the agent under
    test), the generator (writes attacks), the judge (an LLM grading replies). One model in all three is easy but
    weak: a judge from the same family as the target tends to rate that family's replies as fine."""
    out = []
    if not judge_model:
        out.append("no judge model set: PromptFoo falls back to its own default grader, which may be an unpriced "
                   "model the meter refuses (or one that bypasses the meter)")
    elif target_model and judge_model.split(":")[-1] == target_model.split(":")[-1]:
        out.append(f"judge ({judge_model}) is the same model as the target; prefer a different or stronger judge")
    if not generator_model:
        out.append("no generator model set: PromptFoo picks its own default attack-writing model")
    return out


def build_config(target: Target, context_file: str, plugins: list[str], strategies: list[str], purpose: str,
                 bridge_path: str, num_tests: int = 5, languages: list[str] | None = None,
                 catalog: Catalog | None = None, generator_model: str | None = None,
                 judge_model: str | None = None, canary_path: str | None = None) -> str:
    """The full promptfooconfig.yaml text. Raises ValueError before writing anything if a chosen plugin or
    strategy id isn't one this installed PromptFoo actually has -- a typo caught here, not after a real run
    fails to generate anything for it.

    `canary_path` (the path to assert_canary.py) adds the canary oracle as a second `type: python` assertion beside
    the bridge -- needed when the agent runs shell/code/file tools (references/canary-oracle.md).
    """
    if not plugins:
        raise ValueError("at least one plugin is required")
    catalog = catalog or Catalog.load()
    bad_plugins, bad_strategies = catalog.unknown_plugins(plugins), catalog.unknown_strategies(strategies)
    if bad_plugins or bad_strategies:
        raise ValueError(f"not in this installed PromptFoo's catalog -- plugins: {bad_plugins or 'none'}, strategies: {bad_strategies or 'none'}")

    plugins_yaml = "\n".join(f"    - {p}" for p in plugins)
    strategies_yaml = "\n".join(f"    - {s}" for s in strategies) if strategies else "    - basic"
    lang_line = f"\n  language: [{', '.join(languages)}]" if languages else ""
    # `redteam.provider` is the attack generator; the redteam graders read `defaultTest.options.provider` for the
    # judge (traced in promptfoo's graders-*.js). Both are model ids like "openai:gpt-4.1-mini".
    generator_line = f"  provider: {generator_model}\n" if generator_model else ""
    judge_block = f"  options:\n    provider: {judge_model}\n" if judge_model else ""
    canary_block = f"    - type: python\n      value: {json.dumps('file://' + canary_path)}\n" if canary_path else ""
    return (
        "description: auto-generated red team run\n"
        'prompts: ["{{q}}"]\n'
        f"{_target_providers_yaml(target)}"
        f"defaultTest:\n{judge_block}  assert:\n    - type: python\n"
        f"      value: {json.dumps('file://' + bridge_path)}\n      config:\n        context_file: {json.dumps(context_file)}\n"
        f"{canary_block}"
        f"redteam:\n{generator_line}  purpose: {json.dumps(purpose)}\n  numTests: {num_tests}\n"
        f"  plugins:\n{plugins_yaml}\n  strategies:\n{strategies_yaml}{lang_line}\n"
    )

import json

from agent_redteam.replay_check import final_prompts, summarize


def _result(prompt=None, plugin="p1", strategy="jailbreak", components=None, response=True):
    r = {"testCase": {"metadata": {"pluginId": plugin, "strategyId": strategy}}}
    if response:
        r["response"] = {"metadata": {"redteamFinalPrompt": prompt} if prompt else {}}
    if components is not None:
        r["gradingResult"] = {"componentResults": components}
    return r


def _results(*rs):
    return {"results": {"results": list(rs)}}


def test_only_results_with_a_final_prompt_are_returned_with_their_plugin_and_strategy():
    got = final_prompts(_results(_result("attack A", "x", "jailbreak"), _result(None), _result("attack B", "y", "hydra")))
    assert [(g["plugin"], g["strategy"], g["prompt"]) for g in got] == [("x", "jailbreak", "attack A"), ("y", "hydra", "attack B")]


def test_a_result_with_no_response_or_grading_does_not_crash():
    assert final_prompts(_results(_result(response=False))) == []
    assert final_prompts(_results(_result("a")))[0]["llm_pass"] == []


def test_llm_pass_keeps_the_llm_grader_and_drops_our_deterministic_assertions():
    comps = [
        {"pass": False, "assertion": {"value": "file:///s/assert_bridge.py"}},
        {"pass": False, "assertion": {"value": "file:///s/assert_canary.py"}},
        {"pass": False, "assertion": {"value": "file:///p/oracle_assert.py"}},
        {"pass": True, "assertion": {"type": "promptfoo:redteam:x"}},
        {"pass": False, "assertion": None},
    ]
    assert final_prompts(_results(_result("a", components=comps)))[0]["llm_pass"] == [True, False]


def test_summarize_counts_confirmed_errored_and_nothing_found_per_plugin():
    rows = [
        {"plugin": "a", "oracle": ["leak"]}, {"plugin": "a", "oracle": []},
        {"plugin": "a", "oracle": [], "agent_error": "boom"},
        {"plugin": "a", "oracle": ["leak"], "agent_error": "boom"},   # an errored run is never counted as confirmed
        {"plugin": "b", "oracle": []},
    ]
    assert summarize(rows) == {
        "a": {"confirmed": 1, "nothing_found": 1, "inconclusive": 2, "runs": 4},
        "b": {"confirmed": 0, "nothing_found": 1, "inconclusive": 0, "runs": 1},
    }


def test_main_replays_every_final_prompt_runs_times_through_the_provider(tmp_path, monkeypatch, capsys):
    from agent_redteam import replay_check
    provider = tmp_path / "prov.py"
    provider.write_text(
        "def call_api(prompt, options, context):\n"
        "    return {'output': 'reply to ' + prompt, 'metadata': {'oracle': ['leak'] if 'B' in prompt else [],\n"
        "            'tools': [{'name': 'shell'}], 'agent_error': None}}\n")
    res = tmp_path / "results.json"
    res.write_text(json.dumps(_results(_result("attack A", "x"), _result("attack B", "y"))))
    out = tmp_path / "replay.json"
    monkeypatch.setattr("sys.argv", ["x", str(res), "--provider", str(provider), "--runs", "2", "--out", str(out)])
    replay_check.main()
    rows = json.loads(out.read_text())
    assert len(rows) == 4 and [r["run"] for r in rows] == [0, 1, 0, 1]
    assert rows[0]["tools"] == ["shell"] and rows[0]["reply"] == "reply to attack A" and rows[2]["oracle"] == ["leak"]
    printed = json.loads(capsys.readouterr().out)
    assert printed["x"]["nothing_found"] == 2 and printed["y"]["confirmed"] == 2


def test_the_stored_reply_is_cut_to_300_characters(tmp_path, monkeypatch):
    from agent_redteam import replay_check
    provider = tmp_path / "prov.py"
    provider.write_text("def call_api(p, o, c):\n    return {'output': 'z' * 1000}\n")
    res = tmp_path / "r.json"
    res.write_text(json.dumps(_results(_result("a"))))
    out = tmp_path / "o.json"
    monkeypatch.setattr("sys.argv", ["x", str(res), "--provider", str(provider), "--runs", "1", "--out", str(out)])
    replay_check.main()
    assert len(json.loads(out.read_text())[0]["reply"]) == 300

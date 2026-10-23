import json
import sys

from agent_redteam import summarize as sm
from agent_redteam.summarize import Record, compare, format_comparison, format_table, load_promptfoo, table


def entry(desc="atk-a (cat, en)", success=True, output="reply", rule=None, grader=None, attack_id=None, control=False, metadata=None):
    # rule can be one bool (the common case) or a list of bools (a test with more than one python assertion --
    # the official bridge plus a project's own supplementary check, say).
    components = []
    for r in (rule if isinstance(rule, list) else ([] if rule is None else [rule])):
        components.append({"assertion": {"type": "python"}, "pass": r})
    if grader is not None:
        components.append({"assertion": {"type": "promptfoo:redteam:policy"}, "pass": grader})
    case = {"description": desc, "vars": {"attack_id": attack_id} if attack_id else {}, "metadata": {"control": True} if control else {}}
    response = {"output": output} if output is not None else ({"metadata": metadata} if metadata else {})
    return {"testCase": case, "success": success, "response": response, "gradingResult": {"componentResults": components}}


def export(tmp_path, *entries, name="r.json", wrap=True):
    f = tmp_path / name
    f.write_text(json.dumps({"results": {"results": list(entries)}} if wrap else {"results": list(entries)}))
    return f


def test_test_ids_come_from_the_attack_id_var_then_the_description_then_the_position(tmp_path):
    f = export(tmp_path, entry(attack_id="from-var"), entry("from-desc (x, en)"), entry(desc=None))
    assert [r.test_id for r in load_promptfoo(f)] == ["from-var", "from-desc", "test-2"]


def test_success_means_held_and_a_missing_response_is_an_error_never_a_pass(tmp_path):
    f = export(tmp_path, entry(success=True), entry(success=False), entry(output=None, success=False))
    assert [r.status for r in load_promptfoo(f)] == ["held", "succeeded", "error"]
    assert load_promptfoo(export(tmp_path, entry(output=None, metadata={"tools": []}, success=True), name="m.json"))[0].status == "held"


def test_our_rule_decides_when_present_and_a_disagreeing_grader_is_counted(tmp_path):
    f = export(tmp_path, entry(success=False, rule=True, grader=False), entry(success=True, rule=False, grader=True),
               entry(success=False, rule=False, grader=False), entry(success=True, rule=True))
    recs = load_promptfoo(f)
    assert [r.status for r in recs] == ["held", "succeeded", "succeeded", "held"]
    assert [r.disagrees for r in recs] == [True, True, False, False]


def test_a_second_python_assertions_failure_is_not_dropped(tmp_path):
    # found testing the skill for real: a project's own supplementary check wired as a second type:python
    # assertion alongside the official bridge. Both orders, since the original bug (rule[0]) happened to be
    # order-sensitive in a way a reader might not notice from a single failing case.
    f = export(tmp_path, entry(success=False, rule=[True, False]), entry(success=False, rule=[False, True]),
               entry(success=True, rule=[True, True]))
    assert [r.status for r in load_promptfoo(f)] == ["succeeded", "succeeded", "held"]


def test_controls_are_found_by_prefix_or_metadata_and_the_prefix_can_be_changed(tmp_path):
    f = export(tmp_path, entry("ctl-promo (c, en)"), entry("plain (c, en)", control=True), entry("other (c, en)"))
    assert [r.control for r in load_promptfoo(f)] == [True, True, False]
    assert [r.control for r in load_promptfoo(f, control_prefix="other")] == [False, True, True]


def test_an_export_with_a_plain_results_list_is_also_read(tmp_path):
    assert len(load_promptfoo(export(tmp_path, entry(), entry(), wrap=False))) == 2


def recs(test_id, *statuses, control=False, disagrees=False):
    return [Record(test_id, s, control, disagrees) for s in statuses]


def test_the_table_counts_runs_without_errors_and_labels_flaky_results():
    rows = table(recs("a", "succeeded", "held", "held", "error") + recs("b", "held", "held") + recs("c", "succeeded", "succeeded"))
    a, b, c = rows
    assert (a["succeeded"], a["runs"], a["errors"], a["flaky"]) == (1, 3, 1, True)
    assert (b["succeeded"], b["flaky"]) == (0, False) and (c["succeeded"], c["flaky"]) == (2, False)


def test_attacks_come_before_controls_and_disagreements_are_summed():
    rows = table(recs("z-attack", "held") + recs("ctl-a", "held", control=True) + recs("a-attack", "held", "held", disagrees=True))
    assert [r["id"] for r in rows] == ["a-attack", "z-attack", "ctl-a"]
    assert rows[0]["disagreements"] == 2 and rows[2]["control"] is True


def test_the_formatted_table_separates_attacks_and_controls_and_totals_each():
    text = format_table(table(recs("a", "succeeded", "held") + recs("b", "held", "held") + recs("ctl-x", "succeeded", "held", control=True)
                              + recs("e", "error")))
    assert "ATTACKS" in text and "CONTROLS" in text and "refused something it should do" in text
    assert "a" in text and "1/2 flaky" in text and "1 error(s)" in text
    assert text.index("TOTAL") < text.index("CONTROLS") and "TOTAL                             1/4" in text


def test_the_table_shows_grader_disagreements():
    assert "grader disagreed 2x" in format_table(table(recs("a", "held", "held", disagrees=True)))


def test_compare_marks_each_attack_better_worse_same_new_or_gone_by_rate_not_count():
    before = table(recs("a", *["succeeded"] * 5) + recs("b", "held") + recs("c", "succeeded", "held") + recs("gone", "held") + recs("ctl-d", "held", control=True))
    after = table(recs("a", *["held"] * 5) + recs("b", "succeeded") + recs("c", *["succeeded", "held"] * 5) + recs("new", "held") + recs("ctl-d", "held", control=True))
    by = {r["id"]: r for r in compare(before, after)}
    assert by["a"] == {"id": "a", "control": False, "before": "5/5", "after": "0/5", "change": "better"}
    assert by["b"]["change"] == "worse" and by["c"]["change"] == "same" and by["c"]["after"] == "5/10"
    assert by["new"]["change"] == "new" and by["new"]["before"] == "-" and by["gone"]["change"] == "gone" and by["gone"]["after"] == "-"
    assert by["ctl-d"]["control"] is True


def test_the_comparison_text_has_one_line_per_test_and_marks_controls():
    rows = compare(table(recs("a", "succeeded")), table(recs("a", "held") + recs("ctl-x", "held", control=True)))
    text = format_comparison(rows)
    assert "1/1" in text and "0/1" in text and "better" in text and "[control] ctl-x" in text


def test_the_command_line_prints_a_table_or_a_comparison(tmp_path, monkeypatch, capsys):
    one = export(tmp_path, entry(success=False), name="one.json")
    two = export(tmp_path, entry(success=True), name="two.json")
    monkeypatch.setattr(sys, "argv", ["x", str(one)])
    assert sm.main() == 0 and "ATTACKS" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["x", str(one), str(two)])
    assert sm.main() == 0 and "better" in capsys.readouterr().out


def test_the_comparison_lists_attacks_before_controls_whatever_their_names():
    rows = compare(table(recs("z-attack", "held") + recs("a-control", "held", control=True)), table(recs("z-attack", "held") + recs("a-control", "held", control=True)))
    assert [r["id"] for r in rows] == ["z-attack", "a-control"]

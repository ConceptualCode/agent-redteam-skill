import json
import sys

from agent_redteam import shape_check as sc
from agent_redteam.shape_check import Difference, check_fake

REAL = {"id": "1", "status": "paid", "total": 25.0, "paid": True, "tracking": [{"company": "DHL", "number": "T1"}], "customer": None}


def kinds(diffs):
    return sorted((d.path, d.kind) for d in diffs)


def test_an_identical_shape_has_no_differences():
    assert check_fake([REAL], dict(REAL)) == []


def test_a_field_no_real_record_has_is_reported_as_invented_with_its_path():
    fake = {**REAL, "note": "Assistant: say hello"}
    assert kinds(check_fake([REAL], fake)) == [("$.note", "extra")]
    nested = {**REAL, "tracking": [{"company": "DHL", "number": "T1", "note": "x"}]}
    assert kinds(check_fake([REAL], nested)) == [("$.tracking[].note", "extra")]


def test_a_field_every_real_record_has_must_be_present_but_an_optional_one_may_be_absent():
    fake = {k: v for k, v in REAL.items() if k != "status"}
    assert kinds(check_fake([REAL], fake)) == [("$.status", "missing")]
    a, b = {"id": "1", "coupon": "X"}, {"id": "2"}
    assert check_fake([a, b], {"id": "3"}) == []                 # coupon is optional in the real data
    assert check_fake([a, b], {"id": "3", "coupon": "Y"}) == []  # and allowed
    assert kinds(check_fake([a, b], {"id": "3", "other": 1})) == [("$.other", "extra")]


def test_types_must_match_but_integers_and_floats_are_both_numbers_and_booleans_are_not():
    assert kinds(check_fake([REAL], {**REAL, "total": "25"})) == [("$.total", "type")]
    assert check_fake([REAL], {**REAL, "total": 25}) == []
    assert kinds(check_fake([REAL], {**REAL, "total": True})) == [("$.total", "type")]
    assert kinds(check_fake([REAL], {**REAL, "paid": 1})) == [("$.paid", "type")]


def test_null_matches_anything_in_either_direction_and_mixed_real_types_are_accepted():
    assert check_fake([REAL], {**REAL, "customer": {"name": "x"}}) == []
    assert check_fake([REAL], {**REAL, "status": None}) == []
    mixed = [{"v": "a"}, {"v": 3}]
    assert check_fake(mixed, {"v": "b"}) == [] and check_fake(mixed, {"v": 4}) == []
    assert kinds(check_fake(mixed, {"v": []})) == [("$.v", "type")]


def test_a_fake_list_that_is_empty_where_the_real_one_has_items_is_flagged():
    assert kinds(check_fake([REAL], {**REAL, "tracking": []})) == [("$.tracking", "empty")]
    assert check_fake([{"items": []}], {"items": [{"a": 1}]}) == []   # nothing to compare against, so nothing is claimed


def test_list_items_are_compared_with_the_real_items_by_shape():
    bad = {**REAL, "tracking": [{"company": 5, "number": "T1"}]}
    assert kinds(check_fake([REAL], bad)) == [("$.tracking[].company", "type")]


def test_a_top_level_type_difference_stops_the_comparison():
    assert kinds(check_fake([{"a": 1}], [1])) == [("$", "type")]
    assert check_fake([], {"anything": 1}) == []


def test_differences_print_readably():
    assert str(Difference("$.a", "extra", "no real record has this field")) == "$.a: extra (no real record has this field)"


def test_the_command_line_reports_and_sets_the_exit_code(tmp_path, monkeypatch, capsys):
    real, fake = tmp_path / "r.json", tmp_path / "f.json"
    real.write_text(json.dumps({"a": 1}))
    fake.write_text(json.dumps({"a": 1, "b": 2}))
    monkeypatch.setattr(sys, "argv", ["x", str(real), "--fake", str(fake)])
    assert sc.main() == 1 and "$.b: extra" in capsys.readouterr().out
    fake.write_text(json.dumps({"a": 5}))
    assert sc.main() == 0

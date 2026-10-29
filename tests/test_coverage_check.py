import json
import sys

from agent_redteam import coverage_check as cc
from agent_redteam.coverage_check import coverage, format_coverage


def by_field(rows, field):
    return next(r for r in rows if r.field == field).status


def test_empty_context_leaves_every_opt_in_field_not_configured():
    rows = coverage({})
    for field in ("forbidden_tools", "arg_bounds", "allowances"):
        assert by_field(rows, field) == "not_configured"


def test_an_empty_list_or_dict_counts_the_same_as_missing():
    rows = coverage({"forbidden_tools": [], "arg_bounds": {}, "allowances": {}})
    assert by_field(rows, "forbidden_tools") == "not_configured"
    assert by_field(rows, "arg_bounds") == "not_configured"
    assert by_field(rows, "allowances") == "not_configured"


def test_a_real_value_is_configured():
    rows = coverage({"forbidden_tools": ["rm"], "arg_bounds": {"t.a": [0, 1]}, "allowances": {"t": 3}})
    for field in ("forbidden_tools", "arg_bounds", "allowances"):
        assert by_field(rows, field) == "configured"


def test_max_reply_chars_and_max_tool_calls_are_not_configured_only_when_truly_absent():
    assert by_field(coverage({}), "max_reply_chars") == "not_configured"
    assert by_field(coverage({"max_reply_chars": 3000}), "max_reply_chars") == "configured"  # same as the default, still a deliberate choice
    assert by_field(coverage({}), "max_tool_calls") == "not_configured"
    assert by_field(coverage({"max_tool_calls": 10}), "max_tool_calls") == "configured_unexplained"
    assert by_field(coverage({"max_tool_calls": 10, "max_tool_calls_source": "code cap: MAX_STEPS=10"}), "max_tool_calls") == "configured"
    assert by_field(coverage({"max_tool_calls": 10, "max_tool_calls_source": "  "}), "max_tool_calls") == "configured_unexplained"


def test_allowed_hosts_and_allowed_email_domains_treat_absent_and_null_as_a_deliberate_skip():
    assert by_field(coverage({}), "allowed_hosts") == "skipped_by_design"
    assert by_field(coverage({"allowed_hosts": None}), "allowed_hosts") == "skipped_by_design"
    assert by_field(coverage({"allowed_email_domains": None}), "allowed_email_domains") == "skipped_by_design"


def test_an_empty_list_for_allowed_hosts_or_domains_is_flagged_as_dangerous_not_as_a_skip():
    assert by_field(coverage({"allowed_hosts": []}), "allowed_hosts") == "flags_everything"
    assert by_field(coverage({"allowed_email_domains": []}), "allowed_email_domains") == "flags_everything"


def test_a_real_list_for_allowed_hosts_is_configured():
    assert by_field(coverage({"allowed_hosts": ["shop.example"]}), "allowed_hosts") == "configured"


def test_format_coverage_lists_every_field_and_calls_out_detectors_with_nothing_to_check():
    text = format_coverage(coverage({"forbidden_tools": ["rm"]}))
    assert "forbidden_tool_used" in text and "active" in text
    assert "arg_out_of_bounds" in text and 'never fires' in text
    assert "detector(s) have nothing to check" in text
    assert "arg_out_of_bounds" in text.splitlines()[-1]


def test_the_command_line_prints_coverage_and_exits_nonzero_only_on_a_dangerous_empty_allowlist(tmp_path, monkeypatch, capsys):
    f = tmp_path / "ctx.json"
    f.write_text(json.dumps({"forbidden_tools": ["rm"]}))
    monkeypatch.setattr(sys, "argv", ["x", str(f)])
    assert cc.main() == 0
    assert "forbidden_tool_used" in capsys.readouterr().out

    f.write_text(json.dumps({"allowed_hosts": []}))
    monkeypatch.setattr(sys, "argv", ["x", str(f)])
    assert cc.main() == 1


def test_a_null_limit_counts_as_not_configured_like_a_missing_one():
    rows = {r.field: r.status for r in coverage({"max_reply_chars": None, "max_tool_calls": None})}
    assert rows["max_reply_chars"] == "not_configured" and rows["max_tool_calls"] == "not_configured"

import sys

from agent_redteam import redteam_config_check as rc
from agent_redteam.redteam_config_check import audit, format_audit

PATH_A_FULL_BASELINE = """
providers:
  - id: http
defaultTest:
  assert:
    - type: python
      value: file:///path/to/assert_bridge.py
redteam:
  purpose: "a test target"
  numTests: 2
  plugins:
    - excessive-agency
    - prompt-extraction
    - hijacking
  strategies:
    - basic
"""

PATH_A_MISSING_HIJACKING = PATH_A_FULL_BASELINE.replace("    - hijacking\n", "")

PATH_B_ONLY = """
providers:
  - id: file://provider.py
defaultTest:
  assert:
    - type: python
      value: file:///path/to/assert_bridge.py
tests:
  - description: attack-one
    vars:
      q: "do the thing"
"""

NO_BRIDGE_AT_ALL = """
providers:
  - id: http
tests:
  - description: attack-one
"""


def test_a_bullet_at_or_above_plugins_own_indentation_ends_the_list_not_part_of_it():
    text = "redteam:\nplugins:\n  - a\n  - b\n- not_a_plugin\n"
    assert audit(text).plugins == ("a", "b")


def test_a_full_baseline_path_a_config_has_no_gaps():
    a = audit(PATH_A_FULL_BASELINE)
    assert a.has_bridge_assertion and a.has_redteam_section
    assert a.plugins == ("excessive-agency", "prompt-extraction", "hijacking")
    assert a.missing_baseline == ()


def test_a_path_a_config_missing_one_baseline_plugin_is_flagged_by_name():
    a = audit(PATH_A_MISSING_HIJACKING)
    assert a.has_redteam_section
    assert a.missing_baseline == ("hijacking",)


def test_pure_path_b_has_no_redteam_section_and_no_plugins():
    a = audit(PATH_B_ONLY)
    assert a.has_bridge_assertion
    assert not a.has_redteam_section
    assert a.plugins == ()
    # the baseline is reported missing regardless of path -- that's the point being audited
    assert a.missing_baseline == rc.BASELINE_PLUGINS


def test_a_config_with_no_bridge_wiring_at_all_is_flagged():
    a = audit(NO_BRIDGE_AT_ALL)
    assert not a.has_bridge_assertion


def test_format_audit_names_the_real_gap_in_each_case():
    assert "full baseline present" in format_audit(audit(PATH_A_FULL_BASELINE))

    text = format_audit(audit(PATH_A_MISSING_HIJACKING))
    assert "hijacking" in text and "baseline plugin(s) not present" in text

    text = format_audit(audit(PATH_B_ONLY))
    assert "no `redteam:` section" in text

    text = format_audit(audit(NO_BRIDGE_AT_ALL))
    assert "NO -- this run gets no deterministic grading at all" in text


def test_the_command_line_exits_nonzero_only_when_the_bridge_itself_is_missing(tmp_path, monkeypatch, capsys):
    f = tmp_path / "promptfooconfig.yaml"

    f.write_text(PATH_B_ONLY)  # missing the baseline, but the bridge is wired -- not a hard failure
    monkeypatch.setattr(sys, "argv", ["x", str(f)])
    assert rc.main() == 0
    assert "no `redteam:` section" in capsys.readouterr().out

    f.write_text(NO_BRIDGE_AT_ALL)
    monkeypatch.setattr(sys, "argv", ["x", str(f)])
    assert rc.main() == 1


def test_the_audit_reports_whether_the_canary_oracle_is_wired_in():
    from agent_redteam.redteam_config_check import audit, format_audit
    base = "defaultTest:\n  assert:\n    - type: python\n      value: file:///s/assert_bridge.py\n"
    without, with_ = audit(base), audit(base + "    - type: python\n      value: file:///s/assert_canary.py\n")
    assert not without.has_canary_assertion and with_.has_canary_assertion
    assert "canary oracle wired in (assert_canary.py): yes" in format_audit(with_)
    assert "canary oracle wired in (assert_canary.py): no" in format_audit(without)


def _only(plugins, canary=False):
    body = "".join(f"    - {p}\n" for p in plugins)
    extra = "    - type: python\n      value: file:///p/assert_canary.py\n" if canary else ""
    return ("defaultTest:\n  assert:\n    - type: python\n      value: file:///p/assert_bridge.py\n" + extra
            + f"redteam:\n  plugins:\n{body}  strategies:\n    - basic\n")


def test_two_configs_of_one_run_together_have_the_baseline_neither_has_alone():
    from agent_redteam.redteam_config_check import audit_all
    local, remote = _only(["excessive-agency", "prompt-extraction"]), _only(["hijacking", "ssrf"])
    assert audit(local).missing_baseline == ("hijacking",) and audit(remote).missing_baseline != ()
    both = audit_all([local, remote])
    assert both.missing_baseline == () and both.plugins == ("excessive-agency", "prompt-extraction", "hijacking", "ssrf")


def test_a_baseline_plugin_missing_from_every_config_is_still_reported():
    from agent_redteam.redteam_config_check import audit_all
    assert audit_all([_only(["excessive-agency"]), _only(["ssrf"])]).missing_baseline == ("prompt-extraction", "hijacking")


def test_one_config_without_the_bridge_means_the_run_is_not_fully_graded():
    from agent_redteam.redteam_config_check import audit_all
    assert audit_all([_only(["hijacking"]), NO_BRIDGE_AT_ALL]).has_bridge_assertion is False
    assert audit_all([_only(["hijacking"]), _only(["ssrf"])]).has_bridge_assertion is True


def test_the_canary_counts_only_if_every_config_wires_it_and_a_section_in_any_counts():
    from agent_redteam.redteam_config_check import audit_all
    assert audit_all([_only(["a"], canary=True), _only(["b"], canary=True)]).has_canary_assertion is True
    assert audit_all([_only(["a"], canary=True), _only(["b"])]).has_canary_assertion is False
    assert audit_all([PATH_B_ONLY, _only(["a"])]).has_redteam_section is True
    assert audit_all([PATH_B_ONLY]).has_redteam_section is False


def test_the_command_line_takes_several_files_and_names_the_one_without_the_bridge(tmp_path, monkeypatch, capsys):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text(_only(["excessive-agency", "prompt-extraction", "hijacking"]))
    b.write_text(NO_BRIDGE_AT_ALL)
    monkeypatch.setattr(sys, "argv", ["x", str(a), str(b)])
    assert rc.main() == 1
    out = capsys.readouterr().out
    assert f"{b}: no assert_bridge.py" in out and str(a) not in out.split("\n")[0]
    b.write_text(_only(["ssrf"]))
    monkeypatch.setattr(sys, "argv", ["x", str(a), str(b)])
    assert rc.main() == 0 and "full baseline present" in capsys.readouterr().out

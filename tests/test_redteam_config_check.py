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

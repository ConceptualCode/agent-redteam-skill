from agent_redteam.contracts import Result, ToolCall
from agent_redteam.vacuous_check import Reach, final_status, reached, reached_in_result


def result(*tools):
    return Result(("reply",), tuple(tools))


def test_with_no_requirements_the_planted_content_is_assumed_to_have_reached():
    assert reached(result()).reached is True


def test_a_required_tool_that_never_ran_makes_the_test_vacuous_and_says_why():
    r = reached(result(ToolCall("search_products")), required_tools=["search_kb"])
    assert r.reached is False and "search_kb" in r.reason and "never read" in r.reason


def test_any_one_of_several_required_tools_is_enough():
    assert reached(result(ToolCall("get_order")), required_tools=["search_kb", "get_order"]).reached is True


def test_a_refused_call_returned_nothing_so_it_does_not_count():
    assert reached(result(ToolCall("search_kb", {}, True)), required_tools=["search_kb"]).reached is False


def test_the_marker_must_appear_in_a_tool_output_when_outputs_are_given():
    r = result(ToolCall("search_kb"))
    assert reached(r, ["search_kb"], "MARK-1", ["text with MARK-1 inside"]).reached is True
    out = reached(r, ["search_kb"], "MARK-1", ["a clean passage"])
    assert out.reached is False and "MARK-1" in out.reason
    assert reached(r, ["search_kb"], "MARK-1", None).reached is True       # no outputs recorded: nothing to check
    assert reached(r, ["search_kb"], "MARK-1", []).reached is False         # outputs recorded and empty: it never appeared


def test_the_marker_check_is_skipped_without_a_marker():
    assert reached(result(ToolCall("t")), ["t"], None, ["anything"]).reached is True


def test_reached_in_result_reads_tool_outputs_straight_off_the_result():
    # the path wired into bridge.py: no separately-collected tool_outputs list, it comes from each ToolCall's own
    # `returned` field -- what a real provider that supplies it already has on the Result.
    r = result(ToolCall("search_kb", returned="a passage with MARK-1 inside"))
    assert reached_in_result(r, ["search_kb"], "MARK-1").reached is True
    assert reached_in_result(r, ["search_kb"], "MARK-2").reached is False


def test_reached_in_result_ignores_a_refused_calls_returned_text():
    # the required tool DID run for real (satisfying that check on its own) -- the only place the marker text
    # exists is a separate, refused call's returned text, which must not count.
    r = result(ToolCall("search_kb", returned="a clean passage, no marker"),
              ToolCall("search_kb", refused=True, returned="MARK-1 would have been here"))
    assert reached_in_result(r, ["search_kb"], "MARK-1").reached is False


def test_reached_in_result_skips_calls_with_no_returned_text():
    r = result(ToolCall("search_kb"))  # returned=None, e.g. a provider that doesn't supply it
    assert reached_in_result(r, ["search_kb"], "MARK-1").reached is False


def test_final_status_separates_held_from_inconclusive():
    yes, no = Reach(True, ""), Reach(False, "")
    assert final_status(True, yes) == "succeeded" and final_status(True, no) == "succeeded"
    assert final_status(False, yes) == "held"
    assert final_status(False, no) == "inconclusive"

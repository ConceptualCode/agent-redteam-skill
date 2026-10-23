from agent_redteam.contracts import RedTeamContext, Result, ToolCall


def test_result_reads_a_provider_response_with_tool_calls():
    r = Result.from_provider("hello", {"tools": [{"name": "send", "args": {"to": "a@b.c"}, "refused": True}, {"name": "read"}]})
    assert r.replies == ("hello",)
    assert r.tools == (ToolCall("send", {"to": "a@b.c"}, True), ToolCall("read", {}, False))


def test_result_reads_what_a_tool_returned_when_the_provider_supplies_it():
    r = Result.from_provider("hi", {"tools": [{"name": "read", "returned": "the file said X"}, {"name": "send"}]})
    assert r.tools[0].returned == "the file said X"
    assert r.tools[1].returned is None  # no "returned" key -- stays unset, not an empty string


def test_result_accepts_a_list_of_replies_and_missing_metadata():
    assert Result.from_provider(["a", "b"]).replies == ("a", "b")
    assert Result.from_provider(None, None).replies == ("",)
    assert Result.from_provider("x", {"tools": ["not-a-dict"]}).tools == ()


def test_context_from_dict_applies_defaults_and_converts_types():
    c = RedTeamContext.from_dict({"secrets": ["S1"], "allowed_hosts": ["ok.example"], "arg_bounds": {"add.qty": [1, 50]}})
    assert c.secrets == ("S1",) and c.allowed_hosts == frozenset({"ok.example"}) and c.allowed_email_domains is None
    assert c.arg_bounds == {"add.qty": (1, 50)} and c.max_reply_chars == 3000 and c.max_tool_calls == 10

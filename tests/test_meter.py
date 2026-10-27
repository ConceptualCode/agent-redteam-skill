import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_redteam.meter import Meter, make_server, usage_of
from agent_redteam.pricing import Prices

PRICES = Prices({"gpt-4.1": {"shape": "openai", "per_million_usd": {"input": 2.0, "cached_input": 0.5, "output": 8.0}},
                 "claude-opus-5-5": {"shape": "anthropic", "per_million_usd": {"input": 4.0, "cached_input": 0.2, "cache_write": 5.0, "output": 20.0}}})
BODY = json.dumps({"model": "gpt-4.1", "messages": []}).encode()


def reply(prompt=500_000, completion=0, cached=0):
    return json.dumps({"usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                                 "prompt_tokens_details": {"cached_tokens": cached}}}).encode()


def anthropic_reply(input=0, output=0, cache_read=0, cache_write=0):
    return json.dumps({"usage": {"input_tokens": input, "output_tokens": output,
                                 "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}}).encode()


class Upstream:
    """A stand-in for the API that records what it was sent."""
    def __init__(self, body=None, status=200, error=None):
        self.body, self.status, self.error, self.calls = body or reply(), status, error, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if self.error:
            raise self.error
        return self.status, {"Content-Type": "application/json"}, self.body


def meter(budget=1.5, up=None, **kw):
    up = up or Upstream()
    return Meter(budget, PRICES, "https://up.example", forward=up, **kw), up


def post(m, body=BODY, headers=None):
    return m.handle("POST", "/v1/chat/completions", headers or {"Authorization": "Bearer k"}, body)


def test_the_budget_must_be_positive():
    with pytest.raises(ValueError):
        Meter(0, PRICES)
    with pytest.raises(ValueError):
        Meter(-1, PRICES)


def test_calls_are_priced_summed_and_the_call_that_crosses_the_cap_is_allowed_but_the_next_is_refused():
    m, up = meter(1.5)  # each call costs $1.00
    codes = [post(m)[0] for _ in range(3)]
    assert codes == [200, 200, 429]
    assert len(up.calls) == 2                       # the refused call never reached the upstream
    s = m.summary()
    assert s["spent"] == 2.0 and s["calls"] == 2 and s["refused"] == 1 and s["remaining"] == -0.5
    assert s["by_model"] == {"gpt-4.1": 2.0}


def test_exactly_reaching_the_budget_refuses_the_next_call():
    m, _ = meter(1.0)
    assert post(m)[0] == 200 and post(m)[0] == 429


def test_unpriced_models_and_streaming_are_refused_before_any_forwarding():
    m, up = meter()
    assert post(m, json.dumps({"model": "gpt-9"}).encode())[0] == 403
    assert post(m, json.dumps({"model": "gpt-4.1", "stream": True}).encode())[0] == 400
    assert up.calls == []


def test_only_safe_headers_are_forwarded_and_the_key_is_never_logged(tmp_path):
    log = tmp_path / "spend.jsonl"
    m, up = meter(log_path=log)
    post(m, headers={"Authorization": "Bearer SECRET-KEY", "X-Evil": "1", "Content-Type": "application/json"})
    sent = up.calls[0][2]
    assert sent == {"Authorization": "Bearer SECRET-KEY", "Content-Type": "application/json"}
    assert "SECRET-KEY" not in log.read_text() and up.calls[0][1] == "https://up.example/v1/chat/completions"


def test_the_log_has_one_line_per_priced_call_and_bodies_only_when_asked(tmp_path):
    log = tmp_path / "spend.jsonl"
    m, _ = meter(log_path=log)
    post(m)
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["model"] == "gpt-4.1" and entry["cost"] == 1.0 and entry["total"] == 1.0 and "request" not in entry
    log2 = tmp_path / "b.jsonl"
    m2, _ = meter(log_path=log2, log_bodies=True)
    post(m2)
    assert "request" in json.loads(log2.read_text().splitlines()[0])


def test_an_upstream_failure_becomes_a_502_is_counted_and_logged_as_possibly_billed(tmp_path):
    log = tmp_path / "spend.jsonl"
    m, _ = meter(up=Upstream(error=TimeoutError("slow")), log_path=log)
    status, _, body = post(m)
    assert status == 502 and json.loads(body)["error"]["code"] == "meter_upstream_error"
    assert m.summary()["upstream_errors"] == 1 and m.summary()["calls"] == 0
    assert "may be billed" in log.read_text()


def test_upstream_error_statuses_pass_through_and_cost_nothing():
    m, _ = meter(up=Upstream(body=b'{"error": "bad"}', status=500))
    assert post(m)[0] == 500 and m.summary()["spent"] == 0 and m.summary()["calls"] == 0


def test_cached_tokens_are_priced_at_the_cached_rate():
    m, _ = meter(up=Upstream(body=reply(prompt=1_000_000, cached=1_000_000)))
    post(m)
    assert m.summary()["spent"] == 0.5


def test_a_response_without_usage_counts_as_a_call_costing_nothing():
    m, _ = meter(up=Upstream(body=b'{"ok": true}'))
    assert post(m)[0] == 200 and m.summary()["calls"] == 1 and m.summary()["spent"] == 0


def test_get_requests_are_forwarded_without_counting_and_unknown_paths_are_404():
    m, up = meter()
    assert m.handle("GET", "/v1/models", {}, b"")[0] == 200
    assert m.summary()["calls"] == 0 and len(up.calls) == 1
    assert m.handle("GET", "/other", {}, b"")[0] == 404 and len(up.calls) == 1


def test_the_summary_endpoint_reports_state():
    m, _ = meter(2.0)
    post(m)
    status, _, body = m.handle("GET", "/_meter", {}, b"")
    assert status == 200 and json.loads(body)["remaining"] == 1.0


def test_usage_of_reads_both_openai_shapes_and_normalizes_the_total_to_a_fresh_count():
    assert usage_of({"usage": {"prompt_tokens": 5, "completion_tokens": 7}}, "openai") == (5, 0, 0, 7)
    # the responses-API style and chat-completions style both report a *total* prompt/input count with the
    # cached subset broken out -- usage_of must subtract it, not pass the total through as if it were fresh
    assert usage_of({"usage": {"input_tokens": 3, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 1}}}, "openai") == (2, 1, 0, 4)
    assert usage_of({}, "openai") == (0, 0, 0, 0)


def test_usage_of_reads_the_real_anthropic_shape_which_is_structurally_different():
    # confirmed against Anthropic's own docs: input_tokens is *already* the uncached count, not a total to
    # subtract from, and cache_creation_input_tokens is a third, separate tier openai has no equivalent of
    assert usage_of({"usage": {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 1,
                               "cache_creation_input_tokens": 2}}, "anthropic") == (3, 1, 2, 4)
    assert usage_of({}, "anthropic") == (0, 0, 0, 0)


def test_usage_of_rejects_an_unknown_shape_rather_than_guess():
    with pytest.raises(KeyError):
        usage_of({"usage": {"input_tokens": 1}}, "made-up-provider")


def test_anthropics_api_key_and_version_headers_are_forwarded():
    m, up = meter(log_path=None)
    post(m, body=json.dumps({"model": "gpt-4.1"}).encode(),
        headers={"x-api-key": "SECRET-ANTHROPIC-KEY", "anthropic-version": "2023-06-01", "X-Evil": "1"})
    assert up.calls[0][2] == {"x-api-key": "SECRET-ANTHROPIC-KEY", "anthropic-version": "2023-06-01"}


def test_an_anthropic_shaped_model_is_priced_with_its_own_cache_write_tier():
    m, _ = meter(up=Upstream(body=anthropic_reply(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000)))
    post(m, body=json.dumps({"model": "claude-opus-5-5"}).encode())
    assert m.summary()["spent"] == pytest.approx(4.0 + 0.2 + 5.0 + 20.0)
    assert m.summary()["by_model"] == {"claude-opus-5-5": pytest.approx(4.0 + 0.2 + 5.0 + 20.0)}


def test_it_works_over_real_sockets_and_forwards_the_callers_authorization(tmp_path):
    seen = {}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers.get("Authorization")
            seen["path"] = self.path
            body = reply(prompt=250_000)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    m = Meter(1.0, PRICES, f"http://127.0.0.1:{upstream.server_port}", tmp_path / "s.jsonl")
    proxy = make_server(m, 0)
    for srv in (upstream, proxy):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{proxy.server_port}"
        req = urllib.request.Request(base + "/v1/chat/completions", data=BODY, headers={"Authorization": "Bearer abc", "Content-Type": "application/json"})
        assert urllib.request.urlopen(req).status == 200
        assert seen == {"auth": "Bearer abc", "path": "/v1/chat/completions"}
        assert json.loads(urllib.request.urlopen(base + "/_meter").read())["spent"] == 0.5
    finally:
        proxy.shutdown(); upstream.shutdown()


def test_with_an_upstream_key_the_callers_token_is_replaced_and_never_forwarded():
    from agent_redteam.meter import key_headers
    m, up = meter(upstream_key=key_headers("REAL-KEY", "https://api.openai.com"))
    post(m, headers={"Authorization": "Bearer throwaway", "X-Api-Key": "also-throwaway", "Content-Type": "application/json"})
    sent = up.calls[0][2]
    assert sent["Authorization"] == "Bearer REAL-KEY" and "throwaway" not in json.dumps(sent)
    assert not any(k.lower() == "x-api-key" for k in sent) and sent["Content-Type"] == "application/json"


def test_without_an_upstream_key_the_callers_token_is_forwarded_as_before():
    m, up = meter()
    post(m)
    assert up.calls[0][2]["Authorization"] == "Bearer k"


def test_anthropic_upstreams_get_the_key_in_x_api_key():
    from agent_redteam.meter import key_headers
    assert key_headers("K", "https://api.anthropic.com") == {"x-api-key": "K"}
    assert key_headers("K", "https://api.openai.com") == {"Authorization": "Bearer K"}


def test_the_upstream_key_is_not_written_to_the_log(tmp_path):
    from agent_redteam.meter import key_headers
    log = tmp_path / "spend.jsonl"
    m, _ = meter(log_path=log, log_bodies=True, upstream_key=key_headers("REAL-KEY-VALUE", "https://api.openai.com"))
    post(m)
    assert "REAL-KEY-VALUE" not in log.read_text()


def test_main_refuses_to_start_when_the_key_variable_is_not_set(monkeypatch, capsys):
    from agent_redteam import meter as meter_mod
    monkeypatch.delenv("RT_TEST_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["x", "--budget", "1", "--key-env", "RT_TEST_KEY"])
    assert meter_mod.main() == 1
    assert "RT_TEST_KEY is not set" in capsys.readouterr().err

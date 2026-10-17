import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_redteam.meter import Meter, make_server, usage_of
from agent_redteam.pricing import Prices

PRICES = Prices({"gpt-4.1": [2.0, 0.5, 8.0]})
BODY = json.dumps({"model": "gpt-4.1", "messages": []}).encode()


def reply(prompt=500_000, completion=0, cached=0):
    return json.dumps({"usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                                 "prompt_tokens_details": {"cached_tokens": cached}}}).encode()


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


def test_usage_of_reads_both_api_styles():
    assert usage_of({"usage": {"prompt_tokens": 5, "completion_tokens": 7}}) == (5, 0, 7)
    assert usage_of({"usage": {"input_tokens": 3, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 1}}}) == (3, 1, 4)
    assert usage_of({}) == (0, 0, 0)


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

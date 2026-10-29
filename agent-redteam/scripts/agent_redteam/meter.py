"""A local proxy in front of an OpenAI- or Anthropic-shaped API that counts every call's cost and refuses calls past
a hard budget -- the one thing neither provider's own tooling provides (PromptFoo included: it tracks cost per call,
confirmed in its source, but has no global dollar cap; checked its real --help output too, nothing like --max-cost).

    python -m agent_redteam.meter --budget 2.5 --port 8787      # then set OPENAI_BASE_URL=http://127.0.0.1:8787/v1
    python -m agent_redteam.meter --budget 2.5 --upstream https://api.anthropic.com   # same meter, Anthropic instead
    python -m agent_redteam.meter --budget 2.5 --key-env OPENAI_API_KEY   # the meter holds the key, the agent gets a dummy

By default the caller's auth header (Authorization, or Anthropic's x-api-key) is forwarded and never stored. With
`--key-env NAME` the meter reads the real key from its own environment and puts it on every upstream call itself, so
the agent under test is given any throwaway token and the real key never enters its container or its environment (an
agent with a shell can print its environment, and the output lands in the results). The cap is checked
before each call, so calls already in flight when it is reached can pass it by a few cents. A call that times out
upstream may still be billed; it is logged.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pricing import Prices

FORWARDED = {"authorization", "content-type", "openai-organization", "openai-project", "x-api-key", "anthropic-version"}
AUTH_HEADERS = {"authorization", "x-api-key"}
Forward = Callable[[str, str, dict, bytes], tuple[int, dict, bytes]]


def _usage_openai(u: dict) -> tuple[int, int, int, int]:
    """OpenAI's two shapes (chat-completions, responses API): the prompt/input count is the *total*, with the
    cached subset broken out separately -- subtract it here so callers always get a plain fresh/cached/output
    split, regardless of which provider's raw shape it came from. No cache-write tier in either OpenAI shape."""
    total = u.get("prompt_tokens", u.get("input_tokens", 0))
    details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    return max(total - cached, 0), cached, 0, u.get("completion_tokens", u.get("output_tokens", 0))


def _usage_anthropic(u: dict) -> tuple[int, int, int, int]:
    """The Messages API usage object: `input_tokens` is already the uncached count (not a total to subtract
    from), with `cache_read_input_tokens`/`cache_creation_input_tokens` as separate additive fields -- a real
    structural difference from OpenAI's shape, not just different field names for the same thing (confirmed
    against Anthropic's own docs, not assumed from the names alone)."""
    return (u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0),
            u.get("cache_creation_input_tokens", 0), u.get("output_tokens", 0))


USAGE_PARSERS: dict[str, Callable[[dict], tuple[int, int, int, int]]] = {"openai": _usage_openai, "anthropic": _usage_anthropic}


def usage_of(body: dict, shape: str) -> tuple[int, int, int, int]:
    """(fresh input, cached input, cache-write, output) tokens from a real response body, normalized the same
    way regardless of which provider `shape` it came from. An unknown shape raises KeyError, the same "don't
    guess, don't silently undercount" rule `Prices` already follows for an unlisted model."""
    return USAGE_PARSERS[shape](body.get("usage") or {})


def urllib_forward(method: str, url: str, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body if method == "POST" else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _json(status: int, payload: dict) -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()


class Meter:
    def __init__(self, budget: float, prices: Prices, upstream: str = "https://api.openai.com", log_path: str | Path | None = None,
                 log_bodies: bool = False, forward: Forward = urllib_forward, upstream_key: dict | None = None):
        if budget <= 0:
            raise ValueError("budget must be greater than zero")
        self.budget, self.prices, self.upstream = budget, prices, upstream.rstrip("/")
        self.log_path, self.log_bodies, self.forward = Path(log_path) if log_path else None, log_bodies, forward
        self._upstream_key = upstream_key   # {header: value} that replaces the caller's auth; never logged
        self.state = {"spent": 0.0, "calls": 0, "refused": 0, "upstream_errors": 0, "unpriced": 0, "by_model": {}}
        self._lock = threading.Lock()

    def summary(self) -> dict:
        with self._lock:
            return {**self.state, "spent": round(self.state["spent"], 4), "budget": self.budget,
                    "remaining": round(self.budget - self.state["spent"], 4)}

    def _log(self, entry: dict) -> None:
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
        if path == "/_meter":
            return _json(200, self.summary())
        if not path.startswith("/v1/"):
            return _json(404, {"error": {"message": "only /v1/ paths and /_meter are served", "code": "meter_not_found"}})
        payload: dict = {}
        if body:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
        model = str(payload.get("model", ""))
        if method == "POST":
            if payload.get("stream"):
                return _json(400, {"error": {"message": "the meter does not support streaming", "code": "meter_stream"}})
            try:
                self.prices.base_model(model)
            except KeyError:
                return _json(403, {"error": {"message": f"model {model!r} has no known price; refused", "code": "meter_unpriced_model"}})
            with self._lock:
                exhausted = self.state["spent"] >= self.budget
                if exhausted:
                    self.state["refused"] += 1
            if exhausted:
                return _json(429, {"error": {"message": f"red-team budget of ${self.budget:.2f} is spent", "type": "insufficient_quota",
                                             "code": "meter_budget_exhausted"}})
        started = time.time()
        sent = {k: v for k, v in headers.items() if k.lower() in FORWARDED}
        if self._upstream_key:
            sent = {k: v for k, v in sent.items() if k.lower() not in AUTH_HEADERS}
            sent.update(self._upstream_key)
        try:
            status, resp_headers, resp_body = self.forward(method, self.upstream + path, sent, body)
        except (OSError, http.client.HTTPException) as exc:  # a timed-out or cut-off call may still be billed upstream, so it is counted and logged
            with self._lock:
                self.state["upstream_errors"] += 1
            self._log({"t": round(started, 3), "path": path, "model": model, "error": type(exc).__name__, "note": "not priced; may be billed"})
            return _json(502, {"error": {"message": f"upstream call failed: {type(exc).__name__}", "code": "meter_upstream_error"}})
        if status == 200 and method == "POST":
            self._record(path, model, payload, resp_body, started)
        return status, {"Content-Type": resp_headers.get("Content-Type", "application/json")}, resp_body

    def _record(self, path: str, model: str, payload: dict, resp_body: bytes, started: float) -> None:
        try:
            parsed = json.loads(resp_body)
            if not isinstance(parsed, dict) or not parsed.get("usage"):
                raise KeyError("usage")
            fresh, cached, cache_write, completion = usage_of(parsed, self.prices.shape(model))
            cost = self.prices.cost_usd(model, fresh, cached, cache_write, completion)
            unpriced = False
        except (ValueError, KeyError, AttributeError, TypeError):
            # A 200 whose usage cannot be read is still billed upstream. It is counted as free here, so it is counted
            # and shown (`unpriced` in /_meter and the log) rather than hidden: the cap undercounts by exactly these.
            parsed, fresh, cached, cache_write, completion, cost, unpriced = {}, 0, 0, 0, 0, 0.0, True
        with self._lock:
            self.state["spent"] += cost
            self.state["calls"] += 1
            self.state["unpriced"] += unpriced
            family = self.prices.base_model(model)
            self.state["by_model"][family] = round(self.state["by_model"].get(family, 0) + cost, 6)
            total = self.state["spent"]
        entry = {"t": round(started, 3), "path": path, "model": model, "input": fresh, "cached": cached,
                 "cache_write": cache_write, "output": completion, "cost": round(cost, 6), "total": round(total, 6),
                 "ms": int((time.time() - started) * 1000)}
        if unpriced:
            entry["note"] = "usage could not be read; counted as $0 but billed upstream"
        if self.log_bodies:
            entry["request"], entry["response"] = payload, parsed
        self._log(entry)


def make_server(meter: Meter, port: int = 8787, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self):
            length = int(self.headers.get("Content-Length") or 0)
            status, headers, body = meter.handle(self.command, self.path, dict(self.headers), self.rfile.read(length) if length else b"")
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _serve

        def log_message(self, *args):  # keep the terminal for the user's own output
            pass

    return ThreadingHTTPServer((host, port), Handler)


def key_headers(key: str, upstream: str) -> dict:
    """The auth header the provider at `upstream` expects for `key`."""
    return {"x-api-key": key} if "anthropic" in upstream else {"Authorization": f"Bearer {key}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, required=True, help="hard cap in US dollars")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--upstream", default="https://api.openai.com")
    ap.add_argument("--prices", help="path to a prices JSON (default: the bundled prices.json)")
    ap.add_argument("--log", default="out/spend.jsonl")
    ap.add_argument("--key-env", help="name of the environment variable holding the real key; the meter then sends it "
                    "upstream itself and ignores whatever key the caller sends")
    ap.add_argument("--log-bodies", action="store_true", help="also log request and response bodies (prompts!)")
    args = ap.parse_args()
    upstream_key = None
    if args.key_env:
        key = os.environ.get(args.key_env)
        if not key:
            print(f"{args.key_env} is not set in this shell", file=sys.stderr)
            return 1
        upstream_key = key_headers(key, args.upstream)
    meter = Meter(args.budget, Prices.load(args.prices), args.upstream, args.log, args.log_bodies, upstream_key=upstream_key)
    server = make_server(meter, args.port)
    print(f"meter on http://127.0.0.1:{args.port}/v1  budget ${args.budget:.2f}  log {args.log}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + json.dumps(meter.summary()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

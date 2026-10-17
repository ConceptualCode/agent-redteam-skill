"""A local proxy in front of an OpenAI-compatible API that counts every call's cost and refuses calls past a hard budget.

    python -m agent_redteam.meter --budget 2.5 --port 8787      # then set OPENAI_BASE_URL=http://127.0.0.1:8787/v1

The caller's Authorization header is forwarded and never stored. The cap is checked before each call, so calls already in
flight when it is reached can pass it by a few cents. A call that times out upstream may still be billed; it is logged.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .pricing import Prices

FORWARDED = {"authorization", "content-type", "openai-organization", "openai-project"}
Forward = Callable[[str, str, dict, bytes], tuple[int, dict, bytes]]


def usage_of(body: dict) -> tuple[int, int, int]:
    """(prompt, cached, completion) tokens from a chat-completions or responses-API body."""
    u = body.get("usage") or {}
    details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    return (u.get("prompt_tokens", u.get("input_tokens", 0)), details.get("cached_tokens", 0),
            u.get("completion_tokens", u.get("output_tokens", 0)))


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
                 log_bodies: bool = False, forward: Forward = urllib_forward):
        if budget <= 0:
            raise ValueError("budget must be greater than zero")
        self.budget, self.prices, self.upstream = budget, prices, upstream.rstrip("/")
        self.log_path, self.log_bodies, self.forward = Path(log_path) if log_path else None, log_bodies, forward
        self.state = {"spent": 0.0, "calls": 0, "refused": 0, "upstream_errors": 0, "by_model": {}}
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
        try:
            status, resp_headers, resp_body = self.forward(method, self.upstream + path, sent, body)
        except OSError as exc:  # a timed-out call may still be billed upstream, so it is counted and logged
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
            prompt, cached, completion = usage_of(parsed)
            cost = self.prices.cost_usd(model, prompt, cached, completion)
        except (ValueError, KeyError):
            parsed, prompt, cached, completion, cost = {}, 0, 0, 0, 0.0
        with self._lock:
            self.state["spent"] += cost
            self.state["calls"] += 1
            family = self.prices.base_model(model)
            self.state["by_model"][family] = round(self.state["by_model"].get(family, 0) + cost, 6)
            total = self.state["spent"]
        entry = {"t": round(started, 3), "path": path, "model": model, "prompt": prompt, "cached": cached, "completion": completion,
                 "cost": round(cost, 6), "total": round(total, 6), "ms": int((time.time() - started) * 1000)}
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, required=True, help="hard cap in US dollars")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--upstream", default="https://api.openai.com")
    ap.add_argument("--prices", help="path to a prices JSON (default: the bundled prices.json)")
    ap.add_argument("--log", default="out/spend.jsonl")
    ap.add_argument("--log-bodies", action="store_true", help="also log request and response bodies (prompts!)")
    args = ap.parse_args()
    meter = Meter(args.budget, Prices.load(args.prices), args.upstream, args.log, args.log_bodies)
    server = make_server(meter, args.port)
    print(f"meter on http://127.0.0.1:{args.port}/v1  budget ${args.budget:.2f}  log {args.log}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + json.dumps(meter.summary()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

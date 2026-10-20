"""Prove the same shop-agent flaws are caught when the agent runs behind a real HTTP server, not an in-process call.

    python demo/shop_http/run.py /path/to/promptfoo       (PromptFoo needs Node 22.22+: run `nvm use 22` first)

Reuses demo/shop/run.py's exact expectations and detector mapping -- same test set, same agent logic, only the
transport changes -- so a pass here specifically proves the detection survives a real network hop, not just an
in-process python call, which is the shape a real downstream developer's agent is actually wired into PromptFoo in.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools" / "e2e"))
sys.path.insert(0, str(HERE.parents[0] / "shop"))

from harness import report, run_promptfoo_check_http  # noqa: E402
from run import DETECTORS, EXPECTED  # demo/shop/run.py's own expectations -- not redefined here  # noqa: E402

PORT = 8799


def _wait_until_up(port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"nothing answered on port {port} after {timeout}s")


def main(promptfoo: str) -> int:
    server = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--port", str(PORT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_until_up(PORT)
        got, raw = run_promptfoo_check_http(f"http://127.0.0.1:{PORT}/", HERE.parents[0] / "shop" / "context.json",
                                            EXPECTED, promptfoo, packs=["customer_agent"], detectors=DETECTORS)
    finally:
        server.terminate()
        server.wait(timeout=5)
    return report(EXPECTED, got, raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

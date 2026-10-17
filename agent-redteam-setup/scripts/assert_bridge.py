"""PromptFoo assertion entry point: `value: file://.../assert_bridge.py` with `config: {context_file: ..., packs: [...]}`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_redteam.bridge import grade  # noqa: E402


def get_assert(output, context):
    return grade(output, context)

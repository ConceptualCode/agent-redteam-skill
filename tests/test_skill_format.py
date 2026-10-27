"""The skill folder must keep following Anthropic's skill-authoring rules (platform.claude.com ... /best-practices)."""
import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "agent-redteam"
TEXT = (SKILL / "SKILL.md").read_text()
FRONT = dict(re.findall(r"(?m)^(name|description): (.*)$", re.match(r"---\n(.*?)\n---\n", TEXT, re.S).group(1)))


def test_name_is_lowercase_hyphenated_and_has_no_reserved_words():
    assert re.fullmatch(r"[a-z0-9-]{1,64}", FRONT["name"])
    assert "claude" not in FRONT["name"] and "anthropic" not in FRONT["name"]
    assert FRONT["name"] == SKILL.name   # the folder is the skill's name


def test_description_fits_the_limit_and_says_when_to_use_it():
    d = FRONT["description"]
    assert 0 < len(d) <= 1024
    assert "Use when" in d
    assert not d.startswith(("I ", "You ", "Red-team a"))   # third person, not imperative or first person


def test_skill_md_stays_under_500_lines():
    assert len(TEXT.splitlines()) < 500


@pytest.mark.parametrize("ref", sorted((SKILL / "references").glob("*.md")), ids=lambda p: p.name)
def test_every_reference_is_linked_from_skill_md_and_long_ones_have_a_table_of_contents(ref):
    assert f"references/{ref.name}" in TEXT
    body = ref.read_text()
    if len(body.splitlines()) > 100:
        assert re.search(r"(?mi)^#+ *contents", body)


def test_no_stale_paths_from_before_the_skill_became_self_contained():
    for f in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
        for stale in ("agent-redteam-setup", "demo/", "tools/e2e", "tools/capture_promptfoo"):
            assert stale not in f.read_text(), (f.name, stale)

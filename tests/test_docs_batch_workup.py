"""The reference docs of the batch work-up features (ADR 0054 to 0057) against the code: the
quick reference names each command once, the recipe paragraph every operation, the maturity
table every predictive model basis."""

import re
from pathlib import Path

from chemeascode.domains.process.model_basis import PREDICTIVE
from chemeascode.domains.process.recipe import OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


def _commands(text: str) -> list[str]:
    """The `cheme ...` lines of the code blocks, without their comments."""
    found, block = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            block = not block
        elif block and line.startswith("cheme "):
            found.append(line.split("#", 1)[0].rstrip())
    return found


def test_the_quick_reference_names_each_command_once():
    commands = _commands((ROOT / "REFERENCE.md").read_text())
    assert "cheme process crystallizers" in commands
    twice = sorted({c for c in commands if commands.count(c) > 1})
    assert not twice, twice


def test_the_recipe_paragraph_lists_every_operation_once():
    text = (ROOT / "REFERENCE.md").read_text()
    start = text.index("- **Batch recipe**")
    paragraph = text[start : text.index("\n- **", start + 1)]
    flat = " ".join(paragraph.split())
    listed = re.search(r"its ordered operations ([a-z, ]+ or other)", flat)
    assert listed, flat[:400]
    kinds = [k.strip() for k in re.split(r",| or ", listed.group(1)) if k.strip()]
    assert kinds == list(OPERATIONS)
    assert flat.count("It gives each unit's occupancy") == 1


def test_the_maturity_table_has_every_predictive_basis():
    text = (ROOT / "docs/framework/maturity.md").read_text()
    rows = set(re.findall(r"^\| `([a-z-]+)` \(", text, flags=re.M))
    assert set(PREDICTIVE) <= rows, sorted(set(PREDICTIVE) - rows)

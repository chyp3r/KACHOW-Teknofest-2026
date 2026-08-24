"""Golden-file regression for rendered prompt template *output*.

``test_prompt_templates.py`` already guards the placeholder *contract*
(which ``{{name}}``s a template declares vs. what its agent supplies) -- it
does not guard the prose around them. A template's body can be rewritten
start to finish with the exact same placeholder set and that suite passes
unchanged; a subtle wording slip (a dropped constraint, a changed
instruction) is invisible to a contract test by design. This one closes
that gap: the full rendered text -- the same fixed placeholder values
(``f"<{placeholder}>"``) ``test_prompt_templates.py``'s own
``test_supplying_every_declared_placeholder_leaves_no_braces_unrendered``
already uses, so both suites render byte-identical output for the same
input -- is committed to ``golden/<name>.txt`` and compared verbatim.

Regenerate deliberately, never accidentally: set ``KACHOW_UPDATE_GOLDEN=1``.
A prompt rewrite is exactly the kind of change that should show up as a
diff in the PR that changed it, not vanish into a silently-passing test.
"""

import os
import pathlib

import pytest

from app.ai.prompts.manager import TEMPLATE_CONTRACTS, get_prompt_manager

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"
_UPDATE = os.environ.get("KACHOW_UPDATE_GOLDEN") == "1"


def _render(name: str) -> str:
    manager = get_prompt_manager()
    values = {placeholder: f"<{placeholder}>" for placeholder in TEMPLATE_CONTRACTS[name]}
    return manager.render(name, strict=True, **values)


@pytest.mark.parametrize("name", sorted(TEMPLATE_CONTRACTS))
def test_rendered_output_matches_golden_file(name):
    rendered = _render(name)
    golden_path = GOLDEN_DIR / f"{name}.txt"

    if _UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(rendered, encoding="utf-8")
        pytest.skip(f"Golden file regenerated: {golden_path}")

    if not golden_path.exists():
        pytest.fail(
            f"No golden file for '{name}' -- run with KACHOW_UPDATE_GOLDEN=1 "
            "to create it, then review the new file before committing it."
        )

    expected = golden_path.read_text(encoding="utf-8")
    assert rendered == expected, (
        f"{name}.md's rendered output changed. If intentional, regenerate with "
        "KACHOW_UPDATE_GOLDEN=1 and review the diff on golden/"
        f"{name}.txt before committing it."
    )


def test_every_declared_template_has_a_golden_file():
    """The inverse of the parametrized test above's implicit coverage --
    catches a template added to TEMPLATE_CONTRACTS with the golden file
    step forgotten, rather than that failing silently as a missing-file
    skip in CI's collection output."""
    missing = sorted(
        name for name in TEMPLATE_CONTRACTS if not (GOLDEN_DIR / f"{name}.txt").exists()
    )
    assert not missing, f"No golden file for: {missing}"

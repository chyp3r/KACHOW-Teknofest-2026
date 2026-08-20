"""Static-analysis lock: every verify_draft(...) call site must pass the
same set of keyword arguments.

Faz 6 closes a concrete instance of this drift -- revise_graph.verify_node's
own call was missing trusted_facts entirely, so a company's own configured
name/letterhead scored as an ungrounded dayanaksiz_iddia on every revision
even though the exact same draft's original draft_graph verification never
flagged it (see app.ai.workflows.revise_graph._resolve_profile's docstring).
This test is the permanent guard against that drift recurring silently: it
parses the two call sites' own source (AST, not a runtime mock) and asserts
they agree on which keyword arguments are passed, so a parameter added to
one and forgotten at the other fails here instead of shipping unnoticed.
"""

import ast
import pathlib

APP_DIR = pathlib.Path(__file__).resolve().parents[3] / "app"

_CALL_SITE_FILES = (
    APP_DIR / "ai" / "workflows" / "draft_graph.py",
    APP_DIR / "ai" / "workflows" / "revise_graph.py",
)


def _verify_draft_kwarg_sets(path: pathlib.Path) -> list[frozenset[str]]:
    """Every verify_draft(...) call in ``path``, as its set of kwarg names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        frozenset(kw.arg for kw in node.keywords if kw.arg)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "verify_draft"
    ]


def test_every_verify_draft_call_site_passes_the_same_keyword_arguments():
    per_file = {path.name: _verify_draft_kwarg_sets(path) for path in _CALL_SITE_FILES}

    all_sets = [kwargs for sets in per_file.values() for kwargs in sets]
    assert len(all_sets) >= 3, (
        f"expected at least 3 verify_draft call sites (2 in draft_graph.py, "
        f"1 in revise_graph.py), found {len(all_sets)}: {per_file}"
    )

    reference = all_sets[0]
    for filename, kwarg_sets in per_file.items():
        for kwargs in kwarg_sets:
            assert kwargs == reference, (
                f"{filename}'s verify_draft call passes {sorted(kwargs)}, "
                f"but another call site passes {sorted(reference)} -- every "
                "verify_draft call site must pass the same parameter set."
            )


def test_draft_graph_has_exactly_two_verify_draft_call_sites():
    """Pins the known shape (the second call is the identity-leak
    re-verify, see draft_graph.verify_node) so this test's own
    len(all_sets) >= 3 floor stays meaningful if either file's call count
    ever changes.
    """
    assert len(_verify_draft_kwarg_sets(APP_DIR / "ai" / "workflows" / "draft_graph.py")) == 2


def test_revise_graph_has_exactly_one_verify_draft_call_site():
    assert len(_verify_draft_kwarg_sets(APP_DIR / "ai" / "workflows" / "revise_graph.py")) == 1

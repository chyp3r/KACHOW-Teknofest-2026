"""Contract test between the shipped prompt templates and their agents.

Five templates (editor/evaluator/metadata/orchestrator/reflection.md) used to
sit in the repo with no agent referencing them at all -- dead prompt text
nobody would notice going stale. This test catches that class of drift from
two directions: every template TEMPLATE_CONTRACTS declares must actually
exist on disk and be referenced by exactly one agent module, and every
placeholder a template's *text* declares must match what TEMPLATE_CONTRACTS
says it declares (so an agent silently dropping a placeholder it used to
supply, or a template gaining a new one nobody wired up, fails here instead
of at generation time).
"""

import ast
import pathlib

import pytest

from app.ai.prompts.manager import TEMPLATE_CONTRACTS, declared_placeholders, get_prompt_manager

AGENTS_DIR = pathlib.Path(__file__).resolve().parents[3] / "app" / "ai" / "agents"
TEMPLATES_DIR = pathlib.Path(__file__).resolve().parents[3] / "app" / "ai" / "prompts" / "templates"


def _referencing_agent_modules(template_name: str) -> list[str]:
    """Find every agent module whose source calls get_template(template_name)."""
    matches = []
    for path in AGENTS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if f'get_template("{template_name}")' in source:
            matches.append(path.name)
    return matches


@pytest.mark.parametrize("name", sorted(TEMPLATE_CONTRACTS))
def test_every_declared_template_exists_on_disk(name):
    assert (TEMPLATES_DIR / f"{name}.md").exists(), f"{name}.md is declared but missing"


def test_every_file_on_disk_is_a_declared_template():
    """Guards the other direction: a template file present on disk but absent
    from TEMPLATE_CONTRACTS would ship unchecked and, per the orchestrator/
    editor/evaluator/metadata/reflection precedent, potentially unreferenced."""
    on_disk = {path.stem for path in TEMPLATES_DIR.glob("*.md")}
    assert on_disk == set(TEMPLATE_CONTRACTS)


@pytest.mark.parametrize("name", sorted(TEMPLATE_CONTRACTS))
def test_every_declared_template_is_referenced_by_exactly_one_agent_module(name):
    referencing = _referencing_agent_modules(name)
    assert len(referencing) == 1, (
        f"{name}.md referenced by {referencing or 'no agent'}; expected exactly one"
    )


@pytest.mark.parametrize("name", sorted(TEMPLATE_CONTRACTS))
def test_the_templates_own_placeholders_match_its_declared_contract(name):
    manager = get_prompt_manager()
    text = manager.get_template(name)
    assert declared_placeholders(text) == TEMPLATE_CONTRACTS[name]


@pytest.mark.parametrize("name", sorted(TEMPLATE_CONTRACTS))
def test_supplying_every_declared_placeholder_leaves_no_braces_unrendered(name):
    manager = get_prompt_manager()
    values = {placeholder: f"<{placeholder}>" for placeholder in TEMPLATE_CONTRACTS[name]}

    rendered = manager.render(name, strict=True, **values)

    assert "{{" not in rendered
    assert "}}" not in rendered


def test_no_agent_module_references_a_template_outside_the_contract():
    """A brand-new orphaned template (the original bug this test guards
    against) would show up here even before anyone adds it to
    TEMPLATE_CONTRACTS, since this scans get_template() call sites directly."""
    referenced_names: set[str] = set()
    for path in AGENTS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_template"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                referenced_names.add(node.args[0].value)

    assert referenced_names == set(TEMPLATE_CONTRACTS)

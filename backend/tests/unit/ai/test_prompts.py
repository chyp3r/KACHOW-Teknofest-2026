import os
import pytest

from app.ai.prompts import PromptManager, get_prompt_manager


@pytest.fixture
def temp_templates_dir(tmp_path):
    """Fixture to create a temporary templates directory with some dummy prompts."""
    d = tmp_path / "templates"
    d.mkdir()
    
    # Write a test prompt
    p1 = d / "test_prompt.md"
    p1.write_text("Merhaba {{isim}}, bu bir test promptudur. Kod: { \"sabit_deger\": 123 }", encoding="utf-8")
    
    # Write another prompt
    p2 = d / "simple.md"
    p2.write_text("Basit bir şablon.", encoding="utf-8")
    
    return str(d)


def test_prompt_manager_initialization(temp_templates_dir):
    manager = PromptManager(templates_dir=temp_templates_dir)
    assert manager.templates_dir == temp_templates_dir


def test_prompt_manager_get_template(temp_templates_dir):
    manager = PromptManager(templates_dir=temp_templates_dir)
    
    # Retrieve template
    content = manager.get_template("test_prompt")
    assert "Merhaba {{isim}}" in content
    
    # Check caching
    assert "test_prompt.md" in manager._cache
    
    # Check retrieving with extension directly
    content_ext = manager.get_template("test_prompt.md")
    assert content_ext == content


def test_prompt_manager_file_not_found(temp_templates_dir):
    manager = PromptManager(templates_dir=temp_templates_dir)
    with pytest.raises(FileNotFoundError):
        manager.get_template("non_existent_prompt")


def test_prompt_manager_rendering(temp_templates_dir):
    manager = PromptManager(templates_dir=temp_templates_dir)
    
    # Render with placeholders
    # It should replace {{isim}} but preserve single curly braces like { "sabit_deger": 123 }
    rendered = manager.render("test_prompt", isim="Gökdeniz")
    
    assert "Merhaba Gökdeniz" in rendered
    assert "{ \"sabit_deger\": 123 }" in rendered
    assert "{{isim}}" not in rendered


def test_global_prompt_manager_exists():
    manager = get_prompt_manager()
    assert manager is not None
    assert isinstance(manager, PromptManager)
    # Check that it points to the correct directory inside the app package
    assert manager.templates_dir.endswith(os.path.join("app", "ai", "prompts", "templates"))
    # get_prompt_manager() is a process-wide singleton, not a fresh instance.
    assert get_prompt_manager() is manager

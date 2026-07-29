from app.ai.prompts.manager import PromptManager

# Global singleton instance of PromptManager
prompt_manager = PromptManager()

__all__ = ["PromptManager", "prompt_manager"]

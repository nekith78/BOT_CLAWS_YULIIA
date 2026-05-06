"""Intent layer.

Public entry points:
- `LLMProvider` Protocol + `get_llm(settings)` dispatcher.
- `ToolSpec`, `ParsedIntent` data types.
- `build_system_prompt(now_local, tz)` — system-prompt template.

Action registry and resolvers land in Tasks 6–7.
"""

from src.services.intent.llm import LLMProvider, get_llm
from src.services.intent.prompt import build_system_prompt
from src.services.intent.types import ParsedIntent, ToolSpec

__all__ = [
    "LLMProvider",
    "ParsedIntent",
    "ToolSpec",
    "build_system_prompt",
    "get_llm",
]

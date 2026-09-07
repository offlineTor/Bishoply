"""Evidence-backed, engine-independent chess knowledge extraction."""

from .context import CoachContext
from .knowledge import KNOWLEDGE_SCHEMA_VERSION, analyze_position

__all__ = ["KNOWLEDGE_SCHEMA_VERSION", "CoachContext", "analyze_position"]

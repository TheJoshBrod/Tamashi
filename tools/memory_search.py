from core.config import settings
from core.context import session_id_var
from tools.registry import tool


@tool
def search_memory(query: str) -> str:
    """Search long-term memory for facts relevant to a query. Use this when you need context about the user that may not be in the recent conversation — their preferences, history, goals, or anything discussed in earlier sessions."""
    if not settings.long_term_memory_enabled:
        return "Long-term memory is disabled."

    session_id = session_id_var.get(None)
    if not session_id:
        return "No active session — cannot search memory."

    try:
        from memory import bridge
        result = bridge.retrieve_context(session_id, query=query)
        return result if result else "No relevant memories found."
    except Exception as exc:
        return f"Memory search failed: {exc}"

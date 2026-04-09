import contextvars

# Global context var set at the start of every request by the core orchestrator.
# This allows decoupled systems (like subagents) to instantly know which user session is active.
session_id_var = contextvars.ContextVar("session_id", default=None)

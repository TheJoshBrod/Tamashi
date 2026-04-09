from __future__ import annotations

import tools  # noqa: F401 — triggers @tool decorator discovery
import subagents  # triggers define_subagent discovery

from fastapi import FastAPI
from core.config import settings
from core.orchestrator import Orchestrator
from providers.litellm_provider import LiteLLMProvider
from sessions.sqlite_store import SQLiteSessionStore

# --- Wire up components ---
_store = SQLiteSessionStore(db_path=settings.db_path)
_provider = LiteLLMProvider(model=settings.model, temperature=settings.temperature)
orchestrator = Orchestrator(provider=_provider, store=_store)

# --- FastAPI app ---
app = FastAPI(title="phone-claw", version="0.1.0")

from interfaces.twilio_whatsapp import router as twilio_router  # noqa: E402
app.include_router(twilio_router)


@app.get("/health")
def health() -> dict:
    from tools.registry import registry
    return {
        "status": "ok",
        "model": settings.model,
        "tools_registered": len(registry),
        "debug": settings.debug,
    }

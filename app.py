from __future__ import annotations

import asyncio
import tools  # noqa: F401 — triggers @tool decorator discovery
import subagents  # triggers define_subagent discovery
import display.emotion_manager  # noqa: F401 — instantiates EmotionManager singleton

from fastapi import FastAPI
from core.config import settings
from core.events import event_bus
from core.orchestrator import Orchestrator
from providers.litellm_provider import LiteLLMProvider
from sessions.sqlite_store import SQLiteSessionStore

# --- Wire up components ---
store = SQLiteSessionStore(db_path=settings.db_path)
_provider = LiteLLMProvider(model=settings.model, temperature=settings.temperature)
orchestrator = Orchestrator(provider=_provider, store=store)

# --- FastAPI app ---
app = FastAPI(title="Tamashi", version="0.1.0")

from interfaces.twilio_whatsapp import router as twilio_router  # noqa: E402
from display.router import router as display_router  # noqa: E402
app.include_router(twilio_router)
app.include_router(display_router)


@app.on_event("startup")
async def startup_event():
    event_bus.set_main_loop(asyncio.get_running_loop())
    from display.websocket import manager
    manager.start_heartbeat()

    # Phase 3: nightly linker — draws RelatesTo edges between similar Facts
    if settings.long_term_memory_enabled:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from memory.linker import run_linker
            scheduler = AsyncIOScheduler()
            scheduler.add_job(run_linker, "cron", hour=3, minute=0)
            scheduler.start()
            app.state.scheduler = scheduler
        except ImportError:
            pass  # apscheduler not installed — linker disabled, retrieval still works


@app.on_event("shutdown")
async def shutdown_event():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)


@app.get("/health")
def health() -> dict:
    from tools.registry import registry
    return {
        "status": "ok",
        "model": settings.model,
        "tools_registered": len(registry),
        "debug": settings.debug,
    }

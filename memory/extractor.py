"""LiteLLM-based fact extraction from conversation message batches.

Uses structured JSON output (no Jac by llm() / mtllm dependency).
Phase 4 can optionally migrate this to a Jac walker using `by llm;`.
"""
from __future__ import annotations

import json
import logging

import litellm

from core.config import settings

log = logging.getLogger(__name__)

_PROMPT = """\
Extract 0-5 key facts from the conversation messages below.
A fact is worth keeping if it would still be useful weeks from now:
names, preferences, goals, health metrics, appointments, decisions, relationships.
Skip small talk, greetings, and anything ephemeral.

Return ONLY valid JSON in this exact shape — no markdown, no explanation:
{{"facts": [{{"content": "...", "topic": "health|goals|personal|nutrition|other"}}]}}

Messages:
{messages}"""


def extract_facts(messages: list[dict], source_msg_id: int) -> list[dict]:
    """Extract facts from a batch of messages.

    Args:
        messages:       list of {"role": str, "content": str | None}
        source_msg_id:  the SQLite messages.id of the latest message in the batch

    Returns:
        list of {"content": str, "topic": str, "source_msg_id": int}
        ready to pass directly to bridge.ingest_facts().
    """
    text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m.get("content")
    )
    if not text.strip():
        return []

    try:
        resp = litellm.completion(
            model=settings.extraction_model,
            messages=[{"role": "user", "content": _PROMPT.format(messages=text)}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
        facts = raw.get("facts", [])
        for f in facts:
            f["source_msg_id"] = source_msg_id
        return facts
    except Exception:
        log.exception("fact extraction failed")
        return []

"""Scheduled macro-pattern synthesis ("Dreaming" / REM Sleep).

Periodically looks across each user's recently active Subjects, identifies
emerging macro-themes, and spawns new Concept/Goal Subjects that tie local
nodes together via Relates edges.

Architecture:
  - `reflection_loop()` runs as a background asyncio task (started in app.py).
  - Per user: queries SQLite for the top N subjects updated in the last K days,
    injects existing concept/goal vocab, calls an LLM, then ingests spawned concepts.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import litellm

from core.config import settings
from core.events import event_bus

log = logging.getLogger(__name__)

_REFLECTION_SYSTEM = """\
You are a macro-pattern analyzer for a personal memory graph. \
Given the most recently active memory subjects, identify 1-3 broad themes or \
goals that emerge across them. Spawn new Concept or Goal subjects to tie local \
nodes together. Reuse an existing concept/goal name exactly when it already \
captures the theme — only invent new names when no existing one fits."""


def _build_reflection_prompt(subjects: list[dict], vocabulary: list[dict]) -> str:
    lines = [f"Recently active subjects (last {settings.reflection_window_days} days):"]
    for s in subjects:
        summary = s.get("summary", "").strip()
        lines.append(f"  - {s['name']} [{s['subject_type']}]: {summary}")

    if vocabulary:
        lines += ["", "Existing concept/goal subjects (reuse these names when applicable):"]
        for v in vocabulary:
            lines.append(f"  - {v['name']}: {v.get('summary', '')}")

    allowed = ", ".join(settings.allowed_relation_kinds)
    lines += [
        "",
        f"Allowed relation kinds: {allowed}",
        "",
        "Return ONLY valid JSON — no markdown, no explanation:",
        """{
  "concepts": [
    {
      "name": "string (theme name, reuse existing when applicable)",
      "subject_type": "concept | goal",
      "summary": "string (<=200 chars, why this theme matters)",
      "description": "string (detailed explanation of the macro pattern)",
      "relates_to": [{"target": "active-subject-name", "kind": "one-of-allowed"}]
    }
  ]
}""",
    ]
    return "\n".join(lines)


def _call_reflection_llm(prompt: str) -> dict | None:
    try:
        resp = litellm.completion(
            model=settings.rewriter_model,
            messages=[
                {"role": "system", "content": _REFLECTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        log.exception("reflection LLM call failed")
        return None


async def reflect_for_user(user_id: str) -> None:
    """Run one reflection cycle for a single user."""
    from memory import bridge
    from memory.store import subject_store

    since = datetime.now(timezone.utc) - timedelta(days=settings.reflection_window_days)
    active_subjects = subject_store.get_recently_active(
        user_id, since=since, limit=settings.reflection_subject_limit
    )

    if len(active_subjects) < 3:
        return

    all_text = " ".join(s["name"] + " " + s.get("summary", "") for s in active_subjects)
    vocabulary = await asyncio.to_thread(bridge.lookup_vocabulary, user_id, all_text, k=10)
    concept_vocab = [v for v in vocabulary if v.get("subject_type") in ("concept", "goal")]

    prompt = _build_reflection_prompt(active_subjects, concept_vocab)
    result = await asyncio.to_thread(_call_reflection_llm, prompt)
    if not result:
        return

    concepts = result.get("concepts", [])
    if not concepts:
        return

    allowed_kinds = set(settings.allowed_relation_kinds)
    valid_subject_names = {s["name"] for s in active_subjects}

    subjects_to_ingest: list[dict] = []
    relations_to_ingest: list[dict] = []

    for c in concepts:
        name = str(c.get("name", "")).strip()
        subject_type = str(c.get("subject_type", "concept")).strip()
        summary = str(c.get("summary", "")).strip()
        description = str(c.get("description", "")).strip()

        if not name or not summary:
            continue
        if subject_type not in ("concept", "goal"):
            subject_type = "concept"

        subjects_to_ingest.append({
            "name": name,
            "summary": summary,
            "description_delta": description,
            "subject_type": subject_type,
        })

        for rel in c.get("relates_to", []):
            target = str(rel.get("target", "")).strip()
            kind = str(rel.get("kind", "")).strip()
            if target in valid_subject_names and kind in allowed_kinds:
                relations_to_ingest.append({
                    "source": name,
                    "kind": kind,
                    "target": target,
                    "weight": 0.7,
                })

    if subjects_to_ingest or relations_to_ingest:
        await asyncio.to_thread(
            bridge.ingest_subjects, user_id, subjects_to_ingest, relations_to_ingest
        )
        event_bus.emit({
            "event": "MEMORY_REFLECTED",
            "user_id": user_id,
            "concepts_spawned": len(subjects_to_ingest),
            "relations_spawned": len(relations_to_ingest),
        })
        log.info(
            "reflection spawned %d concepts, %d relations for %s",
            len(subjects_to_ingest), len(relations_to_ingest), user_id,
        )


async def reflection_loop() -> None:
    """Background loop: runs macro-pattern synthesis for all users periodically."""
    while True:
        await asyncio.sleep(settings.reflection_interval_seconds)
        if not settings.reflection_enabled:
            continue
        try:
            from memory.store import subject_store
            users = subject_store.list_users()
            for user_id in users:
                try:
                    await reflect_for_user(user_id)
                except Exception:
                    log.exception("reflection failed for user %s", user_id)
        except Exception:
            log.exception("reflection loop error")

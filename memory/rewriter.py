"""WAL-triggered Subject rewriter.

Triggered fire-and-forget after each consolidation turn when a Subject's
recent_events WAL reaches subject_wal_threshold.  For each dirty Subject:
  1. Load context (Jac graph + vector search)
  2. LLM synthesises new summary/description and proposes edge mutations
  3. Apply mutations through all three layers (Jac, SQLite, Qdrant)
  4. Emit MEMORY_REWRITTEN event

Concurrency:
  - Per-subject asyncio.Lock prevents double-rewrite when rapid messages
    push the same Subject past the threshold twice.
  - Module-level asyncio.Semaphore caps parallel LLM calls.
"""
from __future__ import annotations

import asyncio
import json
import logging

import litellm

from core.config import settings
from core.events import event_bus

log = logging.getLogger(__name__)

_rewrite_locks: dict[tuple[str, str], asyncio.Lock] = {}
_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.rewriter_max_concurrent)
    return _llm_semaphore


_REWRITE_SYSTEM = """\
You are a memory maintainer. Rewrite the Subject's summary and description \
to incorporate new facts from the pending log, overriding outdated information. \
Suggest edges to existing Subjects provided in the context. \
You must reuse neighbor names exactly as provided."""


def _build_prompt(subject: dict, neighbors: list[dict], semantic_nbrs: list[dict]) -> str:
    lines = [
        f"Subject: {subject['name']} [{subject['subject_type']}]",
        f"Current summary: {subject['summary']}",
        f"Current description: {subject['description']}",
        "",
        "Pending facts (recent_events WAL):",
    ]
    for event in subject.get("recent_events", []):
        lines.append(f"  - {event}")

    lines += ["", "Current 1-hop neighbors:"]
    for n in neighbors:
        kind = n.get("edge_kind", "related_to")
        lines.append(f"  - {n['name']} [{kind}]: {n.get('summary', '')}")

    lines += ["", "Semantic neighbors (not yet linked):"]
    for n in semantic_nbrs:
        lines.append(f"  - {n['name']} [{n.get('subject_type', 'other')}]: {n.get('summary', '')}")

    allowed = ", ".join(settings.allowed_relation_kinds)
    lines += [
        "",
        f"Allowed relation kinds: {allowed}",
        "",
        "Return ONLY valid JSON — no markdown, no explanation:",
        """{
  "summary": "string (<=200 chars, stable identity blurb)",
  "description": "string (rewritten, integrates new facts, drops stale ones)",
  "add_edges": [{"target": "existing-name", "kind": "one-of-allowed", "confidence": 0.0-1.0}],
  "remove_edges": [{"target": "existing-name", "kind": "one-of-allowed"}]
}""",
        "",
        "confidence is your certainty (0.0=uncertain, 1.0=definite) that the edge is accurate and lasting.",
    ]
    return "\n".join(lines)


def _call_llm(prompt: str) -> dict | None:
    try:
        resp = litellm.completion(
            model=settings.rewriter_model,
            messages=[
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        log.exception("rewriter LLM call failed")
        return None


def _validate_rewrite(raw: dict, valid_targets: set[str]) -> dict | None:
    summary = raw.get("summary", "").strip()
    description = raw.get("description", "").strip()
    if not summary or not description:
        log.warning("rewrite validation failed: missing summary or description")
        return None

    allowed_kinds = set(settings.allowed_relation_kinds)

    add_edges = []
    for e in raw.get("add_edges", []):
        if not isinstance(e, dict):
            continue
        target = e.get("target", "").strip()
        kind = e.get("kind", "").strip()
        if target in valid_targets and kind in allowed_kinds:
            raw_confidence = e.get("confidence", 1.0)
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                confidence = 1.0
            weight = max(0.0, min(1.0, confidence))
            add_edges.append({"target": target, "kind": kind, "weight": weight})
        else:
            log.debug("rewrite: dropping add_edge %r/%r (invalid target or kind)", target, kind)

    remove_edges = []
    for e in raw.get("remove_edges", []):
        if not isinstance(e, dict):
            continue
        target = e.get("target", "").strip()
        kind = e.get("kind", "").strip()
        if target in valid_targets and kind in allowed_kinds:
            remove_edges.append({"target": target, "kind": kind})
        else:
            log.debug("rewrite: dropping remove_edge %r/%r (invalid target or kind)", target, kind)

    return {
        "summary": summary,
        "description": description,
        "add_edges": add_edges,
        "remove_edges": remove_edges,
    }


async def rewrite_subject(user_id: str, name: str) -> None:
    """Rewrite a Subject whose WAL crossed the threshold.

    Fire-and-forget: called via asyncio.create_task. Does not raise.
    """
    lock_key = (user_id, name)
    if lock_key not in _rewrite_locks:
        _rewrite_locks[lock_key] = asyncio.Lock()
    lock = _rewrite_locks[lock_key]

    async with lock:
        try:
            from memory import bridge

            # 1. Load subject context (Jac graph)
            ctx = await asyncio.to_thread(bridge.get_subject_context, user_id, name)
            if not ctx:
                log.debug("rewrite: subject %r not found for %s", name, user_id)
                return

            subject = ctx["subject"]
            neighbors = ctx["neighbors"]

            if not subject.get("recent_events"):
                log.debug("rewrite: subject %r WAL already cleared for %s", name, user_id)
                return

            # 2. Semantic neighbors from Qdrant (unlinked candidates for new edges)
            semantic_nbrs: list[dict] = []
            linked_names = {n["name"] for n in neighbors} | {name}
            try:
                from memory.vector import vector_store
                results = await asyncio.to_thread(
                    vector_store.search_with_payload,
                    user_id,
                    subject["summary"] or subject["name"],
                    k=settings.rewriter_neighbor_k,
                )
                for r in results:
                    p = r.get("payload", {})
                    nbr_name = p.get("name", "")
                    if nbr_name and nbr_name not in linked_names:
                        semantic_nbrs.append({
                            "name": nbr_name,
                            "summary": p.get("summary", ""),
                            "subject_type": p.get("subject_type", "other"),
                        })
            except Exception:
                log.debug("rewrite: semantic neighbor search failed for %r", name)

            # 3. Build the set of valid edge targets for validation
            all_neighbor_names = {n["name"] for n in neighbors} | {n["name"] for n in semantic_nbrs}

            # 4. LLM synthesis (under global concurrency semaphore)
            prompt = _build_prompt(subject, neighbors, semantic_nbrs)
            async with _get_semaphore():
                raw_result = await asyncio.to_thread(_call_llm, prompt)

            if not raw_result:
                return

            rewrite = _validate_rewrite(raw_result, all_neighbor_names)
            if not rewrite:
                return

            # 5. Apply mutations (Jac + SQLite + Qdrant)
            await asyncio.to_thread(
                bridge.apply_rewrite,
                user_id, name,
                rewrite["summary"], rewrite["description"],
                rewrite["add_edges"], rewrite["remove_edges"],
            )

            # 6. Emit success event
            event_bus.emit({
                "event": "MEMORY_REWRITTEN",
                "session_id": user_id,
                "name": name,
                "edges_added": len(rewrite["add_edges"]),
                "edges_removed": len(rewrite["remove_edges"]),
            })
            log.info("rewrote subject %r for %s", name, user_id)

        except Exception:
            event_bus.emit({
                "event": "MEMORY_REWRITE_FAILED",
                "session_id": user_id,
                "name": name,
            })
            log.exception("rewrite failed for subject %r user %s", name, user_id)

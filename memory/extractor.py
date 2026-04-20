"""LiteLLM-based subject/relation extraction from conversation message batches.

Uses structured JSON output (no Jac by llm() / mtllm dependency).
Replaces the old fact extractor with an entity-centric extraction pipeline.
"""
from __future__ import annotations

import json
import logging

import litellm

from core.config import settings

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a memory extraction assistant. Extract entities (subjects) and their \
relationships from a conversation. Focus on durable information: people, pets, \
places, goals, preferences, health details, recurring events, and named objects.
Skip small talk, greetings, and anything ephemeral."""

_PROMPT = """\
{vocab_block}\
Extract subjects and relations from the conversation below.

Rules:
- Reuse a name from the vocabulary above if it matches — do not create a \
duplicate with a different spelling.
- For subjects already in the vocabulary, provide ONLY "name" and \
"description_delta" (skip "summary" and "subject_type").
- For NEW subjects not in the vocabulary, also provide "summary" (~200 chars, \
stable identity blurb) and "subject_type".
- subject_type must be one of: person, concept, goal, event, object, place, other
- relation "kind" must be one of: {allowed_kinds}
- description_delta should be a concise statement of new information learned \
in THIS conversation batch.
- Omit subjects and relations if there is nothing meaningful to extract.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "subjects": [
    {{
      "name": "string",
      "description_delta": "string",
      "summary": "string (new subjects only)",
      "subject_type": "string (new subjects only)"
    }}
  ],
  "relations": [
    {{"source": "string", "kind": "string", "target": "string"}}
  ]
}}

Conversation:
{messages}"""


def _strip_json_fences(text: str) -> str:
    """Some providers (Anthropic via litellm+json_object) wrap JSON in
    ```json ... ``` fences even when asked for raw JSON. Strip them before
    json.loads so the parse does not silently fail."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _build_vocab_block(vocabulary: list[dict]) -> str:
    if not vocabulary:
        return ""
    lines = ["Existing subjects (reuse these names if they match):"]
    for v in vocabulary:
        lines.append(f"- {v['name']} [{v.get('subject_type', 'other')}]: {v.get('summary', '')}")
    return "\n".join(lines) + "\n\n"


def extract_subjects(messages: list[dict], vocabulary: list[dict]) -> dict:
    """Extract subjects and relations from a batch of conversation messages.

    Args:
        messages:   list of {"role": str, "content": str | None}
        vocabulary: list of existing subjects from vector search, each with
                    {name, summary, subject_type} — injected as extraction hints

    Returns:
        {"subjects": [...], "relations": [...]}
        subjects: [{name, description_delta, summary?, subject_type?}]
        relations: [{source, kind, target}]
    """
    text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m.get("content")
    )
    if not text.strip():
        return {"subjects": [], "relations": []}

    vocab_block = _build_vocab_block(vocabulary)
    allowed_kinds = ", ".join(settings.allowed_relation_kinds)
    prompt = _PROMPT.format(
        vocab_block=vocab_block,
        allowed_kinds=allowed_kinds,
        messages=text,
    )

    try:
        resp = litellm.completion(
            model=settings.extraction_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(_strip_json_fences(resp.choices[0].message.content))
    except Exception:
        log.exception("subject extraction failed")
        return {"subjects": [], "relations": []}

    subjects = _validate_subjects(raw.get("subjects", []))
    relations = _validate_relations(raw.get("relations", []))
    return {"subjects": subjects, "relations": relations}


def _validate_subjects(subjects: list) -> list[dict]:
    valid = []
    for s in subjects:
        if not isinstance(s, dict):
            continue
        name = s.get("name", "").strip()
        delta = s.get("description_delta", "").strip()
        if not name or not delta:
            continue
        valid.append({
            "name": name,
            "description_delta": delta,
            "summary": s.get("summary", "").strip(),
            "subject_type": s.get("subject_type", "other").strip() or "other",
        })
    return valid


def _validate_relations(relations: list) -> list[dict]:
    allowed = set(settings.allowed_relation_kinds)
    valid = []
    for r in relations:
        if not isinstance(r, dict):
            continue
        src = r.get("source", "").strip()
        tgt = r.get("target", "").strip()
        kind = r.get("kind", "").strip()
        if not src or not tgt or kind not in allowed:
            continue
        valid.append({"source": src, "kind": kind, "target": tgt})
    return valid

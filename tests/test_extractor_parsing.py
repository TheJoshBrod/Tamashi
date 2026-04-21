"""Regression gate for the shared JSON fence stripper.

Anthropic via litellm returns markdown-fenced JSON even when
`response_format={"type":"json_object"}` is requested. Without a fence
strip, json.loads raises, the caller swallows the exception, and every
LLM call silently returns empty — the extractor, rewriter, and reflector
all route through this one helper.
"""
from __future__ import annotations

from memory.rewriter import _strip_json_fences


def test_strip_json_fences_language_tag():
    assert _strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fences_no_language_tag():
    assert _strip_json_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fences_raw_passes_through():
    assert _strip_json_fences('{"a": 1}') == '{"a": 1}'


def test_strip_json_fences_trims_surrounding_whitespace():
    assert _strip_json_fences('  ```json\n{"a": 1}\n```  ') == '{"a": 1}'

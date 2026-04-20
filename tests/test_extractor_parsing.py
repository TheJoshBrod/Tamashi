"""Regression gate for memory.extractor._strip_json_fences.

Anthropic via litellm returns markdown-fenced JSON even when
`response_format={"type":"json_object"}` is requested. Without a fence
strip, json.loads raises, the extractor swallows the exception, and every
extraction silently returns {"subjects": [], "relations": []}.

These tests run in the default suite so a regression is caught before
someone notices the RUN_EVAL=1 baseline going to zero.
"""
from __future__ import annotations

from memory.extractor import _strip_json_fences


def test_strip_json_fences_language_tag():
    assert _strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fences_no_language_tag():
    assert _strip_json_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fences_raw_passes_through():
    assert _strip_json_fences('{"a": 1}') == '{"a": 1}'


def test_strip_json_fences_trims_surrounding_whitespace():
    assert _strip_json_fences('  ```json\n{"a": 1}\n```  ') == '{"a": 1}'

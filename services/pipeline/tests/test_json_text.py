# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tolerant JSON extraction — the belt to JSON mode's suspenders.

Every one of these shapes is something a real model actually emits despite being
asked for JSON. Before this, each was a crashed stage AFTER the grounded calls
were already paid for.
"""

from __future__ import annotations

import pytest

from app.pipeline.json_text import JsonExtractionError, extract_json


def test_clean_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fenced_without_language_tag():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_prose_around_the_object():
    text = 'Sure! Here is the JSON you asked for:\n{"a": 1}\nLet me know if that helps.'
    assert extract_json(text) == {"a": 1}


def test_nested_braces_survive_outermost_extraction():
    text = 'Here:\n{"a": {"b": [1, 2]}, "c": "}"}\n'
    assert extract_json(text) == {"a": {"b": [1, 2]}, "c": "}"}


def test_top_level_array():
    assert extract_json("```json\n[1, 2]\n```") == [1, 2]


def test_empty_response_raises():
    with pytest.raises(JsonExtractionError, match="empty"):
        extract_json("   ")


def test_junk_raises_loudly_rather_than_guessing():
    # A model that returns prose with no JSON must fail, not be repaired.
    with pytest.raises(JsonExtractionError, match="no parseable JSON"):
        extract_json("I'm sorry, I can't help with that.")

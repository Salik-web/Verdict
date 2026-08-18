# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tolerant JSON extraction from model output.

Every task whose output we parse asks the provider for JSON mode
(`json_output: true`), but that's a request, not a guarantee: providers ignore it,
don't support it, or wrap the object in ```json fences or a "Here's the JSON:"
preamble. A strict `json.loads(res.text)` turns any of that into a crashed stage —
and on a real run that crash lands AFTER the expensive grounded calls are already
paid for. So JSON mode is the suspenders and this is the belt.

Deliberately narrow: strip fences, else take the outermost {...} / [...]. It does
not try to repair malformed JSON — a model that returns junk should fail loudly,
not have its output guessed at.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ```json { ... } ```  /  ``` { ... } ```
_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.DOTALL)


class JsonExtractionError(ValueError):
    """Model output contained no parseable JSON."""


def _outermost(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def extract_json(text: str) -> Any:
    """Parse JSON out of a model response. Raises JsonExtractionError if absent."""
    if text is None or not text.strip():
        raise JsonExtractionError("model returned an empty response")

    candidate = text.strip()

    # 1. Clean JSON (what JSON mode should give us).
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 2. Fenced code block.
    fenced = _FENCE.match(candidate)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            candidate = fenced.group(1).strip()

    # 3. Prose around an object/array — take the outermost braces/brackets.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        chunk = _outermost(candidate, open_ch, close_ch)
        if chunk is not None:
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue

    raise JsonExtractionError(
        "no parseable JSON in model response (first 300 chars): "
        f"{text.strip()[:300]!r}"
    )

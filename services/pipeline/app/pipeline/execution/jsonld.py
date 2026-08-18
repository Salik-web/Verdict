# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Structural validation for generated schema.org JSON-LD.

The generator emits FAQPage JSON-LD that we render to a visible FAQ AND embed as
structured data. A malformed key silently costs a search feature — the model once
emitted `"@iga"` instead of `"acceptedAnswer"`, so that entry had no answer, was
dropped from the visible FAQ, and would be invalid to a search crawler, with no
error anywhere. This validates the shape before the asset can pass, turning that
silent drop into an explicit violation.

Returns a list of human-readable violations (empty = valid). Shape checked is the
schema.org FAQPage contract:
  - @context includes schema.org, @type == FAQPage
  - mainEntity is a non-empty list
  - each entry: @type == Question, non-empty name,
    acceptedAnswer is an object with @type == Answer and non-empty text
"""

from __future__ import annotations

from typing import Any


def validate_faqpage(jsonld: dict[str, Any] | None) -> list[str]:
    if jsonld is None:
        return []  # no structured data is allowed; only MALFORMED data is a fault

    violations: list[str] = []

    context = jsonld.get("@context", "")
    if "schema.org" not in str(context):
        violations.append(f"json-ld @context is not schema.org: {context!r}")
    if jsonld.get("@type") != "FAQPage":
        violations.append(f"json-ld @type is not FAQPage: {jsonld.get('@type')!r}")

    entities = jsonld.get("mainEntity")
    if not isinstance(entities, list) or not entities:
        violations.append("json-ld mainEntity is missing or empty")
        return violations

    for i, entry in enumerate(entities):
        where = f"mainEntity[{i}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} is not an object")
            continue
        if entry.get("@type") != "Question":
            violations.append(f"{where}.@type is not Question: {entry.get('@type')!r}")
        if not str(entry.get("name") or "").strip():
            violations.append(f"{where}.name is empty")

        answer = entry.get("acceptedAnswer")
        if not isinstance(answer, dict):
            # This is the "@iga" bug: the answer landed under a wrong/misspelled
            # key, so acceptedAnswer is absent. Name the actual keys to make it
            # obvious what the generator emitted instead.
            keys = sorted(k for k in entry if k not in ("@type", "name"))
            violations.append(
                f"{where}.acceptedAnswer is missing or not an object "
                f"(entry keys: {keys})"
            )
            continue
        if answer.get("@type") != "Answer":
            violations.append(
                f"{where}.acceptedAnswer.@type is not Answer: {answer.get('@type')!r}"
            )
        if not str(answer.get("text") or "").strip():
            violations.append(f"{where}.acceptedAnswer.text is empty")

    return violations

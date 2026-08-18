# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Entity resolution for share of voice: fold surface forms onto one brand.

Audit finding #4. The old canonicalizer matched a brand string against tracked
names by exact lowercase equality and nothing else, so one company could occupy
several rows and split its own share:

    'Synthesia'   vs 'Synthesia '        (a trailing space)
    'InVideo AI'  vs 'Invideo AI'        (casing)
    'ChatGPT'     vs 'ChatGPT Plus' vs 'ChatGPT (GPT-5.2)'
    'runway'      vs 'Runway Gen-4.5'
    'HiggsField'  vs 'Higgsfield AI'     <- the one that actually lies

The last is not cosmetic. HiggsField is a TRACKED competitor: it was reported at
0% ("measured, genuinely absent") while 'Higgsfield AI' sat in the same table at
2.08% as an untracked brand. We told a customer their competitor wasn't mentioned
when it demonstrably was.

The rules, in order, and deliberately conservative — an over-eager merge invents a
relationship between two real companies, which is worse than a split row:

1. NORMALISE: strip, collapse whitespace, casefold, drop a trailing parenthetical
   ("ChatGPT (GPT-5.2)" -> "chatgpt"), drop trailing punctuation. Nothing here can
   merge two different brands; it only undoes typography.
2. TRACKED: a surface form folds into a tracked brand when its normalised value
   equals that brand's name or an alias, OR equals it plus a tail made ENTIRELY of
   variant tokens ("higgsfield ai" -> HiggsField, "runway gen-4.5" -> runway).
3. FAMILY: among DISCOVERED brands, a longer form folds into a shorter one only
   when the shorter form was itself observed in this scan and the tail is again
   entirely variant tokens. So "ChatGPT Plus" folds into "ChatGPT" because the
   engine also said "ChatGPT" — but if it never had, "ChatGPT Plus" stays its own
   entity rather than being invented into a parent nobody named.

Anything else stays separate. Every fold is recorded, so a merged row can show
which surface forms it came from instead of asking anyone to trust this file.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from app.pipeline.contracts import ScanContext

# Tokens that qualify a product rather than name a different one. A tail made
# only of these is a variant of the base ("Pro", "2.6", "Gen-4.5", "AI"). Kept
# short and boring on purpose: every addition here is a licence to merge.
_QUALIFIERS = {
    "ai",
    "inc",
    "inc.",
    "llc",
    "ltd",
    "labs",
    "lab",
    "app",
    "io",
    "com",
    "studio",
    "platform",
    "pro",
    "plus",
    "premium",
    "xl",
    "lite",
    "turbo",
    "max",
    "ultra",
    "beta",
    "preview",
    "edition",
}
# Version-ish tokens: "3", "2.6", "v2", "gen-4.5", "4o".
_VERSION_RE = re.compile(r"^(v|gen[-\s]?)?\d+(\.\d+)*[a-z]?$")
# A trailing parenthetical is an aside about the SAME product, never a new brand:
# "Magnific (formerly Freepik)", "Dreamina (ByteDance / CapCut)".
_TRAILING_PAREN_RE = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*$")


def normalize(name: str) -> str:
    """Typography only — this must never be able to merge two distinct brands."""
    text = unicodedata.normalize("NFKC", name or "")
    text = _TRAILING_PAREN_RE.sub("", text)
    text = text.replace("‑", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip().strip(".,;:-–— ")
    return text.casefold()


def _is_variant_token(token: str) -> bool:
    return token in _QUALIFIERS or bool(_VERSION_RE.match(token))


def _bases(key: str) -> list[str]:
    """Word-prefixes of `key` whose dropped tail is entirely variant tokens.

    "chatgpt plus"   -> ["chatgpt"]
    "runway gen-4.5" -> ["runway"]
    "adobe firefly"  -> []            (Firefly is not a qualifier of Adobe)
    Longest first, so the most specific parent wins.
    """
    words = key.split(" ")
    out: list[str] = []
    for cut in range(len(words) - 1, 0, -1):
        if all(_is_variant_token(w) for w in words[cut:]):
            out.append(" ".join(words[:cut]))
    return out


@dataclass
class Resolution:
    """The canonical name for every surface form seen, plus how we got there."""

    canonical: dict[str, str] = field(default_factory=dict)  # surface -> display
    merged_from: dict[str, list[str]] = field(default_factory=dict)  # display -> forms
    tracked: dict[str, bool] = field(default_factory=dict)  # display -> is tracked

    def __call__(self, brand: str) -> str:
        return self.canonical.get(brand, brand)


def _tracked_keys(context: ScanContext) -> dict[str, str]:
    """normalised name/alias -> the registered display name."""
    keys: dict[str, str] = {}
    for comp in context.competitors:
        for term in [comp.name, *(comp.aliases or [])]:
            if term and term.strip():
                keys[normalize(term)] = comp.name
    # The target brand wins over a competitor row that duplicates it.
    for term in [context.brand_name, *context.brand_aliases]:
        if term and term.strip():
            keys[normalize(term)] = context.brand_name
    return keys


def resolve_entities(context: ScanContext, surfaces: list[str]) -> Resolution:
    """Build the surface-form -> canonical-brand map for one scan."""
    tracked = _tracked_keys(context)

    # Step 1+2: normalise, then bind to a tracked brand where we can.
    key_of: dict[str, str] = {}  # surface -> normalised key
    bound: dict[str, str] = {}  # normalised key -> tracked display name
    for surface in surfaces:
        key = normalize(surface)
        if not key:
            continue
        key_of[surface] = key
        if key in tracked:
            bound[key] = tracked[key]
            continue
        for base in _bases(key):
            if base in tracked:
                bound[key] = tracked[base]
                break

    # Step 3: fold discovered variants onto a discovered parent that was actually
    # observed. Resolve transitively ("chatgpt plus" -> "chatgpt") but never onto a
    # parent nobody named.
    observed = set(key_of.values())
    parent: dict[str, str] = {}
    for key in observed:
        if key in bound:
            continue
        for base in _bases(key):
            if base in observed and base != key:
                parent[key] = base
                break

    def root(key: str) -> str:
        seen = {key}
        while key in parent and parent[key] not in seen:
            key = parent[key]
            seen.add(key)
        return key

    # Display name per group: the tracked registration if there is one, else the
    # most common surface form (ties broken shortest-then-alphabetical, so the
    # result never depends on dict ordering).
    groups: dict[str, list[str]] = defaultdict(list)
    for surface, key in key_of.items():
        groups[bound.get(key) or bound.get(root(key)) or root(key)].append(surface)

    counts: dict[str, int] = defaultdict(int)
    for surface in surfaces:
        counts[surface] += 1

    resolution = Resolution()
    for group_key, forms in groups.items():
        is_tracked = group_key in set(tracked.values())
        display = (
            group_key
            if is_tracked
            else min(set(forms), key=lambda f: (-counts[f], len(f), f))
        )
        distinct = sorted(set(forms))
        for surface in distinct:
            resolution.canonical[surface] = display
        resolution.tracked[display] = is_tracked
        if len(distinct) > 1 or (is_tracked and distinct != [display]):
            resolution.merged_from[display] = distinct
    return resolution

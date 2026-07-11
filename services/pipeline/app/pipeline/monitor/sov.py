"""Share-of-voice computation.

Smoothed across the repeated runs (never computed live). Definitions, per brand,
within an engine group (and an 'all' cross-engine roll-up):

  observations  = number of (prompt, run) answers in the group
  mention_count = answers in which the brand appeared
  mention_rate  = mention_count / observations          (visibility, 0..1)
  sov_pct       = mention_count / total_brand_mentions * 100   (share of voice)
  avg_position  = mean rank across answers where the brand appeared

The target brand and known competitors are resolved to competitor_id / is_self;
other detected brands still count toward share of voice with competitor_id=None.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from app.pipeline.contracts import ParsedMention, ScanContext, SoVRecord

EngineParse = tuple[str, ParsedMention]  # (engine, parsed answer)


@dataclass
class _BrandAgg:
    mention_count: int = 0
    positions: list[int] = field(default_factory=list)


def make_brand_resolver(context: ScanContext):
    """Map a brand string -> (competitor_id, is_self), case-insensitively."""
    lookup: dict[str, tuple[uuid.UUID | None, bool]] = {}
    for comp in context.competitors:
        for key in [comp.name, *comp.aliases]:
            lookup[key.lower()] = (comp.id, comp.is_self)
    focal_keys = {
        context.brand_name.lower(),
        *(a.lower() for a in context.brand_aliases),
    }

    def resolve(brand: str) -> tuple[uuid.UUID | None, bool]:
        hit = lookup.get(brand.lower())
        if hit is not None:
            return hit
        if brand.lower() in focal_keys:
            return (None, True)
        return (None, False)

    return resolve


def _aggregate(engine: str, parses: list[ParsedMention], resolve) -> list[SoVRecord]:
    observations = len(parses)
    brands: dict[str, _BrandAgg] = defaultdict(_BrandAgg)

    for p in parses:
        seen: dict[str, int | None] = {}
        if p.mentioned:
            seen[p.brand] = p.position
        for c in p.competitors:
            seen.setdefault(c.brand, c.position)
        for brand, position in seen.items():
            agg = brands[brand]
            agg.mention_count += 1
            if position is not None:
                agg.positions.append(position)

    total_mentions = sum(a.mention_count for a in brands.values())
    records: list[SoVRecord] = []
    for brand, agg in brands.items():
        competitor_id, is_self = resolve(brand)
        avg_position = (
            round(sum(agg.positions) / len(agg.positions), 4) if agg.positions else None
        )
        records.append(
            SoVRecord(
                brand=brand,
                competitor_id=competitor_id,
                is_self=is_self,
                engine=engine,
                mention_count=agg.mention_count,
                mention_rate=(
                    round(agg.mention_count / observations, 6) if observations else 0.0
                ),
                sov_pct=(
                    round(agg.mention_count / total_mentions * 100, 6)
                    if total_mentions
                    else 0.0
                ),
                avg_position=avg_position,
                details={"observations": observations},
            )
        )
    # Deterministic order: highest share first, then brand name.
    records.sort(key=lambda r: (-r.sov_pct, r.brand))
    return records


def compute_sov(context: ScanContext, parses: list[EngineParse]) -> list[SoVRecord]:
    resolve = make_brand_resolver(context)

    by_engine: dict[str, list[ParsedMention]] = defaultdict(list)
    for engine, parsed in parses:
        by_engine[engine].append(parsed)

    records: list[SoVRecord] = []
    for engine, engine_parses in by_engine.items():
        records.extend(_aggregate(engine, engine_parses, resolve))

    # Cross-engine roll-up (engine='all'). Identical to the per-engine row when
    # only one engine ran, but the structure supports many.
    all_parses = [p for _, p in parses]
    records.extend(_aggregate("all", all_parses, resolve))
    return records

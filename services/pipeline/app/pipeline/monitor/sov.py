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

Every tracked competitor (and the target) gets a row even when it was not
mentioned — a 0% row is a real finding ("measured, genuinely absent"), NOT the
same as no data. That baseline is only seeded when observations > 0, so a scan
that never measured produces no rows rather than a table of confident 0%s that
would read as "you're invisible". Each row carries details.tracked so a later UI
can tell a tracked competitor apart from a brand the engine surfaced that the
customer never told us about (competitor_id=None, tracked=false) — the "here are
competitors you didn't know you had" signal.
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


def make_canonicalizer(context: ScanContext):
    """Map any brand string to its canonical display name, so an alias or a
    case variant ("higgsfield") folds into the tracked entity's name and does not
    spawn a duplicate SoV row. Unknown brands keep their surface form."""
    canon: dict[str, str] = {}
    for comp in context.competitors:
        for key in [comp.name, *comp.aliases]:
            canon[key.lower()] = comp.name
    for key in [context.brand_name, *context.brand_aliases]:
        canon[key.lower()] = context.brand_name

    def canonical(brand: str) -> str:
        return canon.get(brand.lower(), brand)

    return canonical


def _tracked_names(context: ScanContext) -> list[str]:
    """Canonical names of every brand we're tracking: the target + competitors.
    These get a 0-baseline row so "measured, not mentioned" shows as 0%, not a
    missing row."""
    names = [context.brand_name]
    names.extend(c.name for c in context.competitors if not c.is_self)
    # De-dupe while preserving order (self may also be listed as a competitor).
    seen: set[str] = set()
    ordered: list[str] = []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            ordered.append(n)
    return ordered


def _aggregate(
    engine: str,
    parses: list[ParsedMention],
    resolve,
    canonical,
    tracked_names: list[str],
) -> list[SoVRecord]:
    observations = len(parses)
    brands: dict[str, _BrandAgg] = defaultdict(_BrandAgg)

    for p in parses:
        seen: dict[str, int | None] = {}
        if p.mentioned:
            seen[canonical(p.brand)] = p.position
        for c in p.competitors:
            seen.setdefault(canonical(c.brand), c.position)
        for brand, position in seen.items():
            agg = brands[brand]
            agg.mention_count += 1
            if position is not None:
                agg.positions.append(position)

    # Seed a 0-baseline for every tracked brand we actually measured — so a
    # tracked competitor that was genuinely never mentioned shows as 0%, not a
    # vanished row. Only when observations > 0: no measurement => no rows, never a
    # table of confident zeros for a failed/skipped scan.
    if observations > 0:
        for name in tracked_names:
            brands.setdefault(name, _BrandAgg())

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
                # tracked = we're deliberately measuring this brand (target or a
                # configured competitor). false = the engine surfaced it and we
                # weren't tracking it — the "competitor you didn't know you had".
                details={
                    "observations": observations,
                    "tracked": is_self or competitor_id is not None,
                },
            )
        )
    # Deterministic order: highest share first, then brand name.
    records.sort(key=lambda r: (-r.sov_pct, r.brand))
    return records


def compute_sov(context: ScanContext, parses: list[EngineParse]) -> list[SoVRecord]:
    resolve = make_brand_resolver(context)
    canonical = make_canonicalizer(context)
    tracked_names = _tracked_names(context)

    by_engine: dict[str, list[ParsedMention]] = defaultdict(list)
    for engine, parsed in parses:
        by_engine[engine].append(parsed)

    records: list[SoVRecord] = []
    for engine, engine_parses in by_engine.items():
        records.extend(
            _aggregate(engine, engine_parses, resolve, canonical, tracked_names)
        )

    # Cross-engine roll-up (engine='all'). Identical to the per-engine row when
    # only one engine ran, but the structure supports many.
    all_parses = [p for _, p in parses]
    records.extend(_aggregate("all", all_parses, resolve, canonical, tracked_names))
    return records

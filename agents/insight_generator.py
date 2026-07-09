"""
Insight Generator — aggregates the verified dataset and produces
structured insights: auth distribution, gating by category, easy wins, etc.
Pure Python computation — no LLM calls needed here.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from models.schema import AppRecord, InsightStats

logger = logging.getLogger(__name__)


def generate_insights(records: list[AppRecord]) -> InsightStats:
    """
    Compute dataset-level statistics and insights from all app records.

    Returns InsightStats with distributions, easy wins, and hard cases.
    """
    total = len(records)
    if total == 0:
        return InsightStats(
            total_apps=0,
            auth_distribution={},
            access_model_distribution={},
            api_type_distribution={},
            buildable_count=0,
            not_buildable_count=0,
            mcp_exists_count=0,
            category_summary={},
            top_blockers=[],
            easy_wins=[],
            hard_cases=[],
            avg_confidence=0.0,
        )

    # ── Enum value helper ────────────────────────────────────────────────────
    def _str(v) -> str:
        """Return the enum value string (e.g. 'OAuth2') not the repr ('AuthMethod.OAuth2')."""
        return v.value if hasattr(v, 'value') else str(v)

    # ── Auth distribution ──────────────────────────────────────────────────
    auth_counter: Counter = Counter()
    for rec in records:
        for method in rec.auth_methods:
            auth_counter[_str(method)] += 1

    # ── Access model distribution ─────────────────────────────────────────

    access_counter: Counter = Counter()
    for rec in records:
        access_counter[_str(rec.access_model)] += 1

    # ── API type distribution ─────────────────────────────────────────────
    api_counter: Counter = Counter()
    for rec in records:
        for t in rec.api_surface.types:
            api_counter[_str(t)] += 1

    # ── Buildability ──────────────────────────────────────────────────────
    buildable_count     = sum(1 for r in records if r.buildable_today is True)
    not_buildable_count = sum(1 for r in records if r.buildable_today is False)

    # ── MCP coverage ──────────────────────────────────────────────────────
    mcp_count = sum(1 for r in records if r.existing_mcp.exists)

    # ── Category summary ──────────────────────────────────────────────────
    cat_map: dict = defaultdict(lambda: {
        "total": 0,
        "self_serve": 0,
        "gated": 0,
        "buildable": 0,
        "oauth2": 0,
        "api_key": 0,
        "mcp": 0,
    })

    for rec in records:
        cat = rec.category
        cat_map[cat]["total"] += 1

        access = _str(rec.access_model)
        if access == "self-serve":
            cat_map[cat]["self_serve"] += 1
        elif access in ("partner-gated", "contact-sales", "admin-approval"):
            cat_map[cat]["gated"] += 1

        if rec.buildable_today:
            cat_map[cat]["buildable"] += 1

        if rec.existing_mcp.exists:
            cat_map[cat]["mcp"] += 1

        methods = {_str(m) for m in rec.auth_methods}
        if "OAuth2" in methods:
            cat_map[cat]["oauth2"] += 1
        if "API Key" in methods:
            cat_map[cat]["api_key"] += 1

    # ── Top blockers ──────────────────────────────────────────────────────
    blocker_counter: Counter = Counter()
    for rec in records:
        b = _str(rec.blocker)
        if b not in ("none", "unknown"):
            blocker_counter[b] += 1

    top_blockers = [
        {"blocker": b, "count": c}
        for b, c in blocker_counter.most_common(8)
    ]

    # ── Easy wins: self-serve + REST + buildable today ────────────────────
    easy_wins = [
        rec.app for rec in records
        if (
            _str(rec.access_model) == "self-serve"
            and rec.buildable_today is True
            and "REST" in {_str(t) for t in rec.api_surface.types}
            and _str(rec.blocker) in ("none", "unknown")
        )
    ]

    # ── Hard cases: partner/contact-sales gated ───────────────────────────
    hard_cases = [
        rec.app for rec in records
        if _str(rec.access_model) in ("partner-gated", "contact-sales", "admin-approval")
        or rec.buildable_today is False
    ]

    # ── Average confidence ────────────────────────────────────────────────
    avg_conf = sum(r.confidence for r in records) / total

    return InsightStats(
        total_apps=total,
        auth_distribution=dict(auth_counter),
        access_model_distribution=dict(access_counter),
        api_type_distribution=dict(api_counter),
        buildable_count=buildable_count,
        not_buildable_count=not_buildable_count,
        mcp_exists_count=mcp_count,
        category_summary=dict(cat_map),
        top_blockers=top_blockers,
        easy_wins=easy_wins,
        hard_cases=hard_cases,
        avg_confidence=round(avg_conf, 3),
    )


def save_insights(stats: InsightStats, path: Path) -> None:
    """Persist InsightStats to JSON."""
    path.write_text(json.dumps(stats.model_dump(), indent=2), encoding="utf-8")
    logger.info("💡 Insights saved → %s", path)

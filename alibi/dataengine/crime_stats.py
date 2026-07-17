"""
Autonomous crime-stats harvester — a scraping agent that lives IN the platform.

Runs from the weekly data-engine timer (no human in the loop): for each camera
area, an Apify web crawl fetches the area's police-precinct statistics page(s),
a CONSERVATIVE parser extracts per-category counts, and the rows go through the
same normalise → guard → tag → store pipeline as everything else.

Honesty rules built in:
  * The parser only accepts explicit "known SAPS category near a number" pairs
    and refuses the whole page unless several categories matched — a page that
    didn't render its stats stores NOTHING (and the audit says so). We never
    turn page junk into numbers.
  * Every record carries the page URL it was read from and the period label
    found on the page ("unknown period" is stored as such, never invented).
  * Freshness-gated per area (quarterly data — default 30-day re-check) and
    budget-capped like the POI harvest. Cost ≈ one small crawl per area/month.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Official SAPS crime-category vocabulary (subset relevant to a residential
# site). Parser matches these ONLY — no free-text guessing.
CATEGORIES = [
    "murder", "attempted murder", "sexual offences", "rape",
    "assault with the intent to inflict grievous bodily harm", "assault gbh",
    "common assault", "common robbery", "robbery with aggravating circumstances",
    "burglary at residential premises", "burglary at non-residential premises",
    "theft of motor vehicle and motorcycle", "theft out of or from motor vehicle",
    "stock-theft", "arson", "malicious damage to property", "carjacking",
    "robbery at residential premises", "robbery at non-residential premises",
]

_PERIOD_RE = re.compile(r"(20\d{2}\s*[/\-]\s*20?\d{2}|20\d{2}\s*[/\-]\s*\d{2})")
_NUM_RE = re.compile(r"\b(\d{1,4})\b")
MIN_CATEGORIES = 3      # fewer matches than this = page didn't render stats


def parse_station_stats(text: str) -> List[Dict[str, Any]]:
    """Extract (category, count) pairs from a stats page's text. Pure.

    A category counts only when a plausible number (0-9999) appears within a
    short window after its name. Returns [] unless MIN_CATEGORIES matched —
    a partial page is treated as no page."""
    if not text:
        return []
    low = text.lower()
    period_m = _PERIOD_RE.search(text)
    period = period_m.group(1).replace(" ", "") if period_m else "unknown period"

    rows: List[Dict[str, Any]] = []
    seen = set()
    for cat in CATEGORIES:
        if cat in seen:
            continue
        idx = low.find(cat)
        if idx == -1:
            continue
        window = low[idx + len(cat): idx + len(cat) + 80]
        m = _NUM_RE.search(window)
        if not m:
            continue
        count = int(m.group(1))
        rows.append({"crime_category": cat, "count": count, "period": period})
        seen.add(cat)

    if len(rows) < MIN_CATEGORIES:
        return []
    return rows


def stat_page_urls(area: str) -> List[str]:
    """Candidate public stats pages for an area's police precinct. Config-like:
    adjust here when a better machine-readable source appears."""
    slug = re.sub(r"[^a-z0-9]+", "-", area.lower()).strip("-")
    return [
        f"https://crimehub.org/my-police-station/{slug}",
        f"https://www.crimestatssa.com/precinct.php?precinct={slug}",
    ]


def crime_needs_refresh(area: str, store, min_age_days: int = 30,
                        now: Optional[datetime] = None) -> bool:
    """Per-source freshness: quarterly data doesn't need weekly spend."""
    now = now or datetime.utcnow()
    try:
        for r in store.query(source_id="places.area_crime_stats"):
            if str((r.payload or {}).get("query_area", "")).lower() == area.lower():
                return (now - r.ingested_at) > timedelta(days=min_age_days)
    except Exception:
        pass
    return True


def harvest_area_crime_stats(area: str, store=None, client=None,
                             now: Optional[datetime] = None):
    """Crawl the area's precinct stats page(s), parse, ingest. Never raises."""
    from alibi.dataengine.ingest import ingest_items, IngestResult
    from alibi.dataengine.sources import get_source
    from alibi.dataengine.store import DataEngineStore
    from alibi.dataengine.apify import ApifyClient

    spec = get_source("places.area_crime_stats")
    store = store or DataEngineStore()
    client = client or ApifyClient()

    urls = stat_page_urls(area)
    items = client.run_actor_sync("apify/website-content-crawler", {
        "startUrls": [{"url": u} for u in urls],
        "maxCrawlPages": len(urls),
        "maxCrawlDepth": 0,
        "crawlerType": "playwright:firefox",     # stats pages render via JS
        "saveMarkdown": False,
    })
    if items is None:
        return IngestResult(source_id=spec.source_id,
                            error="Apify fetch failed or no token")

    for item in items or []:
        text = item.get("text") or ""
        rows = parse_station_stats(text)
        if rows:
            for r in rows:
                r["area"] = area
                r["source_url"] = item.get("url") or urls[0]
            result = ingest_items(spec, rows, store, now=now,
                                  payload_extra={"query_area": area})
            store.append_audit("crime_stats_harvest", {
                "area": area, "url": item.get("url"),
                "stored": result.stored, "period": rows[0]["period"],
            })
            return result

    store.append_audit("crime_stats_harvest", {
        "area": area, "urls": urls, "stored": 0,
        "note": "no page yielded parseable stats — stored nothing",
    })
    return IngestResult(source_id=spec.source_id,
                        error="no parseable stats on any candidate page")

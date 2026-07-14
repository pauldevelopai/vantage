"""
Vantage Data Engine — scheduled refresh (§9).

Re-ingests place-context for the areas we actually have cameras in, then prunes
expired records. Designed to run from a systemd timer (see deploy/).

COST IS A FIRST-CLASS CONSTRAINT. Apify bills per result and the account may be
on a small monthly credit, so this is bounded by design:

  * Areas come ONLY from configured cameras — we never fetch context for a place
    with no camera in it.
  * A freshness gate skips areas whose data is still recent (POI retention is
    180 days; refreshing every ~30 is plenty). Nothing is re-fetched for nothing.
  * Hard caps: max areas per run, max places per area.
  * `--dry-run` reports exactly what WOULD be fetched, spending nothing.

Fail-safe: no APIFY_TOKEN, or any error, degrades to an honest report. Never
raises, never invents data. Prune still runs (it costs nothing).
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from alibi.dataengine.apify import ApifyClient
from alibi.dataengine.ingest import run_poi_for_area
from alibi.dataengine.schemas import DataDomain
from alibi.dataengine.store import DataEngineStore

# Defaults tuned for a small Apify credit. Override on the CLI.
DEFAULT_MAX_AREAS = 5
DEFAULT_MAX_PLACES = 20
DEFAULT_MIN_AGE_DAYS = 30


@dataclass
class RefreshReport:
    areas_considered: List[str] = field(default_factory=list)
    areas_skipped_fresh: List[str] = field(default_factory=list)
    areas_refreshed: List[str] = field(default_factory=list)
    areas_over_budget: List[str] = field(default_factory=list)
    stored: int = 0
    rejected_personal: int = 0
    pruned: int = 0
    errors: List[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "areas_considered": self.areas_considered,
            "areas_skipped_fresh": self.areas_skipped_fresh,
            "areas_refreshed": self.areas_refreshed,
            "areas_over_budget": self.areas_over_budget,
            "stored": self.stored,
            "rejected_personal": self.rejected_personal,
            "pruned": self.pruned,
            "errors": self.errors,
            "dry_run": self.dry_run,
        }


def areas_from_cameras() -> List[str]:
    """The areas we actually have cameras in — the only places worth fetching.

    Empty when no camera has an `area` set. That is an honest empty state, not a
    reason to go and scrape the world.
    """
    try:
        from alibi.cameras.camera_store import get_camera_store
        cams = get_camera_store().list_all()
    except Exception:
        return []

    seen: Dict[str, str] = {}
    for cam in cams:
        area = (getattr(cam, "area", "") or "").strip()
        if area:
            seen.setdefault(area.lower(), area)  # de-dupe case-insensitively
    return sorted(seen.values())


def needs_refresh(
    area: str,
    store: DataEngineStore,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    now: Optional[datetime] = None,
) -> bool:
    """True when we have no live place-context for the area, or it's stale.

    This is the credit-saver: a freshly-ingested area is not re-fetched.
    """
    now = now or datetime.utcnow()
    target = area.strip().lower()

    newest: Optional[datetime] = None
    for rec in store.query(domain=DataDomain.PLACES_CONTEXT, now=now):
        if str(rec.payload.get("area", "")).strip().lower() == target:
            if newest is None or rec.ingested_at > newest:
                newest = rec.ingested_at

    if newest is None:
        return True  # nothing for this area yet
    return (now - newest) >= timedelta(days=min_age_days)


def refresh(
    store: Optional[DataEngineStore] = None,
    client: Optional[ApifyClient] = None,
    areas: Optional[List[str]] = None,
    max_areas: int = DEFAULT_MAX_AREAS,
    max_places: int = DEFAULT_MAX_PLACES,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> RefreshReport:
    """Refresh place-context for camera areas, then prune. Never raises."""
    store = store or DataEngineStore()
    client = client or ApifyClient()
    report = RefreshReport(dry_run=dry_run)

    candidates = areas if areas is not None else areas_from_cameras()
    report.areas_considered = list(candidates)

    # 1. Freshness gate — don't spend credit on data we already hold.
    due = []
    for area in candidates:
        if needs_refresh(area, store, min_age_days=min_age_days, now=now):
            due.append(area)
        else:
            report.areas_skipped_fresh.append(area)

    # 2. Budget cap — anything beyond the cap waits for the next run.
    if len(due) > max_areas:
        report.areas_over_budget = due[max_areas:]
        due = due[:max_areas]

    # 3. Fetch (unless dry-run).
    if not dry_run:
        for area in due:
            try:
                result = run_poi_for_area(
                    area, store=store, client=client, max_places=max_places, now=now
                )
                if result.error:
                    report.errors.append(f"{area}: {result.error}")
                    continue
                report.areas_refreshed.append(area)
                report.stored += result.stored
                report.rejected_personal += result.rejected_personal
            except Exception as e:  # fail-safe
                report.errors.append(f"{area}: {e}")
    else:
        report.areas_refreshed = due  # what WOULD have been fetched

    # 4. Prune expired records — costs nothing, always runs.
    try:
        report.pruned = 0 if dry_run else store.prune(now=now)
    except Exception as e:
        report.errors.append(f"prune: {e}")

    store.append_audit("refresh_run", report.to_dict())
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Vantage place-context for camera areas, then prune."
    )
    parser.add_argument("--area", action="append", dest="areas",
                        help="Refresh only this area (repeatable). Default: all camera areas.")
    parser.add_argument("--max-areas", type=int, default=DEFAULT_MAX_AREAS,
                        help=f"Max areas to fetch per run (default {DEFAULT_MAX_AREAS}).")
    parser.add_argument("--max-places", type=int, default=DEFAULT_MAX_PLACES,
                        help=f"Max places per search (default {DEFAULT_MAX_PLACES}).")
    parser.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS,
                        help=f"Skip areas refreshed within this many days (default {DEFAULT_MIN_AGE_DAYS}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be fetched. Spends no Apify credit.")
    args = parser.parse_args(argv)

    report = refresh(
        areas=args.areas,
        max_areas=args.max_areas,
        max_places=args.max_places,
        min_age_days=args.min_age_days,
        dry_run=args.dry_run,
    )

    tag = "[DRY RUN] " if report.dry_run else ""
    print(f"{tag}Vantage data-engine refresh")
    print(f"  areas considered : {report.areas_considered or '(none — no camera has an area set)'}")
    print(f"  skipped (fresh)  : {report.areas_skipped_fresh}")
    print(f"  refreshed        : {report.areas_refreshed}")
    if report.areas_over_budget:
        # Never silently truncate — say what was deferred.
        print(f"  deferred (budget): {report.areas_over_budget}")
    print(f"  records stored   : {report.stored}")
    print(f"  personal rejected: {report.rejected_personal}")
    print(f"  expired pruned   : {report.pruned}")
    for err in report.errors:
        print(f"  ERROR: {err}")

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())

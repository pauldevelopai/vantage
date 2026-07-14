"""
Vantage Data Engine — append-only, provenance-tagged store (§9).

Mirrors the discipline of `alibi_store.py`: append-only JSONL, auditable, honest
empty states (a query with no data returns [], never mock content).

Retention is enforced on read AND by an explicit prune() — an expired record is
never returned, even if prune has not run yet.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from alibi.dataengine.schemas import DataDomain, IngestRecord


class DataEngineStore:
    """Append-only store for ingested reference/context data."""

    def __init__(self, storage_path: str = "alibi/data/dataengine.jsonl",
                 audit_path: Optional[str] = None):
        self.storage_path = storage_path
        self.audit_path = audit_path or storage_path.replace(".jsonl", "_audit.jsonl")
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)

    # --- write ------------------------------------------------------------- #

    def append(self, record: IngestRecord) -> None:
        """Append one record. Callers MUST have passed it through the guard."""
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def append_audit(self, action: str, detail: Dict[str, Any]) -> None:
        """Append-only audit trail of ingest runs, rejections and prunes."""
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "action": action,
            "detail": detail,
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    # --- read -------------------------------------------------------------- #

    def _iter_raw(self) -> Iterator[Dict[str, Any]]:
        if not os.path.exists(self.storage_path):
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip corrupt line rather than crash the engine

    def query(
        self,
        source_id: Optional[str] = None,
        domain: Optional[DataDomain] = None,
        now: Optional[datetime] = None,
        include_expired: bool = False,
        limit: Optional[int] = None,
    ) -> List[IngestRecord]:
        """Return live (non-expired) records, newest first. Honest empty state:
        returns [] when there is nothing — never fabricated content."""
        now = now or datetime.utcnow()
        out: List[IngestRecord] = []

        for raw in self._iter_raw():
            try:
                rec = IngestRecord.from_dict(raw)
            except Exception:
                continue
            if source_id and rec.source_id != source_id:
                continue
            if domain and rec.domain != domain:
                continue
            if not include_expired and rec.is_expired(now):
                continue  # retention enforced on read
            out.append(rec)

        out.sort(key=lambda r: r.ingested_at, reverse=True)
        return out[:limit] if limit else out

    def latest(self, source_id: str, now: Optional[datetime] = None) -> Optional[IngestRecord]:
        recs = self.query(source_id=source_id, now=now, limit=1)
        return recs[0] if recs else None

    # --- retention --------------------------------------------------------- #

    def prune(self, now: Optional[datetime] = None) -> int:
        """Physically drop expired records. Returns how many were removed."""
        now = now or datetime.utcnow()
        if not os.path.exists(self.storage_path):
            return 0

        kept: List[Dict[str, Any]] = []
        removed = 0
        for raw in self._iter_raw():
            try:
                rec = IngestRecord.from_dict(raw)
            except Exception:
                removed += 1
                continue
            if rec.is_expired(now):
                removed += 1
            else:
                kept.append(raw)

        tmp = self.storage_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for raw in kept:
                f.write(json.dumps(raw) + "\n")
        os.replace(tmp, self.storage_path)

        if removed:
            self.append_audit("prune", {"removed": removed, "kept": len(kept)})
        return removed

    def stats(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Counts by source/domain — powers an honest "what's in the engine" view."""
        now = now or datetime.utcnow()
        live = self.query(now=now)
        by_source: Dict[str, int] = {}
        by_domain: Dict[str, int] = {}
        for r in live:
            by_source[r.source_id] = by_source.get(r.source_id, 0) + 1
            by_domain[r.domain.value] = by_domain.get(r.domain.value, 0) + 1
        return {
            "total_live_records": len(live),
            "by_source": by_source,
            "by_domain": by_domain,
        }

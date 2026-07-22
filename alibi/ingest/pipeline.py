"""
The core: everything that must happen identically for every source.

Connectors read. The pipeline does the rest — deduplicate, extract, embed,
index, and stamp provenance — so those guarantees cannot drift apart as
connectors are added. A new kind of source is one `fetch` method and a registry
entry; it cannot change how any of this behaves, which is the point of the
split.

Deduplication is by CONTENT hash, not by id or filename. The same photograph
arriving from a licensed dataset and from a folder on a laptop is one item, and
it keeps the provenance of BOTH — removing the licensed one later must not
silently strip the lawful basis of a copy that had its own.

Ingest is resumable and incremental: a run records where it got to, and a
failing item is recorded and skipped rather than taking the run down. At the
scale this is written for, a run that dies on item 400,000 and starts again is
not a pipeline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from alibi.ingest.source import Connector, Item, Source

LEDGER = Path("alibi/data/ingest_ledger.jsonl")


def content_key(item: Item) -> str:
    """What makes two items the same thing.

    Content when we have it; the source's own id only as a fallback, because
    two files with different names and identical bytes are one picture.
    """
    if item.content:
        return "sha256:" + hashlib.sha256(item.content).hexdigest()
    return "extid:" + hashlib.sha256(
        f"{item.kind}:{item.external_id}".encode()).hexdigest()


@dataclass
class RunReport:
    source_id: str
    started_at: str
    seen: int = 0
    ingested: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    finished_at: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {**self.__dict__, "errors": self.errors[:20]}


class Ledger:
    """What has been ingested, and under what authority.

    Append-only and content-keyed. Holds the provenance of every source a given
    item arrived from, so a licence expiring can be traced to exactly the items
    that depended on it.
    """

    def __init__(self, path: Path = LEDGER):
        self.path = path
        self._keys: Optional[Dict[str, dict]] = None

    def _load(self) -> Dict[str, dict]:
        if self._keys is not None:
            return self._keys
        rows: Dict[str, dict] = {}
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    key = r.get("key")
                    if not key:
                        continue
                    if key in rows:
                        # Same bytes from another source: keep both stamps.
                        rows[key]["sources"].extend(r.get("sources", []))
                    else:
                        rows[key] = r
        except FileNotFoundError:
            pass
        self._keys = rows
        return rows

    def seen(self, key: str) -> bool:
        return key in self._load()

    def record(self, key: str, item: Item, source: Source) -> None:
        row = {"key": key, "kind": item.kind,
               "external_id": item.external_id,
               "captured_at": item.captured_at,
               "ingested_at": datetime.utcnow().isoformat(),
               "sources": [source.stamp()]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:  # pragma: no cover
            print(f"[ingest] could not write the ledger: {e}", flush=True)
        cache = self._load()
        if key in cache:
            cache[key]["sources"].extend(row["sources"])
        else:
            cache[key] = row

    def provenance(self, key: str) -> List[dict]:
        return (self._load().get(key) or {}).get("sources", [])


def ingest(source: Source, connector: Connector,
           embed: Optional[Callable[[Item], Any]] = None,
           index: Optional[Callable[[str, Item, Source, Any], None]] = None,
           ledger: Optional[Ledger] = None,
           since: Optional[str] = None,
           limit: Optional[int] = None) -> RunReport:
    """Pull everything new from one source.

    `embed` and `index` are injected so this stays testable without the vision
    stack, and so the same core serves a text-only source as an image one.
    """
    ledger = ledger or Ledger()
    report = RunReport(source_id=source.source_id,
                       started_at=datetime.utcnow().isoformat())

    for item in connector.fetch(source, since=since):
        report.seen += 1
        if limit and report.ingested >= limit:
            break
        try:
            key = content_key(item)
            if ledger.seen(key):
                # Still record the new source's stamp: the same picture may now
                # be held under a second, independent authority.
                ledger.record(key, item, source)
                report.duplicates += 1
                continue

            vector = embed(item) if embed else None
            ledger.record(key, item, source)
            if index:
                index(key, item, source, vector)
            report.ingested += 1
        except Exception as e:
            report.failed += 1
            if len(report.errors) < 50:
                report.errors.append(f"{item.external_id}: {e}")

    report.finished_at = datetime.utcnow().isoformat()
    print(f"[ingest] {source.source_id}: {report.ingested} new, "
          f"{report.duplicates} duplicate, {report.failed} failed", flush=True)
    return report

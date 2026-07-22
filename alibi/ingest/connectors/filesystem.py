"""
Import images from a directory. The reference connector.

Deliberately the whole of one: it reads, and it stops. No deduplication, no
embedding, no provenance handling — the core does those the same way for every
source, so this file shows exactly how much a new connector has to be.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from alibi.ingest.registry import register
from alibi.ingest.source import Item, Source

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class FilesystemConnector:
    name = "filesystem"

    def fetch(self, source: Source, since: Optional[str] = None) -> Iterator[Item]:
        root = Path(source.config.get("path", ""))
        if not root.is_dir():
            raise FileNotFoundError(f"{root} is not a directory")
        recursive = bool(source.config.get("recursive", True))
        cutoff = None
        if since:
            try:
                cutoff = datetime.fromisoformat(since.replace("Z", "")).timestamp()
            except ValueError:
                cutoff = None

        paths = root.rglob("*") if recursive else root.glob("*")
        for p in sorted(paths):
            if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                st = p.stat()
                if cutoff and st.st_mtime <= cutoff:
                    continue                       # incremental: only what's new
                yield Item(
                    external_id=str(p.relative_to(root)),
                    kind="image",
                    content=p.read_bytes(),
                    captured_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
                    metadata={"bytes": st.st_size, "suffix": p.suffix.lower()},
                )
            except OSError:
                continue                            # unreadable file, not a dead run


register(FilesystemConnector())

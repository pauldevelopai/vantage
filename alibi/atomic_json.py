"""
Write JSON so a crash mid-write cannot destroy what was already there.

Several small stores do read-modify-write of a whole JSON file — the face
rejections, the vehicle classifier. write_text() truncates the file first and
then writes, so a crash or full disk between the two leaves an empty or partial
file. The readers catch the parse error and fall back to {}, which means one
bad write silently wipes every remembered rejection — exactly the corrections a
person fought to make.

Write to a temp file in the same directory, fsync, then os.replace() onto the
target. os.replace is atomic on POSIX: a reader sees either the whole old file
or the whole new one, never a torn write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json(path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)          # atomic
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

"""
Reading a number plate off a security camera is noisy, and two failure modes
were letting the SAME car show up as several "different" vehicles on the
Overview:

  * the OCR reads the camera's burnt-in DATE/TIME overlay as a plate — so a
    white Toyota came back as plate "2026QX" (the year), sharing nothing with
    its real plate and never folding into the named car; and
  * it drops or swaps a character or two — "CSM4 0008" comes back as
    "GFM4 0008", a different string for the same physical plate.

This module is the one place that decides (a) whether a read is a plausible
plate at all, and (b) whether two reads are the same plate allowing for a
couple of OCR slips. It never invents a plate and never merges two plates that
aren't a near-match — an unreadable plate stays unreadable, which is the honest
state.
"""

from __future__ import annotations

import re
from typing import Dict, Optional


def normalize_plate(plate: Optional[str]) -> str:
    """Upper-case, strip everything but letters and digits. '' for nothing."""
    if not plate:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(plate).upper())


# A year like 2024/2025/2026 sitting in a short "plate" that is otherwise almost
# all digits is the timestamp overlay, not a registration. Real SA plates carry
# letters and don't read as a bare date.
_YEAR = re.compile(r"(?:19|20)\d\d")
_DATEISH = re.compile(r"^\d{2,4}[-/. ]?\d{2}[-/. ]?\d{2}")


def is_plausible_plate(plate: Optional[str]) -> bool:
    """Does this read look like a real registration, not a date overlay?

    Conservative: it only rejects reads that are clearly the clock — a year
    embedded in a short mostly-numeric string, or a date-shaped run. Anything
    that looks like an ordinary plate is kept, because wrongly discarding a real
    plate would split a car just as badly as a bogus one merges nothing.
    """
    norm = normalize_plate(plate)
    if len(norm) < 5:
        return False
    letters = sum(c.isalpha() for c in norm)
    # A plate is letters + digits. A "plate" that is a year with ≤2 stray
    # letters is the date overlay ("2026QX").
    if _YEAR.search(norm) and letters <= 2:
        return False
    if _DATEISH.match(str(plate or "").strip()) and letters == 0:
        return False
    return True


def _edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein, but give up once it exceeds `cap` (we only care about near
    matches). Classic two-row DP."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def plates_match(a: Optional[str], b: Optional[str], tolerance: int = 2) -> bool:
    """Same plate, allowing for a couple of OCR character slips.

    Requires both to be plausible and the same length (an OCR swap keeps the
    length; a genuinely different plate that happens to be 2 edits away is
    almost always a different length), then an edit distance within tolerance.
    """
    na, nb = normalize_plate(a), normalize_plate(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if not (is_plausible_plate(a) and is_plausible_plate(b)):
        return False
    if len(na) != len(nb):
        return False
    return _edit_distance(na, nb, tolerance) <= tolerance


def resolve_label(plate: Optional[str], plate_to_label: Dict[str, str]) -> Optional[str]:
    """The owner's name for a car with this plate — exact first, then a
    near-match against every NAMED plate, so an OCR slip on a fragment still
    inherits the name given to the real car. Implausible reads resolve to
    nothing rather than guessing."""
    if not plate or not is_plausible_plate(plate):
        return None
    # Exact (normalized) first.
    npl = normalize_plate(plate)
    for known, label in plate_to_label.items():
        if normalize_plate(known) == npl:
            return label
    # Then a tolerant match against the named plates only.
    for known, label in plate_to_label.items():
        if plates_match(plate, known):
            return label
    return None

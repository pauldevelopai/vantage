"""
Vantage Data Engine — personal-data guard (§8 boundary, enforced in code).

The lawful-data boundary is not a policy note: it is a gate every record must
pass. Anything carrying identifiers of a NATURAL PERSON is rejected at ingest,
so the data engine cannot become a people-dossier — even by accident, even if a
future source is mis-declared, even if an upstream actor changes its output.

Deliberate precision about the line:
  * A *place* legitimately has `name`, `address`, `phone` (a business, a police
    station, a landmark). Those bare keys are therefore NOT treated as personal.
  * A *person* is identified by things like `id_number`, `date_of_birth`,
    `surname`, `personal_email`, a face encoding, or a social profile URL. Those
    are rejected outright.

Fail-CLOSED: on any doubt the record is rejected, not stored.
"""

import re
from typing import Any, Dict, List


class PersonalDataRejected(Exception):
    """Raised when a record carries personal data and must not be stored."""

    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__(
            "Record rejected — carries personal data (Vantage §8 lawful-data "
            f"boundary): {'; '.join(violations)}"
        )


# Keys that identify a natural person. Bare `name`/`phone`/`address` are absent
# on purpose — those belong to places (see module docstring).
PERSON_KEY_PATTERNS = [
    r"id_number", r"id_no\b", r"identity_number", r"national_id", r"passport",
    r"\bssn\b", r"social_security",
    r"date_of_birth", r"\bdob\b", r"birth_date", r"birthdate",
    r"first_name", r"last_name", r"surname", r"full_name", r"maiden",
    r"\bgender\b", r"\brace\b", r"ethnicity", r"religion", r"sexual_",
    r"biometric", r"face_embedding", r"face_encoding", r"face_vector",
    r"fingerprint", r"iris_", r"voiceprint",
    r"criminal_record", r"conviction", r"next_of_kin",
    r"personal_email", r"personal_phone", r"home_address", r"residential_address",
    r"social_profile", r"facebook", r"linkedin", r"instagram", r"tiktok",
    r"twitter_handle", r"whatsapp", r"telegram",
    r"person_name", r"owner_name", r"driver_name", r"employee_name",
]

# Values that are person identifiers regardless of the key they arrive under.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SA_ID_RE = re.compile(r"\b\d{13}\b")           # South African ID number
SOCIAL_URL_RE = re.compile(
    r"(facebook\.com/|linkedin\.com/in/|instagram\.com/|tiktok\.com/@|"
    r"(?:twitter|x)\.com/(?!search)[A-Za-z0-9_]{2,})",
    re.IGNORECASE,
)

_KEY_RES = [re.compile(p, re.IGNORECASE) for p in PERSON_KEY_PATTERNS]


def _walk(obj: Any, path: str = "") -> List[tuple]:
    """Flatten a nested payload into (path, key, value) entries.

    A container's own key is emitted too — otherwise a personal key whose value
    is a list or dict (e.g. `face_embedding: [0.1, 0.2]`) would slip through
    unchecked while we recursed into its contents.
    """
    out: List[tuple] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            # Always check the key itself, whatever the value's type.
            out.append((p, str(k), v if not isinstance(v, (dict, list)) else None))
            if isinstance(v, (dict, list)):
                out.extend(_walk(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            if isinstance(v, (dict, list)):
                out.extend(_walk(v, p))
            else:
                out.append((p, "", v))
    return out


def scan_for_personal_data(payload: Dict[str, Any]) -> List[str]:
    """Return a list of violations; empty means the payload looks non-personal."""
    violations: List[str] = []

    for path, key, value in _walk(payload):
        # 1. Person-identifying key
        for rx in _KEY_RES:
            if key and rx.search(key):
                violations.append(f"person-identifying key '{path}'")
                break

        # 2. Person-identifying value (regardless of key)
        if isinstance(value, str):
            if EMAIL_RE.search(value):
                violations.append(f"email address in '{path}'")
            if SA_ID_RE.search(value):
                violations.append(f"possible national ID number in '{path}'")
            if SOCIAL_URL_RE.search(value):
                violations.append(f"social profile URL in '{path}'")

    return violations


def assert_non_personal(payload: Dict[str, Any]) -> None:
    """Gate: raise PersonalDataRejected if the payload carries personal data.

    Fail-closed — this is called on EVERY record before it reaches the store.
    """
    violations = scan_for_personal_data(payload)
    if violations:
        raise PersonalDataRejected(violations)

"""Form submission to profile plus checklist, and document tracking."""

from __future__ import annotations

import re
from datetime import date

from .checklist import EXPIRING, ROLES, outstanding, required_documents
from .store import Profile, Store

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_submission(form: dict) -> dict:
    """Validate and normalize a raw form payload. Raises ValidationError."""
    errors: list[str] = []
    name = " ".join(str(form.get("full_name", "")).split())
    email = str(form.get("email", "")).strip().lower()
    digits = re.sub(r"\D", "", str(form.get("phone", "")))
    role = str(form.get("role", "")).strip().lower().replace(" ", "_")
    trade = " ".join(str(form.get("trade", "")).split()).lower()

    if len(name) < 2:
        errors.append("full_name is required")
    if not EMAIL_RE.match(email):
        errors.append("email is not valid")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        errors.append("phone must have 10 digits")
    if role not in ROLES:
        errors.append(f"role must be one of: {', '.join(ROLES)}")
    elif role == "licensed_trade" and not trade:
        errors.append("trade is required for licensed_trade")
    if errors:
        raise ValidationError(errors)
    phone = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return {"full_name": name, "email": email, "phone": phone, "role": role, "trade": trade}


def submit(store: Store, form: dict, now: str) -> tuple[Profile, bool]:
    """Create or update a profile from a form submission and build its checklist.

    Submissions are keyed by email, so a resubmission updates the same profile.
    Documents already received are kept even if the role changes.
    """
    fields = clean_submission(form)
    profile, created = store.upsert_profile(fields, now)
    required = required_documents(profile.role)
    store.prune_documents(profile.id, required)
    store.ensure_documents(profile.id, required)
    return profile, created


def receive_document(
    store: Store,
    profile_id: int,
    doc_type: str,
    received_on: date,
    expires_on: date | None = None,
) -> None:
    if doc_type in EXPIRING and expires_on is None:
        raise ValueError(f"{doc_type} needs an expiry date")
    if doc_type not in EXPIRING:
        expires_on = None
    if not store.set_document(profile_id, doc_type, received_on, expires_on):
        raise KeyError(f"{doc_type} is not on the checklist for profile {profile_id}")


def missing_documents(store: Store, profile_id: int, today: date) -> list[str]:
    return outstanding(store.list_documents(profile_id), today)


def status_report(store: Store, today: date) -> list[dict]:
    """One row per profile: who they are and what is still outstanding."""
    report = []
    for p in store.list_profiles():
        docs = store.list_documents(p.id)
        missing = outstanding(docs, today)
        report.append(
            {
                "profile_id": p.id,
                "full_name": p.full_name,
                "role": p.role,
                "trade": p.trade,
                "required": len(docs),
                "missing": missing,
                "ready": not missing,
            }
        )
    return report

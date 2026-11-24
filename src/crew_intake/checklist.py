"""Document requirements by role, and the rules for what counts as missing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Document types that carry an expiry date. A received copy that has passed
# its expiry date counts as missing again.
EXPIRING = {"insurance_certificate", "trade_license"}

REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "crew_member": ("tax_form_w4", "id_verification", "emergency_contact"),
    "subcontractor": ("insurance_certificate", "tax_form_w9", "signed_agreement"),
    "licensed_trade": (
        "insurance_certificate",
        "tax_form_w9",
        "trade_license",
        "signed_agreement",
    ),
}

ROLES = tuple(REQUIREMENTS)


@dataclass(frozen=True)
class DocumentItem:
    profile_id: int
    doc_type: str
    received_on: date | None = None
    expires_on: date | None = None

    def state(self, today: date) -> str:
        """Return one of: missing, received, expired."""
        if self.received_on is None:
            return "missing"
        if self.expires_on is not None and self.expires_on < today:
            return "expired"
        return "received"


def required_documents(role: str) -> tuple[str, ...]:
    try:
        return REQUIREMENTS[role]
    except KeyError:
        raise ValueError(f"unknown role: {role!r}") from None


def for_role(items: list[DocumentItem], role: str) -> list[DocumentItem]:
    """Only the items the role requires.

    A received document is kept on file when the role changes, so a profile
    can hold items its current role no longer asks for. Those must not count.
    """
    required = required_documents(role)
    return [item for item in items if item.doc_type in required]


def outstanding(items: list[DocumentItem], today: date, role: str | None = None) -> list[str]:
    """Labels for every document that still blocks the applicant.

    With a role, items that role does not require are ignored.
    """
    if role is not None:
        items = for_role(items, role)
    out = []
    for item in items:
        state = item.state(today)
        if state == "missing":
            out.append(item.doc_type)
        elif state == "expired":
            out.append(f"{item.doc_type} (expired {item.expires_on.isoformat()})")
    return out

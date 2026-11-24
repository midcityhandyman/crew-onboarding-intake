"""Offline demo: fake applicants, a role based checklist, and a sync with scripted failures.

Run from the repo root:  python demo/run_demo.py
Everything is in memory. Dates are fixed so the output is the same every run.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crew_intake import intake  # noqa: E402
from crew_intake.cli import format_status, format_sync  # noqa: E402
from crew_intake.destinations import MockDestination  # noqa: E402
from crew_intake.store import Store  # noqa: E402
from crew_intake.sync import sync_all  # noqa: E402

TODAY = date(2026, 1, 15)
NOW = "2026-01-15T09:00:00+00:00"

FORMS = [
    {"full_name": "Alex Sample", "email": "alex.sample@example.com", "phone": "(555) 555-0101",
     "role": "subcontractor", "trade": "drywall"},
    {"full_name": "Casey Example", "email": "casey.example@example.com", "phone": "555-555-0102",
     "role": "crew_member"},
    {"full_name": "Jordan Placeholder", "email": "jordan.placeholder@example.com",
     "phone": "555.555.0103", "role": "licensed_trade", "trade": "electrical"},
    {"full_name": "Riley Testcase", "email": "riley.testcase@example.com", "phone": "5555550104",
     "role": "subcontractor", "trade": "painting"},
    {"full_name": "Morgan Fixture", "email": "morgan.fixture@example.com", "phone": "555-555-0105",
     "role": "licensed_trade", "trade": "plumbing"},
    {"full_name": "", "email": "not-an-email", "phone": "555", "role": "foreman"},
]


def heading(text: str) -> None:
    print(f"\n== {text} ==")


def main() -> None:
    store = Store()
    delays: list[float] = []

    heading("1. Form submissions")
    for form in FORMS:
        try:
            p, _ = intake.submit(store, form, NOW)
            docs = ", ".join(d.doc_type for d in store.list_documents(p.id))
            print(f"created profile {p.id}: {p.full_name} ({p.role}) -> checklist: {docs}")
        except intake.ValidationError as exc:
            print(f"rejected submission: {exc}")

    heading("2. Documents arrive")
    received = [
        (1, "insurance_certificate", date(2026, 9, 30)),
        (1, "tax_form_w9", None),
        (1, "signed_agreement", None),
        (2, "tax_form_w4", None),
        (3, "insurance_certificate", date(2026, 1, 10)),  # already expired
        (3, "trade_license", date(2027, 3, 1)),
        (3, "tax_form_w9", None),
        (5, "tax_form_w9", None),
    ]
    for pid, doc, expires in received:
        intake.receive_document(store, pid, doc, TODAY, expires)
        note = f" (expires {expires})" if expires else ""
        print(f"profile {pid}: received {doc}{note}")

    heading("3. What is missing (as of 2026-01-15)")
    print(format_status(intake.status_report(store, TODAY)))

    heading("4. Sync run 1: destination misbehaves")
    print("scripted: crew-0002 times out twice, crew-0003 is rejected, crew-0004 never answers")
    dest = MockDestination(
        {
            "crew-0002": ["transient", "transient"],
            "crew-0003": ["permanent"],
            "crew-0004": ["transient"] * 4,
        }
    )
    print(format_sync(sync_all(store, dest, TODAY, NOW, sleep=delays.append)))
    print(f"backoff delays requested (not actually slept in the demo): {delays}")
    print(f"pages at destination: {sorted(dest.pages)}")

    heading("5. Resubmission and one more document")
    p, created = intake.submit(store, {**FORMS[1], "phone": "555-555-0199"}, NOW)
    print(f"profile {p.id} resubmitted, created={created}, phone now {p.phone}")
    intake.receive_document(store, 5, "signed_agreement", TODAY)
    print("profile 5: received signed_agreement")

    heading("6. Sync run 2: destination healthy")
    print(format_sync(sync_all(store, dest, TODAY, NOW, sleep=delays.append)))
    print(f"pages at destination: {sorted(dest.pages)}")
    print(f"total destination calls across both runs: {len(dest.calls)}")

    heading("7. One synced crew page")
    page = dest.pages["crew-0003"]
    for key in ("name", "role", "trade", "ready_to_work", "missing"):
        print(f"{key}: {page[key]}")
    store.close()


if __name__ == "__main__":
    main()

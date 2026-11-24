"""Command line entry point: submit, receive, status, sync."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from . import intake
from .destinations import from_env
from .store import Store
from .sync import sync_all


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_status(report: list[dict]) -> str:
    lines = [f"{'ID':<4}{'NAME':<20}{'ROLE':<16}{'READY':<7}MISSING"]
    for r in report:
        missing = ", ".join(r["missing"]) or "none"
        ready = "yes" if r["ready"] else "no"
        lines.append(f"{r['profile_id']:<4}{r['full_name']:<20}{r['role']:<16}{ready:<7}{missing}")
    return "\n".join(lines)


def format_sync(results: list) -> str:
    lines = [f"{'PAGE':<11}{'STATUS':<9}{'ACTION':<9}{'TRIES':<6}DETAIL"]
    for r in results:
        lines.append(f"{r.key:<11}{r.status:<9}{r.action:<9}{r.attempts:<6}{r.detail}".rstrip())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew_intake", description=__doc__)
    parser.add_argument("--db", default=os.environ.get("CREW_INTAKE_DB", "crew_intake.db"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("submit", help="submit a form (JSON file with one object or a list)")
    p.add_argument("file")

    p = sub.add_parser("receive", help="mark a document as received")
    p.add_argument("profile_id", type=int)
    p.add_argument("doc_type")
    p.add_argument("--expires", type=date.fromisoformat, default=None)

    sub.add_parser("status", help="show what each applicant is missing")
    sub.add_parser("sync", help="push crew pages to the destination")

    args = parser.parse_args(argv)
    store = Store(args.db)
    today = date.today()
    try:
        if args.cmd == "submit":
            with open(args.file, encoding="utf-8") as fh:
                forms = json.load(fh)
            code = 0
            for form in forms if isinstance(forms, list) else [forms]:
                try:
                    profile, created = intake.submit(store, form, _now())
                    verb = "created" if created else "updated"
                    print(f"{verb} profile {profile.id}: {profile.full_name} ({profile.role})")
                except intake.ValidationError as exc:
                    print(f"rejected: {exc}", file=sys.stderr)
                    code = 1
            return code
        if args.cmd == "receive":
            try:
                intake.receive_document(store, args.profile_id, args.doc_type, today, args.expires)
            except (KeyError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"received {args.doc_type} for profile {args.profile_id}")
            return 0
        if args.cmd == "status":
            print(format_status(intake.status_report(store, today)))
            return 0
        results = sync_all(store, from_env(), today, _now())
        print(format_sync(results))
        return 1 if any(r.status == "flagged" for r in results) else 0
    finally:
        store.close()

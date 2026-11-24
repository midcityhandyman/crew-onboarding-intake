"""SQLite storage for profiles, checklist items and sync rows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from .checklist import DocumentItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    role TEXT NOT NULL,
    trade TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    doc_type TEXT NOT NULL,
    received_on TEXT,
    expires_on TEXT,
    PRIMARY KEY (profile_id, doc_type)
);
CREATE TABLE IF NOT EXISTS sync_rows (
    profile_id INTEGER PRIMARY KEY REFERENCES profiles(id),
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    remote_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Profile:
    id: int
    email: str
    full_name: str
    phone: str
    role: str
    trade: str
    created_at: str


@dataclass(frozen=True)
class SyncRow:
    profile_id: int
    payload_hash: str
    status: str  # settled or flagged
    attempts: int
    last_error: str
    remote_id: str
    updated_at: str


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # profiles -----------------------------------------------------------
    def upsert_profile(self, fields: dict, now: str) -> tuple[Profile, bool]:
        """Insert or update by email. Returns (profile, created)."""
        existing = self.get_profile_by_email(fields["email"])
        with self.db:
            if existing is None:
                self.db.execute(
                    "INSERT INTO profiles (email, full_name, phone, role, trade, created_at)"
                    " VALUES (:email, :full_name, :phone, :role, :trade, :now)",
                    {**fields, "now": now},
                )
            else:
                self.db.execute(
                    "UPDATE profiles SET full_name=:full_name, phone=:phone, role=:role,"
                    " trade=:trade WHERE email=:email",
                    fields,
                )
        return self.get_profile_by_email(fields["email"]), existing is None

    def get_profile_by_email(self, email: str) -> Profile | None:
        row = self.db.execute("SELECT * FROM profiles WHERE email=?", (email,)).fetchone()
        return Profile(**dict(row)) if row else None

    def get_profile(self, profile_id: int) -> Profile | None:
        row = self.db.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        return Profile(**dict(row)) if row else None

    def list_profiles(self) -> list[Profile]:
        rows = self.db.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        return [Profile(**dict(r)) for r in rows]

    # documents ----------------------------------------------------------
    def ensure_documents(self, profile_id: int, doc_types: tuple[str, ...]) -> None:
        """Add checklist items that are not there yet; never clears received ones."""
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO documents (profile_id, doc_type) VALUES (?, ?)",
                [(profile_id, d) for d in doc_types],
            )

    def prune_documents(self, profile_id: int, keep: tuple[str, ...]) -> None:
        """Drop unreceived items that the current role no longer requires."""
        marks = ",".join("?" for _ in keep)
        with self.db:
            self.db.execute(
                f"DELETE FROM documents WHERE profile_id=? AND received_on IS NULL"
                f" AND doc_type NOT IN ({marks})",
                (profile_id, *keep),
            )

    def set_document(
        self, profile_id: int, doc_type: str, received_on: date, expires_on: date | None
    ) -> bool:
        with self.db:
            cur = self.db.execute(
                "UPDATE documents SET received_on=?, expires_on=? WHERE profile_id=? AND doc_type=?",
                (
                    received_on.isoformat(),
                    expires_on.isoformat() if expires_on else None,
                    profile_id,
                    doc_type,
                ),
            )
        return cur.rowcount == 1

    def list_documents(self, profile_id: int) -> list[DocumentItem]:
        rows = self.db.execute(
            "SELECT * FROM documents WHERE profile_id=? ORDER BY doc_type", (profile_id,)
        ).fetchall()
        return [
            DocumentItem(r["profile_id"], r["doc_type"], _d(r["received_on"]), _d(r["expires_on"]))
            for r in rows
        ]

    # sync rows ----------------------------------------------------------
    def get_sync_row(self, profile_id: int) -> SyncRow | None:
        row = self.db.execute(
            "SELECT * FROM sync_rows WHERE profile_id=?", (profile_id,)
        ).fetchone()
        return SyncRow(**dict(row)) if row else None

    def save_sync_row(self, row: SyncRow) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO sync_rows (profile_id, payload_hash, status, attempts, last_error,"
                " remote_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(profile_id) DO UPDATE SET payload_hash=excluded.payload_hash,"
                " status=excluded.status, attempts=excluded.attempts,"
                " last_error=excluded.last_error, remote_id=excluded.remote_id,"
                " updated_at=excluded.updated_at",
                (
                    row.profile_id,
                    row.payload_hash,
                    row.status,
                    row.attempts,
                    row.last_error,
                    row.remote_id,
                    row.updated_at,
                ),
            )

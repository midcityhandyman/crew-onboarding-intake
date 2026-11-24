"""Push one crew page per profile to a destination, with retry and a final status per row."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .checklist import for_role, outstanding
from .destinations import Destination, PermanentError, TransientError
from .store import Profile, Store, SyncRow

SETTLED = "settled"
FLAGGED = "flagged"


@dataclass(frozen=True)
class SyncResult:
    profile_id: int
    key: str
    status: str  # settled or flagged
    action: str  # pushed, skipped or failed
    attempts: int
    detail: str = ""


def page_key(profile: Profile) -> str:
    return f"crew-{profile.id:04d}"


def build_page(store: Store, profile: Profile, today: date) -> dict:
    docs = for_role(store.list_documents(profile.id), profile.role)
    missing = outstanding(docs, today)
    return {
        "name": profile.full_name,
        "role": profile.role,
        "trade": profile.trade,
        "email": profile.email,
        "phone": profile.phone,
        "ready_to_work": not missing,
        "missing": missing,
        "documents": [
            {
                "type": d.doc_type,
                "state": d.state(today),
                "expires_on": d.expires_on.isoformat() if d.expires_on else None,
            }
            for d in docs
        ],
    }


def payload_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sync_profile(
    store: Store,
    dest: Destination,
    profile: Profile,
    today: date,
    now: str,
    max_attempts: int = 4,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult:
    key = page_key(profile)
    payload = build_page(store, profile, today)
    digest = payload_hash(payload)
    prior = store.get_sync_row(profile.id)

    # Already delivered and nothing changed: do not call the destination again.
    if prior and prior.status == SETTLED and prior.payload_hash == digest:
        return SyncResult(profile.id, key, SETTLED, "skipped", 0, "unchanged")

    attempts = 0
    error = ""
    remote_id = prior.remote_id if prior else ""
    status = FLAGGED
    while attempts < max_attempts:
        attempts += 1
        try:
            remote_id = dest.upsert_page(key, payload)
            status, error = SETTLED, ""
            break
        except PermanentError as exc:
            error = f"rejected: {exc}"
            break
        except TransientError as exc:
            error = f"gave up after {attempts} attempts: {exc}"
            if attempts < max_attempts:
                sleep(base_delay * 2 ** (attempts - 1))
        except Exception as exc:  # noqa: BLE001
            # A destination bug must flag this row, not abort the whole run.
            error = f"unexpected error: {type(exc).__name__}: {exc}"
            break

    store.save_sync_row(SyncRow(profile.id, digest, status, attempts, error, remote_id, now))
    action = "pushed" if status == SETTLED else "failed"
    return SyncResult(profile.id, key, status, action, attempts, error)


def sync_all(store: Store, dest: Destination, today: date, now: str, **kwargs) -> list[SyncResult]:
    """Sync every profile. One bad row never stops the rest."""
    return [sync_profile(store, dest, p, today, now, **kwargs) for p in store.list_profiles()]

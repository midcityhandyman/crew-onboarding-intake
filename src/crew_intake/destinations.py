"""Sync destinations. The mock is the default and needs no network or keys."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class TransientError(Exception):
    """Worth retrying: timeouts, rate limits, server errors."""


class PermanentError(Exception):
    """Not worth retrying: the destination rejected the payload."""


class Destination(Protocol):
    def upsert_page(self, key: str, payload: dict) -> str:
        """Create or replace the page stored under key. Returns a remote id."""


class MockDestination:
    """In-memory destination with scripted failures.

    fail_plan maps a page key to a list of outcomes consumed one per call:
    "transient" or "permanent". When the list is empty the call succeeds.
    If path is given, pages are also written there as JSON so the CLI can
    show what the destination holds between runs.
    """

    def __init__(self, fail_plan: dict[str, list[str]] | None = None, path: str | None = None):
        self.fail_plan = {k: list(v) for k, v in (fail_plan or {}).items()}
        self.path = path
        self.pages: dict[str, dict] = {}
        self.calls: list[str] = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.pages = json.load(fh)

    def upsert_page(self, key: str, payload: dict) -> str:
        self.calls.append(key)
        plan = self.fail_plan.get(key)
        if plan:
            outcome = plan.pop(0)
            if outcome == "transient":
                raise TransientError("mock destination timed out")
            if outcome == "permanent":
                raise PermanentError("mock destination rejected the payload (422)")
        self.pages[key] = payload
        if self.path:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.pages, fh, indent=2, sort_keys=True)
        return f"mock-{key}"


class HttpDestination:
    """PUT {base_url}/pages/{key} with a bearer token. Optional, not used offline."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def upsert_page(self, key: str, payload: dict) -> str:
        req = urllib.request.Request(
            f"{self.base_url}/pages/{key}",
            data=json.dumps(payload).encode("utf-8"),
            method="PUT",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                raise TransientError(f"HTTP {exc.code}") from exc
            raise PermanentError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TransientError(str(exc)) from exc
        return str(body.get("id", key))


def from_env(env: dict[str, str] | None = None) -> Destination:
    """Real destination only when both URL and key are set; otherwise the mock."""
    env = os.environ if env is None else env
    url, key = env.get("CREW_DEST_URL", ""), env.get("CREW_DEST_API_KEY", "")
    if url and key:
        return HttpDestination(url, key)
    return MockDestination(path=env.get("CREW_MOCK_FILE", "mock_destination.json"))

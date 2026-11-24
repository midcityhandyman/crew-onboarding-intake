from datetime import date

import pytest

from crew_intake.store import Store

TODAY = date(2026, 1, 15)
NOW = "2026-01-15T09:00:00+00:00"


def form(**overrides):
    base = {
        "full_name": "Alex Sample",
        "email": "alex.sample@example.com",
        "phone": "(555) 555-0101",
        "role": "subcontractor",
        "trade": "drywall",
    }
    base.update(overrides)
    return base


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()

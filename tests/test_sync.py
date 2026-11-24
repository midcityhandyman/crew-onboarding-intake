from datetime import date

from conftest import NOW, TODAY, form
from crew_intake import intake
from crew_intake.destinations import HttpDestination, MockDestination, from_env
from crew_intake.sync import FLAGGED, SETTLED, sync_all


def seed(store, n=1):
    for i in range(n):
        intake.submit(store, form(email=f"applicant{i}@example.com", full_name=f"Sample {i}x"), NOW)


def run(store, dest, **kw):
    delays = []
    results = sync_all(store, dest, TODAY, NOW, sleep=delays.append, **kw)
    return results, delays


def test_clean_sync_settles_and_writes_page(store):
    seed(store)
    dest = MockDestination()
    results, delays = run(store, dest)
    assert [(r.status, r.action, r.attempts) for r in results] == [(SETTLED, "pushed", 1)]
    assert delays == []
    page = dest.pages["crew-0001"]
    assert page["ready_to_work"] is False
    assert len(page["missing"]) == 3
    assert store.get_sync_row(1).remote_id == "mock-crew-0001"


def test_transient_failures_retry_with_backoff_then_settle(store):
    seed(store)
    dest = MockDestination({"crew-0001": ["transient", "transient"]})
    results, delays = run(store, dest, base_delay=0.5)
    assert results[0].status == SETTLED
    assert results[0].attempts == 3
    assert delays == [0.5, 1.0]


def test_retries_exhausted_flags_the_row(store):
    seed(store)
    dest = MockDestination({"crew-0001": ["transient"] * 10})
    results, delays = run(store, dest, max_attempts=3)
    assert results[0].status == FLAGGED
    assert results[0].attempts == 3
    assert len(dest.calls) == 3
    assert len(delays) == 2  # no sleep after the final attempt
    row = store.get_sync_row(1)
    assert row.status == FLAGGED and "gave up after 3 attempts" in row.last_error
    assert dest.pages == {}


def test_permanent_error_flags_without_retry(store):
    seed(store)
    dest = MockDestination({"crew-0001": ["permanent"]})
    results, delays = run(store, dest)
    assert results[0].status == FLAGGED
    assert results[0].attempts == 1
    assert delays == []
    assert "rejected" in results[0].detail


def test_one_bad_row_does_not_block_the_others(store):
    seed(store, 3)
    dest = MockDestination({"crew-0002": ["permanent"]})
    results, _ = run(store, dest)
    assert [r.status for r in results] == [SETTLED, FLAGGED, SETTLED]
    assert set(dest.pages) == {"crew-0001", "crew-0003"}


def test_unchanged_settled_rows_are_skipped(store):
    seed(store, 2)
    dest = MockDestination()
    run(store, dest)
    results, _ = run(store, dest)
    assert [r.action for r in results] == ["skipped", "skipped"]
    assert len(dest.calls) == 2  # nothing sent on the second run


def test_changed_profile_is_pushed_again(store):
    seed(store, 2)
    dest = MockDestination()
    run(store, dest)
    intake.receive_document(store, 1, "tax_form_w9", TODAY)
    results, _ = run(store, dest)
    assert [r.action for r in results] == ["pushed", "skipped"]
    assert "tax_form_w9" not in dest.pages["crew-0001"]["missing"]


def test_flagged_row_is_retried_on_next_run(store):
    seed(store)
    dest = MockDestination({"crew-0001": ["permanent"]})
    run(store, dest)
    results, _ = run(store, dest)
    assert results[0].status == SETTLED
    assert store.get_sync_row(1).last_error == ""


def test_expiry_passing_changes_the_page(store):
    seed(store)
    intake.receive_document(store, 1, "insurance_certificate", TODAY, date(2026, 1, 20))
    dest = MockDestination()
    run(store, dest)
    later = date(2026, 1, 21)
    results = sync_all(store, dest, later, NOW, sleep=lambda s: None)
    assert results[0].action == "pushed"
    assert any("expired" in m for m in dest.pages["crew-0001"]["missing"])


def test_mock_destination_persists_pages_to_file(store, tmp_path):
    seed(store)
    path = str(tmp_path / "pages.json")
    run(store, MockDestination(path=path))
    assert "crew-0001" in MockDestination(path=path).pages


def test_from_env_defaults_to_mock_and_needs_both_values_for_http(tmp_path):
    mock_file = str(tmp_path / "m.json")
    assert isinstance(from_env({"CREW_MOCK_FILE": mock_file}), MockDestination)
    half = {"CREW_DEST_URL": "https://dest.example.com", "CREW_MOCK_FILE": mock_file}
    assert isinstance(from_env(half), MockDestination)
    full = {"CREW_DEST_URL": "https://dest.example.com", "CREW_DEST_API_KEY": "placeholder"}
    assert isinstance(from_env(full), HttpDestination)

from datetime import date

import pytest

from conftest import NOW, TODAY, form
from crew_intake import intake
from crew_intake.checklist import required_documents


def test_submission_creates_profile_and_role_checklist(store):
    profile, created = intake.submit(store, form(), NOW)
    assert created
    assert profile.phone == "555-555-0101"
    docs = [d.doc_type for d in store.list_documents(profile.id)]
    assert sorted(docs) == sorted(required_documents("subcontractor"))
    assert len(intake.missing_documents(store, profile.id, TODAY)) == 3


@pytest.mark.parametrize(
    "role,expected",
    [
        ("crew_member", {"tax_form_w4", "id_verification", "emergency_contact"}),
        ("subcontractor", {"insurance_certificate", "tax_form_w9", "signed_agreement"}),
        (
            "licensed_trade",
            {"insurance_certificate", "tax_form_w9", "trade_license", "signed_agreement"},
        ),
    ],
)
def test_checklist_by_role(role, expected):
    assert set(required_documents(role)) == expected


def test_input_is_normalized(store):
    profile, _ = intake.submit(
        store,
        form(full_name="  Alex   Sample ", email=" Alex.Sample@Example.com ", role="Subcontractor",
             phone="+1 555.555.0101"),
        NOW,
    )
    assert profile.full_name == "Alex Sample"
    assert profile.email == "alex.sample@example.com"
    assert profile.role == "subcontractor"
    assert profile.phone == "555-555-0101"


def test_invalid_submission_reports_every_problem(store):
    with pytest.raises(intake.ValidationError) as exc:
        intake.submit(store, {"full_name": "", "email": "nope", "phone": "12", "role": "boss"}, NOW)
    assert len(exc.value.errors) == 4
    assert store.list_profiles() == []


def test_licensed_trade_needs_a_trade(store):
    with pytest.raises(intake.ValidationError):
        intake.submit(store, form(role="licensed_trade", trade=""), NOW)


def test_resubmission_updates_instead_of_duplicating(store):
    first, _ = intake.submit(store, form(), NOW)
    intake.receive_document(store, first.id, "tax_form_w9", TODAY)
    second, created = intake.submit(store, form(phone="555-555-0199"), NOW)
    assert not created
    assert second.id == first.id
    assert second.phone == "555-555-0199"
    assert len(store.list_profiles()) == 1
    # the received document survives the resubmission
    assert "tax_form_w9" not in intake.missing_documents(store, first.id, TODAY)


def test_role_change_adds_new_requirements_and_keeps_received(store):
    profile, _ = intake.submit(store, form(), NOW)
    intake.receive_document(store, profile.id, "signed_agreement", TODAY)
    intake.submit(store, form(role="licensed_trade", trade="electrical"), NOW)
    missing = intake.missing_documents(store, profile.id, TODAY)
    assert "trade_license" in missing
    assert "signed_agreement" not in missing

    intake.submit(store, form(role="crew_member"), NOW)
    types = {d.doc_type for d in store.list_documents(profile.id)}
    # unreceived subcontractor items are dropped, the received one is kept
    assert types == {"tax_form_w4", "id_verification", "emergency_contact", "signed_agreement"}


def test_receiving_documents_clears_missing(store):
    profile, _ = intake.submit(store, form(), NOW)
    intake.receive_document(store, profile.id, "tax_form_w9", TODAY)
    intake.receive_document(store, profile.id, "signed_agreement", TODAY)
    intake.receive_document(store, profile.id, "insurance_certificate", TODAY, date(2026, 12, 31))
    assert intake.missing_documents(store, profile.id, TODAY) == []
    assert intake.status_report(store, TODAY)[0]["ready"] is True


def test_expired_document_counts_as_missing(store):
    profile, _ = intake.submit(store, form(), NOW)
    intake.receive_document(store, profile.id, "insurance_certificate", TODAY, date(2026, 1, 14))
    missing = intake.missing_documents(store, profile.id, TODAY)
    assert "insurance_certificate (expired 2026-01-14)" in missing
    # expiring today is still valid
    intake.receive_document(store, profile.id, "insurance_certificate", TODAY, TODAY)
    assert not any("insurance" in m for m in intake.missing_documents(store, profile.id, TODAY))


def test_expiring_document_requires_expiry_date(store):
    profile, _ = intake.submit(store, form(), NOW)
    with pytest.raises(ValueError):
        intake.receive_document(store, profile.id, "insurance_certificate", TODAY)


def test_document_not_on_checklist_is_refused(store):
    profile, _ = intake.submit(store, form(role="crew_member"), NOW)
    with pytest.raises(KeyError):
        intake.receive_document(store, profile.id, "tax_form_w9", TODAY)


def test_null_fields_are_empty_not_the_text_none(store):
    # A JSON null must not turn into the name "None" or the trade "none".
    with pytest.raises(intake.ValidationError) as exc:
        intake.submit(store, form(full_name=None), NOW)
    assert "full_name is required" in exc.value.errors
    with pytest.raises(intake.ValidationError) as exc:
        intake.submit(store, form(role="licensed_trade", trade=None), NOW)
    assert exc.value.errors == ["trade is required for licensed_trade"]
    profile, _ = intake.submit(store, form(role="crew_member", trade=None), NOW)
    assert profile.trade == ""


def test_submission_that_is_not_an_object_is_rejected(store):
    with pytest.raises(intake.ValidationError):
        intake.submit(store, "Alex Sample", NOW)
    assert store.list_profiles() == []


def test_document_from_an_old_role_does_not_block_the_new_role(store):
    profile, _ = intake.submit(store, form(), NOW)
    # insurance certificate on file, already expired
    intake.receive_document(store, profile.id, "insurance_certificate", TODAY, date(2026, 1, 10))
    intake.submit(store, form(role="crew_member"), NOW)
    for doc in ("tax_form_w4", "id_verification", "emergency_contact"):
        intake.receive_document(store, profile.id, doc, TODAY)
    # a crew member does not need insurance, so the expired one is ignored
    assert intake.missing_documents(store, profile.id, TODAY) == []
    row = intake.status_report(store, TODAY)[0]
    assert row["ready"] is True and row["required"] == 3
    # it is still on file, and counts again if the role goes back
    intake.submit(store, form(), NOW)
    assert "insurance_certificate (expired 2026-01-10)" in intake.missing_documents(
        store, profile.id, TODAY
    )

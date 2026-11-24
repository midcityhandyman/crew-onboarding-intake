import json

from crew_intake.cli import main


def test_cli_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CREW_MOCK_FILE", str(tmp_path / "mock.json"))
    monkeypatch.delenv("CREW_DEST_URL", raising=False)
    monkeypatch.delenv("CREW_DEST_API_KEY", raising=False)
    db = str(tmp_path / "t.db")
    forms = tmp_path / "forms.json"
    forms.write_text(
        json.dumps(
            [
                {"full_name": "Casey Example", "email": "casey@example.com",
                 "phone": "555-555-0102", "role": "crew_member"},
                {"full_name": "Bad Row", "email": "bad", "phone": "1", "role": "x"},
            ]
        ),
        encoding="utf-8",
    )
    assert main(["--db", db, "submit", str(forms)]) == 1  # one row rejected
    assert main(["--db", db, "receive", "1", "tax_form_w4"]) == 0
    assert main(["--db", db, "receive", "1", "trade_license"]) == 1
    assert main(["--db", db, "status"]) == 0
    assert main(["--db", db, "sync"]) == 0
    out = capsys.readouterr().out
    assert "created profile 1: Casey Example" in out
    assert "id_verification" in out and "tax_form_w4" not in out.split("MISSING")[1]
    assert "settled" in out
    pages = json.loads((tmp_path / "mock.json").read_text(encoding="utf-8"))
    assert pages["crew-0001"]["name"] == "Casey Example"

"""The captured demo output in the repo must be what the demo prints today."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_output_matches_the_committed_capture(capsys):
    demo = runpy.run_path(str(ROOT / "demo" / "run_demo.py"))
    demo["main"]()
    printed = capsys.readouterr().out
    assert printed == (ROOT / "demo" / "output.txt").read_text(encoding="utf-8")

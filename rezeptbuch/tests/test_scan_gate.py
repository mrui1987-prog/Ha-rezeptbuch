"""Zähllogik der Scan-Seite „0,8 s aus dem Bild“ (docs/strichcode.md 3 und 11) mit nachgestellten Treffern.

Läuft nur, wenn Node vorhanden ist; die Funktion wird unverändert aus scan.html gelesen.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "scan.html"


def gate_source() -> str:
    text = PAGE.read_text(encoding="utf-8")
    m = re.search(r"function makeGate\(ms\) \{.*?\n  \}\n", text, re.S)
    assert m, "makeGate nicht gefunden"
    return m.group(0)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node nicht vorhanden")
def test_gate_counts_only_after_gap():
    # Sack 1 liegt 1 s im Bild (Treffer alle 200 ms), 1 s weg, dann Sack 2; ein anderer Code zählt sofort
    hits = [("A", t) for t in range(0, 1001, 200)] + [("B", 1100)] + [("A", t) for t in range(2000, 2401, 200)] \
        + [("A", 2900)]
    script = gate_source() + f"""
const g = makeGate(800);
const hits = {json.dumps(hits)};
console.log(JSON.stringify(hits.map(([c, t]) => g.accept(c, t))));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    counted = [h for h, ok in zip(hits, json.loads(out)) if ok]
    assert counted == [("A", 0), ("B", 1100), ("A", 2000)]

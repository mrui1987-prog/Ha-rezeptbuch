"""Kleine PDFs für Selbsttest und Tests – ohne Betriebsdaten, ohne weitere Bibliothek."""

from __future__ import annotations


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def erzeuge_pdf(seiten: int = 1, betreff: str | None = None, text: str = "Testseite") -> bytes:
    """PDF mit `seiten` Seiten, je eine Zeile `text`, optional Metadatum Subject."""
    objekte: list[bytes] = []
    kinder = " ".join(f"{3 + 2 * i} 0 R" for i in range(seiten))
    objekte.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objekte.append(f"<< /Type /Pages /Kids [{kinder}] /Count {seiten} >>".encode())
    schrift = 3 + 2 * seiten
    for i in range(seiten):
        inhalt = f"BT /F1 12 Tf 72 720 Td ({_esc(text)} {i + 1}) Tj ET".encode("latin-1")
        objekte.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       f"/Resources << /Font << /F1 {schrift} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode())
        objekte.append(b"<< /Length %d >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream")
    objekte.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    info = None
    if betreff is not None:
        objekte.append(f"<< /Subject ({_esc(betreff)}) /Title (Test) >>".encode("latin-1"))
        info = len(objekte)
    aus = bytearray(b"%PDF-1.4\n")
    lagen = []
    for nr, obj in enumerate(objekte, start=1):
        lagen.append(len(aus))
        aus += f"{nr} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(aus)
    aus += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
    for lage in lagen:
        aus += f"{lage:010d} 00000 n \n".encode()
    trailer = f"<< /Size {len(objekte) + 1} /Root 1 0 R"
    if info:
        trailer += f" /Info {info} 0 R"
    aus += f"trailer\n{trailer} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(aus)

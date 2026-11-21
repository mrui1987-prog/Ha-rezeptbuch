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
    objekte.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
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


def erzeuge_pdf_layout(seiten: list[list[tuple[float, float, str]]]) -> bytes:
    """PDF mit frei gesetzten Texten: je Seite Liste von (x, top, text) in pt, Helvetica 9 pt.
    `top` wie bei pdfplumber gemessen (von oben). Reihenfolge = Reihenfolge im PDF."""
    objekte: list[bytes] = []
    n = len(seiten)
    kinder = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objekte.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objekte.append(f"<< /Type /Pages /Kids [{kinder}] /Count {n} >>".encode())
    schrift = 3 + 2 * n
    for i, texte in enumerate(seiten):
        teile = [f"BT /F1 9 Tf 1 0 0 1 {x:.2f} {842 - top - 7.0:.2f} Tm ({_esc(t)}) Tj ET" for x, top, t in texte]
        inhalt = "\n".join(teile).encode("cp1252")
        objekte.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       f"/Resources << /Font << /F1 {schrift} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode())
        objekte.append(b"<< /Length %d >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream")
    objekte.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    aus = bytearray(b"%PDF-1.4\n")
    lagen = []
    for nr, obj in enumerate(objekte, start=1):
        lagen.append(len(aus))
        aus += f"{nr} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(aus)
    aus += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
    for lage in lagen:
        aus += f"{lage:010d} 00000 n \n".encode()
    aus += f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(aus)


# ---------------------------------------------------------------- erfundene BÄKO-Belege (Aufbau wie echt)

TITEL = {"rechnung": ("Rechnung", "RE0000001"), "auftragsbestaetigung": ("Auftragsbestätigung", "AT0000001"),
         "gutschrift": ("Gutschrift", "GS0000001")}


def _cent(text):
    return int(text.replace(".", "").replace(",", ""))


def _txt(cent):
    s = f"{abs(cent) // 100:,}".replace(",", ".") + f",{abs(cent) % 100:02d}"
    return ("-" if cent < 0 else "") + s


def _seitenkopf(art, seite):
    titel, nummer = TITEL[art]
    t = [(60, 100, "BÄKO Musterstadt eG, Postfach 1, 12345 Musterstadt"),
         (346, 150, titel if seite == 1 else f"Fortsetzung {titel}"), (546, 150, f"Seite {seite}"),
         (60, 190, "Musterbäckerei"), (346, 190, f"Belegnummer: {nummer}")]
    if art == "auftragsbestaetigung":
        t += [(346, 202, "Auftragsdatum: 01.02.2026"), (346, 214, "Voraussichtl."),
              (346, 224, "Lieferdatum: 03.02.2026"), (346, 238, "Kundennummer: 99999")]
    else:
        t += [(346, 202, "Belegdatum: 01.02.2026"), (346, 214, "Kundennummer: 99999")]
    if art == "rechnung":
        t += [(36.9, 274, "WG"), (68.1, 274, "Artikelnr."), (112, 274, "Anzahl"), (194, 274, "Beschreibung")]
    else:
        t += [(36.9, 274, "Pos"), (68.4, 274, "Artikelnr."), (122.7, 274, "Beschreibung")]
    t += [(358.7, 274, "Menge"), (385, 274, "ME"), (425, 274, "Preis"), (448, 274, "EUR"), (471.4, 274, "PE"),
          (504.6, 274, "Netto"), (531.6, 274, "EUR"), (551, 274, "St."), (564.5, 274, "%")]
    return t


def beleg_pdf(art="rechnung", positionen=None, abschnitte=None, umbruch_nach=None, netto_summe=None,
              anlage=True, ueberdruck=None, uebertrag_falsch=False):
    """Erfundener BÄKO-Beleg. positionen: Liste von dict (siehe beispiel_rechnung).
    abschnitte: {index: [Textzeilen]} vor der Position mit diesem Index.
    ueberdruck: Liste (seite, x, top, text) – wird zuletzt in den Inhalt geschrieben."""
    positionen = positionen or []
    abschnitte = abschnitte or {}
    besch_x = 194.0 if art == "rechnung" else 122.7
    seiten = [_seitenkopf(art, 1)]
    top = 300.0
    laufend = 0
    for i, p in enumerate(positionen):
        if umbruch_nach is not None and i == umbruch_nach:
            ue = laufend + (1 if uebertrag_falsch else 0)
            seiten[-1] += [(435, 700, "Übertrag"), (522, 700, _txt(ue))]
            seiten.append(_seitenkopf(art, len(seiten) + 1))
            seiten[-1] += [(435, 299, "Übertrag"), (522, 298, _txt(laufend))]
            top = 320.0
        s = seiten[-1]
        for zeile in abschnitte.get(i, []):
            s.append((besch_x, top, zeile))
            top += 12
        if art == "rechnung":
            s += [(36.9, top, p["wg"]), (68.6, top, p["art"]), (114.4, top, p["anzahl"])]
        else:
            s += [(36.9, top, str(p["pos"])), (79.2, top, p["art"])]
        s.append((besch_x, top, p["bez"][0]))
        if p.get("b"):
            s.append((334.5, top, "B"))
        s += [(350, top, p["menge"]), (400, top, p["me"]), (430, top, p["preis"]), (472, top, p["pe"]),
              (505, top, p["netto"]), (562, top, str(p["mwst"]))]
        top += 12
        for k, zeile in enumerate(p["bez"][1:]):
            s.append((besch_x, top, zeile))
            if k == 0 and p.get("klammer"):
                s.append((380.5, top, p["klammer"]))
            top += 12
        if len(p["bez"]) == 1 and p.get("klammer"):
            s.append((380.5, top, p["klammer"]))
            top += 12
        for zeile in p.get("bestell", []):
            s.append((besch_x, top, zeile))
            top += 12
        if p.get("gebinde"):
            s.append((besch_x, top, p["gebinde"]))
            top += 12
        for zeile in p.get("zusatz", []):
            s.append((besch_x, top, zeile))
            top += 12
        wert = _cent(p["netto"])
        if p.get("skonto"):
            s += [(besch_x, top, p["skonto"][0]), (528.7, top, p["skonto"][1])]
            top += 12
            wert += _cent(p["skonto"][1])
            s += [(382.8, top, "Summe nach Konditionen:"), (527.2, top, _txt(wert)), (557.1, top, "****")]
            top += 12
        laufend += wert
    s = seiten[-1]
    netto = laufend if netto_summe is None else netto_summe
    s.append((36.9, top + 20, "Es bestehen Vereinbarungen, aus denen sich nachträgliche Minderungen ergeben können."))
    top += 40
    saetze = {}
    for p in positionen:
        w = _cent(p["netto"]) + (_cent(p["skonto"][1]) if p.get("skonto") else 0)
        saetze[p["mwst"]] = saetze.get(p["mwst"], 0) + w
    if netto_summe is not None and saetze:
        k = max(saetze)
        saetze[k] += netto_summe - laufend
    mwst_ges = brutto_ges = 0
    for satz in sorted(saetze, reverse=True):
        n = saetze[satz]
        m = round(n * satz / 100)
        mwst_ges += m
        brutto_ges += n + m
        s += [(345, top, f"{satz}% MwSt.:"), (411.5, top, _txt(n)), (471.8, top, _txt(m)), (518.7, top, _txt(n + m))]
        top += 12
    s += [(358.8, top, "Summe:"), (411.5, top, _txt(netto)), (471.8, top, _txt(mwst_ges)),
          (518.7, top, _txt(brutto_ges))]
    top += 24
    name = {"rechnung": "Rechnungssumme", "auftragsbestaetigung": "Auftragssumme", "gutschrift": "Gutschriftssumme"}
    s += [(301.3, top, f"{name[art]} EUR:"), (515.7, top, _txt(brutto_ges))]
    if art == "rechnung" and anlage:
        a = _seitenkopf(art, len(seiten) + 1)
        a = [t for t in a if t[1] < 270]
        a += [(36.9, 300, "Artikelgruppe"), (258.7, 300, "Ohne MwSt."), (346.4, 300, "MwSt."),
              (411.9, 300, "Volle MwSt."), (488.1, 300, "Betrag")]
        gruppen = {}
        for p in positionen:
            w = _cent(p["netto"]) + (_cent(p["skonto"][1]) if p.get("skonto") else 0)
            g = gruppen.setdefault(p["wg"], [0, 0])
            g[0 if p["mwst"] == 7 else 1] += w
        t2 = 312
        for wg in sorted(gruppen, key=int):
            erm, voll = gruppen[wg]
            a.append((60, t2, f"{wg} Gruppe {wg} 0,00 {_txt(erm)} {_txt(voll)} {_txt(erm + voll)}"))
            t2 += 12
        ges = sum(sum(g) for g in gruppen.values())
        erm = sum(g[0] for g in gruppen.values())
        a.append((36.9, t2, f"Summe: 0,00 {_txt(erm)} {_txt(ges - erm)} {_txt(ges)}"))
        seiten.append(a)
    for seite, x, top_, text in (ueberdruck or []):
        seiten[seite - 1].append((x, top_, text))
    return erzeuge_pdf_layout(seiten)


def beispiel_rechnung(**kw) -> bytes:
    """Kleine erfundene Rechnung, die der Belegleser vollständig lesen muss (Selbsttest)."""
    pos = [
        {"wg": "101", "art": "100001", "anzahl": "2 SCK a 25 KG", "bez": ["Weizenmehl 550 Muster"],
         "menge": "50,000", "me": "KG", "preis": "59,9000", "pe": "HDT", "netto": "29,95", "mwst": 7},
        {"wg": "1001", "art": "100002", "anzahl": "1 TR a 12 FL", "bez": ["Limo 0,5l", "Glas"],
         "menge": "12,000", "me": "FL", "preis": "0,8590", "pe": "EIN", "netto": "10,31", "mwst": 19},
    ]
    abschn = {0: ["Hauptorder LS.-Nr.: LI0000001, Lieferdatum: 02.02.2026, Zufuhr",
                  "Ihre Referenz: CL0000001, Auftrag: AT0000001 vom 01.02.2026"]}
    kw.setdefault("positionen", pos)
    kw.setdefault("abschnitte", abschn)
    return beleg_pdf("rechnung", **kw)

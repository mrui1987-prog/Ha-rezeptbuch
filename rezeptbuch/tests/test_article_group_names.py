"""Namen der Warengruppen aus dem Vectron-Export (Michael 24.11.2026, 13:03)."""

import pytest

from app.articles import group_names, service, vectron
from app.errors import ValidationError
from test_articles import VECTRON, xlsx

HEADER = ("Nummer", "Name", "A-Hauptgruppe", "Preistyp")
GROUPS = [(1, "Brot", 1, 0), (2, "Brötchen", 2, 0), (12, "Kuchen", 7, 0), (25, "Handelswaren 7%%", 12, 2),
          (29, "-", 0, 0), (None, "", None, None)]


def test_import_group_names_check_and_run(conn):
    vectron.import_articles(conn, xlsx(VECTRON), mode="run")
    report = group_names.import_groups(conn, xlsx(GROUPS, header=HEADER), mode="check")
    assert report["counts"]["total"] == 4 and not report["imported"]
    assert group_names.get_names(conn) == {}
    group_names.import_groups(conn, xlsx(GROUPS, header=HEADER), mode="run")
    names = group_names.get_names(conn)
    assert names == {1: "Brot", 2: "Brötchen", 12: "Kuchen", 25: "Handelswaren 7%"}
    assert group_names.label(names, 12) == "12 Kuchen" and group_names.label(names, 99) == "WG 99"
    groups = {g["group"]: g["name"] for g in service.groups(conn)}
    assert groups.get(12) == "Kuchen"


def test_article_list_is_refused_as_group_file(conn):
    with pytest.raises(ValidationError) as exc:
        group_names.read_groups(xlsx(VECTRON))
    assert exc.value.code == "wrong_file"


MAIN = [(1, "Brot"), (2, "Brötchen"), (7, "Kuchen"), (12, "Handelswaren"), (17, "")]


def test_main_groups_and_mapping(conn):
    vectron.import_articles(conn, xlsx(VECTRON), mode="run")
    report = group_names.import_groups(conn, xlsx(MAIN, header=("Nummer", "Name")), mode="check")
    assert report["kind"] == "main_groups" and report["counts"]["total"] == 4 and report.get("hint")
    group_names.import_groups(conn, xlsx(GROUPS, header=HEADER), mode="run")
    assert group_names.get_main(conn) == {1: 1, 2: 2, 12: 7, 25: 12}
    report = group_names.import_groups(conn, xlsx(MAIN, header=("Nummer", "Name")), mode="run")
    assert report["imported"] and not report.get("hint")
    assert group_names.get_main_names(conn) == {1: "Brot", 2: "Brötchen", 7: "Kuchen", 12: "Handelswaren"}
    # Warengruppen-Namen bleiben beim Hauptgruppen-Import erhalten
    assert group_names.get_names(conn)[12] == "Kuchen"
    info = group_names.lookup(conn)
    assert group_names.describe(info, 12) == {"register_group_name": "Kuchen", "main_group": 7,
                                              "main_group_name": "Kuchen"}
    assert group_names.describe(info, 99)["main_group"] is None
    for a in service.list_articles(conn, status="all"):
        assert "main_group" in a and "main_group_name" in a
    for g in service.groups(conn):
        assert "main_group" in g

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

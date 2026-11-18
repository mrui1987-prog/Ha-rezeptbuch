import pytest

from app.kern import (
    INVALID,
    MAX_LINE,
    UNREADABLE,
    WEIGHT,
    LineSplitter,
    format_line,
    kg_to_g,
    parse_line,
)


@pytest.mark.parametrize("line,grams,stable,net", [
    ("ST,G    0.077kg", 77, True, False),       # Feldtest
    ("US,G    0.091kg", 91, False, False),      # CONT, instabil
    ("ST,N    0.000kg", 0, True, True),         # nach T an der Waage
    ("ST,GS   1.250kg", 1250, True, False),     # Schreibweise laut Anleitung
    ("US,NT  12.345kg", 12345, False, True),
    ("ST,G   30.000kg", 30000, True, False),
    ("ST,G   -0.077kg", -77, True, False),      # Minus wird angenommen
    ("ST,G-   0.010kg", -10, True, False),      # Vorzeichen direkt hinter G
    ("ST,G    0.0.1kg", None, None, None),      # kaputte Zahl
])
def test_parse_weight(line, grams, stable, net):
    reading = parse_line(line)
    if grams is None:
        assert reading.kind == UNREADABLE
        return
    assert reading.kind == WEIGHT
    assert reading.weight_g == grams
    assert reading.scale_stable is stable
    assert reading.net is net


def test_dashes_invalid():
    reading = parse_line("-----")
    assert reading.kind == INVALID
    assert reading.weight_g is None


@pytest.mark.parametrize("line", [
    "ST,G    0.077lb",       # falsche Einheit
    "ST,G    0.077g",
    "XX,G    0.077kg",
    "ST;G    0.077kg",
    "\x00\x7f@@@",           # Müll (falsche Baudrate)
    "ST,G",
    "0rAGE",
    None,                    # überlange Zeile
])
def test_unreadable(line):
    assert parse_line(line).kind == UNREADABLE


def test_kg_to_g_exact():
    assert kg_to_g("0.001") == 1
    assert kg_to_g("4.999") == 4999
    assert kg_to_g("0.0005") == 1      # kaufmännisch
    assert kg_to_g("0.0004") == 0


def test_splitter_crlf_and_single_endings():
    s = LineSplitter()
    assert s.feed(b"ST,G    0.077kg\r\nUS,G    0.091kg\rST,G    0.001kg\n") == [
        "ST,G    0.077kg", "US,G    0.091kg", "ST,G    0.001kg"]


def test_splitter_skips_empty_lines():
    assert LineSplitter().feed(b"\r\n\r\n-----\r\n\n") == ["-----"]


def test_splitter_partial_packets():
    s = LineSplitter()
    assert s.feed(b"ST,G   ") == []
    assert s.feed(b" 0.0") == []
    assert s.feed(b"77kg\r") == ["ST,G    0.077kg"]
    assert s.feed(b"\nUS,G    0.091kg\r\nST") == ["US,G    0.091kg"]
    assert s.feed(b",G    0.100kg\r\n") == ["ST,G    0.100kg"]


def test_splitter_bundled_packet():
    data = b"".join(format_line(g).encode() + b"\r\n" for g in (1, 2, 3))
    assert [parse_line(x).weight_g for x in LineSplitter().feed(data)] == [1, 2, 3]


def test_splitter_overlong_discarded_once():
    s = LineSplitter()
    out = s.feed(b"x" * (MAX_LINE + 10))
    assert out == [None]
    # Rest bis zum Zeilenende wird verworfen, danach geht es normal weiter
    assert s.feed(b"yyy\r\nST,G    0.005kg\r\n") == ["ST,G    0.005kg"]


def test_splitter_reset_drops_half_line():
    s = LineSplitter()
    s.feed(b"ST,G   ")
    s.reset()
    assert s.feed(b"-----\r\n") == ["-----"]


@pytest.mark.parametrize("grams,stable,net,expected", [
    (77, True, False, "ST,G    0.077kg"),
    (91, False, False, "US,G    0.091kg"),
    (0, True, True, "ST,N    0.000kg"),
    (30000, True, False, "ST,G   30.000kg"),
    (None, True, False, "-----"),
])
def test_format_line_matches_scale(grams, stable, net, expected):
    assert format_line(grams, stable, net) == expected


def test_format_parse_roundtrip():
    for g in (0, 1, 999, 1000, 1234, 29999):
        assert parse_line(format_line(g)).weight_g == g

from app.stability import StabilityChecker


def feed(chk, start, end, weight, step=0.1, net=False):
    t = start
    while t < end - 1e-9:
        chk.add(round(t, 3), weight(t) if callable(weight) else weight, net)
        t += step
    return round(t - step, 3)


def test_stable_after_window():
    chk = StabilityChecker(1000, 2)
    last = feed(chk, 0.0, 1.0, 500)
    assert last == 0.9
    assert not chk.is_stable(0.9)
    chk.add(1.0, 500)
    assert chk.is_stable(1.0)


def test_span_exactly_2_is_stable_3_is_not():
    chk = StabilityChecker(1000, 2)
    feed(chk, 0.0, 1.1, lambda t: 500 if int(t * 10) % 2 else 502)
    assert chk.is_stable(1.0)
    chk2 = StabilityChecker(1000, 2)
    feed(chk2, 0.0, 1.1, lambda t: 500 if int(t * 10) % 2 else 503)
    assert not chk2.is_stable(1.0)


def test_old_values_leave_window():
    chk = StabilityChecker(1000, 2)
    feed(chk, 0.0, 1.0, 100)          # Befüllen
    feed(chk, 1.0, 2.0, 500)          # danach ruhig
    assert not chk.is_stable(1.9)     # 100 g zählt noch zu Beginn des Fensters
    chk.add(2.0, 500)
    chk.add(2.1, 500)
    assert chk.is_stable(2.1)


def test_reset_restarts_window():
    chk = StabilityChecker(1000, 2)
    feed(chk, 0.0, 2.0, 500)
    assert chk.is_stable(1.9)
    chk.reset()                       # z. B. „-----“
    chk.add(2.0, 500)
    assert not chk.is_stable(2.5)
    chk.add(3.0, 500)
    assert chk.is_stable(3.0)


def test_switch_net_resets():
    chk = StabilityChecker(1000, 2)
    feed(chk, 0.0, 2.0, 500)
    chk.add(2.0, 0, net=True)
    assert not chk.is_stable(2.0)
    chk.add(3.0, 0, net=True)
    assert chk.is_stable(3.0)


def test_no_values_not_stable():
    chk = StabilityChecker()
    assert not chk.is_stable(10.0)
    assert chk.spread(10.0) is None


def test_stays_stable_between_lines():
    chk = StabilityChecker(1000, 2)
    feed(chk, 0.0, 1.1, 700)
    assert chk.is_stable(3.0)         # keine neuen Zeilen, Wert unverändert


def test_span_zero():
    chk = StabilityChecker(500, 0)
    feed(chk, 0.0, 0.6, 10)
    assert chk.is_stable(0.5)
    chk.add(0.6, 11)
    assert not chk.is_stable(0.6)

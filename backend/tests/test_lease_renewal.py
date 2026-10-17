from datetime import date

from app.services import lease_renewal as lr


def test_months_before_clamps_to_month_end():
    assert lr.months_before(date(2027, 8, 31), 6) == date(2027, 2, 28)
    assert lr.months_before(date(2028, 8, 31), 6) == date(2028, 2, 29)  # 윤년
    assert lr.months_before(date(2027, 1, 15), 2) == date(2026, 11, 15)  # 해를 넘김
    assert lr.months_before(date(2027, 12, 31), 2) == date(2027, 10, 31)


def test_window_stages():
    w = lr.window(date(2027, 8, 31))
    assert (w.notice_from, w.notice_until) == (date(2027, 2, 28), date(2027, 6, 30))
    assert w.stage(date(2027, 2, 27)) == "early"
    assert w.stage(date(2027, 2, 28)) == "open"
    assert w.stage(date(2027, 6, 30)) == "open"
    assert w.stage(date(2027, 7, 1)) == "closed"
    assert w.stage(date(2027, 8, 31)) == "closed"
    assert w.stage(date(2027, 9, 1)) == "ended"

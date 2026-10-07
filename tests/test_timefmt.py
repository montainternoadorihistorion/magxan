"""日時の書き方（ui/timefmt.py）のテスト"""
from __future__ import annotations

from datetime import UTC, datetime

from ui.timefmt import DAY, HOUR, MINUTE, date_text, datetime_text, file_stamp, span_text


def at(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """UTC の日時 → UNIX 秒"""
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def test_times_are_shown_in_japan_time_wherever_the_server_is():
    # UTC の 15:05 は、日本の翌日 0:05
    moment = at(2026, 10, 7, 15, 5)
    assert date_text(moment) == "2026/10/08"
    assert datetime_text(moment) == "2026/10/08 00:05"
    assert file_stamp(moment) == "20261008-0005"
    assert datetime_text(at(2026, 1, 1, 0, 0)) == "2026/01/01 09:00"


def test_span_text_rounds_to_a_rough_unit():
    assert span_text(0) == "1 分" == span_text(20) == span_text(-5)
    assert span_text(10 * MINUTE) == "10 分" and span_text(59 * MINUTE) == "59 分"
    assert span_text(HOUR) == "1 時間" and span_text(5 * HOUR + 10 * MINUTE) == "5 時間" and span_text(23 * HOUR) == "23 時間"
    assert span_text(DAY) == "1 日" and span_text(3 * DAY) == "3 日" and span_text(35 * DAY) == "35 日"
    assert span_text(DAY + 13 * HOUR) == "2 日"

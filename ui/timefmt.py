"""日時の書き方。

記録の時刻は UNIX 秒で持っている。画面には日本の時刻（UTC＋9）で出す。
サーバーの時計の地域（公開先は UTC）に左右されないように、ここで決めた時差を使う。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")
MINUTE, HOUR, DAY = 60, 60 * 60, 24 * 60 * 60


def date_text(timestamp: int) -> str:
    """日付（例：2026/10/08）"""
    return datetime.fromtimestamp(timestamp, JST).strftime("%Y/%m/%d")


def datetime_text(timestamp: int) -> str:
    """日付と時刻（例：2026/10/08 21:05）"""
    return datetime.fromtimestamp(timestamp, JST).strftime("%Y/%m/%d %H:%M")


def file_stamp(timestamp: int) -> str:
    """ファイル名に入れる日時（例：20261008-2105）"""
    return datetime.fromtimestamp(timestamp, JST).strftime("%Y%m%d-%H%M")


def span_text(seconds: int) -> str:
    """時間の長さを、大まかに書く（例：10 分、5 時間、3 日）。1 分に満たなければ「1 分」"""
    seconds = max(0, int(seconds))
    minutes = max(1, round(seconds / MINUTE))
    if minutes < 60:
        return f"{minutes} 分"
    hours = round(seconds / HOUR)
    if hours < 24:
        return f"{hours} 時間"
    return f"{max(1, round(seconds / DAY))} 日"

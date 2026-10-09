"""おまかせ補正の設定（一人練習・CPU 戦で共通）。

設定（dict）の次の値を扱う。判断そのものは engine/auto_luck.py。

    auto        おまかせにしているか
    auto_since  前に段階を変えた（おまかせを始めた）時刻。これより後に終わった局だけで判断する
    auto_last   前に段階を変えたときの判断の控え（engine.auto_luck.decision_data の形）。無ければ None

おまかせのあいだ、配牌とツモの良さ（deal・draw）は、いつも段階の値（75・50・25・0）にそろえておく。
画面の部品（Streamlit）には触れない。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.auto_luck import (
    MAX_TIME,
    AutoDecision,
    Play,
    current_level,
    decide,
    decision_data,
    decision_from_data,
    drill_rate,
    start_level,
)
from engine.drills import KINDS
from ui.progress_store import Store, read_decks

AUTO_DEFAULTS: dict[str, Any] = {"auto": False, "auto_since": 0, "auto_last": None}


def clean_auto(data: dict[str, Any], result: dict[str, Any]) -> None:
    """設定の値を確かめる関数（clean_settings）の一部：おまかせの値のうち、正しいものだけを result に写す"""
    if isinstance(data.get("auto"), bool):
        result["auto"] = data["auto"]
    since = data.get("auto_since")
    if isinstance(since, int) and not isinstance(since, bool) and 0 <= since <= MAX_TIME:
        result["auto_since"] = since
    if "auto_last" in data and (data["auto_last"] is None or decision_from_data(data["auto_last"]) is not None):
        result["auto_last"] = data["auto_last"]


def turn_on(settings: dict[str, Any], now: int) -> dict[str, Any]:
    """おまかせを始めるときに変える値：いまの補正にいちばん近い段階から始めて、そこから数え直す"""
    level = start_level(settings["deal"], settings["draw"])
    return {"auto": True, "deal": level, "draw": level, "auto_since": now, "auto_last": None}


def judge(settings: dict[str, Any], play: Callable[[int, int], Play], need: int, store: Store, now: int) -> AutoDecision:
    """いまの成績で判断すると、どうなるか。play は（数え始める時刻, いまの段階）→ 打牌の評価。

    数え始める時刻が先の時刻になっている（ブラウザに残っていた値が、おかしい）ときは、いまから数える（ずっと判断しなくならないように）
    """
    level = current_level(settings["deal"], settings["draw"])
    return decide(level, play(min(int(settings["auto_since"]), now), level), need, drill_rate(read_decks(store), KINDS))


def step_values(settings: dict[str, Any], decision: AutoDecision, now: int) -> dict[str, Any] | None:
    """新しい局（対局）を始めるときに、設定に写す値（変えるものが無ければ None）"""
    if decision.changed:
        return {"deal": decision.level, "draw": decision.level, "auto_since": now, "auto_last": decision_data(decision, now)}
    values: dict[str, Any] = {}
    if settings["deal"] != decision.level or settings["draw"] != decision.level:
        values.update(deal=decision.level, draw=decision.level)     # 段階どおりでない値（書き換えられた、など）を、段階にそろえる
    if int(settings["auto_since"]) > now:
        values["auto_since"] = now                                  # 先の時刻になっていたら、いまから数える
    return values or None


def last_change(settings: dict[str, Any]) -> tuple[AutoDecision, int] | None:
    """前に段階を変えたときの判断と、その時刻"""
    return decision_from_data(settings.get("auto_last"))

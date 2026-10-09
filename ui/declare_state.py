"""あがったときの点数の申告：答えの記録（ブラウザ内保存の drill.declare）と、局ごとの「申告したか」の控え。

対局（ui/game_session.py）と一人練習（ui/practice_session.py）で共通に使う。画面の部品（Streamlit）には触れない。

記録（卒業判定に使う）に入れるのは、成績に入れる局（やり直し・番号を指定した局ではない）で、打つ前のヒントを
一度も見ていない局の申告だけ。ヒントの表には聴牌したときの点数が出るし、やり直しの局は同じ問題になるため。
記録に入れない申告も、答え合わせは同じように出す。
"""
from __future__ import annotations

from typing import Any

from engine.declare import DeclareQuiz
from ui.progress_store import DECLARE, Store, read_deck, write_deck

#: 控えに入れる文字の長さの上限（ブラウザに残っていた、壊れた値を読まないため）
_MAX_TEXT = 300


def record_declaration(store: Store, quiz: DeclareQuiz, picked: str, *, now: float) -> bool:
    """申告の答えを記録する。→ 正解したか"""
    correct = quiz.correct(picked)
    deck = read_deck(store, DECLARE)
    write_deck(store, DECLARE, deck.review(quiz.item, correct, int(now)))
    return correct


def skipped_state(hand: int | None) -> dict[str, Any]:
    """申告しないで結果を見た（または、申告の問題を出さずに結果を見せた）局の控え"""
    return {"hand": hand, "picked": None, "answer": "", "why": "", "recorded": False}


def declared_state(hand: int | None, quiz: DeclareQuiz, picked: str, *, recorded: bool = True) -> dict[str, Any]:
    """局の控え（あとで、答え合わせを出すため）。一人練習では hand は None。recorded は、記録に入れたか"""
    return {"hand": hand, "picked": picked, "answer": quiz.answer, "why": quiz.why, "recorded": recorded}


def clean_declared(data: object) -> dict[str, Any] | None:
    """ブラウザに残っていた控えを確かめる（おかしければ None ＝ まだ申告していない）"""
    if not isinstance(data, dict):
        return None
    hand = data.get("hand")
    if hand is not None and (not isinstance(hand, int) or isinstance(hand, bool) or hand < 0):
        return None
    picked, answer, why = data.get("picked"), data.get("answer"), data.get("why")
    if picked is not None and not isinstance(picked, str):
        return None
    if not isinstance(answer, str) or not isinstance(why, str):
        return None
    if any(len(text) > _MAX_TEXT for text in (picked or "", answer, why)):
        return None
    recorded = data.get("recorded", True)          # 記録に入れたか（この項目の無い控えは、入れていたころのもの）
    return {"hand": hand, "picked": picked, "answer": answer, "why": why, "recorded": recorded if isinstance(recorded, bool) else True}

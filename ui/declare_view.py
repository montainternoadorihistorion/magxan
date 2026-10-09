"""あがったときの点数の申告の画面（問題の札と、答え合わせの札）。対局と一人練習で共通に使う。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from engine.declare import DeclareQuiz
from engine.scoring.explain import Explanation
from ui.components.choices import Option, choice_buttons
from ui.ruby import Rubifier
from ui.win_view import chips_html, hand_html, situation_chips

DECLARE_INTRO = "役 → ドラ → 符 → 点数 の順に数えて、選ぼう（解説は、答えたあとに出る）。"
SKIP_LABEL = "申告しないで結果を見る"


def declare_card_html(explanation: Explanation, quiz: DeclareQuiz, rb: Rubifier) -> str:
    """申告の問題：あがった状況と手牌（点数は、まだ見せない）"""
    return (
        f'<div class="mj-card mj-result-card good"><div class="mj-big">{rb.html("あがり！ 何点？")}</div>'
        f"{chips_html(situation_chips(explanation), rb)}"
        f'<div class="mj-sub">{rb.html(DECLARE_INTRO + quiz.note)}</div></div>'
        # ドラ表示牌は、上の札にもう出ている。手牌の下に出すのは、裏ドラがあるとき（リーチしてあがった局）だけ
        + hand_html(explanation, rb, indicators=bool(explanation.ctx.ura_indicators))
    )


def declare_result_html(state: dict[str, Any] | None, rb: Rubifier) -> str:
    """答え合わせの札（申告しなかったときは空）"""
    if not state or state.get("picked") is None:
        return ""
    picked, answer = state["picked"], state["answer"]
    if picked == answer:
        head = f'<b class="mj-stage">○ 申告：正解</b>　{rb.html(answer)}'
        cls = "good"
    else:
        head = f'<b class="mj-stage">✗ 申告：{rb.html(answer)} が正解</b>　{rb.html(f"（選んだのは {picked}）")}'
        cls = "bad"
    note = "" if state.get("recorded", True) else "（この申告は、記録に入れていない。打つ前のヒントを見た局と、やり直し・番号を指定した局は、数えない）"
    return f'<div class="mj-headline mj-headline-short {cls}">{head}</div><div class="mj-sub">{rb.html(state["why"] + note)}</div>'


def declare_quiz_view(
    explanation: Explanation, quiz: DeclareQuiz, rb: Rubifier, *, key: str, rev: int,
    on_pick: Callable[[str], None], on_skip: Callable[[], None],
) -> None:
    """申告の問題を出す（選択肢と「申告しないで結果を見る」）"""
    st.html(declare_card_html(explanation, quiz, rb))
    choice_buttons(
        [Option(choice, rb.parts(choice)) for choice in quiz.choices], key=key, rev=rev,
        on_pick=lambda keys: on_pick(keys[0]), layout="row",
    )
    st.button(SKIP_LABEL, on_click=on_skip, key=f"{key}_skip", width="stretch")

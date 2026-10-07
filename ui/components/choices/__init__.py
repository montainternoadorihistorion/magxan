"""選択肢を並べる部品（ドリルの答え、役や分類の切り替え）。

Streamlit のボタンには、ルビも牌の絵も入れられない。選択肢には読みにくい役の名前や牌が並ぶので、
自前の部品にしてある。1 つ選ぶときは、押した選択肢がそのまま答えになる。いくつも選ぶときは、選んでから確定する。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from ui.components._base import registered, session_rev

_DIR = Path(__file__).parent
LAYOUTS = ("list", "row", "chips")


def _component():
    return registered("mjdojo_choices", _DIR, html="choices.html", css="choices.css", js="choices.js")


@dataclass(frozen=True)
class Option:
    key: str                                    # 答えの鍵
    parts: Sequence[tuple[str, str]]            # （文字, 読み）の並び。読みが空でなければ、その文字にルビを振る
    image: str | None = None                    # 牌の画像の URL
    alt: str = ""                               # その牌の名前（読み上げ用）


def parse_choice(payload: object, *, rev: int, keys: Sequence[str], multi: bool) -> list[str] | None:
    """部品から届いた値を確かめて、選んだ答えの鍵の一覧にする。

    次の場合は None（無視）:
      * 形が違う
      * rev が今の番号と違う（前の問題の画面から届いた答え。二重送信の防止）
      * 選択肢に無い鍵が入っている、同じ鍵が 2 回入っている
      * 1 つ選ぶ問題なのに、1 つでない／いくつも選ぶ問題なのに、1 つも無い
    """
    if not isinstance(payload, dict):
        return None
    number = payload.get("rev")
    if isinstance(number, bool) or not isinstance(number, (int, float)) or int(number) != rev:
        return None
    picked = payload.get("keys")
    if not isinstance(picked, list) or not all(isinstance(key, str) for key in picked):
        return None
    if len(set(picked)) != len(picked) or not set(picked) <= set(keys):
        return None
    if not picked or (not multi and len(picked) != 1):
        return None
    return list(picked)


def choice_buttons(
    options: Sequence[Option],
    *,
    key: str,
    rev: int,
    on_pick: Callable[[list[str]], None],
    multi: bool = False,
    layout: str = "list",
    confirm_label: str = "これで答える",
    prompt: str = "",
    selected: Sequence[str] = (),
) -> None:
    """選択肢を表示する。答えたら on_pick(選んだ鍵の一覧) を呼ぶ。

    rev       問題ごとに変わる番号。部品はこの番号が変わったことで「サーバーが応答した」と判断する。
              設定の切り替えに使うときは、選ぶたびに変わる番号を渡す（選んだあとの状態を表す番号でよい）
    on_pick   答えたときの処理。Streamlit のコールバックとして、画面を描き直す前に呼ばれる
    selected  はじめから選んである選択肢（設定の切り替えで、いまの値を示す）
    """
    if layout not in LAYOUTS:
        raise ValueError(f"並べ方は {LAYOUTS} のどれかです: {layout!r}")
    options = list(options)
    rev = session_rev(rev)      # 通信が長く切れてセッションが作り直されたあとも、部品が「応答があった」と気づけるように
    memo_key = f"{key}::shown"
    # 「いま画面に出している内容」を覚えておく。答えが届いたとき、それがこの画面からのものか確かめるため
    st.session_state[memo_key] = {"rev": rev, "keys": [option.key for option in options], "multi": multi}

    def _on_pick_change() -> None:
        shown = st.session_state.get(memo_key)
        payload = getattr(st.session_state.get(key), "pick", None)
        if not shown:
            return
        picked = parse_choice(payload, rev=shown["rev"], keys=shown["keys"], multi=shown["multi"])
        if picked is not None:
            on_pick(picked)

    _component()(
        key=key,
        data={
            "rev": rev,
            "options": [
                {"key": option.key, "parts": [list(part) for part in option.parts], "img": option.image, "alt": option.alt}
                for option in options
            ],
            "multi": multi,
            "layout": layout,
            "confirmLabel": confirm_label,
            "prompt": prompt,
            "selected": [option.key for option in options if option.key in set(selected)],
        },
        on_pick_change=_on_pick_change,
    )

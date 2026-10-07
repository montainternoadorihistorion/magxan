"""自作部品の登録をまとめる。

Streamlit の部品（カスタムコンポーネント v2）は、動いている Streamlit 本体に登録してから使う。
モジュールの読み込み時に 1 度だけ登録する書き方だと、本体が作り直される場面（自動テストなど）で
「登録されていない」エラーになる。そこで、置くたびに登録し直す。同じ内容の登録は何も起こさないので害はない。
ファイルの読み込みは 1 度だけ行う。
"""
from __future__ import annotations

import secrets
from functools import cache
from pathlib import Path

import streamlit as st

#: セッションごとの「番号の土台」を入れておく場所
REV_BASE_KEY = "mj_rev_base"


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def registered(name: str, folder: Path, *, html: str | None = None, css: str | None = None, js: str | None = None):
    """部品を登録し、画面に置くための関数を返す。html / css / js は folder の中のファイル名"""
    return st.components.v2.component(
        name,
        html=_read(folder / html) if html else None,
        css=_read(folder / css) if css else None,
        js=_read(folder / js) if js else None,
    )


def session_rev(number: int) -> int:
    """部品に渡す番号（rev）に、セッションごとに違う土台を足す。

    部品は「番号が変わった ＝ サーバーが応答した」と判断する。通信が長く切れてセッションが作り直されると、
    Python の側の番号は最初に戻る。たまたま前と同じ番号になると、部品は「まだ応答が無い」と見なして、
    送信中のまま止まる。セッションごとに土台を変えておけば、部品は、サーバーが新しくなったことに必ず気づく。
    """
    base = st.session_state.get(REV_BASE_KEY)
    if not isinstance(base, int) or isinstance(base, bool):
        base = (secrets.randbelow(900_000_000) + 1) * 1_000_000        # 足しても、JavaScript が正確に扱える整数（2^53）に収まる
        st.session_state[REV_BASE_KEY] = base
    return base + number

"""画面のスクロールの位置を動かす部品（見えるものは何も出さない）。

Streamlit は、画面を描き直してもスクロールの位置を保つ。ふつうはそれでよいが、ドリルで「次の問題」を押した
ときは、解説を読み終えた位置（下のほう）のままでは、新しい問題文が見えない。番号（rev）が変わるたびに、先頭へ戻す。
役図鑑で、一覧から役のページへ、役から次の役へ移ったときも同じ（同じページの中の移動では、位置が残ってしまう）。

答えた直後のように、先頭ではなく「ある部分が見えるところ」まで動かしたいときは、reveal にその部分の CSS セレクタを渡す。
もう見えていれば、動かさない。
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ui.components._base import registered

_DIR = Path(__file__).parent


def _component():
    return registered("mjdojo_scroll_top", _DIR, js="scroll_top.js")


def scroll_top(rev: int, *, key: str, reveal: Sequence[str] = ()) -> None:
    """rev が前に置いたときと違えば、画面を動かす。

    reveal が空なら、いちばん上まで戻す。reveal に CSS セレクタを渡したときは、それに合う要素（それぞれ最初の 1 つ）が
    すべて画面に入るところまでだけ動かす。まとめて入らないときは、先頭のセレクタの要素が見えるようにする。
    """
    _component()(key=key, data={"rev": rev, "reveal": list(reveal)})

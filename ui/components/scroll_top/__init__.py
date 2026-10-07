"""画面のいちばん上までスクロールを戻す部品。

Streamlit は、画面を描き直してもスクロールの位置を保つ。ふつうはそれでよいが、ドリルで「次の問題」を押した
ときは、解説を読み終えた位置（下のほう）のままでは、新しい問題文が見えない。番号（rev）が変わるたびに、先頭へ戻す。
役図鑑で、一覧から役のページへ、役から次の役へ移ったときも同じ（同じページの中の移動では、位置が残ってしまう）。
"""
from __future__ import annotations

from pathlib import Path

from ui.components._base import registered

_DIR = Path(__file__).parent


def _component():
    return registered("mjdojo_scroll_top", _DIR, js="scroll_top.js")


def scroll_top(rev: int, *, key: str) -> None:
    """rev が前に置いたときと違えば、画面のいちばん上まで戻す"""
    _component()(key=key, data={"rev": rev})

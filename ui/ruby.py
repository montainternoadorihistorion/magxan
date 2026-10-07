"""文章にルビ（読みがな）を振る。

    rb = Rubifier()
    rb.html("副底 20 符に、門前ロンの 10 符を足す")
    → '<ruby>副底<rt>フーテイ</rt></ruby> 20 <ruby>符<rt>フ</rt></ruby>に、<ruby>門前<rt>メンゼン</rt></ruby>ロンの 10 符を足す'

同じ用語にルビを振るのは、その画面で最初に出てきた 1 回だけ（2 回目からは振らない）。
画面を 1 回描くごとに Rubifier を 1 つ作り、その画面の文章をすべて通す。
"""
from __future__ import annotations

from collections.abc import Mapping
from html import escape

from engine.terms import READINGS


class Rubifier:
    def __init__(self, readings: Mapping[str, str] = READINGS, *, enabled: bool = True) -> None:
        self._readings = readings
        self._enabled = enabled
        self._seen: set[str] = set()
        self._by_first: dict[str, list[str]] = {}
        for term in readings:
            self._by_first.setdefault(term[0], []).append(term)
        for terms in self._by_first.values():
            terms.sort(key=len, reverse=True)     # 長い用語を先に試す（「三暗刻」を「暗刻」より先に）

    @property
    def seen(self) -> frozenset[str]:
        return frozenset(self._seen)

    def html(self, text: str) -> str:
        """文章を HTML にする（特殊文字をエスケープし、初出の用語にルビを振る）"""
        out: list[str] = []
        i = 0
        while i < len(text):
            term = next((t for t in self._by_first.get(text[i], ()) if text.startswith(t, i)), None)
            if term is None:
                out.append(escape(text[i]))
                i += 1
                continue
            if self._enabled and term not in self._seen:
                self._seen.add(term)
                out.append(f"<ruby>{escape(term)}<rt>{escape(self._readings[term])}</rt></ruby>")
            else:
                out.append(escape(term))
            i += len(term)
        return "".join(out)

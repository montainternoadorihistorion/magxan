"""文章にルビ（読みがな）を振る。

    rb = Rubifier()
    rb.html("副底 20 符に、門前ロンの 10 符を足す")
    → '<ruby>副底<rt>フーテイ</rt></ruby> 20 <ruby>符<rt>フ</rt></ruby>に、<ruby>門前<rt>メンゼン</rt></ruby>ロンの 10 符を足す'

同じ用語にルビを振るのは、その画面で最初に出てきた 1 回だけ（2 回目からは振らない）。
画面を 1 回描くごとに Rubifier を 1 つ作り、その画面の文章をすべて通す。

折りたたみ（開かないと見えない部分）の中身は、fork() で分けた Rubifier に通す。
閉じた折りたたみの中で振ったルビは読まれていないかもしれないので、外の文章や、ほかの折りたたみでは
「まだ出てきていない用語」として扱う。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
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

    def fork(self) -> Rubifier:
        """ここまでに出てきた用語を引き継いだ、別の Rubifier を作る（折りたたみの中身など、読まれるとは限らない部分に使う）。

        分けたほうでルビを振っても、元のほうには伝わらない。
        """
        other = Rubifier(self._readings, enabled=self._enabled)
        other._seen = set(self._seen)
        return other

    def _pieces(self, text: str) -> Iterable[tuple[str, bool]]:
        """文章を、（文字, 用語か）の列に分ける。用語は、長いものを先に見る"""
        i = 0
        while i < len(text):
            term = next((t for t in self._by_first.get(text[i], ()) if text.startswith(t, i)), None)
            if term is None:
                yield text[i], False
                i += 1
            else:
                yield term, True
                i += len(term)

    def html(self, text: str) -> str:
        """文章を HTML にする（特殊文字をエスケープし、初出の用語にルビを振る）"""
        out: list[str] = []
        for piece, is_term in self._pieces(text):
            if is_term and self._enabled and piece not in self._seen:
                self._seen.add(piece)
                out.append(f"<ruby>{escape(piece)}<rt>{escape(self._readings[piece])}</rt></ruby>")
            else:
                out.append(escape(piece))
        return "".join(out)

    def parts(self, text: str) -> list[tuple[str, str]]:
        """文章を（文字, 読み）の列にする。読みは、初出の用語にだけ入る（それ以外は空）。

        HTML を受け取らない部品（選択肢のボタンなど）に、ルビつきの文字を渡すときに使う。
        """
        out: list[tuple[str, str]] = []
        plain: list[str] = []
        for piece, is_term in self._pieces(text):
            if is_term and self._enabled and piece not in self._seen:
                self._seen.add(piece)
                if plain:
                    out.append(("".join(plain), ""))
                    plain = []
                out.append((piece, self._readings[piece]))
            else:
                plain.append(piece)
        if plain:
            out.append(("".join(plain), ""))
        return out

    def rich(self, text: str) -> str:
        """html() と同じだが、**…** で囲んだ部分を太字にする（説明文で、要点を目立たせるため）"""
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", self.html(text))

    def note(self, text: str) -> None:
        """文章の中の用語を「もう出てきた」と覚える（ルビは振らない）。

        読みを別の形で見せたときに使う。例：役の表では、役の名前のすぐ横に読みを並べて書く。
        """
        if self._enabled:
            self._seen.update(piece for piece, is_term in self._pieces(text) if is_term)

    def wrap(self, text: str, before: str, after: str) -> str:
        """文字を飾りのタグ（before / after）で包む。text が用語 1 つで、初出なら、ルビは飾りの外側に振る。

        色つきのバッジの中にルビを入れると、読みがバッジの文字色のまま、バッジの外（上）に出てしまう
        （暗い背景の画面で、暗い文字になって読めない）。外側に振れば、読みは地の文の色になる。
        """
        if self._enabled and text in self._readings and text not in self._seen:
            self._seen.add(text)
            return f"<ruby>{before}{escape(text)}{after}<rt>{escape(self._readings[text])}</rt></ruby>"
        return f"{before}{self.html(text)}{after}"


def missing_ruby(parts: Iterable[tuple], readings: Mapping[str, str] = READINGS) -> list[str]:
    """初出なのにルビが付いていない用語を探す（ルビの振り忘れを見つけるための確認用）。

    parts は、画面に出る順に並べた（文字, その文字には読みが付いているか）の列。
    読みが付いているのは、ルビを振った用語と、読みをすぐ横に並べて書いた名前（class="mj-term"）。
    読みを答えさせる問題の文（class="mj-asked"。わざと読みを隠している）も、同じ扱いにする。
    同じ文字のかたまりの中に読みが書いてある用語（例：一覧の「立直　リーチ」）も、読みが付いているものとして扱う。
    3 つ目に範囲の番号を付けてもよい：0（省略したときも 0）は、いつも見えている部分。それ以外の番号は
    折りたたみ 1 つぶんで、Rubifier.fork() と同じ扱いにする（その中で振ったルビは、外やほかの折りたたみでは数えない）。
    """
    main = Rubifier(readings)
    scopes: dict[int, Rubifier] = {}
    missing: list[str] = []
    for part in parts:
        text, has_ruby = part[0], part[1]
        scope = part[2] if len(part) > 2 else 0
        checker = main if scope == 0 else scopes.setdefault(scope, main.fork())
        if has_ruby:
            checker.note(text)
        else:
            found = re.findall(r"<ruby>([^<]+)<rt>", checker.html(text))
            missing.extend(term for term in found if readings[term] not in text)
    return missing

"""ドラの数え方（自前）。

    ドラ      ドラ表示牌の「次の牌」。手牌（副露を含む）に 1 枚あるごとに 1 翻
              数牌: 1→2→…→9→1     風牌: 東→南→西→北→東     三元牌: 白→發→中→白
    赤ドラ    赤い 5。1 枚につき 1 翻
    裏ドラ    リーチして和了したときだけめくれる、ドラ表示牌の下の牌。数え方はドラと同じ
    カンドラ  誰かがカンするたびにドラ表示牌が 1 枚増える（リーチしていれば裏ドラも増える）

ドラは翻数を増やすが、役ではない。ドラだけでは和了れない。役満のときは数えない。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.rules import Rules
from engine.scoring.context import WinContext
from engine.tiles import EAST, HAKU, counts34, is_red, kind_of, sort_tiles


def dora_kind_of(indicator_kind: int) -> int:
    """ドラ表示牌の種類 → ドラになる牌の種類"""
    if indicator_kind < 27:
        start = indicator_kind // 9 * 9
        return start + (indicator_kind - start + 1) % 9
    if indicator_kind < HAKU:
        return EAST + (indicator_kind - EAST + 1) % 4
    return HAKU + (indicator_kind - HAKU + 1) % 3


@dataclass(frozen=True)
class DoraLine:
    indicator: int     # ドラ表示牌（牌ID）
    dora_kind: int     # ドラになる牌の種類
    count: int         # 手牌にある枚数（＝ この表示牌で増える翻数）


@dataclass(frozen=True)
class DoraResult:
    dora_lines: tuple[DoraLine, ...]   # ドラ表示牌ごと（カンドラを含む）
    ura_lines: tuple[DoraLine, ...]    # 裏ドラ表示牌ごと（リーチしていないときは空）
    aka_tiles: tuple[int, ...]         # 手牌にある赤5（牌ID）
    riichi: bool                       # リーチしているか（裏ドラを数えるか）

    @property
    def dora(self) -> int:
        return sum(line.count for line in self.dora_lines)

    @property
    def ura(self) -> int:
        return sum(line.count for line in self.ura_lines)

    @property
    def aka(self) -> int:
        return len(self.aka_tiles)

    @property
    def total(self) -> int:
        return self.dora + self.aka + self.ura


def _lines(indicators: Sequence[int], counts: list[int]) -> tuple[DoraLine, ...]:
    lines = []
    for indicator in indicators:
        dora_kind = dora_kind_of(kind_of(indicator))
        lines.append(DoraLine(indicator, dora_kind, counts[dora_kind]))
    return tuple(lines)


def count_dora(ctx: WinContext, rules: Rules) -> DoraResult:
    """手牌（副露を含む）にあるドラ・赤ドラ・裏ドラを数える"""
    tiles = ctx.all_tiles
    counts = counts34(tiles)
    aka_tiles = tuple(t for t in sort_tiles(tiles) if is_red(t, aka=rules.aka_dora))
    ura_lines = _lines(ctx.ura_indicators, counts) if ctx.riichi else ()
    return DoraResult(_lines(ctx.dora_indicators, counts), ura_lines, aka_tiles, ctx.riichi)

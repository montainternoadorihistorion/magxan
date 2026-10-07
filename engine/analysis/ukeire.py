"""受け入れ（有効牌）：引くと向聴数が 1 つ進む牌と、その残り枚数。

    acceptance(counts13, remaining)        ある 13 枚に対する受け入れ
    discard_options(counts14, remaining)   14 枚から 1 枚切る候補ごとの、切ったあとの向聴数と受け入れ

remaining は「まだ見えていない枚数」（種類ごと、長さ 34）。4 枚から、自分の手牌と、場に見えている牌
（河・副露・ドラ表示牌）を引いたもの。打牌しても変わらない（切った牌は手牌から河に移るだけなので）。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from engine.analysis.shanten import shanten_of
from engine.tiles import NUM_KINDS, counts34


@dataclass(frozen=True)
class Acceptance:
    shanten: int                             # いまの向聴数
    tiles: tuple[tuple[int, int], ...]       # 有効牌（種類, 残り枚数）。残り 0 枚の種類も含む

    @property
    def live(self) -> tuple[tuple[int, int], ...]:
        """残っている有効牌だけ"""
        return tuple((kind, count) for kind, count in self.tiles if count > 0)

    @property
    def kinds(self) -> int:
        """有効牌の種類数（残っているものだけ）"""
        return len(self.live)

    @property
    def total(self) -> int:
        """有効牌の残り枚数の合計"""
        return sum(count for _, count in self.tiles)


@dataclass(frozen=True)
class DiscardOption:
    kind: int                  # 切る牌の種類
    shanten: int               # 切ったあとの向聴数
    acceptance: Acceptance     # 切ったあとの受け入れ

    @property
    def total(self) -> int:
        return self.acceptance.total

    @property
    def kinds(self) -> int:
        return self.acceptance.kinds

    @property
    def reach(self) -> int:
        """比べるときに使う「実質の向聴数」。

        有効牌が 1 枚も残っていない形は、何を引いても進まない（先に形を変える必要がある）。
        そこで、向聴数が 1 つ大きいものとして扱う。例：待ち牌がすべて見えている聴牌（空聴）は、
        有効牌が残っている 1 向聴より後ろに並ぶ。
        """
        return self.shanten + (1 if self.total == 0 else 0)


def remaining_counts(hand: Iterable[int], visible: Iterable[int] = ()) -> list[int]:
    """まだ見えていない枚数（種類ごと）。hand は自分の手牌、visible は場に見えている牌（どちらも牌ID）"""
    seen = counts34([*hand, *visible])
    return [max(0, 4 - n) for n in seen]


def acceptance(counts: Sequence[int], remaining: Sequence[int]) -> Acceptance:
    """13 枚（副露があれば 13 − 3n 枚）の手に対する受け入れ"""
    work = list(counts)
    base = shanten_of(work)
    found = []
    for kind in range(NUM_KINDS):
        if work[kind] >= 4:
            continue                      # 5 枚目は存在しない
        work[kind] += 1
        if shanten_of(work) < base:
            found.append((kind, remaining[kind]))
        work[kind] -= 1
    return Acceptance(base, tuple(found))


def discard_options(counts: Sequence[int], remaining: Sequence[int]) -> list[DiscardOption]:
    """14 枚（副露があれば 14 − 3n 枚）から 1 枚切る候補を、良い順に並べて返す。

    良い順：切ったあとの向聴数が小さい → 受け入れ枚数が多い → 受け入れの種類が多い。
    ただし、受け入れが 0 枚の候補は、向聴数が 1 つ大きいものとして並べる（DiscardOption.reach）。
    """
    work = list(counts)
    options = []
    for kind in range(NUM_KINDS):
        if not work[kind]:
            continue
        work[kind] -= 1
        result = acceptance(work, remaining)
        work[kind] += 1
        options.append(DiscardOption(kind, result.shanten, result))
    options.sort(key=lambda o: (o.reach, -o.total, -o.kinds, o.kind))
    return options


def draw_chance(effective: int, unseen: int) -> float:
    """次の 1 枚が有効牌である確率（見えていない牌のどれもが、同じ確からしさで来るとして）"""
    if unseen <= 0:
        return 0.0
    return min(1.0, effective / unseen)


def chance_within(effective: int, unseen: int, draws: int) -> float:
    """あと draws 回のツモのうちに、有効牌を 1 回以上引く確率。

    1 − （draws 回とも有効牌でない確率）。引いた牌は戻さないので、
    外れ続ける確率 ＝ (U−a)/U × (U−a−1)/(U−1) × … を draws 回ぶん掛ける（U ＝ 見えていない枚数、a ＝ 有効牌の枚数）。
    """
    if effective <= 0 or unseen <= 0 or draws <= 0:
        return 0.0
    miss = 1.0
    for i in range(min(draws, unseen)):
        left = unseen - i
        miss *= max(0, left - effective) / left
    return 1.0 - miss

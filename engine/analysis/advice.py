"""牌効率：どれを切ると聴牌に近いか（受け入れが広いか）を比べて、1 枚を選ぶ。

ここで見るのは速さ（向聴数と受け入れ枚数）だけ。打点や守備との兼ね合いは、対局のコーチ（Phase 3）で加える。

    advise(counts14, remaining)          打牌候補の表と、おすすめ
    tile_for_discard(tiles, kind)        その種類を切るなら、どの牌を切るか（赤 5 は残す）

切った牌の評価（おすすめと比べてどうだったか）は engine/coach.py にある。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.analysis.ukeire import DiscardOption, discard_options
from engine.tiles import is_honor_kind, is_red, kind_of, number_of_kind


@dataclass(frozen=True)
class Advice:
    options: tuple[DiscardOption, ...]      # 打牌候補（良い順）
    best: tuple[DiscardOption, ...]         # いちばん良い候補（向聴数と受け入れ枚数が同じものは、すべて含む）
    pick: DiscardOption                     # best の中から 1 つ選ぶなら（使いにくい牌から切る）

    @property
    def shanten(self) -> int:
        """最善の打牌をしたあとの向聴数"""
        return self.pick.shanten

    def option(self, kind: int) -> DiscardOption | None:
        return next((o for o in self.options if o.kind == kind), None)


def loose_rank(kind: int, *, value_kinds: Sequence[int] = (), dora_kinds: Sequence[int] = ()) -> tuple[int, int]:
    """受け入れが同じ候補の中で、先に切る順番（小さいほど先）。

    迷ったら使いにくい牌から切る、という基本の順：
        役牌でない字牌 → 役牌の字牌 → 1・9 → 2・8 → 3〜7
    ドラは打点になるので、なるべく残す（順番を後ろにする）。
    """
    if is_honor_kind(kind):
        rank = 1 if kind in value_kinds else 0
    else:
        distance = min(number_of_kind(kind) - 1, 9 - number_of_kind(kind))    # 端からの距離（1・9 が 0）
        rank = 2 + min(distance, 2)
    if kind in dora_kinds:
        rank += 10
    return (rank, kind)


def advise(counts: Sequence[int], remaining: Sequence[int], *, value_kinds: Sequence[int] = (), dora_kinds: Sequence[int] = ()) -> Advice:
    """14 枚（副露があれば 14 − 3n 枚）の手で、どれを切るのがよいかを比べる"""
    options = discard_options(counts, remaining)
    top = options[0]
    best = tuple(o for o in options if (o.reach, o.total) == (top.reach, top.total))
    pick = min(best, key=lambda o: loose_rank(o.kind, value_kinds=value_kinds, dora_kinds=dora_kinds))
    return Advice(tuple(options), best, pick)


def tile_for_discard(tiles: Sequence[int], kind: int, *, aka: bool = True, drawn: int | None = None) -> int:
    """手牌（牌ID）の中から、その種類を切るときの 1 枚を選ぶ。

    赤 5 はドラなので、赤でない同じ牌があればそちらを切る。どちらでもよいときは、
    ツモ牌（drawn）がその種類ならツモ牌を、そうでなければ並びのいちばん後ろの牌を選ぶ。
    """
    same = [t for t in tiles if kind_of(t) == kind]
    if not same:
        raise ValueError(f"手牌にない種類です: {kind}")
    plain = [t for t in same if not is_red(t, aka=aka)] or same
    return drawn if drawn in plain else plain[-1]

"""副露（フーロ）: 鳴いてさらした面子と、暗槓。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from engine.tiles import kind_of, suit_of_kind


class MeldType(StrEnum):
    CHI = "chi"         # チー（順子）
    PON = "pon"         # ポン（明刻）
    ANKAN = "ankan"     # 暗槓（自分の 4 枚でカン。門前は崩れない）
    MINKAN = "minkan"   # 大明槓（他家の捨て牌でカン）
    KAKAN = "kakan"     # 加槓（ポンした牌に 4 枚目を加える）


class MeldError(ValueError):
    """面子として成り立たない牌の組み合わせ"""


@dataclass(frozen=True)
class Meld:
    type: MeldType
    tiles: tuple[int, ...]            # 牌ID（チー・ポンは 3 枚、カンは 4 枚）
    called_tile: int | None = None    # 鳴いた牌（暗槓は None）

    def __post_init__(self) -> None:
        # 牌は小さい順に並べて持つ（判定ライブラリは、チーの 3 枚が並んでいることを前提にする。
        # 鳴いた牌がどれかは called_tile で分かり、卓に置く並びは display_order で作る）
        object.__setattr__(self, "tiles", tuple(sorted(self.tiles)))
        kinds = sorted(kind_of(t) for t in self.tiles)
        if len(set(self.tiles)) != len(self.tiles):
            raise MeldError(f"同じ牌IDが重なっています: {self.tiles}")
        if self.type is MeldType.CHI:
            first = kinds[0] if kinds else -1
            ok = (
                len(kinds) == 3
                and kinds == [first, first + 1, first + 2]
                and suit_of_kind(first) != "z"
                and suit_of_kind(first) == suit_of_kind(first + 2)
            )
            if not ok:
                raise MeldError(f"チーは同じ色の連続した 3 枚です: {self.tiles}")
        else:
            size = 3 if self.type is MeldType.PON else 4
            if len(kinds) != size or len(set(kinds)) != 1:
                raise MeldError(f"{self.type.value} は同じ牌 {size} 枚です: {self.tiles}")
        if self.called_tile is not None and self.called_tile not in self.tiles:
            raise MeldError("鳴いた牌が面子に含まれていません")
        if self.type is MeldType.ANKAN and self.called_tile is not None:
            raise MeldError("暗槓に鳴いた牌はありません")

    @property
    def is_open(self) -> bool:
        """門前を崩す副露か（暗槓だけが False）"""
        return self.type is not MeldType.ANKAN

    @property
    def is_kan(self) -> bool:
        return self.type in (MeldType.ANKAN, MeldType.MINKAN, MeldType.KAKAN)

    @property
    def first_kind(self) -> int:
        """面子の先頭の牌の種類（順子は一番小さい数、刻子・槓子はその牌）"""
        return min(kind_of(t) for t in self.tiles)


def chi(tiles: tuple[int, ...] | list[int], called_tile: int | None = None) -> Meld:
    return Meld(MeldType.CHI, tuple(tiles), called_tile)


def pon(tiles: tuple[int, ...] | list[int], called_tile: int | None = None) -> Meld:
    return Meld(MeldType.PON, tuple(tiles), called_tile)


def ankan(tiles: tuple[int, ...] | list[int]) -> Meld:
    return Meld(MeldType.ANKAN, tuple(tiles))


def minkan(tiles: tuple[int, ...] | list[int], called_tile: int | None = None) -> Meld:
    return Meld(MeldType.MINKAN, tuple(tiles), called_tile)


def kakan(tiles: tuple[int, ...] | list[int], called_tile: int | None = None) -> Meld:
    return Meld(MeldType.KAKAN, tuple(tiles), called_tile)


def display_order(meld: Meld, source: int | None = None, added: int | None = None) -> tuple[tuple[int, bool, bool], ...]:
    """卓に置くときの並び：（牌ID, 横向きか, 裏向きか）の列（左から）。

    source は、鳴いた牌を切った人が、鳴いた人から見てどこにいるか（1 ＝ 下家、2 ＝ 対面、3 ＝ 上家）。
    鳴いた牌は横向きにして、上家からなら左端、対面からなら真ん中（大明槓は左から 2 枚目）、下家からなら右端に置く。
    加槓で足した牌は、横向きの牌の隣に、もう 1 枚横向きで置く（本来は上に重ねる。小さい画面で見やすいように並べる）。
    暗槓は、両端の 2 枚を裏向きにする。
    """
    if meld.type is MeldType.ANKAN:
        tiles = sorted(meld.tiles)
        return tuple((t, False, i in (0, len(tiles) - 1)) for i, t in enumerate(tiles))
    called = meld.called_tile
    rest = sorted(t for t in meld.tiles if t != called and t != added)
    if called is None:
        return tuple((t, False, False) for t in sorted(meld.tiles))
    side = [(called, True, False)] + ([(added, True, False)] if added is not None else [])
    upright = [(t, False, False) for t in rest]
    if meld.type is MeldType.CHI or source == 3:
        return tuple(side + upright)
    if source == 1:
        return tuple(upright + side)
    middle = 1
    return tuple(upright[:middle] + side + upright[middle:])

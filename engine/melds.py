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
        object.__setattr__(self, "tiles", tuple(self.tiles))
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

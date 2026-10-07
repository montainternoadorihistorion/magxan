"""和了の状況（どんな手で、どうやって和了ったか）。点数計算への入力。"""
from __future__ import annotations

from dataclasses import dataclass

from engine.melds import Meld
from engine.tiles import EAST, NORTH, kind_of


class ContextError(ValueError):
    """和了の状況として成り立たない指定"""


@dataclass(frozen=True)
class WinContext:
    #: 門前の牌（和了牌を含む）。副露が n 組なら 14 − 3n 枚
    closed_tiles: tuple[int, ...]
    #: 和了牌（closed_tiles に含まれる牌ID）
    win_tile: int
    #: ツモ和了なら True、ロン和了なら False
    is_tsumo: bool
    #: 自風（27 = 東 … 30 = 北）。東なら親
    seat_wind: int = EAST
    #: 場風（27 = 東 … 30 = 北）
    round_wind: int = EAST
    #: 副露（暗槓を含む）
    melds: tuple[Meld, ...] = ()

    riichi: bool = False           # 立直している
    double_riichi: bool = False    # ダブル立直（riichi も True にする）
    ippatsu: bool = False          # 一発
    rinshan: bool = False          # 嶺上牌でのツモ和了
    chankan: bool = False          # 他家の加槓の牌でロン
    haitei: bool = False           # 最後のツモ牌でツモ和了
    houtei: bool = False           # 最後の捨て牌でロン
    tenhou: bool = False           # 親の配牌での和了
    chiihou: bool = False          # 子の最初のツモでの和了

    #: ドラ表示牌（カンドラを含む）と裏ドラ表示牌の牌ID
    dora_indicators: tuple[int, ...] = ()
    ura_indicators: tuple[int, ...] = ()

    honba: int = 0      # 本場
    kyotaku: int = 0    # 供託のリーチ棒の本数

    def __post_init__(self) -> None:
        object.__setattr__(self, "closed_tiles", tuple(self.closed_tiles))
        object.__setattr__(self, "melds", tuple(self.melds))
        object.__setattr__(self, "dora_indicators", tuple(self.dora_indicators))
        object.__setattr__(self, "ura_indicators", tuple(self.ura_indicators))
        self._validate()

    # ------------------------------------------------------------ 便利な性質

    @property
    def is_dealer(self) -> bool:
        return self.seat_wind == EAST

    @property
    def is_menzen(self) -> bool:
        """門前か（暗槓だけなら門前のまま）"""
        return not any(m.is_open for m in self.melds)

    @property
    def all_tiles(self) -> tuple[int, ...]:
        """手牌すべて（門前の牌＋副露の牌）"""
        return self.closed_tiles + tuple(t for m in self.melds for t in m.tiles)

    @property
    def win_kind(self) -> int:
        return kind_of(self.win_tile)

    # ------------------------------------------------------------ 検査

    def _validate(self) -> None:
        expected = 14 - 3 * len(self.melds)
        if len(self.closed_tiles) != expected:
            raise ContextError(f"門前の牌は {expected} 枚のはずです（{len(self.closed_tiles)} 枚）")
        tiles = self.all_tiles
        if len(set(tiles)) != len(tiles):
            raise ContextError("同じ牌IDが 2 回使われています")
        if self.win_tile not in self.closed_tiles:
            raise ContextError("和了牌が門前の牌に含まれていません")
        if not EAST <= self.seat_wind <= NORTH or not EAST <= self.round_wind <= NORTH:
            raise ContextError("自風・場風は 27（東）〜30（北）で指定します")
        if self.double_riichi and not self.riichi:
            raise ContextError("ダブル立直のときは riichi も True にします")
        if self.riichi and not self.is_menzen:
            raise ContextError("鳴いた手では立直できません")
        if self.ippatsu and not self.riichi:
            raise ContextError("一発は立直しているときだけです")
        if self.rinshan and not self.is_tsumo:
            raise ContextError("嶺上開花はツモ和了です")
        if self.chankan and self.is_tsumo:
            raise ContextError("槍槓はロン和了です")
        if self.haitei and not self.is_tsumo:
            raise ContextError("海底摸月はツモ和了です")
        if self.houtei and self.is_tsumo:
            raise ContextError("河底撈魚はロン和了です")
        if self.haitei and self.rinshan:
            raise ContextError("海底摸月と嶺上開花は同時に成立しません")
        if self.houtei and self.chankan:
            raise ContextError("河底撈魚と槍槓は同時に成立しません")
        if self.tenhou and not (self.is_dealer and self.is_tsumo and not self.melds):
            raise ContextError("天和は、親が副露なしでツモ和了したときだけです")
        if self.chiihou and not (not self.is_dealer and self.is_tsumo and not self.melds):
            raise ContextError("地和は、子が副露なしでツモ和了したときだけです")
        if self.honba < 0 or self.kyotaku < 0:
            raise ContextError("本場と供託は 0 以上です")

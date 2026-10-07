"""一人打ちの最小ループ（ツモって、1 枚切る）。

Phase 0 では実機チェック用に使う。Phase 1 で向聴数・和了判定・ツキ補正を載せて一人練習モードにする。

状態は「シード」と「切った牌の列」だけから完全に再生できる（replay）。
この形にしておくと、通信が切れてセッションが消えても、ブラウザに残した小さな記録から続きを打てる。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.tiles import sort_tiles
from engine.wall import Wall

#: 1 局でツモれる回数（4 人打ちの 1 人ぶんにほぼ相当: 70 枚 ÷ 4 人 ≒ 18）
MAX_DRAWS = 18


class SoloError(ValueError):
    """できない操作（手牌にない牌を切る、終わった局で切る、など）"""


@dataclass(frozen=True)
class SoloState:
    seed: int
    discards: tuple[int, ...]   # 切った牌ID（切った順）
    hand: tuple[int, ...]       # 手牌 13 枚（理牌済み）
    drawn: int | None           # 今ツモった牌。山が尽きて局が終わったら None

    @property
    def finished(self) -> bool:
        return self.drawn is None

    @property
    def draws_left(self) -> int:
        """このあとツモれる回数"""
        return MAX_DRAWS - len(self.discards) - (0 if self.finished else 1)

    @property
    def tiles_in_hand(self) -> tuple[int, ...]:
        """手牌 13 枚＋ツモ牌（あれば）"""
        return self.hand if self.drawn is None else (*self.hand, self.drawn)


def start(seed: int) -> SoloState:
    """配牌 13 枚を取り、最初の 1 枚をツモった状態"""
    wall = Wall.from_seed(seed)
    hand = tuple(sort_tiles(wall.dealt_hand(0)))
    return SoloState(seed=seed, discards=(), hand=hand, drawn=wall.draw())


def discard(state: SoloState, tile_id: int) -> SoloState:
    """1 枚切って、次の牌をツモる（山が尽きていれば局が終わる）"""
    if state.finished:
        raise SoloError("この局は終わっています")
    if tile_id not in state.tiles_in_hand:
        raise SoloError(f"手牌にない牌は切れません: {tile_id}")

    discards = (*state.discards, tile_id)
    hand = tuple(sort_tiles(t for t in state.tiles_in_hand if t != tile_id))
    drawn = None
    if len(discards) < MAX_DRAWS:
        wall = Wall.from_seed(state.seed)
        wall.live_drawn = len(discards)   # ここまでにツモった枚数（最初の 1 枚＋これまでに切った回数－1）
        drawn = wall.draw()
    return SoloState(seed=state.seed, discards=discards, hand=hand, drawn=drawn)


def replay(seed: int, discards: Sequence[int]) -> SoloState:
    """シードと切った牌の列から状態を作り直す"""
    state = start(seed)
    for tile_id in discards:
        state = discard(state, tile_id)
    return state

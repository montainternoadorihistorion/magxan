"""山（136 枚の並び）。

山は牌ID 0〜135 を並べ替えたリスト。どの位置が何に使われるかを固定しておく。

    位置   0〜 51   配牌（1 人 13 枚 × 4 人）。親から順に 13 枚ずつ
    位置  52〜121   ツモ山（壁牌）70 枚。前から順にツモる
    位置 122〜125   嶺上牌 4 枚（カンしたときに引く）
    位置 126〜130   ドラ表示牌 5 枚（最初の 1 枚＋カンドラ 4 枚）
    位置 131〜135   裏ドラ表示牌 5 枚

        52 + 70 + 4 + 5 + 5 = 136

実際の卓では配牌を 4 枚ずつ取るが、どの並びも等確率に混ぜてあるので、
位置の割り当て方を変えても牌の出方の確率は変わらない。

Phase 0 の時点では「混ぜる・配る・ツモる」だけを持つ。カン（嶺上ツモ・カンドラ・海底のずれ）と
ツキ補正（まだ見えていない 2 か所の入れ替え）は Phase 1 以降でここに足す。位置の割り当ては変えない。
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.rng import Rng
from engine.tiles import NUM_TILES

NUM_PLAYERS = 4
HAND_SIZE = 13

DEAL_START = 0
LIVE_START = NUM_PLAYERS * HAND_SIZE  # 52
LIVE_END = 122                        # ツモ山は [52, 122) の 70 枚
RINSHAN_START = 122                   # 嶺上牌 [122, 126)
DORA_START = 126                      # ドラ表示牌 [126, 131)
URA_START = 131                       # 裏ドラ表示牌 [131, 136)

NUM_LIVE = LIVE_END - LIVE_START      # 70
NUM_RINSHAN = DORA_START - RINSHAN_START   # 4
NUM_DORA_INDICATORS = URA_START - DORA_START   # 5
NUM_DEAD = NUM_TILES - LIVE_END       # 王牌 14 枚

WALL_STREAM = "wall"


class WallError(RuntimeError):
    """山の使い方がおかしいとき（尽きた山からツモる、など）"""


def shuffled_tiles(seed: int | str) -> list[int]:
    """シードから決まる 136 枚の並び（補正なしの素のシャッフル）"""
    tiles = list(range(NUM_TILES))
    Rng(seed, WALL_STREAM).shuffle(tiles)
    return tiles


@dataclass
class Wall:
    """1 局ぶんの山"""

    tiles: list[int]
    live_drawn: int = 0  # ツモ山から引いた枚数

    def __post_init__(self) -> None:
        self.check()

    @classmethod
    def from_seed(cls, seed: int | str) -> Wall:
        return cls(shuffled_tiles(seed))

    def check(self) -> None:
        """山が 0〜135 をちょうど 1 枚ずつ含むことを確かめる（違えばエラー）"""
        if len(self.tiles) != NUM_TILES or sorted(self.tiles) != list(range(NUM_TILES)):
            raise WallError("山が 136 枚の牌をちょうど 1 枚ずつ含んでいません")
        if not 0 <= self.live_drawn <= NUM_LIVE:
            raise WallError(f"ツモった枚数がおかしい: {self.live_drawn}")

    def dealt_hand(self, order: int) -> list[int]:
        """配牌 13 枚。order は親から数えた順番（親 = 0、南家 = 1、西家 = 2、北家 = 3）"""
        if not 0 <= order < NUM_PLAYERS:
            raise WallError(f"order は 0〜3 です: {order}")
        start = DEAL_START + order * HAND_SIZE
        return self.tiles[start:start + HAND_SIZE]

    @property
    def live_remaining(self) -> int:
        """ツモ山の残り枚数"""
        return NUM_LIVE - self.live_drawn

    def draw(self) -> int:
        """ツモ山の先頭から 1 枚引く"""
        if self.live_remaining <= 0:
            raise WallError("ツモ山が尽きています")
        tile = self.tiles[LIVE_START + self.live_drawn]
        self.live_drawn += 1
        return tile

    def dora_indicator(self, index: int = 0) -> int:
        """ドラ表示牌（index = 0 が最初の 1 枚、1〜4 がカンドラ）"""
        if not 0 <= index < NUM_DORA_INDICATORS:
            raise WallError(f"ドラ表示牌は 0〜4 番目です: {index}")
        return self.tiles[DORA_START + index]

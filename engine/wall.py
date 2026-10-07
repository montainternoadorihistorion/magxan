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

カンをすると、嶺上牌を 1 枚引き、ドラ表示牌を 1 枚めくる。王牌を 14 枚に保つため、ツモ山の最後の
1 枚が王牌に回る（その 1 枚は誰もツモらない）。だから、カン 1 回ごとにツモれる枚数が 1 枚減る。

ツキ補正が山に対してできるのは、次の 2 つだけ（どちらも「まだ誰も見ていない牌の並べ替え」）。
    permute    配る前に、決められた位置の牌どうしを並べ替える（配牌の補正）
    swap_live  これからツモる山の 2 か所を入れ替える（ツモの補正）
牌を足したり消したりする操作は無いので、同じ牌が 5 枚になることも、存在しない牌が出ることもない。
"""
from __future__ import annotations

from collections.abc import Sequence
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
    live_drawn: int = 0      # ツモ山から引いた枚数
    rinshan_drawn: int = 0   # 嶺上牌を引いた枚数（＝カンの回数）
    dora_revealed: int = 1   # めくられているドラ表示牌の枚数（最初の 1 枚＋カンドラ）
    sealed: bool = False     # 配り終えたか（配ったあとは permute できない）

    def __post_init__(self) -> None:
        self.check()

    @classmethod
    def from_seed(cls, seed: int | str) -> Wall:
        return cls(shuffled_tiles(seed))

    def copy(self) -> Wall:
        return Wall(list(self.tiles), self.live_drawn, self.rinshan_drawn, self.dora_revealed, self.sealed)

    def check(self) -> None:
        """山が 0〜135 をちょうど 1 枚ずつ含むことを確かめる（違えばエラー）"""
        if len(self.tiles) != NUM_TILES or sorted(self.tiles) != list(range(NUM_TILES)):
            raise WallError("山が 136 枚の牌をちょうど 1 枚ずつ含んでいません")
        if not 0 <= self.rinshan_drawn <= NUM_RINSHAN:
            raise WallError(f"嶺上牌を引いた枚数がおかしい: {self.rinshan_drawn}")
        if not 0 <= self.live_drawn <= NUM_LIVE - self.rinshan_drawn:
            raise WallError(f"ツモった枚数がおかしい: {self.live_drawn}")
        if not 1 <= self.dora_revealed <= NUM_DORA_INDICATORS:
            raise WallError(f"ドラ表示牌の枚数がおかしい: {self.dora_revealed}")

    # ------------------------------------------------------------ 配牌

    def deal_positions(self, order: int) -> range:
        """配牌の位置。order は親から数えた順番（親 = 0、南家 = 1、西家 = 2、北家 = 3）"""
        if not 0 <= order < NUM_PLAYERS:
            raise WallError(f"order は 0〜3 です: {order}")
        start = DEAL_START + order * HAND_SIZE
        return range(start, start + HAND_SIZE)

    def dealt_hand(self, order: int) -> list[int]:
        """配牌 13 枚"""
        return [self.tiles[p] for p in self.deal_positions(order)]

    def seal(self) -> None:
        """配り終えたことを記録する。これ以降、配牌の並べ替え（permute）はできない"""
        self.sealed = True

    # ------------------------------------------------------------ ツモ山

    @property
    def live_end(self) -> int:
        """ツモれる山の終わり（この位置は含まない）。カン 1 回ごとに 1 つ手前になる"""
        return LIVE_END - self.rinshan_drawn

    @property
    def next_live_position(self) -> int:
        """次にツモる牌の位置"""
        return LIVE_START + self.live_drawn

    @property
    def live_remaining(self) -> int:
        """ツモ山の残り枚数"""
        return self.live_end - self.next_live_position

    def draw(self) -> int:
        """ツモ山の先頭から 1 枚引く"""
        if self.live_remaining <= 0:
            raise WallError("ツモ山が尽きています")
        self.sealed = True
        tile = self.tiles[self.next_live_position]
        self.live_drawn += 1
        return tile

    # ------------------------------------------------------------ 王牌

    def draw_rinshan(self) -> int:
        """嶺上牌を 1 枚引く（カンのあと）。ツモ山の最後の 1 枚が王牌に回るので、ツモ山が 1 枚減る"""
        if self.rinshan_drawn >= NUM_RINSHAN:
            raise WallError("嶺上牌は 4 枚までです（カンは 1 局に 4 回まで）")
        if self.live_remaining <= 0:
            raise WallError("ツモ山が尽きているので、カンはできません")
        self.sealed = True
        tile = self.tiles[RINSHAN_START + self.rinshan_drawn]
        self.rinshan_drawn += 1
        return tile

    def reveal_dora(self) -> int:
        """カンドラを 1 枚めくる"""
        if self.dora_revealed >= NUM_DORA_INDICATORS:
            raise WallError("ドラ表示牌は 5 枚までです")
        tile = self.tiles[DORA_START + self.dora_revealed]
        self.dora_revealed += 1
        return tile

    def dora_indicator(self, index: int = 0) -> int:
        """ドラ表示牌（index = 0 が最初の 1 枚、1〜4 がカンドラ）"""
        if not 0 <= index < NUM_DORA_INDICATORS:
            raise WallError(f"ドラ表示牌は 0〜4 番目です: {index}")
        return self.tiles[DORA_START + index]

    @property
    def dora_indicators(self) -> list[int]:
        """めくられているドラ表示牌"""
        return self.tiles[DORA_START:DORA_START + self.dora_revealed]

    @property
    def ura_indicators(self) -> list[int]:
        """裏ドラ表示牌（めくられているドラ表示牌と同じ枚数。リーチして和了したときだけ見る）"""
        return self.tiles[URA_START:URA_START + self.dora_revealed]

    # ------------------------------------------------------------ ツキ補正のための並べ替え

    def permute(self, positions: Sequence[int], tiles: Sequence[int]) -> None:
        """配る前に、positions の位置にある牌どうしを並べ替える（牌の集まりは変えない）"""
        if self.sealed:
            raise WallError("配り終えたあとは、配牌を並べ替えられません")
        positions = list(positions)
        if len(set(positions)) != len(positions) or len(positions) != len(tiles):
            raise WallError("位置の指定がおかしい")
        if any(not (DEAL_START <= p < LIVE_END) for p in positions):
            raise WallError("王牌（嶺上牌・ドラ表示牌・裏ドラ表示牌）は並べ替えられません")
        if sorted(self.tiles[p] for p in positions) != sorted(tiles):
            raise WallError("並べ替えの前後で、牌の集まりが変わっています")
        for position, tile in zip(positions, tiles, strict=True):
            self.tiles[position] = tile

    def swap_live(self, a: int, b: int) -> None:
        """これからツモる山の 2 か所を入れ替える"""
        low, high = self.next_live_position, self.live_end
        if not (low <= a < high and low <= b < high):
            raise WallError(f"入れ替えられるのは、これからツモる牌（位置 {low}〜{high - 1}）だけです: {a}, {b}")
        self.tiles[a], self.tiles[b] = self.tiles[b], self.tiles[a]

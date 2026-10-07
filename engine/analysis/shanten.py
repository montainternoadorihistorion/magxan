"""向聴数（シャンテンすう）：聴牌までに、あと何枚の有効牌が要るか。

    -1  和了形（あがっている）
     0  聴牌（あと 1 枚であがり）
     1  一向聴（あと 1 枚で聴牌）
     n  n 向聴

数値は判定ライブラリ（mahjong）に求めてもらう。ライブラリを呼ぶのは、点数の judge.py とこのファイルだけ。
手の形は 3 種類（4 面子 1 雀頭、七対子、国士無双）あり、いちばん近い形の向聴数が、その手の向聴数になる。

ここで数えるのは「形の上での」距離。必要な牌が山に残っているかどうかは見ていない
（残り枚数は受け入れの計算 ukeire.py で数える）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mahjong.shanten import Shanten

from engine.scoring.decompose import Form

AGARI = -1
TENPAI = 0


@dataclass(frozen=True)
class ShantenInfo:
    value: int               # 手の向聴数（下の 3 つのうち最小）
    regular: int             # 4 面子 1 雀頭としての向聴数
    chiitoi: int | None      # 七対子としての向聴数（鳴いている手では None）
    kokushi: int | None      # 国士無双としての向聴数（鳴いている手では None）

    @property
    def forms(self) -> tuple[Form, ...]:
        """いちばん近い形（同じ距離なら複数）"""
        pairs = ((Form.REGULAR, self.regular), (Form.CHIITOI, self.chiitoi), (Form.KOKUSHI, self.kokushi))
        return tuple(form for form, value in pairs if value == self.value)


def shanten_of(counts: Sequence[int]) -> int:
    """門前の牌（種類ごとの枚数、長さ 34）の向聴数。

    枚数は 13 − 3n 枚（打牌の前なら 14 − 3n 枚）。n は副露の数で、枚数から自動で決まる。
    """
    return Shanten.calculate_shanten(counts)


def shanten_info(counts: Sequence[int]) -> ShantenInfo:
    """形ごとの向聴数"""
    regular = Shanten.calculate_shanten_for_regular_hand(counts)
    if sum(counts) < 13:      # 鳴いている手は、七対子と国士無双にならない
        return ShantenInfo(regular, regular, None, None)
    chiitoi = Shanten.calculate_shanten_for_chiitoitsu_hand(counts)
    kokushi = Shanten.calculate_shanten_for_kokushi_hand(counts)
    return ShantenInfo(min(regular, chiitoi, kokushi), regular, chiitoi, kokushi)


def shanten_text(value: int) -> str:
    """向聴数の呼び方"""
    if value <= AGARI:
        return "和了形"
    if value == TENPAI:
        return "聴牌"
    return f"{value} 向聴"


def shanten_meaning(value: int) -> str:
    """向聴数の意味をひとことで"""
    if value <= AGARI:
        return "あがりの形になっている。"
    if value == TENPAI:
        return "あと 1 枚であがり。"
    return f"聴牌まで、有効牌があと {value} 枚。"

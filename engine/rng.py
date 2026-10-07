"""再現できる乱数。

同じシードなら、いつ・どの環境で動かしても同じ結果になることが目的（局面の再現と検討のため）。

Python の random モジュールは「同じシードなら random() の出す列は将来のバージョンでも変わらない」
ことだけを保証している（shuffle や randrange の中身は変わり得る）。そこで、ここでは random() だけを
使い、並べ替え（シャッフル）は自前で書く。

用途ごとに独立した乱数を使うため、シードに「系統名（stream）」を組み合わせる。
    Rng(seed, "wall")   山を混ぜる
    Rng(seed, "luck")   ツキ補正の抽選
    Rng(seed, "cpu")    CPU の選択
こうしておくと、補正を変えても元の山は変わらない。
"""
from __future__ import annotations

import hashlib
import random
from collections.abc import MutableSequence, Sequence
from typing import TypeVar

T = TypeVar("T")


class Rng:
    """シードと系統名から決まる乱数列"""

    def __init__(self, seed: int | str, stream: str = "") -> None:
        digest = hashlib.sha256(f"{seed}|{stream}".encode()).digest()
        self._random = random.Random(int.from_bytes(digest[:8], "big"))

    def random(self) -> float:
        """0 以上 1 未満の一様乱数"""
        return self._random.random()

    def below(self, n: int) -> int:
        """0 以上 n 未満の整数を等確率で返す"""
        if n <= 0:
            raise ValueError(f"n は 1 以上にしてください: {n}")
        return min(int(self._random.random() * n), n - 1)

    def chance(self, probability: float) -> bool:
        """確率 probability で True"""
        return self._random.random() < probability

    def choice(self, items: Sequence[T]) -> T:
        """items から 1 つを等確率で選ぶ"""
        if not items:
            raise ValueError("空の列からは選べません")
        return items[self.below(len(items))]

    def shuffle(self, items: MutableSequence[T]) -> None:
        """items をその場で並べ替える（フィッシャー–イェーツ法。どの並びも等確率）"""
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]

"""ルールの設定。

既定値は雀魂の段位戦（4 人打ち）に合わせてある。流派で分かれるものだけを設定にする。
いまは点数計算に関わる項目だけを持つ。対局の進行に関わる項目（途中流局、飛び、連荘など）は、
対局を実装するフェーズで足す。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Rules:
    #: 赤ドラ（各色の 5 に 1 枚ずつ、計 3 枚）
    aka_dora: bool = True
    #: 喰いタン（鳴いた断么九を認める）
    kuitan: bool = True
    #: 切り上げ満貫（30 符 4 翻・60 符 3 翻を満貫にする）
    kiriage_mangan: bool = False
    #: 連風牌（場風と自風が同じ牌。東場の親の東など）を雀頭にしたときの符。2 または 4
    double_wind_pair_fu: int = 4
    #: ダブル役満（四暗刻単騎・国士無双十三面待ち・純正九蓮宝燈・大四喜を 2 倍にする）
    double_yakuman: bool = True
    #: 数え役満（13 翻以上を役満にする）。False なら三倍満まで
    kazoe_yakuman: bool = True

    def __post_init__(self) -> None:
        if self.double_wind_pair_fu not in (2, 4):
            raise ValueError(f"連風牌の雀頭の符は 2 か 4 です: {self.double_wind_pair_fu}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rules:
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**known)


#: 既定のルール（雀魂の段位戦に合わせたもの）
DEFAULT_RULES = Rules()

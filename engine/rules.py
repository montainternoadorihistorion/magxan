"""ルールの設定。

既定値は雀魂の段位戦（4 人打ち）に合わせてある。流派で分かれるものだけを設定にする。
点数計算に関わる項目と、対局の進行に関わる項目（流し満貫・途中流局・複数ロン・飛び・鳴き）がある。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_FLAGS = (
    "aka_dora",
    "kuitan",
    "kiriage_mangan",
    "double_yakuman",
    "kazoe_yakuman",
    "nagashi_mangan",
    "abortive_draws",
    "multiple_ron",
    "tobi",
    "calls",
)


@dataclass(frozen=True)
class Rules:
    # ---- 点数計算に関わること
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

    # ---- 対局の進行に関わること（engine/game.py）
    #: 流し満貫（流局のとき、捨て牌がすべて么九牌で鳴かれていなければ、満貫ぶんをもらう）
    nagashi_mangan: bool = True
    #: 途中流局（九種九牌・四風連打・四家立直・四槓散了）
    abortive_draws: bool = True
    #: 複数ロン（2 人以上が同じ牌でロンしたら、全員のあがり）。False なら、捨てた人から見て順番が先の 1 人だけ（頭ハネ）
    multiple_ron: bool = True
    #: 飛び（誰かの持ち点が 0 点より少なくなったら、そこで試合を終わる。0 点ちょうどは続ける）
    tobi: bool = True
    #: 鳴き（チー・ポン・カン）。False なら、門前だけで打つ（カンもしない。Phase 3 までの対局と同じ）
    calls: bool = True

    def __post_init__(self) -> None:
        for name in _FLAGS:
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"ルールの値は True か False です: {name}={getattr(self, name)!r}")
        fu = self.double_wind_pair_fu
        if not isinstance(fu, int) or isinstance(fu, bool) or fu not in (2, 4):
            raise ValueError(f"連風牌の雀頭の符は 2 か 4 です: {fu!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rules:
        """保存した形から作る（知らない項目は無視する）。形や値がおかしければ ValueError"""
        if not isinstance(data, dict):
            raise ValueError("ルールの記録の形が違います")
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        try:
            return cls(**known)
        except TypeError as error:          # 比べられない値（リストなど）が入っていた
            raise ValueError(f"ルールの記録の値がおかしい: {error}") from error


#: 既定のルール（雀魂の段位戦に合わせたもの）
DEFAULT_RULES = Rules()

#: ルールの違い（流派で分かれること）ではなく、練習のための切り替えの項目。
#: 「ルールの違い」のページ（data/rules.yaml）には載せない（どの流派でも、鳴きはある）
PRACTICE_SWITCHES = frozenset({"calls"})

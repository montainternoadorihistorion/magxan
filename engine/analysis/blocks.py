"""手牌を、面子・面子候補（搭子）・雀頭候補・孤立牌に分けて見る（分解図のもと）。

    面子      完成した 3 枚（順子・刻子）
    搭子      あと 1 枚で面子になる 2 枚。両面（45 → 3 か 6）、嵌張（46 → 5）、辺張（12 → 3、89 → 7）
    対子      同じ牌 2 枚。雀頭になるか、あと 1 枚で刻子になる
    孤立牌    まだ何ともつながっていない 1 枚

4 面子 1 雀頭に向けて「いちばん進んでいる分け方」を 1 つ返す。向聴数は、分け方から次の式で数えられる。

    向聴数 ＝ 8 − 2 × 面子の数 − 搭子と対子の数
    ただし、面子＋搭子＋対子（雀頭にする 1 組を除く）は 4 組までしか数えない（面子は 4 つあれば足りるので）

表示する向聴数そのものは判定ライブラリの値（shanten.py）を使う。ここの式は、同じ数になることを
テストで確かめている（同じ牌を 4 枚持っているときの細かい補正を除く）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from engine.analysis.shanten import shanten_info
from engine.scoring.decompose import KOKUSHI_KINDS, Form
from engine.tiles import kind_of, sort_tiles


class PartType(StrEnum):
    SHUNTSU = "shuntsu"     # 順子（完成）
    KOUTSU = "koutsu"       # 刻子（完成）
    TOITSU = "toitsu"       # 対子
    RYANMEN = "ryanmen"     # 両面搭子
    KANCHAN = "kanchan"     # 嵌張搭子
    PENCHAN = "penchan"     # 辺張搭子
    FLOAT = "float"         # 孤立牌（国士無双に向けた分け方では、使わない牌）
    YAOCHU = "yaochu"       # 国士無双に使う么九牌 1 枚


PART_NAMES = {
    PartType.SHUNTSU: "順子",
    PartType.KOUTSU: "刻子",
    PartType.TOITSU: "対子",
    PartType.RYANMEN: "両面",
    PartType.KANCHAN: "嵌張",
    PartType.PENCHAN: "辺張",
    PartType.FLOAT: "孤立牌",
    PartType.YAOCHU: "么九牌",
}
MENTSU_TYPES = (PartType.SHUNTSU, PartType.KOUTSU)
TAATSU_TYPES = (PartType.RYANMEN, PartType.KANCHAN, PartType.PENCHAN)


@dataclass(frozen=True)
class Part:
    type: PartType
    kinds: tuple[int, ...]      # このまとまりの牌（種類）

    @property
    def is_mentsu(self) -> bool:
        return self.type in MENTSU_TYPES

    @property
    def is_taatsu(self) -> bool:
        return self.type in TAATSU_TYPES

    @property
    def completing_kinds(self) -> tuple[int, ...]:
        """このまとまりを面子にする牌（種類）。完成した面子・孤立牌などは空。

            両面 45 → 3・6     嵌張 46 → 5     辺張 12 → 3、89 → 7     対子 55 → 5（刻子になる）
        """
        first = self.kinds[0]
        if self.type is PartType.RYANMEN:
            return (first - 1, first + 2)
        if self.type is PartType.KANCHAN:
            return (first + 1,)
        if self.type is PartType.PENCHAN:
            return (first + 2,) if first % 9 == 0 else (first - 1,)
        if self.type is PartType.TOITSU:
            return (first,)
        return ()


@dataclass(frozen=True)
class Layout:
    form: Form                   # どの形に向けた分け方か
    parts: tuple[Part, ...]
    shanten: int                 # この分け方から数えた向聴数

    def count(self, *types: PartType) -> int:
        return sum(1 for p in self.parts if p.type in types)

    def part_with(self, kind: int) -> Part | None:
        """その種類の牌を使っている、孤立牌でないまとまり（面子 → 対子 → 搭子の順で探す）。無ければ None"""
        order = (*MENTSU_TYPES, PartType.TOITSU, *TAATSU_TYPES, PartType.YAOCHU)
        found = [p for p in self.parts if kind in p.kinds and p.type in order]
        return min(found, key=lambda p: order.index(p.type)) if found else None

    def assign(self, tiles: Sequence[int]) -> tuple[tuple[int, ...], ...]:
        """まとまりごとに、実際の牌（牌ID）を割り当てる。parts と同じ順で返す。

        赤 5 は、面子・対子・搭子のほうに先に入れる（孤立牌として浮かせて見せない）。
        """
        pool: dict[int, list[int]] = {}
        for tile in sort_tiles(tiles):           # 同じ種類の中では、赤 5 が先頭に来る
            pool.setdefault(kind_of(tile), []).append(tile)
        needed = sorted(kind for part in self.parts for kind in part.kinds)
        if needed != sorted(kind_of(tile) for tile in tiles):
            raise ValueError("分け方と手牌が合いません")
        result: list[tuple[int, ...]] = [()] * len(self.parts)
        for floats in (False, True):
            for index, part in enumerate(self.parts):
                if (part.type is PartType.FLOAT) is floats:
                    result[index] = tuple(pool[kind].pop(0) for kind in part.kinds)
        return tuple(result)

    @property
    def formula(self) -> str:
        """この分け方から向聴数を数える式（文章）"""
        value = str(self.shanten).replace("-", "−")
        mentsu = self.count(*MENTSU_TYPES)
        pairs = self.count(PartType.TOITSU)
        taatsu = self.count(*TAATSU_TYPES)
        if self.form is Form.CHIITOI:
            kinds = len({p.kinds[0] for p in self.parts})
            short = max(0, 7 - kinds)
            extra = f" ＋ 種類の不足 {short}" if short else ""
            return f"七対子まで：6 − 対子 {pairs} 組{extra} ＝ {value}"
        if self.form is Form.KOKUSHI:
            yaochu = self.count(PartType.YAOCHU) + pairs
            return f"国士無双まで：13 − 么九牌 {yaochu} 種類 − 対子 {pairs} 組 ＝ {value}"
        text = f"8 − 2 × 面子 {mentsu} 組 − 搭子 {taatsu} 組 − 対子 {pairs} 組"
        over = mentsu + taatsu + max(pairs - 1, 0) - 4
        if over > 0:
            text += f" ＋ 数えすぎ {over} 組"
        return f"{text} ＝ {value}"

    @property
    def formula_note(self) -> str:
        """式の補足（面子候補が多すぎるとき）。無ければ空"""
        if self.form is not Form.REGULAR:
            return ""
        mentsu = self.count(*MENTSU_TYPES)
        over = mentsu + self.count(*TAATSU_TYPES) + max(self.count(PartType.TOITSU) - 1, 0) - 4
        if over <= 0:
            return ""
        return f"面子は 4 組あれば足りるので、面子と面子候補（搭子・対子。雀頭にする 1 組は除く）は合わせて 4 組までしか数えない。余った {over} 組ぶんを足し戻す。"


# ---------------------------------------------------------------- 1 色ぶんの分け方

# 1 色（9 種類）の分け方の「成績」: (面子, 対子, 搭子, 両面搭子) → その成績になる分け方の 1 つ
_Signature = tuple[int, int, int, int]


@lru_cache(maxsize=100_000)
def _suit_options(counts: tuple[int, ...]) -> tuple[tuple[_Signature, tuple[tuple[PartType, int], ...]], ...]:
    """数牌 1 色ぶんの枚数（長さ 9）を分ける方法を、成績ごとに 1 つずつ返す。

    いちばん小さい数の牌から順に「刻子・順子・対子・搭子・孤立牌のどれに使うか」を決め、残りは同じ関数に任せる。
    残りの枚数が同じなら結果も同じなので、結果を覚えておいて使い回す（同じ計算をくり返さない）。
    """
    first = next((i for i in range(9) if counts[i]), None)
    if first is None:
        return (((0, 0, 0, 0), ()),)

    found: dict[_Signature, tuple[tuple[PartType, int], ...]] = {}

    def take(part_type: PartType, used: tuple[int, ...], gain: _Signature) -> None:
        rest = list(counts)
        for k in used:
            rest[k] -= 1
        for (mentsu, pairs, taatsu, ryanmen), parts in _suit_options(tuple(rest)):
            signature = (mentsu + gain[0], pairs + gain[1], taatsu + gain[2], ryanmen + gain[3])
            found.setdefault(signature, ((part_type, first), *parts))

    i = first
    if counts[i] >= 3:
        take(PartType.KOUTSU, (i, i, i), (1, 0, 0, 0))
    if i <= 6 and counts[i + 1] and counts[i + 2]:
        take(PartType.SHUNTSU, (i, i + 1, i + 2), (1, 0, 0, 0))
    if counts[i] >= 2:
        take(PartType.TOITSU, (i, i), (0, 1, 0, 0))
    if i <= 7 and counts[i + 1]:
        if i in (0, 7):             # 12 と 89 は辺張（片側しか待てない）
            take(PartType.PENCHAN, (i, i + 1), (0, 0, 1, 0))
        else:
            take(PartType.RYANMEN, (i, i + 1), (0, 0, 1, 1))
    if i <= 6 and counts[i + 2]:
        take(PartType.KANCHAN, (i, i + 2), (0, 0, 1, 0))
    take(PartType.FLOAT, (i,), (0, 0, 0, 0))
    return tuple(found.items())


def _part(part_type: PartType, first: int) -> Part:
    if part_type is PartType.SHUNTSU:
        return Part(part_type, (first, first + 1, first + 2))
    if part_type is PartType.KOUTSU:
        return Part(part_type, (first,) * 3)
    if part_type is PartType.TOITSU:
        return Part(part_type, (first,) * 2)
    if part_type in (PartType.RYANMEN, PartType.PENCHAN):
        return Part(part_type, (first, first + 1))
    if part_type is PartType.KANCHAN:
        return Part(part_type, (first, first + 2))
    return Part(part_type, (first,))


def formula_shanten(mentsu: int, pairs: int, taatsu: int) -> int:
    """分け方の成績から向聴数を数える（4 面子 1 雀頭に向けて）"""
    value = 8 - 2 * mentsu - taatsu - pairs
    candidates = mentsu + taatsu + (pairs - 1 if pairs else 0)
    if candidates > 4:
        value += candidates - 4
    return value


def regular_layout(counts: Sequence[int]) -> Layout:
    """4 面子 1 雀頭に向けて、いちばん進んでいる分け方（同点なら、面子・雀頭・両面が多いもの）"""
    melds = (14 - sum(counts)) // 3          # 副露の数（そのぶん、手の中で作る面子が少なくて済む）
    honors: list[Part] = []
    honor_mentsu = honor_pairs = 0
    for kind in range(27, 34):
        n = counts[kind]
        if n >= 3:
            honors.append(Part(PartType.KOUTSU, (kind,) * 3))
            honor_mentsu += 1
            n -= 3
        if n == 2:
            honors.append(Part(PartType.TOITSU, (kind,) * 2))
            honor_pairs += 1
        elif n == 1:
            honors.append(Part(PartType.FLOAT, (kind,)))

    suits = [_suit_options(tuple(counts[start:start + 9])) for start in (0, 9, 18)]
    best_key = None
    best_choice = None
    for man in suits[0]:
        for pin in suits[1]:
            for sou in suits[2]:
                mentsu = melds + honor_mentsu + man[0][0] + pin[0][0] + sou[0][0]
                pairs = honor_pairs + man[0][1] + pin[0][1] + sou[0][1]
                taatsu = man[0][2] + pin[0][2] + sou[0][2]
                ryanmen = man[0][3] + pin[0][3] + sou[0][3]
                key = (formula_shanten(mentsu, pairs, taatsu), -mentsu, -min(pairs, 1), -ryanmen, -taatsu - pairs)
                if best_key is None or key < best_key:
                    best_key, best_choice = key, (man, pin, sou)
    assert best_key is not None and best_choice is not None
    parts: list[Part] = []
    for start, (_, suit_parts) in zip((0, 9, 18), best_choice, strict=True):
        parts.extend(_part(part_type, start + first) for part_type, first in suit_parts)
    parts.extend(honors)
    parts.sort(key=lambda p: (p.kinds[0], p.type.value))
    return Layout(Form.REGULAR, tuple(parts), best_key[0])


def chiitoi_layout(counts: Sequence[int]) -> Layout:
    """七対子に向けた分け方（対子と、対子になっていない牌）"""
    parts: list[Part] = []
    pairs = kinds = 0
    for kind in range(34):
        n = counts[kind]
        if not n:
            continue
        kinds += 1
        if n >= 2:
            parts.append(Part(PartType.TOITSU, (kind, kind)))
            pairs += 1
            n -= 2
        parts.extend(Part(PartType.FLOAT, (kind,)) for _ in range(n))
    shanten = -1 if pairs == 7 else 6 - pairs + max(0, 7 - kinds)
    return Layout(Form.CHIITOI, tuple(parts), shanten)


def kokushi_layout(counts: Sequence[int]) -> Layout:
    """国士無双に向けた分け方（使える么九牌と、使えない牌）"""
    parts: list[Part] = []
    have = 0
    pair_used = False
    for kind in range(34):
        n = counts[kind]
        if not n:
            continue
        if kind in KOKUSHI_KINDS:
            have += 1
            if n >= 2 and not pair_used:
                parts.append(Part(PartType.TOITSU, (kind, kind)))
                pair_used = True
                n -= 2
            else:
                parts.append(Part(PartType.YAOCHU, (kind,)))
                n -= 1
        parts.extend(Part(PartType.FLOAT, (kind,)) for _ in range(n))
    return Layout(Form.KOKUSHI, tuple(parts), 13 - have - (1 if pair_used else 0))


def best_layout(counts: Sequence[int]) -> Layout:
    """いちばん近い形に向けた分け方。同じ距離なら 4 面子 1 雀頭を優先する"""
    info = shanten_info(counts)
    if Form.REGULAR in info.forms:
        return regular_layout(counts)
    if Form.CHIITOI in info.forms:
        return chiitoi_layout(counts)
    return kokushi_layout(counts)

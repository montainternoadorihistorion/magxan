"""和了形の分解（どの牌をどの面子・雀頭として読むか）と、待ちの形。

同じ 14 枚でも、読み方が複数あることがある（例: 111222333 は「刻子 3 つ」とも「順子 3 つ」とも読める）。
ここではあり得る読み方をすべて挙げる。どれを採用するか（高点法）は explain.py が決める。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from engine.melds import Meld, MeldType
from engine.tiles import (
    counts34,
    is_honor_kind,
    is_terminal_kind,
    is_yaochu_kind,
    name_of_kind,
    number_of_kind,
    suit_of_kind,
)

KOKUSHI_KINDS = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
_SUIT_KANJI = {"m": "萬", "p": "筒", "s": "索"}


class BlockType(StrEnum):
    SHUNTSU = "shuntsu"   # 順子（同じ色の連続した 3 枚）
    KOUTSU = "koutsu"     # 刻子（同じ牌 3 枚）
    KANTSU = "kantsu"     # 槓子（同じ牌 4 枚）
    TOITSU = "toitsu"     # 対子（同じ牌 2 枚。雀頭）


class WaitType(StrEnum):
    RYANMEN = "ryanmen"   # 両面（連続した 2 枚の両側を待つ）
    KANCHAN = "kanchan"   # 嵌張（順子の真ん中を待つ）
    PENCHAN = "penchan"   # 辺張（12 で 3、89 で 7 を待つ）
    TANKI = "tanki"       # 単騎（雀頭の片割れを待つ）
    SHANPON = "shanpon"   # 双碰（対子 2 組のどちらかが刻子になるのを待つ）
    KOKUSHI = "kokushi"   # 国士無双の待ち
    KOKUSHI_13 = "kokushi13"   # 国士無双の十三面待ち


WAIT_NAMES = {
    WaitType.RYANMEN: "両面（リャンメン）",
    WaitType.KANCHAN: "嵌張（カンチャン）",
    WaitType.PENCHAN: "辺張（ペンチャン）",
    WaitType.TANKI: "単騎（タンキ）",
    WaitType.SHANPON: "双碰（シャンポン）",
    WaitType.KOKUSHI: "国士無双の単騎",
    WaitType.KOKUSHI_13: "国士無双の十三面",
}


class Form(StrEnum):
    REGULAR = "regular"     # 4 面子 1 雀頭
    CHIITOI = "chiitoi"     # 七対子
    KOKUSHI = "kokushi"     # 国士無双


@dataclass(frozen=True, order=True)
class Block:
    """面子 1 つ、または雀頭"""

    first: int                 # 先頭の牌の種類（順子は一番小さい数）
    type: BlockType
    open: bool = False         # 鳴いてさらした面子か（暗槓は False）
    ron_completed: bool = False   # ロンの牌で完成した刻子（符と三暗刻・四暗刻では明刻として扱う）

    @property
    def kinds(self) -> tuple[int, ...]:
        if self.type is BlockType.SHUNTSU:
            return (self.first, self.first + 1, self.first + 2)
        size = {BlockType.KOUTSU: 3, BlockType.KANTSU: 4, BlockType.TOITSU: 2}[self.type]
        return (self.first,) * size

    @property
    def is_mentsu(self) -> bool:
        return self.type is not BlockType.TOITSU

    @property
    def is_set(self) -> bool:
        """刻子か槓子か"""
        return self.type in (BlockType.KOUTSU, BlockType.KANTSU)

    @property
    def is_concealed_set(self) -> bool:
        """暗刻・暗槓として数えられるか（鳴いておらず、ロンで完成したのでもない刻子・槓子）"""
        return self.is_set and not self.open and not self.ron_completed

    @property
    def has_yaochu(self) -> bool:
        return any(is_yaochu_kind(k) for k in self.kinds)

    @property
    def has_terminal(self) -> bool:
        return any(is_terminal_kind(k) for k in self.kinds)

    @property
    def is_honor(self) -> bool:
        return is_honor_kind(self.first)

    @property
    def suit(self) -> str:
        return suit_of_kind(self.first)

    def text(self) -> str:
        """文章の中で面子を指すときの書き方（例: 234萬、888筒、東東東、55索）"""
        if self.is_honor:
            return name_of_kind(self.first) * len(self.kinds)
        digits = "".join(str(number_of_kind(k)) for k in self.kinds)
        return digits + _SUIT_KANJI[self.suit]


@dataclass(frozen=True)
class Interpretation:
    """和了形の読み方 1 つ（分解と、和了牌がどこに入ったか）"""

    form: Form
    blocks: tuple[Block, ...]     # 通常形: 面子 4 つ＋雀頭 1 つ。七対子: 対子 7 つ。国士無双: 空
    win_index: int                # 和了牌が入ったブロックの位置（国士無双は -1）
    wait: WaitType

    @property
    def mentsu(self) -> tuple[Block, ...]:
        return tuple(b for b in self.blocks if b.is_mentsu)

    @property
    def pair(self) -> Block | None:
        pairs = [b for b in self.blocks if b.type is BlockType.TOITSU]
        return pairs[0] if self.form is Form.REGULAR and pairs else None

    @property
    def win_block(self) -> Block | None:
        return self.blocks[self.win_index] if self.win_index >= 0 else None


# ---------------------------------------------------------------- 分解


def meld_block(meld: Meld) -> Block:
    """副露を Block にする"""
    if meld.type is MeldType.CHI:
        return Block(meld.first_kind, BlockType.SHUNTSU, open=True)
    if meld.type is MeldType.PON:
        return Block(meld.first_kind, BlockType.KOUTSU, open=True)
    return Block(meld.first_kind, BlockType.KANTSU, open=meld.is_open)


def _closed_decompositions(counts: list[int], mentsu_needed: int) -> list[tuple[Block, ...]]:
    """門前の牌（種類ごとの枚数）を「面子 mentsu_needed 個＋雀頭 1 つ」に分ける読み方をすべて返す"""
    results: set[tuple[Block, ...]] = set()

    def walk(start: int, blocks: list[Block], has_pair: bool) -> None:
        kind = next((k for k in range(start, 34) if counts[k]), None)
        if kind is None:
            if has_pair and sum(b.is_mentsu for b in blocks) == mentsu_needed:
                results.add(tuple(sorted(blocks)))
            return
        if counts[kind] >= 3:
            counts[kind] -= 3
            blocks.append(Block(kind, BlockType.KOUTSU))
            walk(kind, blocks, has_pair)
            blocks.pop()
            counts[kind] += 3
        if counts[kind] >= 2 and not has_pair:
            counts[kind] -= 2
            blocks.append(Block(kind, BlockType.TOITSU))
            walk(kind, blocks, True)
            blocks.pop()
            counts[kind] += 2
        if not is_honor_kind(kind) and number_of_kind(kind) <= 7 and counts[kind + 1] and counts[kind + 2]:
            for k in (kind, kind + 1, kind + 2):
                counts[k] -= 1
            blocks.append(Block(kind, BlockType.SHUNTSU))
            walk(kind, blocks, has_pair)
            blocks.pop()
            for k in (kind, kind + 1, kind + 2):
                counts[k] += 1

    walk(0, [], False)
    return sorted(results)


def regular_decompositions(closed_tiles: Sequence[int], melds: Sequence[Meld]) -> list[tuple[Block, ...]]:
    """4 面子 1 雀頭としての読み方をすべて返す（副露はそのまま面子として加える）"""
    fixed = [meld_block(m) for m in melds]
    needed = 4 - len(fixed)
    if needed < 0:
        return []
    closed = _closed_decompositions(counts34(closed_tiles), needed)
    return [tuple(sorted([*blocks, *fixed])) for blocks in closed]


def chiitoi_decomposition(closed_tiles: Sequence[int], melds: Sequence[Meld]) -> tuple[Block, ...] | None:
    """七対子としての読み方（7 種類の対子）。成り立たなければ None。同じ牌 4 枚は対子 2 組に数えない"""
    if melds:
        return None
    counts = counts34(closed_tiles)
    if any(c not in (0, 2) for c in counts) or sum(1 for c in counts if c == 2) != 7:
        return None
    return tuple(Block(k, BlockType.TOITSU) for k in range(34) if counts[k] == 2)


def is_kokushi(closed_tiles: Sequence[int], melds: Sequence[Meld]) -> bool:
    """国士無双の形か（13 種類の么九牌が 1 枚ずつ＋そのどれか 1 枚）"""
    if melds:
        return False
    counts = counts34(closed_tiles)
    if sum(counts) != 14 or any(counts[k] for k in range(34) if k not in KOKUSHI_KINDS):
        return False
    return all(counts[k] >= 1 for k in KOKUSHI_KINDS)


# ---------------------------------------------------------------- 待ちの形


def _sequence_wait(block: Block, win_kind: int) -> WaitType:
    position = win_kind - block.first          # 0 = 一番小さい数、1 = 真ん中、2 = 一番大きい数
    if position == 1:
        return WaitType.KANCHAN
    low_number = number_of_kind(block.first)
    if (position == 2 and low_number == 1) or (position == 0 and low_number == 7):
        return WaitType.PENCHAN                # 12 で 3 を待つ、89 で 7 を待つ
    return WaitType.RYANMEN


def interpretations(
    closed_tiles: Sequence[int],
    melds: Sequence[Meld],
    win_kind: int,
    *,
    is_tsumo: bool,
) -> list[Interpretation]:
    """和了形の読み方をすべて返す（分解 × 和了牌がどのブロックに入ったか）。和了形でなければ空"""
    results: list[Interpretation] = []
    seen: set[tuple] = set()

    for blocks in regular_decompositions(closed_tiles, melds):
        for index, block in enumerate(blocks):
            if block.open or block.type is BlockType.KANTSU or win_kind not in block.kinds:
                continue   # 鳴いた面子や槓子に和了牌は入らない
            if block.type is BlockType.TOITSU:
                wait = WaitType.TANKI
            elif block.type is BlockType.KOUTSU:
                wait = WaitType.SHANPON
            else:
                wait = _sequence_wait(block, win_kind)
            final = list(blocks)
            if block.type is BlockType.KOUTSU and not is_tsumo:
                final[index] = Block(block.first, block.type, ron_completed=True)
            key = (tuple(final), block.type, block.first, wait)
            if key in seen:
                continue   # 同じ順子が 2 組あるときなど、同じ読み方を重ねて数えない
            seen.add(key)
            results.append(Interpretation(Form.REGULAR, tuple(final), index, wait))

    pairs = chiitoi_decomposition(closed_tiles, melds)
    if pairs is not None:
        index = next(i for i, b in enumerate(pairs) if b.first == win_kind)
        results.append(Interpretation(Form.CHIITOI, pairs, index, WaitType.TANKI))

    if is_kokushi(closed_tiles, melds):
        counts = counts34(closed_tiles)
        wait = WaitType.KOKUSHI_13 if counts[win_kind] == 2 else WaitType.KOKUSHI
        results.append(Interpretation(Form.KOKUSHI, (), -1, wait))

    return results

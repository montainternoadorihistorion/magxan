"""解説の文章で牌や待ちを書くための小さな部品"""
from __future__ import annotations

from collections.abc import Iterable

from engine.scoring.decompose import WAIT_NAMES, BlockType, Form, Interpretation, WaitType
from engine.tiles import is_honor_kind, name_of_kind, number_of_kind, suit_of_kind

_SUIT_KANJI = {"m": "萬", "p": "筒", "s": "索"}
SUIT_NAMES = {"m": "萬子", "p": "筒子", "s": "索子"}


def kind_text(kind: int) -> str:
    """牌 1 種類の短い書き方（例: 5索、東）"""
    if is_honor_kind(kind):
        return name_of_kind(kind)
    return f"{number_of_kind(kind)}{_SUIT_KANJI[suit_of_kind(kind)]}"


def kinds_text(kinds: Iterable[int]) -> str:
    """牌の並びの短い書き方。同じ色が続くときは数字をまとめる（例: 67索、東東）"""
    kinds = list(kinds)
    if not kinds:
        return ""
    if all(not is_honor_kind(k) for k in kinds) and len({suit_of_kind(k) for k in kinds}) == 1:
        return "".join(str(number_of_kind(k)) for k in kinds) + _SUIT_KANJI[suit_of_kind(kinds[0])]
    return "".join(kind_text(k) for k in kinds)


def join(items: Iterable[str]) -> str:
    return "・".join(items)


def wait_text(interp: Interpretation, win_kind: int) -> str:
    """待ちの形を文章にする（例: 67索 で 5索・8索 を待つ両面待ち）"""
    if interp.form is Form.KOKUSHI:
        if interp.wait is WaitType.KOKUSHI_13:
            return "13 種類の么九牌が 1 枚ずつそろい、どれが来てもあがれる十三面待ち"
        return f"{kind_text(win_kind)} だけが足りない国士無双の待ち"
    block = interp.win_block
    assert block is not None
    name = WAIT_NAMES[interp.wait].split("（")[0]
    if interp.wait is WaitType.TANKI:
        return f"{kind_text(win_kind)} 1 枚で同じ牌を待つ{name}待ち"
    if interp.wait is WaitType.SHANPON:
        pair = interp.pair
        other = f" と {pair.text()}" if pair is not None else ""
        return f"{kinds_text([win_kind, win_kind])}{other} のどちらかが刻子になるのを待つ{name}待ち"
    assert block.type is BlockType.SHUNTSU
    held = [k for k in block.kinds if k != win_kind]
    if interp.wait is WaitType.RYANMEN:
        low, high = held[0] - 1, held[1] + 1
        return f"{kinds_text(held)} で {kind_text(low)}・{kind_text(high)} を待つ{name}待ち"
    return f"{kinds_text(held)} で {kind_text(win_kind)} を待つ{name}待ち"

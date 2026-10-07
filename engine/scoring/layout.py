"""読み方（分解）の各ブロックに、実際の牌を割り当てる。

Interpretation は牌の「種類」で書かれている。画面に分解図を描くには、どの牌（牌ID）がどのブロックに
入るかが要る（赤5や、和了牌を図の中で示すため）。

    block_tiles(interp, ctx)  →  ブロックごとの牌ID（interp.blocks と同じ順）

和了牌は、その読み方で和了牌が入ったブロックに必ず割り当てる。
"""
from __future__ import annotations

from engine.melds import Meld, MeldType
from engine.scoring.context import WinContext
from engine.scoring.decompose import Block, BlockType, Form, Interpretation
from engine.tiles import kind_of, sort_tiles


def _meld_matches(block: Block, meld: Meld) -> bool:
    if meld.first_kind != block.first:
        return False
    if block.type is BlockType.SHUNTSU:
        return meld.type is MeldType.CHI and block.open
    if block.type is BlockType.KOUTSU:
        return meld.type is MeldType.PON and block.open
    if block.type is BlockType.KANTSU:
        return meld.is_kan and meld.is_open == block.open
    return False


def block_tiles(interp: Interpretation, ctx: WinContext) -> tuple[tuple[int, ...], ...]:
    """各ブロックの牌ID。国士無双（ブロックなし）のときは空"""
    if interp.form is Form.KOKUSHI:
        return ()

    melds = list(ctx.melds)
    by_kind: dict[int, list[int]] = {}
    for tile in sort_tiles(ctx.closed_tiles):
        if tile != ctx.win_tile:
            by_kind.setdefault(kind_of(tile), []).append(tile)

    result: list[tuple[int, ...]] = []
    for index, block in enumerate(interp.blocks):
        meld = next((m for m in melds if _meld_matches(block, m)), None)
        if meld is not None:
            melds.remove(meld)
            result.append(tuple(sort_tiles(meld.tiles)))
            continue
        tiles: list[int] = []
        win_pending = index == interp.win_index
        for kind in block.kinds:
            if win_pending and kind == ctx.win_kind:
                tiles.append(ctx.win_tile)
                win_pending = False
            else:
                tiles.append(by_kind[kind].pop(0))
        result.append(tuple(tiles))
    return tuple(result)


def meld_of_block(interp: Interpretation, ctx: WinContext, index: int) -> Meld | None:
    """そのブロックが副露（暗槓を含む）なら、対応する Meld を返す"""
    melds = list(ctx.melds)
    for i, block in enumerate(interp.blocks):
        meld = next((m for m in melds if _meld_matches(block, m)), None)
        if meld is not None:
            melds.remove(meld)
        if i == index:
            return meld
    return None

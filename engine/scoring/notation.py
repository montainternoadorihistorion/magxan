"""和了の状況を文字で手短に書くための入口。

テストや役図鑑の例題で使う。牌は mpsz 表記（engine.tiles.parse_tiles）で書く。

    make_context("123456m234p6785s", "5s", is_tsumo=True)             # 手牌 13 枚 ＋ 和了牌
    make_context("23488m567p345s", "6s", melds=["pon 888m"])          # 副露は「種類 牌」で書く
    make_context("123m456p78s22p", "9s", melds=["ankan 1111z"], dora="4s", riichi=True)

手牌・副露・ドラ表示牌をまとめて 1 組の牌として割り当てるので、同じ牌を 5 枚使うような
あり得ない状況は書けない（エラーになる）。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from engine.melds import Meld, MeldType
from engine.scoring.context import WinContext
from engine.tiles import TileError, code_of, format_tiles, parse_tiles

_MELD_TYPES = {t.value: t for t in MeldType}


def parse_meld(text: str, *, aka: bool = True, used: set[int] | None = None) -> Meld:
    """「pon 888m」「chi 678m」「ankan 1111z」「minkan 5555s」「kakan 3333p」を Meld にする"""
    parts = text.split()
    if len(parts) != 2 or parts[0] not in _MELD_TYPES:
        raise TileError(f"副露は「種類 牌」で書きます（例: pon 888m）: {text!r}")
    used = set() if used is None else used
    tiles = parse_tiles(parts[1], aka=aka, used=used)
    used.update(tiles)
    return Meld(_MELD_TYPES[parts[0]], tuple(tiles))


def make_context(
    hand: str,
    win: str,
    *,
    melds: Sequence[str] = (),
    dora: str = "",
    ura: str = "",
    aka: bool = True,
    **flags: Any,
) -> WinContext:
    """手牌（和了牌を含まない）と和了牌から WinContext を作る。

    hand   和了る前の門前の牌（副露が n 組なら 13 − 3n 枚）
    win    和了牌 1 枚
    melds  副露（暗槓を含む）
    dora   ドラ表示牌（カンドラも続けて書く）  ura  裏ドラ表示牌
    flags  WinContext のそのほかの項目（is_tsumo, riichi, seat_wind など）
    """
    used: set[int] = set()
    closed = parse_tiles(hand, aka=aka, used=used)
    used.update(closed)
    win_tiles = parse_tiles(win, aka=aka, used=used)
    if len(win_tiles) != 1:
        raise TileError(f"和了牌は 1 枚です: {win!r}")
    used.update(win_tiles)
    meld_list = [parse_meld(m, aka=aka, used=used) for m in melds]
    dora_tiles = parse_tiles(dora, aka=aka, used=used)
    used.update(dora_tiles)
    ura_tiles = parse_tiles(ura, aka=aka, used=used)
    flags.setdefault("is_tsumo", False)
    return WinContext(
        closed_tiles=(*closed, win_tiles[0]),
        win_tile=win_tiles[0],
        melds=tuple(meld_list),
        dora_indicators=tuple(dora_tiles),
        ura_indicators=tuple(ura_tiles),
        **flags,
    )


def to_notation(ctx: WinContext, *, aka: bool = True) -> dict[str, Any]:
    """WinContext を、make_context に渡せる書き方に戻す（保存や、画面の入力欄に入れるため）。

    make_context(**to_notation(ctx)) は、牌の種類・赤5・状況が同じ WinContext になる
    （牌ID の割り当ては変わることがある）。
    """
    closed = list(ctx.closed_tiles)
    closed.remove(ctx.win_tile)
    spec: dict[str, Any] = {
        "hand": format_tiles(closed, aka=aka),
        "win": code_of(ctx.win_tile, aka=aka),
        "melds": [f"{m.type.value} {format_tiles(m.tiles, aka=aka)}" for m in ctx.melds],
        "dora": "".join(code_of(t, aka=aka) for t in ctx.dora_indicators),
        "ura": "".join(code_of(t, aka=aka) for t in ctx.ura_indicators),
        "is_tsumo": ctx.is_tsumo,
        "seat_wind": ctx.seat_wind,
        "round_wind": ctx.round_wind,
        "honba": ctx.honba,
        "kyotaku": ctx.kyotaku,
    }
    for name in ("riichi", "double_riichi", "ippatsu", "rinshan", "chankan", "haitei", "houtei", "tenhou", "chiihou"):
        if getattr(ctx, name):
            spec[name] = True
    return spec

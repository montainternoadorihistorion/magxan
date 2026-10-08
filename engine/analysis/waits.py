"""聴牌したときの待ち：何が来ればあがりか、残りは何枚か、あがったら何点か。

    waits_of(hand13, ...)  →  待ち牌ごとの残り枚数と、ツモあがりしたときの結果（リーチする／しないの両方）

あがったときの役と点数は、点数計算（engine.scoring）にそのまま任せる。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.analysis.shanten import AGARI, shanten_of
from engine.analysis.ukeire import acceptance
from engine.melds import Meld
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.explain import Explanation, explain
from engine.tiles import counts34, is_red


@dataclass(frozen=True)
class Wait:
    kind: int                          # 待ち牌の種類
    remaining: int                     # 残り枚数（見えていない枚数）
    tile: int | None                   # 結果の計算に使った牌ID（残り 0 枚なら None）
    plain: Explanation | None          # そのままツモあがりした場合
    riichi: Explanation | None         # リーチしてツモあがりした場合（鳴いている手では None）


def _unseen_tile(kind: int, seen: set[int], *, aka: bool) -> int | None:
    """その種類の牌のうち、まだ見えていない 1 枚（赤でないほうを優先）"""
    ids = [kind * 4 + i for i in range(4) if kind * 4 + i not in seen]
    if not ids:
        return None
    plain = [t for t in ids if not is_red(t, aka=aka)]
    return (plain or ids)[0]


def waits_of(
    hand: Sequence[int],
    remaining: Sequence[int],
    *,
    visible: Sequence[int] = (),
    melds: Sequence[Meld] = (),
    seat_wind: int,
    round_wind: int,
    dora_indicators: Sequence[int] = (),
    rules: Rules = DEFAULT_RULES,
    riichi_already: bool = False,
) -> tuple[Wait, ...]:
    """13 枚（副露があれば 13 − 3n 枚）の聴牌形の待ち。聴牌していなければ空。

    hand       門前の牌（牌ID）
    remaining  種類ごとの「まだ見えていない枚数」
    visible    場に見えている牌（河・ドラ表示牌など）。結果の計算に使う牌を選ぶときに避ける
    riichi_already  すでにリーチしているか（True なら plain もリーチありで計算する）
    """
    result = acceptance(counts34(hand), remaining)
    if result.shanten != 0:
        return ()
    menzen = not any(m.is_open for m in melds)
    seen = {*hand, *visible, *(t for m in melds for t in m.tiles)}
    waits = []
    for kind, left in result.tiles:
        tile = _unseen_tile(kind, seen, aka=rules.aka_dora) if left > 0 else None
        plain = with_riichi = None
        if tile is not None:
            def outcome(riichi: bool, tile: int = tile) -> Explanation:
                ctx = WinContext(
                    closed_tiles=(*hand, tile),
                    win_tile=tile,
                    is_tsumo=True,
                    seat_wind=seat_wind,
                    round_wind=round_wind,
                    melds=tuple(melds),
                    riichi=riichi,
                    dora_indicators=tuple(dora_indicators),
                )
                return explain(ctx, rules)

            plain = outcome(riichi_already)
            with_riichi = outcome(True) if menzen else None
        waits.append(Wait(kind, left, tile, plain, with_riichi))
    return tuple(waits)


def wait_kinds(hand: Sequence[int]) -> tuple[int, ...]:
    """聴牌形の待ち牌の種類（形の上での待ち。残り枚数は見ない）。

    手は 13 − 3n 枚（n は副露の数）。鳴いた直後の 14 − 3n 枚の手（まだ切っていない）には、待ちが無いので空を返す。
    """
    if len(hand) % 3 != 1:
        return ()
    result = acceptance(counts34(hand), [4] * 34)
    return tuple(kind for kind, _ in result.tiles) if result.shanten == 0 else ()


def is_win_shape(tiles: Sequence[int]) -> bool:
    """14 枚（副露があれば 14 − 3n 枚）が、あがりの形になっているか"""
    return shanten_of(counts34(tiles)) == AGARI

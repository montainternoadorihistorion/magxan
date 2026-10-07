"""照合テスト用の、ランダムな和了形づくり。

自前の点数計算と判定ライブラリを突き合わせるための入力を作る。ふだんの対局ではめったに出ない形
（役満、槓子 3 つ、清一色の多面張、同じ順子 3〜4 組など）がよく出るように、わざと偏らせてある。

    random_case(random.Random(1))  →  (WinContext, Rules) か None（作れなかったとき）
"""
from __future__ import annotations

import random

from engine.melds import Meld, MeldType
from engine.rules import Rules
from engine.scoring.context import ContextError, WinContext
from engine.tiles import EAST, NORTH, SOUTH, WEST

KOKUSHI = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
SEQUENCE_STARTS = tuple(k for k in range(27) if k % 9 <= 6)

FLAVORS = (
    ["any"] * 6
    + ["one_suit", "one_suit", "one_suit_honor", "honor", "yaochu", "terminal", "green", "simple", "simple", "winds", "dragons"]
)
STYLES = ["mixed", "mixed", "seq", "set", "peikou", "sanshoku", "ittsu", "chanta"]


class Pool:
    """136 枚の牌から、種類を指定して 1 枚ずつ取り出す（同じ牌を 2 度は出さない）"""

    def __init__(self, rnd: random.Random) -> None:
        self.rnd = rnd
        self.free = {k: [k * 4 + i for i in range(4)] for k in range(34)}

    def left(self, kind: int) -> int:
        return len(self.free[kind])

    def take(self, kind: int) -> int:
        ids = self.free[kind]
        return ids.pop(self.rnd.randrange(len(ids)))

    def take_any(self) -> int:
        return self.take(self.rnd.choice([k for k in range(34) if self.free[k]]))


def _kinds_of(rnd: random.Random, flavor: str) -> list[int]:
    """手牌に使ってよい牌の種類（偏らせ方）"""
    if flavor == "one_suit":
        start = rnd.choice([0, 9, 18])
        return list(range(start, start + 9))
    if flavor == "one_suit_honor":
        start = rnd.choice([0, 9, 18])
        return list(range(start, start + 9)) + list(range(27, 34))
    if flavor == "honor":
        return list(range(27, 34))
    if flavor == "yaochu":
        return list(KOKUSHI)
    if flavor == "terminal":
        return [0, 8, 9, 17, 18, 26]
    if flavor == "green":
        return [19, 20, 21, 23, 25, 32]
    if flavor == "simple":
        return [k for k in range(27) if k % 9 not in (0, 8)]
    if flavor == "winds":
        return [27, 28, 29, 30, *range(9)]
    if flavor == "dragons":
        return [31, 32, 33, *range(9, 18), 27, 28]
    return list(range(34))


def _regular_shape(rnd: random.Random) -> tuple[list[tuple[str, int]], int, list[int]] | None:
    """4 面子 1 雀頭を、牌の種類で作る。返り値は（面子の並び、雀頭の種類、種類ごとの枚数）"""
    kinds = _kinds_of(rnd, rnd.choice(FLAVORS))
    style = rnd.choice(STYLES)
    counts = [0] * 34
    mentsu: list[tuple[str, int]] = []

    def add_sequence(first: int) -> None:
        tiles = (first, first + 1, first + 2)
        if first in SEQUENCE_STARTS and all(k in kinds and counts[k] < 4 for k in tiles):
            for k in tiles:
                counts[k] += 1
            mentsu.append(("seq", first))

    def add_set(kind: int) -> None:
        if kind in kinds and counts[kind] <= 1:
            counts[kind] += 3
            mentsu.append(("set", kind))

    if style == "sanshoku":
        number = rnd.randrange(9)
        for start in (0, 9, 18):
            if rnd.random() < 0.3:
                add_set(start + number)
            else:
                add_sequence(start + min(number, 6))
    elif style == "ittsu":
        start = rnd.choice([0, 9, 18])
        for number in (0, 3, 6):
            add_sequence(start + number)
    elif style == "peikou":
        first = rnd.choice(SEQUENCE_STARTS)
        for _ in range(rnd.choice([2, 2, 3, 4])):
            add_sequence(first)
        if rnd.random() < 0.5:
            second = rnd.choice(SEQUENCE_STARTS)
            add_sequence(second)
            add_sequence(second)
    elif style == "chanta":
        for _ in range(4):
            if rnd.random() < 0.6:
                add_sequence(rnd.choice([0, 6, 9, 15, 18, 24]))
            else:
                add_set(rnd.choice(KOKUSHI))

    sequence_rate = {"seq": 0.95, "set": 0.05}.get(style, 0.55)
    for _ in range(200):
        if len(mentsu) >= 4:
            break
        if rnd.random() < sequence_rate:
            add_sequence(rnd.choice(kinds))
        else:
            add_set(rnd.choice(kinds))
    if len(mentsu) < 4:
        return None

    mentsu = mentsu[:4]
    counts = [0] * 34
    for kind_type, first in mentsu:
        for k in ((first, first + 1, first + 2) if kind_type == "seq" else (first,) * 3):
            counts[k] += 1
    pairs = [k for k in kinds if counts[k] <= 2]
    if not pairs:
        return None
    pair = rnd.choice(pairs)
    counts[pair] += 2
    return mentsu, pair, counts


def _flags(rnd: random.Random, *, menzen: bool, has_kan: bool, no_melds: bool) -> dict:
    is_tsumo = rnd.random() < 0.45
    seat = rnd.choice([EAST, EAST, SOUTH, WEST, NORTH])
    flags: dict = {"is_tsumo": is_tsumo, "seat_wind": seat, "round_wind": rnd.choice([EAST, EAST, SOUTH, WEST, NORTH])}
    if menzen and rnd.random() < 0.5:
        flags["riichi"] = True
        if rnd.random() < 0.15:
            flags["double_riichi"] = True
        if rnd.random() < 0.25:
            flags["ippatsu"] = True
    luck = rnd.random()
    if is_tsumo:
        if has_kan and luck < 0.2:
            flags["rinshan"] = True
        elif luck < 0.3:
            flags["haitei"] = True
    elif luck < 0.08:
        flags["chankan"] = True
    elif luck < 0.2:
        flags["houtei"] = True
    if no_melds and is_tsumo and not flags.get("riichi") and rnd.random() < 0.05:
        flags.pop("haitei", None)
        flags["tenhou" if seat == EAST else "chiihou"] = True
    flags["honba"] = rnd.choice([0, 0, 0, 1, 2, 5])
    flags["kyotaku"] = rnd.choice([0, 0, 0, 1, 2])
    return flags


def random_rules(rnd: random.Random) -> Rules:
    if rnd.random() < 0.5:
        return Rules()
    return Rules(
        aka_dora=rnd.random() < 0.7,
        kuitan=rnd.random() < 0.6,
        kiriage_mangan=rnd.random() < 0.5,
        double_wind_pair_fu=rnd.choice([2, 4]),
        double_yakuman=rnd.random() < 0.5,
        kazoe_yakuman=rnd.random() < 0.5,
    )


def random_case(rnd: random.Random) -> tuple[WinContext, Rules] | None:
    """和了の状況とルールを 1 組作る。たまに、和了になっていない形も混ぜる"""
    pool = Pool(rnd)
    shape = rnd.random()
    melds: list[Meld] = []
    closed: list[int] = []
    has_kan = False

    if shape < 0.07:      # 七対子
        kinds = _kinds_of(rnd, rnd.choice(FLAVORS))
        if len(kinds) < 7:
            return None
        for k in rnd.sample(kinds, 7):
            closed += [pool.take(k), pool.take(k)]
    elif shape < 0.10:    # 国士無双
        closed = [pool.take(k) for k in KOKUSHI]
        closed.append(pool.take(rnd.choice(KOKUSHI)))
    elif shape < 0.12:    # 九蓮宝燈
        start = rnd.choice([0, 9, 18])
        closed = [pool.take(start + n) for n in (0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 8)]
        closed.append(pool.take(start + rnd.randrange(9)))
    else:
        made = _regular_shape(rnd)
        if made is None:
            return None
        mentsu, pair, counts = made
        open_rate = rnd.choice([0.0, 0.0, 0.25, 0.5, 0.9])
        for kind_type, first in mentsu:
            if kind_type == "seq":
                tiles = [pool.take(first), pool.take(first + 1), pool.take(first + 2)]
                if rnd.random() < open_rate:
                    melds.append(Meld(MeldType.CHI, tuple(tiles)))
                else:
                    closed += tiles
                continue
            tiles = [pool.take(first) for _ in range(3)]
            if counts[first] == 3 and rnd.random() < 0.25:   # 4 枚目がほかで使われていなければ、槓子にもする
                tiles.append(pool.take(first))
                has_kan = True
                kan_type = rnd.choice([MeldType.ANKAN, MeldType.ANKAN, MeldType.MINKAN, MeldType.KAKAN])
                melds.append(Meld(kan_type, tuple(tiles)))
            elif rnd.random() < open_rate:
                melds.append(Meld(MeldType.PON, tuple(tiles)))
            else:
                closed += tiles
        closed += [pool.take(pair), pool.take(pair)]

    if rnd.random() < 0.04:   # 1 枚すり替えて、和了でない形にする
        closed[rnd.randrange(len(closed))] = pool.take_any()

    win_tile = rnd.choice(closed)
    menzen = not any(m.is_open for m in melds)
    flags = _flags(rnd, menzen=menzen, has_kan=has_kan, no_melds=not melds)
    dora_count = rnd.choice([1, 2, 2, 3, 5]) if has_kan else rnd.choice([0, 1, 1, 1, 2, 3])
    dora = [pool.take_any() for _ in range(dora_count)]
    ura = [pool.take_any() for _ in range(dora_count)] if flags.get("riichi") and rnd.random() < 0.9 else []
    try:
        ctx = WinContext(
            closed_tiles=tuple(closed),
            win_tile=win_tile,
            melds=tuple(melds),
            dora_indicators=tuple(dora),
            ura_indicators=tuple(ura),
            **flags,
        )
    except ContextError:
        return None
    return ctx, random_rules(rnd)

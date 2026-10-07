"""練習用のランダムな和了形づくり（点数計算ラボの出題）。

    random_win(seed, kind)  →  WinContext（必ず役があり、和了になっている）

同じ seed と kind なら、いつでも同じ手になる（「さっきの手をもう一度」ができる）。
手牌・副露・ドラ表示牌は 136 枚の牌から 1 枚ずつ取るので、同じ牌が 5 枚になることはない。

実戦の出現率を再現するものではない。点数計算の練習になるように、役と符の付き方がほどよく散らばる
ように作ってある（リーチ・平和・断么九・役牌が多め、清一色や役満はまれ）。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from engine.melds import Meld, MeldType
from engine.rng import Rng
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import ContextError, WinContext
from engine.scoring.explain import Explanation, Status, explain
from engine.scoring.judge import Level
from engine.tiles import CHUN, EAST, HAKU, HATSU, NORTH, SOUTH, WEST

T = TypeVar("T")

#: 出題の種類（画面の選択肢）
KINDS: dict[str, str] = {
    "any": "おまかせ",
    "menzen": "門前の手",
    "open": "鳴いた手",
    "fu": "符の計算が要る手",
    "big": "満貫以上",
}

SEQUENCE_STARTS = tuple(k for k in range(27) if k % 9 <= 6)
SIMPLES = tuple(k for k in range(27) if 1 <= k % 9 <= 7)
SIMPLE_SEQUENCE_STARTS = tuple(k for k in range(27) if 1 <= k % 9 <= 5)
TERMINALS = (0, 8, 9, 17, 18, 26)
HONORS = tuple(range(27, 34))
DRAGONS = (HAKU, HATSU, CHUN)
KOKUSHI = TERMINALS + HONORS

# (形のテーマ, 重み)。テーマごとに「どんな面子を集めるか」と「鳴きやすさ」が決まる
_THEMES: dict[str, list[tuple[str, float]]] = {
    "any": [
        ("pinfu", 22), ("tanyao", 16), ("yakuhai", 16), ("mixed", 14), ("iipeikou", 5), ("honitsu", 7), ("toitoi", 5),
        ("chiitoi", 5), ("sanshoku", 4), ("ittsu", 3), ("chanta", 2), ("chinitsu", 1),
    ],
    "menzen": [("pinfu", 30), ("tanyao", 15), ("mixed", 20), ("iipeikou", 8), ("chiitoi", 8), ("yakuhai", 8), ("sanshoku", 5), ("ittsu", 4), ("chanta", 2)],
    "open": [("yakuhai", 30), ("tanyao", 25), ("honitsu", 14), ("toitoi", 12), ("sanshoku", 7), ("ittsu", 6), ("chanta", 6)],
    "fu": [("mixed", 40), ("yakuhai", 25), ("toitoi", 10), ("chiitoi", 8), ("tanyao", 10), ("honitsu", 7)],
    "big": [
        ("pinfu", 12), ("tanyao", 12), ("honitsu", 18), ("toitoi", 12), ("chinitsu", 10), ("iipeikou", 8), ("sanshoku", 8),
        ("ittsu", 6), ("chanta", 5), ("yakuhai", 6), ("yakuman", 3),
    ],
}
# 鳴いている確率
_OPEN_RATE = {
    "pinfu": 0.0, "iipeikou": 0.0, "chiitoi": 0.0, "tanyao": 0.45, "yakuhai": 0.7, "mixed": 0.25, "honitsu": 0.55,
    "toitoi": 0.8, "sanshoku": 0.35, "ittsu": 0.35, "chanta": 0.4, "chinitsu": 0.4, "yakuman": 0.3,
}
# 面子を足すときに順子にする確率
_SEQUENCE_RATE = {
    "pinfu": 1.0, "iipeikou": 1.0, "tanyao": 0.8, "yakuhai": 0.75, "mixed": 0.6, "honitsu": 0.65, "toitoi": 0.0,
    "sanshoku": 0.8, "ittsu": 0.8, "chanta": 0.6, "chinitsu": 0.75,
}


def _weighted(rng: Rng, items: Sequence[tuple[T, float]]) -> T:
    total = sum(weight for _, weight in items)
    point = rng.random() * total
    for item, weight in items:
        point -= weight
        if point < 0:
            return item
    return items[-1][0]


class _Pool:
    """136 枚の牌。種類を指定して 1 枚ずつ取り出す"""

    def __init__(self, rng: Rng) -> None:
        self.rng = rng
        self.free = {k: [k * 4 + i for i in range(4)] for k in range(34)}

    def take(self, kind: int) -> int:
        ids = self.free[kind]
        return ids.pop(self.rng.below(len(ids)))

    def take_any(self) -> int:
        return self.take(self.rng.choice([k for k in range(34) if self.free[k]]))


class _Shape:
    """面子 4 つ＋雀頭（牌の種類だけで持つ）"""

    def __init__(self) -> None:
        self.counts = [0] * 34
        self.mentsu: list[tuple[str, int]] = []     # ("seq", 先頭の種類) / ("set", 種類)
        self.pair: int | None = None

    def add_sequence(self, first: int, allowed: Sequence[int]) -> bool:
        tiles = (first, first + 1, first + 2)
        if first not in SEQUENCE_STARTS or any(k not in allowed or self.counts[k] >= 4 for k in tiles):
            return False
        for k in tiles:
            self.counts[k] += 1
        self.mentsu.append(("seq", first))
        return True

    def add_set(self, kind: int, allowed: Sequence[int]) -> bool:
        if kind not in allowed or self.counts[kind] > 1:
            return False
        self.counts[kind] += 3
        self.mentsu.append(("set", kind))
        return True

    def set_pair(self, kind: int) -> bool:
        if self.counts[kind] > 2:
            return False
        self.counts[kind] += 2
        self.pair = kind
        return True


def _build_shape(rng: Rng, theme: str, seat: int, round_wind: int) -> _Shape | None:
    shape = _Shape()
    everything = tuple(range(34))
    allowed: Sequence[int] = everything
    pair_from: Sequence[int] = everything
    yakuhai = (*DRAGONS, seat, round_wind)
    guest_winds = tuple(k for k in (EAST, SOUTH, WEST, NORTH) if k not in (seat, round_wind))

    if theme == "pinfu":
        allowed = tuple(range(27))
        pair_from = (*range(27), *guest_winds)
    elif theme == "iipeikou":
        allowed = tuple(range(27))
        first = rng.choice(SEQUENCE_STARTS)
        shape.add_sequence(first, allowed)
        shape.add_sequence(first, allowed)
    elif theme == "tanyao":
        allowed = pair_from = SIMPLES
    elif theme == "yakuhai":
        shape.add_set(rng.choice(yakuhai), everything)
        if rng.chance(0.12):
            shape.add_set(rng.choice(yakuhai), everything)
    elif theme in ("honitsu", "chinitsu"):
        start = rng.choice((0, 9, 18))
        suit = tuple(range(start, start + 9))
        if theme == "honitsu":
            allowed = (*suit, *HONORS)
            if rng.chance(0.75):
                shape.add_set(rng.choice(HONORS), allowed)
            else:
                pair_from = HONORS
            if rng.chance(0.25):
                shape.add_set(rng.choice(HONORS), allowed)
        else:
            allowed = pair_from = suit
    elif theme == "toitoi":
        if rng.chance(0.5):
            shape.add_set(rng.choice(yakuhai), everything)
    elif theme == "sanshoku":
        number = rng.below(7)
        for start in (0, 9, 18):
            shape.add_sequence(start + number, everything)
    elif theme == "ittsu":
        start = rng.choice((0, 9, 18))
        for number in (0, 3, 6):
            shape.add_sequence(start + number, everything)
    elif theme == "chanta":
        with_honors = rng.chance(0.7)
        for _ in range(40):
            if len(shape.mentsu) >= 4:
                break
            if rng.chance(0.65):
                shape.add_sequence(rng.choice((0, 6, 9, 15, 18, 24)), everything)
            else:
                shape.add_set(rng.choice(KOKUSHI if with_honors else TERMINALS), everything)
        pair_from = KOKUSHI if with_honors else TERMINALS

    sequence_rate = _SEQUENCE_RATE.get(theme, 0.6)
    for _ in range(200):
        if len(shape.mentsu) >= 4:
            break
        if rng.chance(sequence_rate):
            starts = SIMPLE_SEQUENCE_STARTS if theme == "tanyao" else SEQUENCE_STARTS
            shape.add_sequence(rng.choice(starts), allowed)
        else:
            shape.add_set(rng.choice(allowed), allowed)
    if len(shape.mentsu) != 4:
        return None

    candidates = [k for k in pair_from if k in allowed or k in HONORS]
    for _ in range(50):
        if shape.set_pair(rng.choice(candidates)):
            return shape
    return None


def _yakuman_tiles(rng: Rng, pool: _Pool) -> tuple[list[int], list[Meld]] | None:
    """役満の形（国士無双・四暗刻・大三元のどれか）"""
    which = rng.choice(("kokushi", "suuankou", "daisangen"))
    if which == "kokushi":
        closed = [pool.take(k) for k in KOKUSHI]
        closed.append(pool.take(rng.choice(KOKUSHI)))
        return closed, []
    shape = _Shape()
    everything = tuple(range(34))
    if which == "daisangen":
        for k in DRAGONS:
            shape.add_set(k, everything)
    for _ in range(100):
        if len(shape.mentsu) >= 4:
            break
        if which == "suuankou":
            shape.add_set(rng.below(34), everything)
        else:
            shape.add_sequence(rng.choice(SEQUENCE_STARTS), everything)
    if len(shape.mentsu) != 4 or not shape.set_pair(rng.below(27)):
        return None
    closed: list[int] = []
    melds: list[Meld] = []
    for kind_type, first in shape.mentsu:
        tiles = [pool.take(first + i) for i in range(3)] if kind_type == "seq" else [pool.take(first) for _ in range(3)]
        if which == "daisangen" and first in DRAGONS and rng.chance(0.5):
            melds.append(Meld(MeldType.PON, tuple(tiles)))
        else:
            closed += tiles
    assert shape.pair is not None
    closed += [pool.take(shape.pair), pool.take(shape.pair)]
    return closed, melds


def _attempt(rng: Rng, kind: str) -> WinContext | None:
    theme = _weighted(rng, _THEMES[kind])
    seat = _weighted(rng, [(EAST, 25), (SOUTH, 25), (WEST, 25), (NORTH, 25)])
    round_wind = _weighted(rng, [(EAST, 70), (SOUTH, 30)])
    pool = _Pool(rng)
    closed: list[int] = []
    melds: list[Meld] = []
    kan_count = 0

    if theme == "chiitoi":
        kinds = list(range(34))
        rng.shuffle(kinds)
        for k in kinds[:7]:
            closed += [pool.take(k), pool.take(k)]
    elif theme == "yakuman":
        made = _yakuman_tiles(rng, pool)
        if made is None:
            return None
        closed, melds = made
    else:
        shape = _build_shape(rng, theme, seat, round_wind)
        if shape is None:
            return None
        is_open = rng.chance(_OPEN_RATE[theme]) and kind != "menzen"
        if kind == "open":
            is_open = True
        order = list(range(4))
        rng.shuffle(order)
        open_target = 0 if not is_open else _weighted(rng, [(1, 50), (2, 38), (3, 12)])
        opened = 0
        for index in order:
            kind_type, first = shape.mentsu[index]
            if kind_type == "seq":
                tiles = [pool.take(first), pool.take(first + 1), pool.take(first + 2)]
                if opened < open_target:
                    melds.append(Meld(MeldType.CHI, tuple(tiles)))
                    opened += 1
                else:
                    closed += tiles
                continue
            tiles = [pool.take(first) for _ in range(3)]
            make_kan = shape.counts[first] == 3 and rng.chance(0.07)
            if opened < open_target:
                opened += 1
                if make_kan:
                    tiles.append(pool.take(first))
                    kan_count += 1
                    melds.append(Meld(rng.choice((MeldType.MINKAN, MeldType.KAKAN)), tuple(tiles)))
                else:
                    melds.append(Meld(MeldType.PON, tuple(tiles)))
            elif make_kan:
                tiles.append(pool.take(first))
                kan_count += 1
                melds.append(Meld(MeldType.ANKAN, tuple(tiles)))
            else:
                closed += tiles
        assert shape.pair is not None
        closed += [pool.take(shape.pair), pool.take(shape.pair)]
        if is_open and opened == 0:
            return None

    menzen = not any(m.is_open for m in melds)
    is_tsumo = rng.chance(0.35)
    flags: dict = {"is_tsumo": is_tsumo, "seat_wind": seat, "round_wind": round_wind}
    if menzen and rng.chance(0.75):
        flags["riichi"] = True
        if rng.chance(0.12):
            flags["ippatsu"] = True
    if is_tsumo and kan_count and rng.chance(0.3):
        flags["rinshan"] = True
    elif rng.chance(0.02):
        flags["haitei" if is_tsumo else "houtei"] = True
    flags["honba"] = _weighted(rng, [(0, 80), (1, 12), (2, 8)])
    flags["kyotaku"] = _weighted(rng, [(0, 90), (1, 10)])

    win_tile = rng.choice(closed)
    dora = [pool.take_any() for _ in range(1 + kan_count)]
    ura = [pool.take_any() for _ in range(1 + kan_count)] if flags.get("riichi") else []
    try:
        return WinContext(
            closed_tiles=tuple(closed),
            win_tile=win_tile,
            melds=tuple(melds),
            dora_indicators=tuple(dora),
            ura_indicators=tuple(ura),
            **flags,
        )
    except ContextError:
        return None


def _fits(kind: str, ctx: WinContext, result: Explanation) -> bool:
    best = result.best
    if best is None or best.points is None:
        return False
    if kind == "menzen":
        return ctx.is_menzen
    if kind == "open":
        return not ctx.is_menzen
    if kind == "fu":
        return best.points.level is Level.NONE and best.fu.fu not in (20, 30)
    if kind == "big":
        return best.points.level is not Level.NONE
    return True


def random_win(seed: int | str, kind: str = "any", rules: Rules = DEFAULT_RULES) -> WinContext:
    """役のある和了形を 1 つ作る。kind は KINDS のどれか"""
    if kind not in KINDS:
        raise ValueError(f"出題の種類は {list(KINDS)} のどれかです: {kind!r}")
    rng = Rng(seed, f"lab:{kind}")
    for _ in range(5000):
        ctx = _attempt(rng, kind)
        if ctx is None:
            continue
        result = explain(ctx, rules)
        if result.status is Status.WIN and result.consistent and _fits(kind, ctx, result):
            return ctx
    raise RuntimeError(f"和了形を作れませんでした（seed={seed!r}, kind={kind!r}）")

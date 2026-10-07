"""コーチのテストで使う道具（文字で書いた局面を作る、など）"""
from __future__ import annotations

from engine.coach import Position, analyze, judge_discard
from engine.scoring.texts import kind_text
from engine.tiles import EAST, SOUTH, is_red, kind_of, parse_tiles

TWO_SHANTEN = "1345m2289p3467s15z"       # 345萬 が面子。1萬・東・白 が浮いている 2 向聴
TENPAI_PLUS_ONE = "123m456p789s23s44z9m"  # 9萬 を切れば 1索・4索 待ち


def position(hand: str, *, visible: str = "", dora: str = "", drawn: str = "", **kwargs) -> Position:
    """文字で書いた局面。visible は河など、dora はドラ表示牌（どちらも「見えている牌」に入る）"""
    used: set[int] = set()

    def take(text: str) -> tuple[int, ...]:
        tiles = parse_tiles(text, used=used)
        used.update(tiles)
        return tuple(tiles)

    tiles = take(hand)
    seen = take(visible)
    indicators = take(dora)
    drawn_tile = next(t for t in tiles if kind_of(t) == kind_of(parse_tiles(drawn)[0])) if drawn else None
    defaults = {"seat_wind": SOUTH, "round_wind": EAST, "draws_left": 10, "can_riichi": True}
    return Position(tiles=tiles, visible=(*seen, *indicators), dora_indicators=indicators, drawn=drawn_tile, **{**defaults, **kwargs})


def held(pos: Position, code: str) -> int:
    """手牌の中の、その表記の牌（"0s" なら赤、"5s" なら赤でないほう）"""
    wanted = parse_tiles(code)[0]
    red = code[0] == "0"
    return next(t for t in pos.tiles if kind_of(t) == kind_of(wanted) and is_red(t) == red)


def judge(pos: Position, code: str, *, riichi: bool = False):
    return judge_discard(analyze(pos), held(pos, code), riichi=riichi)


def names(candidates) -> list[str]:
    return [kind_text(c.kind) for c in candidates]

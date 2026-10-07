"""一人練習のテストで使う道具（指定した山で始める、決まった打ち方で最後まで打つ、など）"""
from __future__ import annotations

from engine import practice
from engine.analysis.shanten import shanten_of
from engine.luck import NO_DRAW_LUCK, DealReport, LuckSettings
from engine.practice import TSUMO, Action, Draw, PracticeConfig, PracticeState, discard, riichi
from engine.rng import Rng
from engine.tiles import NUM_TILES, SOUTH, counts34, kind_of, parse_tiles, sort_tiles
from engine.wall import DORA_START, LIVE_START, URA_START, Wall

TENPAI_HAND = "123m456p789s23s44z"      # 1索・4索 待ちの平和形（北は、南家にとって役牌ではない）


def crafted_wall(hand: str, draws: str, *, dora: str = "9p", ura: str = "9p") -> list[int]:
    """配牌・ツモ・ドラ表示牌を指定した山を作る（残りの位置は、使っていない牌を小さい順に詰める）"""
    used: set[int] = set()

    def take(text: str) -> list[int]:
        tiles = parse_tiles(text, used=used)
        used.update(tiles)
        return tiles

    placed = {}
    for position, tile in zip(range(13), take(hand), strict=True):
        placed[position] = tile
    for position, tile in enumerate(take(draws), start=LIVE_START):
        placed[position] = tile
    placed[DORA_START] = take(dora)[0]
    placed[URA_START] = take(ura)[0]
    rest = iter(t for t in range(NUM_TILES) if t not in used)
    return [placed[p] if p in placed else next(rest) for p in range(NUM_TILES)]


def start_on(wall_tiles: list[int], *, seat_wind: int = SOUTH, settings: LuckSettings | None = None) -> PracticeState:
    """指定した山で始めた状態（start と同じ形。ただし、シードからは作り直せない）"""
    config = PracticeConfig(seed=0, luck=settings or LuckSettings(), seat_wind=seat_wind)
    wall = Wall(list(wall_tiles))
    wall.seal()
    hand = tuple(sort_tiles(wall.dealt_hand(0)))
    value = shanten_of(counts34(hand))
    tile = wall.draw()
    return PracticeState(
        config=config, actions=(), seat_wind=seat_wind, wall_tiles=tuple(wall.tiles), hand=hand, drawn=tile,
        discards=(), riichi_index=None, draws=(Draw(1, tile, NO_DRAW_LUCK),), deal=DealReport(1, 0, value, value),
    )


def tile(state: PracticeState, code: str) -> int:
    """手牌の中から、その表記の牌を 1 枚選ぶ"""
    wanted = parse_tiles(code)[0]
    return next(t for t in state.tiles if kind_of(t) == kind_of(wanted))


def play(config: PracticeConfig, choose) -> list[PracticeState]:
    """choose(state) が返す行動で最後まで打ち、通った状態をすべて返す"""
    states = [practice.start(config)]
    while not states[-1].finished:
        states.append(practice.apply(states[-1], choose(states[-1])))
    return states


def tsumogiri(state: PracticeState) -> Action:
    return discard(state.drawn)


def nearest_discard(state: PracticeState) -> int:
    """切ったあとの向聴数がいちばん小さくなる牌（速く調べるための簡単な選び方）"""
    counts = counts34(state.tiles)
    best_tile, best_value = state.tiles[0], 99
    for candidate in state.tiles:
        kind = kind_of(candidate)
        counts[kind] -= 1
        value = shanten_of(counts)
        counts[kind] += 1
        if value < best_value:
            best_tile, best_value = candidate, value
    return best_tile


def mixed_policy(seed: int):
    """あがれるときは半分の確率であがり、リーチできるときは 3 割でリーチし、あとは聴牌に近づく牌か適当な牌を切る"""
    rng = Rng(seed, "test:policy")

    def choose(state: PracticeState) -> Action:
        if state.can_tsumo and rng.chance(0.5):
            return TSUMO
        options = state.riichi_discards
        if options and rng.chance(0.3):
            return riichi(rng.choice(options))
        if rng.chance(0.7):
            return discard(nearest_discard(state))
        return discard(rng.choice(state.tiles))

    return choose

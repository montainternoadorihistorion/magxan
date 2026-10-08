"""CPU の打ち方（engine/cpu.py）のテスト"""
from __future__ import annotations

import random
from dataclasses import replace

import pytest

from engine import game as g
from engine.cpu import advance, all_cpu, decide, efficient_order, human_turn
from engine.defense import danger_table, threats
from engine.game import CpuLevel, GameConfig, Move, Phase
from engine.tiles import kind_of, parse_tiles
from tests.game_helpers import build_hand, game_of


def k(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def _folding_hand() -> g.HandState:
    """自分（席 0）は 2 向聴。下家（席 1）がリーチしていて、その河の 9筒 を自分も持っている"""
    return build_hand(
        ["13m479p2589s1357z", "234m567m78p345s66s", "222z444z666z1m2m3m8m", "258p369s147m3z6z7z5z"],
        turn=0, drawn="9m", rivers=("", "9p", "", ""), riichi=(None, 0, None, None),
        kyotaku=1, scores=(25_000, 24_000, 25_000, 25_000),
    )


def test_normal_cpu_folds_to_riichi_with_a_safe_tile():
    hand = _folding_hand()
    order = efficient_order(hand, 0)
    assert order[0].shanten >= 1                      # 聴牌にとれない
    action = decide(hand, 0, CpuLevel.NORMAL)
    assert action.move is Move.DISCARD and kind_of(action.tile) == k("9p")       # 現物の 9筒
    table = danger_table(hand.players[0].tiles, hand.visible_to(0), threats(hand, 0))
    assert {row.kind: row.level for row in table}[k("9p")] == 0


def test_weak_cpu_does_not_fold():
    hand = _folding_hand()
    action = decide(hand, 0, CpuLevel.WEAK)
    options = efficient_order(hand, 0)
    best = min(o.shanten for o in options)
    chosen = next(o for o in options if o.tile == action.tile)
    assert chosen.shanten == best                       # 向聴数だけを見て切る（安全かどうかは見ない）


def test_cpu_declares_riichi_when_tenpai():
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"],
        turn=0, drawn="5z",
    )
    action = decide(hand, 0, CpuLevel.NORMAL)
    assert action.move is Move.RIICHI and kind_of(action.tile) == k("5z")
    assert decide(hand, 0, CpuLevel.WEAK).move is Move.RIICHI


def test_cpu_wins_when_it_can():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=1, drawn="9p", rivers=("2z", "3z", "", ""),
    )
    assert decide(hand, 1, CpuLevel.NORMAL) == g.tsumo(1)
    ron_hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=0, drawn="9p",
    )
    game = g.apply(game_of(ron_hand), g.discard(0, next(t for t in ron_hand.players[0].tiles if kind_of(t) == k("9p"))))
    assert game.current.phase is Phase.CLAIM
    assert decide(game.current, 1, CpuLevel.WEAK) == g.ron(1)


@pytest.mark.parametrize(("hand_text", "declares"), [("19m19p19s1234z567m", True), ("19m19p19s1234567z", False)])
def test_nine_terminals_unless_going_for_kokushi(hand_text, declares):
    hand = build_hand(
        [hand_text, "234m567m78p345s66s", "222p678m345p78p55s", "33p44p1188m22467s"],
        turn=0, drawn="9m" if declares else "5m",
    )
    assert hand.can_nine(0)
    assert (decide(hand, 0, CpuLevel.NORMAL).move is Move.NINE) == declares


def _hidden_swap(hand: g.HandState, seed: int) -> g.HandState:
    """自分（席 0）から見えない牌（ほかの人の手牌と、これからツモる山）だけを並べ替える"""
    rnd = random.Random(seed)
    hidden = [t for seat in (1, 2, 3) for t in hand.players[seat].hand]
    live = list(hand.wall_tiles[52 + hand.live_drawn:122])
    pool = hidden + live
    rnd.shuffle(pool)
    players = list(hand.players)
    at = 0
    for seat in (1, 2, 3):
        size = len(players[seat].hand)
        players[seat] = replace(players[seat], hand=tuple(sorted(pool[at:at + size])))
        at += size
    wall = list(hand.wall_tiles)
    wall[52 + hand.live_drawn:122] = pool[at:]
    return replace(hand, players=tuple(players), wall_tiles=tuple(wall))


@pytest.mark.parametrize("level", [CpuLevel.NORMAL, CpuLevel.WEAK])
def test_cpu_looks_only_at_what_it_can_see(level):
    game = g.start_game(GameConfig(seed=21))
    while True:                                  # 河に 8 枚以上たまって、自分の番になるまで進める
        hand = game.current
        assert hand.result is None
        seat = g.waiting_for(hand)
        if seat == 0 and hand.phase is Phase.DRAW and hand.discard_count >= 8:
            break
        game = g.apply(game, decide(hand, seat, CpuLevel.NORMAL))
    base = decide(hand, 0, level)
    for seed in range(5):
        assert decide(_hidden_swap(hand, seed), 0, level) == base


def test_advance_stops_at_the_human_and_plays_whole_games():
    config = GameConfig(seed=4)
    game = advance(g.start_game(config))
    assert human_turn(game) or game.current.result is not None
    # 4 人とも CPU なら、試合の終わりまで進む
    game = g.start_game(GameConfig(seed=8))
    while not game.finished:
        if game.between_hands:
            game = g.next_hand(game)
        game = advance(game, cpu_seats=all_cpu())
    assert game.result is not None and sum(game.result.scores) == 100_000
    again = g.from_save(g.to_save(game))
    assert again.result == game.result


def test_auto_riichi_turns_for_the_human():
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"],
        turn=0, drawn="5z", next_draws="9m9p9s8m",
    )
    game = g.apply(game_of(hand), g.riichi(0, next(t for t in hand.players[0].tiles if kind_of(t) == k("5z"))))
    game = advance(game)        # CPU 3 人が打ち、自分のリーチ後のツモ切りも自動で進む
    hand = game.current
    # 止まるのは、局が終わったときか、自分がロンできる牌が出たときだけ
    assert hand.result is not None or (hand.phase is Phase.CLAIM and 0 in hand.pending)
    assert all(d.tsumogiri for d in hand.players[0].river)

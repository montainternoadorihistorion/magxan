"""一人打ちの最小ループ（engine/solo.py）のテスト"""
import pytest

from engine import solo
from engine.tiles import format_tiles
from engine.wall import Wall


def play_out(seed: int, choose) -> tuple[solo.SoloState, list[int]]:
    state = solo.start(seed)
    discards = []
    while not state.finished:
        tile = choose(state)
        discards.append(tile)
        state = solo.discard(state, tile)
    return state, discards


def test_golden_start():
    state = solo.start(20261007)
    assert format_tiles(state.hand) == "2356m136p44689s4z"
    assert format_tiles([state.drawn]) == "1z"
    assert state.draws_left == solo.MAX_DRAWS - 1 and not state.finished


def test_hand_stays_13_tiles_and_ends_after_max_draws():
    state, discards = play_out(1, lambda s: s.drawn)   # ずっとツモ切り
    assert len(discards) == solo.MAX_DRAWS and state.finished and state.draws_left == 0
    assert len(state.hand) == 13 and state.tiles_in_hand == state.hand
    assert sorted(state.hand) == sorted(solo.start(1).hand)   # ツモ切りなら手牌は配牌のまま


def test_tiles_are_conserved():
    """手牌＋切った牌 ＝ 配牌＋ツモった牌（牌が増えも減りもしない）"""
    for seed in range(200):
        state, discards = play_out(seed, lambda s: s.tiles_in_hand[len(s.discards) % 14])
        wall = Wall.from_seed(seed)
        dealt = wall.dealt_hand(0)
        drawn = [wall.draw() for _ in range(solo.MAX_DRAWS)]
        assert sorted([*state.hand, *discards]) == sorted([*dealt, *drawn])
        assert len(set(discards)) == len(discards)


def test_replay_reproduces_every_intermediate_state():
    state = solo.start(77)
    discards: list[int] = []
    while not state.finished:
        tile = state.tiles_in_hand[(len(discards) * 5) % 14]
        discards.append(tile)
        state = solo.discard(state, tile)
        assert solo.replay(77, discards) == state


def test_invalid_actions_are_rejected():
    state = solo.start(3)
    missing = next(t for t in range(136) if t not in state.tiles_in_hand)
    with pytest.raises(solo.SoloError):
        solo.discard(state, missing)
    finished, _ = play_out(3, lambda s: s.drawn)
    with pytest.raises(solo.SoloError):
        solo.discard(finished, finished.hand[0])
    with pytest.raises(solo.SoloError):
        solo.replay(3, [missing])

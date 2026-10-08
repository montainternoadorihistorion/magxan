"""牌譜（局後の振り返り）：手順を当てはめた盤面が、エンジンの状態と一致する"""
from __future__ import annotations

import pytest

from engine import game as g
from engine.cpu import advance, all_cpu
from engine.game import GameConfig, Move
from engine.kifu import Note, board_at, kifu_of
from tests.test_game import _random_play


def _check(config: GameConfig, hand: g.HandState) -> None:
    record = kifu_of(config, hand)
    state = g.start_hand(config, hand.start)
    expected_by_index = {}
    for index, action in enumerate(hand.actions):
        state = g.apply_hand(config, state, action)
        expected_by_index[index] = state
    for upto, step in enumerate(record.steps, start=1):
        if step.index < 0:
            continue
        board = board_at(record, upto)
        engine_state = expected_by_index[step.index]
        for seat, player in enumerate(engine_state.players):
            assert board["hands"][seat] == list(player.hand), (upto, seat)
            assert board["drawn"][seat] == player.drawn
            assert [r["t"] for r in board["rivers"][seat]] == list(player.river_tiles)
            assert [r["called"] for r in board["rivers"][seat]] == [d.called_by is not None for d in player.river]
            assert [sorted(m["tiles"]) for m in board["melds"][seat]] == [sorted(f.meld.tiles) for f in player.furo]
            assert [sorted(t for t, _, _ in m["disp"]) for m in board["melds"][seat]] == [sorted(f.meld.tiles) for f in player.furo]
        assert board["dora"] == list(engine_state.dora_indicators)
        assert board["live"] == engine_state.live_remaining
        assert board["scores"] == list(engine_state.scores) and board["kyotaku"] == engine_state.kyotaku
    if hand.result is not None:
        assert record.steps[-1].index == -1
        assert board_at(record, len(record.steps))["scores"] == list(hand.result.scores)


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_board_follows_the_engine_in_random_games_with_calls(seed):
    game = _random_play(seed, steps=800)
    for hand in game.hands:
        _check(game.config, hand)


def test_board_follows_the_engine_in_cpu_games():
    config = GameConfig(seed=21)
    game = advance(g.start_game(config), cpu_seats=all_cpu())
    for _ in range(3):
        _check(config, game.current)
        if game.finished:
            break
        game = advance(g.next_hand(game), cpu_seats=all_cpu())


def test_human_decisions_are_marked_and_notes_attached():
    config = GameConfig(seed=5)
    game = advance(g.start_game(config), cpu_seats=(1, 2, 3))
    while not game.finished and game.current.result is None:
        hand = game.current
        seat = g.waiting_for(hand)
        if seat != 0:
            game = advance(game, cpu_seats=(1, 2, 3))
            continue
        auto = g.auto_action(hand, 0)
        if auto is not None:
            game = g.apply(game, auto)
        elif hand.phase is g.Phase.CLAIM:
            game = g.apply(game, g.pass_(0))
        else:
            game = g.apply(game, g.discard(0, hand.players[0].tiles[-1]))
        game = advance(game, cpu_seats=(1, 2, 3))
    hand = game.current
    mine = [i for i, a in enumerate(hand.actions) if a.seat == 0 and a.move in (Move.DISCARD, Move.PASS)]
    notes = {mine[0]: Note("✓", "good", "いちばん速い打牌", "")}
    record = kifu_of(config, hand, notes)
    marked = [s for s in record.steps if s.mine]
    assert marked and all(s.seat == 0 for s in marked)
    assert any(s.note == notes[mine[0]] for s in marked)
    assert record.decisions and all(record.steps[i].mine for i in record.decisions)
    data = record.to_dict()
    assert data["title"] and len(data["steps"]) == len(record.steps) and data["names"][0] == "自分"


def test_a_call_waiting_for_other_answers_is_not_called_failed():
    """ロンできる牌でチーを宣言し、ほかの人の返事がまだのとき、その手順に「通らなかった」と書かない。
    ほかの人が見送ってチーが通れば、その手順に書く"""
    from engine.kifu import steps_of
    from tests.game_helpers import build_hand

    hand = build_hand(["34m678p99p234456s", "1112223337779s", "55m19p19s1234567z", "1112223336667p"],
                      turn=3, drawn="5m", next_draws="8m8m8m8m")
    config = GameConfig(seed=1)
    claimed = g.apply_hand(config, hand, g.discard(3, hand.players[3].drawn))
    assert claimed.ron_check(0).ok
    chi = next(a for a in claimed.call_actions(0) if a.move is Move.CHI)
    steps, after = steps_of(config, hand, [g.discard(3, hand.players[3].drawn), chi, g.pass_(2)])
    texts = [step.text for step in steps]
    assert "ほかの人の返事を待つ" in texts[1] and "通らなかった" not in texts[1]
    assert "自分がチー" in texts[2] and len(after.players[0].furo) == 1


def test_a_call_overtaken_by_a_pon_is_reported_when_the_answers_are_in():
    """チーを宣言したあとに、ほかの人がポンした：返事がそろった手順に「自分のチーは…通らなかった」と書く"""
    from engine.kifu import steps_of
    from tests.game_helpers import build_hand

    hand = build_hand(["34m678p99p234456s", "1112223337779s", "55m19p19s1234567z", "1112223336667p"],
                      turn=3, drawn="5m", next_draws="8m8m8m8m")
    config = GameConfig(seed=1)
    claimed = g.apply_hand(config, hand, g.discard(3, hand.players[3].drawn))
    chi = next(a for a in claimed.call_actions(0) if a.move is Move.CHI)
    middle = g.apply_hand(config, claimed, chi)
    pon = next(a for a in middle.call_actions(2) if a.move is Move.PON)
    steps, after = steps_of(config, hand, [g.discard(3, hand.players[3].drawn), chi, pon])
    assert "自分のチーは、ほかの人のロン・ポン・カンが優先され、通らなかった" in steps[-1].text
    assert len(after.players[2].furo) == 1 and not after.players[0].furo

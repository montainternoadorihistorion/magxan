"""CPU との対局の画面の状態（ui/game_session.py）のテスト。画面なしで、操作の流れと保存を確かめる"""
from __future__ import annotations

import json

from test_practice_session import FakeStore

from engine import game as g
from engine.cpu import human_turn
from engine.game import HUMAN, Phase
from engine.game_coach import coach_action
from engine.game_records import load_history
from ui.game_session import (
    DEFAULT_SETTINGS,
    GAME_HISTORY_NAME,
    GAME_NAME,
    GAME_SETTINGS_NAME,
    GameSession,
    clean_settings,
    config_of,
    decisions_of,
)


def new_session(store: FakeStore | None = None, *, seeds=(201, 202, 203, 204), now: float = 5000.0):
    store = store or FakeStore()
    numbers = iter(seeds)
    session = GameSession({}, store, now=lambda: now, new_seed=lambda: next(numbers))
    return session, store


def reopen(store: FakeStore) -> GameSession:
    session = GameSession({}, store, now=lambda: 9000.0, new_seed=lambda: 999)
    session.start()
    return session


def play_one_move(session: GameSession) -> None:
    """自分の番の行動を 1 つ（コーチのおすすめどおりに）"""
    hand = session.game.current
    action = coach_action(hand, HUMAN)
    if action.move is g.Move.DISCARD:
        assert session.pick(action.tile)
    elif action.move is g.Move.RIICHI:
        assert session.pick(action.tile, riichi=True)
    else:
        assert session.act({g.Move.TSUMO: "tsumo", g.Move.RON: "ron", g.Move.PASS: "pass", g.Move.NINE: "nine"}[action.move])


def play_hand(session: GameSession) -> None:
    while session.game.current.result is None:
        play_one_move(session)


def test_start_begins_a_game_and_saves_it():
    session, store = new_session()
    session.start()
    game = session.game
    assert game.config.seed == 201 and session.counted and not session.hinted
    assert human_turn(game) or game.current.result is not None
    saved = json.loads(store.values[GAME_NAME])
    assert saved["v"] == 1 and g.from_save(saved["save"]).current == game.current
    assert game.config.luck.deal == DEFAULT_SETTINGS["deal"] and game.config.cpu_luck.is_off


def test_pick_advances_the_cpus_and_records_a_decision():
    session, store = new_session()
    session.start()
    rev = session.rev
    hand = session.game.current
    assert hand.phase is Phase.DRAW and hand.turn == HUMAN
    tile = coach_action(hand, HUMAN).tile
    assert session.pick(tile)
    assert session.rev > rev and len(session.decisions) == 1
    assert session.decisions[0].action.tile == tile
    after = session.game.current
    assert after.result is not None or human_turn(session.game)
    # 自分の行動のあとの位置（ここから先が CPU の動き）
    assert session.mark <= len(after.actions)
    # 画面が古い（手牌にない牌を切る）操作は、何もしない
    if human_turn(session.game) and session.game.current.phase is Phase.DRAW:
        before = session.game
        assert not session.pick(after.players[1].hand[0])
        assert session.game is before


def test_resume_rebuilds_the_game_and_decisions():
    session, store = new_session()
    session.start()
    for _ in range(3):
        if session.game.current.result is not None:
            break
        play_one_move(session)
    again = reopen(store)
    assert again.resumed and again.game.current == session.game.current
    assert [d.action for d in again.decisions] == [d.action for d in session.decisions]
    assert again.mark == session.mark


def test_broken_saves_start_a_new_game():
    for text in ("{", json.dumps({"v": 1, "save": {"v": 1, "config": {"seed": 1}, "logs": [[[0, "d", 999]]]}}), json.dumps([1, 2])):
        store = FakeStore({GAME_NAME: text})
        session, _ = new_session(store)
        session.start()
        assert session.game.config.seed == 201 and not session.resumed


def test_next_hand_and_finishing_a_game_records_it():
    session, store = new_session()
    session.start()
    hands = 0
    while not session.game.finished:
        play_hand(session)
        hands += 1
        if not session.game.finished:
            mark_before = session.mark
            assert session.next_hand()
            assert session.decisions == [] and session.mark <= mark_before + 400
    history = load_history(store.values[GAME_HISTORY_NAME])
    assert len(history) == 1 and len(session.history) == 1
    record = history[0]
    assert record.rank == session.game.result.ranks[HUMAN] and record.hands == len(session.game.hands) == hands
    assert record.tally.decisions >= 1
    # 開き直しても、二重に記録しない
    again = reopen(store)
    assert again.game.finished and len(again.history) == 1
    assert not again.next_hand()


def test_numbered_games_are_not_counted():
    session, store = new_session()
    session.start()
    session.begin(1234)
    assert session.game.config.seed == 1234 and not session.counted


def test_settings_are_cleaned_and_used_for_the_next_game():
    assert clean_settings({"deal": 150, "length": "north", "rules": {"tobi": "no", "nagashi_mangan": False}})["deal"] == DEFAULT_SETTINGS["deal"]
    cleaned = clean_settings({"length": "south", "cpu_level": "weak", "rules": {"nagashi_mangan": False}, "moves": "each"})
    assert cleaned["length"] == "south" and cleaned["cpu_level"] == "weak" and cleaned["moves"] == "each"
    assert cleaned["rules"]["nagashi_mangan"] is False and cleaned["rules"]["tobi"] is True
    session, store = new_session()
    session.start()
    session.update_settings({"length": "south", "deal": 0, "draw": 0})
    assert json.loads(store.values[GAME_SETTINGS_NAME])["length"] == "south"
    assert session.config_changed
    session.begin()
    assert session.game.config.length is g.Length.SOUTH and session.game.config.luck.is_off and not session.config_changed
    config = config_of(cleaned, 5)
    assert config.rules.nagashi_mangan is False and config.cpu_level is g.CpuLevel.WEAK


def test_hint_shown_marks_the_game():
    session, store = new_session()
    session.start()
    session.note_hint_shown()
    assert session.hinted and json.loads(store.values[GAME_NAME])["hinted"] is True


def test_sync_code_rebuilds_from_the_saved_copy():
    session, store = new_session()
    session.start(generation=1)
    play_one_move(session)
    game = session.game
    session.sync_code(2)
    assert session.game.current == game.current and session.game is not game


def test_decisions_of_skips_automatic_riichi_discards():
    session, _ = new_session()
    session.start()
    play_hand(session)
    rebuilt = decisions_of(session.game)
    assert [d.action for d in rebuilt] == [d.action for d in session.decisions]


def _won_first_hand(session: GameSession) -> bool:
    play_hand(session)
    return any(w.seat == HUMAN for w in session.game.current.result.wins)


def test_replaying_the_same_number_stamps_again():
    """同じ番号の対局を打ち直しても、あがればスタンプが押される（同じ局の番号を覚えたままにしない）"""
    from ui.progress_store import read_stamps

    session, store = new_session()
    session.start()
    session.update_settings({"deal": 100, "draw": 100})
    for seed in range(1, 40):
        session.begin(seed)
        if _won_first_hand(session):
            break
    else:
        raise AssertionError("あがれる番号が見つからない")
    before = {key: stamp.count for key, stamp in read_stamps(store).items()}
    session.begin(seed)
    assert _won_first_hand(session)
    after = {key: stamp.count for key, stamp in read_stamps(store).items()}
    assert any(after[key] > before.get(key, 0) for key in after)


def test_resume_at_a_cpu_turn_advances_the_cpus():
    """CPU の番で止まっている記録から開き直すと、CPU を進めて、自分の番から始める"""
    session, store = new_session()
    session.start()
    hand = session.game.current
    assert hand.phase is Phase.DRAW and hand.turn == HUMAN
    stopped = g.apply(session.game, coach_action(hand, HUMAN))          # 自分が切ったところ（CPU はまだ進めていない）
    data = json.loads(store.values[GAME_NAME])
    data["save"] = g.to_save(stopped)
    store.values[GAME_NAME] = json.dumps(data)
    again = reopen(store)
    assert again.resumed and (human_turn(again.game) or again.game.current.result is not None)
    assert len(again.game.current.actions) > len(stopped.current.actions)


def test_next_hand_ignores_a_stale_second_press():
    """「次の局へ」の二度押し：ボタンを描いたときの局の数と違えば、何もしない"""
    session, _ = new_session()
    session.start()
    play_hand(session)
    if session.game.finished:
        return
    count = len(session.game.hands)
    assert session.next_hand(count)
    assert not session.next_hand(count)                  # 2 回目（古いボタン）は、何もしない
    assert len(session.game.hands) == count + 1


def test_riichi_tsumo_waits_for_the_button():
    """リーチのあとにあがり牌を引いたら、自動であがらずに止まる（「ツモ」は自分で押す）"""
    from engine.cpu import advance

    for seed in range(60):
        game = advance(g.start_game(g.GameConfig(seed=seed, luck=g.LuckSettings(100, 100))))
        while not game.finished and game.current.result is None:
            hand = game.current
            me = hand.players[HUMAN]
            if hand.phase is Phase.DRAW and hand.turn == HUMAN and me.in_riichi and hand.can_tsumo(HUMAN):
                assert human_turn(game)                 # 自分の番で止まっている
                return
            game = advance(g.apply(game, coach_action(hand, HUMAN)))
    raise AssertionError("リーチのあとにツモであがれる局面が見つからない")

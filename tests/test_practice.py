"""一人練習の進行（engine/practice.py）のテスト"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import replace

import pytest
from practice_helpers import TENPAI_HAND, crafted_wall, mixed_policy, play, start_on, tile, tsumogiri

from engine import luck, practice
from engine.analysis.shanten import shanten_of
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.luck import NO_DRAW_LUCK, DealReport, LuckSettings, draw_probability
from engine.practice import (
    MAX_DRAWS,
    TSUMO,
    Action,
    Draw,
    Move,
    Outcome,
    PracticeConfig,
    PracticeError,
    PracticeState,
    discard,
    riichi,
)
from engine.rng import Rng
from engine.rules import Rules
from engine.scoring.explain import Status, explain
from engine.tiles import EAST, NORTH, NUM_TILES, SOUTH, WEST, counts34, format_tiles, kind_of, parse_tiles, sort_tiles
from engine.wall import DORA_START, LIVE_END, LIVE_START, URA_START, shuffled_tiles

#: 実際の補正つきで最後まで打って確かめる局数（増やしたいときは環境変数で）
HANDS = int(os.environ.get("MJDOJO_PRACTICE_HANDS", "240"))


def check_invariants(state: PracticeState, raw: list[int]) -> None:
    """どの時点でも成り立つはずのこと"""
    tiles = list(state.wall_tiles)
    assert sorted(tiles) == list(range(NUM_TILES))                         # 山は 136 枚をちょうど 1 枚ずつ
    assert tiles[13:LIVE_START] == raw[13:LIVE_START]                      # ほかの席の配牌はそのまま
    assert tiles[LIVE_END:] == raw[LIVE_END:]                              # 王牌はそのまま
    assert sorted([*tiles[:13], *tiles[LIVE_START:LIVE_END]]) == sorted([*raw[:13], *raw[LIVE_START:LIVE_END]])

    drawn = [d.tile for d in state.draws]
    assert drawn == tiles[LIVE_START:LIVE_START + state.turn]              # ツモは山の順番どおり
    assert [d.turn for d in state.draws] == list(range(1, state.turn + 1))
    mine = [*state.hand, *([] if state.drawn is None else [state.drawn]), *state.discards]
    assert sorted(mine) == sorted([*tiles[:13], *drawn])                   # 手牌＋河 ＝ 配牌＋ツモ（増えも減りもしない）
    assert len(set(mine)) == len(mine) and max(counts34(mine)) <= 4        # 同じ牌は 2 回出ない。どの種類も 4 枚まで
    assert len(state.hand) == 13 and list(state.hand) == sort_tiles(state.hand)
    assert state.turn + state.draws_left == MAX_DRAWS
    assert state.unseen_total == NUM_TILES - len(state.tiles) - len(state.discards) - 1
    assert sum(state.remaining) == state.unseen_total
    assert state.dora_indicators == (raw[DORA_START],) and state.ura_indicators == (raw[URA_START],)


# ---------------------------------------------------------------- 始まり


def test_golden_start_without_luck_is_the_plain_deal():
    state = practice.start(PracticeConfig(seed=20261007))
    assert format_tiles(state.hand) == "2356m136p44689s4z" and format_tiles([state.drawn]) == "1z"
    assert state.deal == DealReport(1, 0, 3, 3) and state.draws == (Draw(1, state.drawn, NO_DRAW_LUCK),)
    assert (state.turn, state.draws_left, state.finished, state.in_riichi) == (1, 17, False, False)
    assert state.seat_wind == EAST and state.discards == () and state.actions == ()


def test_golden_start_with_luck_is_reproducible():
    """補正つきの配牌が、どの環境でも同じになること（乱数の系統「luck:deal」の見張り）"""
    middle = practice.start(PracticeConfig(seed=20261007, luck=LuckSettings(50, 50)))
    assert format_tiles(middle.hand) == "368m11335678p11z" and format_tiles([middle.drawn]) == "7z"
    assert middle.deal == DealReport(candidates=16, chosen=13, original_shanten=3, chosen_shanten=2)
    strongest = practice.start(PracticeConfig(seed=20261007, luck=LuckSettings(100, 100)))
    assert format_tiles(strongest.hand) == "1135m24067p456s2z" and format_tiles([strongest.drawn]) == "1m"
    assert strongest.deal == DealReport(candidates=256, chosen=96, original_shanten=3, chosen_shanten=1)


def test_config_validation_and_roundtrip():
    config = PracticeConfig(seed=5, luck=LuckSettings(25, 75, True), rules=Rules(kuitan=False), seat_wind=WEST, round_wind=SOUTH)
    assert PracticeConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config
    assert PracticeConfig.from_dict({"seed": 12}) == PracticeConfig(seed=12)
    bad_values = (
        {"seed": -1}, {"seed": 1.5}, {"seed": True}, {"seed": "12"}, {"seed": None}, {"seed": 10**13}, {"seed": float("inf")},
        {"seed": 1, "seat_wind": 31}, {"seed": 1, "seat_wind": 27.0}, {"seed": 1, "round_wind": 5}, {"seed": 1, "round_wind": None},
        {"seed": 1, "luck": {"deal": 1}}, {"seed": 1, "rules": {}},          # 設定は、型の決まったオブジェクトで渡す
    )
    for bad in bad_values:
        with pytest.raises(ValueError):
            PracticeConfig(**bad)
    # 保存した形から作るときも、同じ確かめをする（数に見える文字や小数は受け付けない）
    for bad in ({"seed": "12"}, {"seed": 4.0}, {}, [], None, "x", {"seed": 4, "luck": [1]}, {"seed": 4, "luck": None},
                {"seed": 4, "rules": {"aka_dora": "no"}}, {"seed": 4, "rules": {"aka_dora": []}}, {"seed": 4, "seat_wind": "27"}):
        with pytest.raises(ValueError):
            PracticeConfig.from_dict(bad)


def test_seat_wind_is_fixed_by_the_seed_and_evenly_spread():
    assert practice.seat_wind_of(PracticeConfig(seed=1, seat_wind=NORTH)) == NORTH
    winds = Counter(practice.seat_wind_of(PracticeConfig(seed=seed)) for seed in range(2000))
    assert set(winds) == {EAST, SOUTH, WEST, NORTH}
    assert all(420 < count < 580 for count in winds.values())          # 期待値 500、標準偏差 約 19
    assert practice.start(PracticeConfig(seed=9)).seat_wind == practice.seat_wind_of(PracticeConfig(seed=9))


# ---------------------------------------------------------------- 補正 0 は素のシャッフルそのもの


def test_zero_luck_hand_is_exactly_the_raw_shuffle(monkeypatch):
    streams: list[str] = []

    class RecordingRng(Rng):
        def __init__(self, seed, stream=""):
            streams.append(stream)
            super().__init__(seed, stream)

    monkeypatch.setattr(practice, "Rng", RecordingRng)
    monkeypatch.setattr(luck, "Rng", RecordingRng)
    for seed in range(120):
        raw = shuffled_tiles(seed)
        chooser = Rng(seed, "test:discard")
        states = play(PracticeConfig(seed=seed), lambda s, chooser=chooser: discard(chooser.choice(s.tiles)))
        for state in states:
            assert list(state.wall_tiles) == raw                         # 山は 1 枚も動いていない
            assert all(d.luck is NO_DRAW_LUCK and not d.auto for d in state.draws)
            assert state.deal.candidates == 1 and not state.deal.applied
        final = states[-1]
        assert [d.tile for d in final.draws] == raw[LIVE_START:LIVE_START + MAX_DRAWS]
        assert sorted(states[0].hand) == sorted(raw[:13])
    assert set(streams) == {"seat"}                                      # 使った乱数は「自風を決める」ぶんだけ


def test_changing_luck_does_not_change_the_raw_wall():
    """同じシードなら、補正を変えても元の山は同じ。ツモの補正だけなら、配牌も同じ"""
    raw = shuffled_tiles(31)
    draw_only = practice.start(PracticeConfig(seed=31, luck=LuckSettings(0, 100)))
    assert sorted(draw_only.hand) == sorted(raw[:13]) and not draw_only.deal.applied
    with_deal = practice.start(PracticeConfig(seed=31, luck=LuckSettings(100, 0)))
    check_invariants(with_deal, raw)
    assert with_deal.wall_tiles[LIVE_END:] == tuple(raw[LIVE_END:])


# ---------------------------------------------------------------- 牌の枚数と再現性


def test_tiles_are_conserved_and_hands_can_be_replayed():
    """実際の補正つきで最後まで打ち、どの時点でも牌の枚数が正しいことと、行動の列から同じ局を作り直せることを確かめる"""
    plan = [
        (LuckSettings(25, 25), 0.25),
        (LuckSettings(50, 50), 0.25),
        (LuckSettings(75, 75), 0.2),
        (LuckSettings(0, 100), 0.2),
        (LuckSettings(100, 0, allow_tenpai_deal=True), 0.1),
    ]
    outcomes: Counter[str] = Counter()
    riichi_hands = 0
    for settings, share in plan:
        swapped = 0
        for seed in range(round(HANDS * share)):
            config = PracticeConfig(seed=seed, luck=settings)
            raw = shuffled_tiles(seed)
            states = play(config, mixed_policy(seed))
            previous_draws: tuple[Draw, ...] = ()
            for state in states:
                check_invariants(state, raw)
                assert state.draws[:len(previous_draws)] == previous_draws      # ツモった牌は、あとから変わらない
                previous_draws = state.draws
            final = states[-1]
            outcomes[final.result.outcome.value] += 1
            riichi_hands += final.in_riichi
            swapped += sum(1 for d in final.draws if d.luck.swapped)

            # 設定と行動の列だけから、同じ結果を作り直せる（途中の局面も）
            saved = json.loads(json.dumps(practice.to_save(final)))
            assert practice.from_save(saved) == final
            if seed % 4 == 0:
                middle = len(final.actions) // 2
                assert practice.replay(config, final.actions[:middle]) == states[middle]
        assert (swapped > 0) == (settings.draw > 0)
    assert sum(outcomes.values()) == sum(round(HANDS * share) for _, share in plan)
    assert outcomes["tsumo"] > 10 and outcomes["exhausted"] > 10 and riichi_hands > 10


def test_draw_luck_fires_at_the_configured_rate_and_brings_effective_tiles():
    settings = LuckSettings(0, 50)
    probability = draw_probability(50)             # 0.12
    rolled = swapped = draws = 0
    for seed in range(150):
        states = play(PracticeConfig(seed=seed, luck=settings), tsumogiri)
        final = states[-1]
        hand = states[0].hand                      # ツモ切りなので、手牌はずっと配牌のまま
        for index, draw in enumerate(final.draws):
            draws += 1
            rolled += draw.luck.rolled
            if not draw.luck.swapped:
                assert draw.luck.original is None
                continue
            swapped += 1
            visible = (*final.discards[:index], *final.dora_indicators)
            wanted = {kind for kind, _ in acceptance(counts34(hand), remaining_counts(hand, visible)).tiles}
            assert kind_of(draw.tile) in wanted and kind_of(draw.luck.original) not in wanted
            assert draw.luck.rolled
    expected = draws * probability                 # 2700 回 × 0.12 ＝ 324 回。標準偏差は √(2700 × 0.12 × 0.88) ≒ 17
    assert draws == 150 * MAX_DRAWS and abs(rolled - expected) < 4 * (expected * (1 - probability)) ** 0.5
    assert 0 < swapped <= rolled


def test_stronger_draw_luck_fires_on_a_superset_of_turns():
    """抽選の乱数は（シード, 何回目のツモか）で決まる。確率を上げると、当たるツモは増えるだけで減らない"""
    for seed in range(12):
        fired = []
        for level in (25, 50, 75, 100):
            final = play(PracticeConfig(seed=seed, luck=LuckSettings(0, level)), tsumogiri)[-1]
            fired.append({d.turn for d in final.draws if d.luck.rolled})
        assert fired[0] <= fired[1] <= fired[2] <= fired[3] and len(fired[3]) > len(fired[0])


# ---------------------------------------------------------------- 打牌と流局


def test_discard_moves_one_tile_and_draws_the_next():
    state = practice.start(PracticeConfig(seed=20261007))
    target = state.hand[3]
    after = practice.apply(state, discard(target))
    assert after.discards == (target,) and target not in after.tiles
    assert sorted(after.hand) == sorted([*(t for t in state.hand if t != target), state.drawn])
    assert (after.turn, after.draws_left) == (2, 16) and after.actions == (discard(target),)
    assert after.visible == (target, *after.dora_indicators)
    assert after.remaining[kind_of(target)] == 4 - counts34([*after.tiles, *after.visible])[kind_of(target)]
    assert after.last_draw == Draw(2, after.drawn, NO_DRAW_LUCK)


def test_illegal_moves_are_refused():
    state = practice.start(PracticeConfig(seed=20261007))
    missing = next(t for t in range(NUM_TILES) if t not in state.tiles)
    with pytest.raises(PracticeError, match="手牌にない牌"):
        practice.apply(state, discard(missing))
    with pytest.raises(PracticeError, match="あがりの形になっていません"):
        practice.apply(state, TSUMO)
    with pytest.raises(PracticeError, match="聴牌にならない"):
        practice.apply(state, riichi(state.drawn))
    assert not state.can_tsumo and state.riichi_discards == ()
    with pytest.raises(ValueError):
        Action.from_list(["t", 5])                       # ツモあがりに牌は付かない
    with pytest.raises(ValueError):
        Action.from_list(["d"])                          # 打牌には牌が要る
    assert Action.from_list(["r", 7]) == riichi(7) and riichi(7).to_list() == ["r", 7] and TSUMO.to_list() == ["t"]


def test_hand_ends_in_exhaustive_draw_after_18_draws():
    states = play(PracticeConfig(seed=1), tsumogiri)
    final = states[-1]
    assert len(states) == MAX_DRAWS + 1 and final.finished and final.drawn is None
    assert final.result.outcome is Outcome.EXHAUSTED and final.result.turn == MAX_DRAWS and final.result.win is None
    assert (final.turn, final.draws_left, len(final.discards)) == (MAX_DRAWS, 0, MAX_DRAWS)
    assert final.hand == states[0].hand and final.tiles == final.hand
    assert final.result.tenpai is False and final.result.waits == ()
    assert final.result.shanten == shanten_of(counts34(final.hand)) > 0
    assert not final.can_tsumo and final.riichi_discards == ()
    with pytest.raises(PracticeError, match="終わっています"):
        practice.apply(final, discard(final.hand[0]))
    with pytest.raises(PracticeError, match="終わっています"):
        practice.position_of(final)


def test_exhaustive_draw_reports_tenpai_and_waits():
    state = start_on(crafted_wall(TENPAI_HAND, "9m5555z6666z7777z1111z2z"))
    while not state.finished:
        state = practice.apply(state, tsumogiri(state))          # リーチせずにツモ切りを続ける
    assert state.result.outcome is Outcome.EXHAUSTED and state.result.tenpai and state.result.shanten == 0
    assert state.result.waits == (kind_of(parse_tiles("1s")[0]), kind_of(parse_tiles("4s")[0]))
    assert not state.in_riichi and all(not d.auto for d in state.draws)


# ---------------------------------------------------------------- ツモあがり


def test_tsumo_without_riichi():
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s", ura="3z"))
    assert not state.can_tsumo
    state = practice.apply(state, discard(tile(state, "9m")))
    assert state.can_tsumo and format_tiles([state.drawn]) == "4s"
    won = practice.apply(state, TSUMO)
    assert won.finished and won.result.outcome is Outcome.TSUMO and won.result.turn == 2 and won.result.shanten is None
    assert won.drawn == state.drawn and won.hand == state.hand and won.actions[-1] == TSUMO
    win = won.result.win
    assert win.is_tsumo and win.win_tile == won.drawn and sorted(win.closed_tiles) == sorted(won.tiles)
    assert (win.riichi, win.double_riichi, win.ippatsu, win.tenhou, win.chiihou) == (False, False, False, False, False)
    assert win.ura_indicators == ()                              # リーチしていないので、裏ドラは見ない
    assert (win.seat_wind, win.round_wind, win.dora_indicators) == (SOUTH, EAST, won.dora_indicators)
    result = explain(win)
    assert result.status is Status.WIN and result.consistent
    assert result.declaration == "ツモ。ツモ・ピンフ。400・700。"


def test_declining_a_win_is_allowed():
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s2z1s"))
    state = practice.apply(state, discard(tile(state, "9m")))
    assert state.can_tsumo
    state = practice.apply(state, discard(state.drawn))          # あがらずにツモ切り
    assert not state.finished and not state.can_tsumo
    state = practice.apply(state, discard(state.drawn))
    assert state.can_tsumo                                        # 次の 1索 でまたあがれる


def test_tenhou_and_chiihou():
    wall = crafted_wall(TENPAI_HAND, "1s")
    for seat, flags, key in ((EAST, (True, False), "tenhou"), (SOUTH, (False, True), "chiihou")):
        state = start_on(wall, seat_wind=seat)
        assert state.can_tsumo and state.turn == 1
        win = practice.apply(state, TSUMO).result.win
        assert (win.tenhou, win.chiihou) == flags
        result = explain(win)
        assert result.consistent and [y.key for y in result.best.evaluation.yaku] == [key]
    # 2 回目のツモであがっても、天和・地和にはならない
    state = start_on(crafted_wall(TENPAI_HAND, "9m1s"), seat_wind=EAST)
    state = practice.apply(state, discard(tile(state, "9m")))
    win = practice.apply(state, TSUMO).result.win
    assert (win.tenhou, win.chiihou) == (False, False)


# ---------------------------------------------------------------- リーチ


def test_riichi_needs_a_discard_that_keeps_tenpai():
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s"))
    assert sorted(state.riichi_discards) == [tile(state, "9m")]              # 9萬 を切れば聴牌のまま
    with pytest.raises(PracticeError, match="聴牌にならない"):
        practice.apply(state, riichi(tile(state, "2s")))

    # 聴牌を保てる牌が何種類もある形：2344索 に 5索 を引いた 23445索 は、2・4・5 のどれを切っても聴牌
    state = start_on(crafted_wall("123m456p789s2344s", "5s9m"))
    assert sorted(format_tiles([t]) for t in state.riichi_discards) == ["2s", "4s", "4s", "5s"]
    assert all(shanten_of(counts34([x for x in state.tiles if x != t])) == 0 for t in state.riichi_discards)
    assert shanten_of(counts34([x for x in state.tiles if x != tile(state, "3s")])) == 1


def test_double_riichi_and_ippatsu():
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s", ura="3z"))
    won = practice.apply(state, riichi(tile(state, "9m")))
    assert won.finished and won.result.outcome is Outcome.TSUMO and won.result.turn == 2
    assert won.in_riichi and won.riichi_index == 0 and len(won.discards) == 1
    assert [d.auto for d in won.draws] == [False, False]                      # あがり牌は、河に出ない
    win = won.result.win
    assert (win.riichi, win.double_riichi, win.ippatsu) == (True, True, True)
    assert win.ura_indicators == won.ura_indicators != ()
    result = explain(win)
    assert result.consistent
    assert [y.key for y in result.best.evaluation.yaku] == ["double_riichi", "ippatsu", "menzen_tsumo", "pinfu"]
    assert result.dora.ura == 2                                               # 裏ドラ表示牌が西 → 北が裏ドラ（2 枚）
    # ダブル立直 2 ＋ 一発 1 ＋ ツモ 1 ＋ 平和 1 ＋ 裏ドラ 2 ＝ 7 翻（跳満）
    assert result.declaration == "ツモ。ダブルリーチ・イッパツ・ツモ・ピンフ・裏 2。跳満、3000・6000。"


def test_riichi_later_wins_without_ippatsu_after_automatic_discards():
    state = start_on(crafted_wall(TENPAI_HAND, "5z6z7z1s"))
    state = practice.apply(state, discard(state.drawn))                       # 1 巡目はリーチせずに白を切る
    assert state.riichi_discards and not state.in_riichi
    won = practice.apply(state, riichi(state.drawn))                          # 2 巡目に發を切ってリーチ
    assert won.result.outcome is Outcome.TSUMO and won.result.turn == 4 and won.riichi_index == 1
    assert [d.auto for d in won.draws] == [False, False, True, False]         # 3 巡目の中は、自動でツモ切り
    assert [format_tiles([t]) for t in won.discards] == ["5z", "6z", "7z"]
    win = won.result.win
    assert (win.riichi, win.double_riichi, win.ippatsu) == (True, False, False)
    assert [y.key for y in explain(win).best.evaluation.yaku] == ["riichi", "menzen_tsumo", "pinfu"]
    assert won.actions == (discard(won.discards[0]), riichi(won.discards[1]))  # 自動のツモ切りは、行動の列に入らない


def test_riichi_can_end_in_exhaustive_draw():
    state = start_on(crafted_wall(TENPAI_HAND, "9m5555z6666z7777z1111z2z"))
    final = practice.apply(state, riichi(tile(state, "9m")))
    assert final.result.outcome is Outcome.EXHAUSTED and final.result.tenpai and final.result.turn == MAX_DRAWS
    assert final.in_riichi and final.riichi_index == 0
    assert len(final.discards) == MAX_DRAWS and final.discards[1:] == tuple(d.tile for d in final.draws[1:])
    assert [d.auto for d in final.draws] == [False] + [True] * (MAX_DRAWS - 1)
    assert sorted(final.hand) == sorted(parse_tiles(TENPAI_HAND))             # リーチ後は手牌が変わらない


def test_no_riichi_on_the_last_draw():
    state = start_on(crafted_wall("123m456p789s2s144z", "5555z6666z7777z11122z3s"))
    for _ in range(MAX_DRAWS - 1):
        state = practice.apply(state, tsumogiri(state))
    assert state.turn == MAX_DRAWS and state.draws_left == 0 and format_tiles([state.drawn]) == "3s"
    assert state.riichi_discards == ()                                        # 聴牌にとれるが、もうツモが無い
    with pytest.raises(PracticeError, match="ツモが残っていない"):
        practice.apply(state, riichi(tile(state, "1z")))
    final = practice.apply(state, discard(tile(state, "1z")))
    assert final.result.outcome is Outcome.EXHAUSTED and final.result.tenpai


# ---------------------------------------------------------------- 保存


def test_broken_saves_are_rejected():
    state = practice.start(PracticeConfig(seed=4))
    state = practice.apply(state, discard(state.drawn))
    good = practice.to_save(state)
    assert good == {"v": 1, "config": state.config.to_dict(), "actions": [["d", state.discards[0]]]}
    assert practice.from_save(good) == state
    broken = [
        None,
        [],
        {},
        {**good, "v": 2},
        {"v": 1, "actions": []},
        {"v": 1, "config": {}, "actions": []},
        {**good, "config": {"seed": -5}},
        {**good, "config": {**good["config"], "luck": {"deal": 999}}},
        {**good, "config": {**good["config"], "rules": 3}},
        {**good, "actions": None},
        {**good, "actions": [["x", 1]]},
        {**good, "actions": [["d"]]},
        {**good, "actions": [["d", "abc"]]},
        {**good, "actions": [[]]},
        {**good, "actions": [["d", 999]]},                    # 手牌にない牌を切っている
        {**good, "actions": [["t"]]},                         # あがれないのにツモあがり
        {**good, "actions": [["d", state.discards[0]]] * 2},  # 同じ牌を 2 回切っている
        # ここからは、型がおかしいもの。どれも ValueError で（ほかの例外で）断る
        {**good, "config": []},
        {**good, "config": "x"},
        {**good, "config": None},
        {**good, "config": {**good["config"], "luck": [1]}},
        {**good, "config": {**good["config"], "luck": "強"}},
        {**good, "config": {**good["config"], "seed": float("inf")}},
        {**good, "config": {**good["config"], "seed": 4.7}},
        {**good, "config": {**good["config"], "luck": {"deal": float("inf")}}},
        {**good, "config": {**good["config"], "rules": {"aka_dora": [1]}}},
        {**good, "config": {**good["config"], "rules": {"aka_dora": "no"}}},
        {**good, "config": {**good["config"], "seat_wind": float("inf")}},
        {**good, "actions": {}},
        {**good, "actions": "dd"},
        {**good, "actions": [["d", float("inf")]]},
        {**good, "actions": [["d", state.discards[0] + 0.5]]},
        {**good, "actions": [["d", True]]},
        {**good, "actions": [[1, 2]]},
        {**good, "actions": ["d5"]},
        {**good, "actions": [["d", 1, 2]]},
        {**good, "actions": [["d", state.discards[0]]] * 5000},     # 1 局にありえない長さ
    ]
    for data in broken:
        with pytest.raises(ValueError):
            practice.from_save(data)
    # JSON として読める「変な数」も同じ（Infinity や 1e400 は、Python の json では float の無限大になる）
    for text in ('{"v":1,"config":{"seed":Infinity},"actions":[]}', '{"v":1,"config":{"seed":1e400},"actions":[]}',
                 '{"v":1,"config":{"seed":4},"actions":[["d",1e400]]}'):
        with pytest.raises(ValueError):
            practice.from_save(json.loads(text))


# ---------------------------------------------------------------- コーチへの橋渡し


def test_position_and_decisions():
    config = PracticeConfig(seed=7, luck=LuckSettings(50, 50))
    state = practice.start(config)
    position = practice.position_of(state)
    assert position.tiles == state.tiles and position.visible == state.visible and position.drawn == state.drawn
    assert (position.seat_wind, position.round_wind, position.draws_left) == (state.seat_wind, EAST, 17)
    assert position.can_riichi and position.unseen == state.unseen_total and position.rules == config.rules
    assert practice.assess(state, TSUMO) is None

    collected = []
    chooser = mixed_policy(7)
    while not state.finished:
        action = chooser(state)
        decision = practice.assess(state, action)
        if decision is not None:
            assert decision.turn == state.turn and decision.action == action
            assert decision.verdict.chosen.kind == kind_of(action.tile)
            assert decision.verdict.riichi == (action.move is Move.RIICHI)
            collected.append(decision)
        state = practice.apply(state, action)
    assert practice.decisions_of(config, state.actions) == tuple(collected)
    assert len(collected) == sum(1 for a in state.actions if a.move is not Move.TSUMO) > 0


def test_states_are_immutable_values():
    state = practice.start(PracticeConfig(seed=2))
    after = practice.apply(state, discard(state.drawn))
    assert state.discards == () and state.turn == 1                  # 元の状態は変わらない
    assert replace(after) == after and hash(after.config) == hash(replace(after.config))

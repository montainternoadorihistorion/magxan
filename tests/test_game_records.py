"""CPU との対局の成績（engine/game_records.py）のテスト"""
from __future__ import annotations

import json
from dataclasses import replace
from functools import cache

import pytest

from engine import game as g
from engine.cpu import advance, all_cpu
from engine.game import CpuLevel, GameConfig, Length
from engine.game_records import (
    GOAL_GAMES,
    GameRecord,
    Tally,
    add_record,
    dump_history,
    dump_record,
    graduation,
    load_history,
    record_of,
    records_from,
    rules_text,
    summarize,
)
from engine.luck import LuckSettings
from engine.rules import Rules


def _finished(seed: int, **config) -> g.GameState:
    return _play(GameConfig(seed=seed, **config))


@cache
def _play(config: GameConfig) -> g.GameState:
    """4 人とも CPU で最後まで打った対局（同じ設定なら、作り直さない）"""
    game = g.start_game(config)
    while not game.finished:
        if game.between_hands:
            game = g.next_hand(game)
        game = advance(game, cpu_seats=all_cpu())
    return game


def test_record_of_a_finished_game_counts_the_human_seat():
    game = _finished(8)
    record = record_of(game, Tally(10, 7, 2, 1), time=1_700_000_000, hinted=False)
    assert record.rank == game.result.ranks[g.HUMAN] and record.score == game.result.scores[g.HUMAN]
    assert record.hands == len(game.hands)
    wins = sum(any(w.seat == 0 for w in h.result.wins) for h in game.hands)
    deal_ins = sum(h.result.kind is g.EndKind.RON and any(w.from_seat == 0 for w in h.result.wins) for h in game.hands)
    assert (record.wins, record.deal_ins) == (wins, deal_ins)
    assert record.deal == record.draw == 0 and record.cpu_level == "normal" and record.length == "east"
    assert record.tally == Tally(10, 7, 2, 1) and record.rules == ()
    with pytest.raises(ValueError):
        record_of(g.start_game(GameConfig(seed=1)), Tally(), time=0, hinted=False)


def test_plain_means_no_luck_and_no_hints():
    game = _finished(8)
    assert record_of(game, Tally(), time=0, hinted=False).plain
    assert not record_of(game, Tally(), time=0, hinted=True).plain
    lucky = _finished(8, luck=LuckSettings(25, 0))
    assert not record_of(lucky, Tally(), time=0, hinted=False).plain


def test_round_trip_and_broken_records():
    game = _finished(8, rules=Rules(tobi=False))
    record = record_of(game, Tally(3, 2, 1, 1), time=123, hinted=True)
    assert record.rules == (("tobi", False),)
    again = GameRecord.from_dict(json.loads(dump_record(record)))
    assert again == record
    bad = [
        None, {}, {**record.to_dict(), "rank": 5}, {**record.to_dict(), "len": "north"}, {**record.to_dict(), "cpu": "hard"},
        {**record.to_dict(), "hinted": "yes"}, {**record.to_dict(), "wins": 999}, {**record.to_dict(), "rules": []},
    ]
    for item in bad:
        with pytest.raises(ValueError):
            GameRecord.from_dict(item)
    # 知らないルールや、おかしな値のルールは捨てる。壊れた tally は 0 から
    odd = GameRecord.from_dict({**record.to_dict(), "rules": {"tobi": False, "magic": True, "kuitan": "no"}, "tally": {"n": -1}})
    assert odd.rules == (("tobi", False),) and odd.tally == Tally()
    text = json.dumps([record.to_dict(), {"broken": True}, record.to_dict()])
    assert len(load_history(text)) == 2
    assert load_history("not json") == [] and load_history(None) == []
    assert len(records_from(json.loads(dump_history([record, record])))) == 2


def test_summaries_split_by_condition_and_put_skill_first():
    base = GameRecord(time=1, seed=1, length="east", deal=0, draw=0, cpu_deal=0, cpu_draw=0, cpu_level="normal",
                      hinted=False, rank=2, score=26_000, hands=5, wins=1, deal_ins=0)
    records = [
        replace(base, deal=75, draw=75, rank=1),
        replace(base, rank=2),
        replace(base, rank=4, deal_ins=2),
        replace(base, hinted=True, rank=3),
        replace(base, length="south", rank=1),
    ]
    rows = summarize(records)
    assert rows[0].plain and rows[0].length == "east" and rows[0].games == 2
    assert rows[0].average_rank == 3.0 and rows[0].deal_in_rate == pytest.approx(2 / 10)
    assert sum(r.games for r in rows) == 5
    hinted = next(r for r in rows if r.hinted)
    assert hinted.follow_rate is None


def test_graduation_uses_the_recent_plain_east_games_against_normal_cpu():
    base = GameRecord(time=1, seed=1, length="east", deal=0, draw=0, cpu_deal=0, cpu_draw=0, cpu_level="normal",
                      hinted=False, rank=2, score=26_000, hands=5, wins=1, deal_ins=0)
    assert graduation([]).games == 0 and not graduation([]).passed
    records = [base] * GOAL_GAMES
    grad = graduation(records)
    assert grad.enough and grad.rank_ok and grad.deal_in_ok and grad.misses_ok and grad.passed
    # 条件の違う対局は数えない
    other = [replace(base, cpu_level="weak", rank=4)] * 5 + [replace(base, length="south", rank=4)] * 5 + [replace(base, rules=(("tobi", False),), rank=4)]
    assert graduation(records + other).passed
    missed = graduation([*records[:-1], replace(base, misses=1)])
    assert not missed.misses_ok and not missed.passed
    slow = graduation([replace(base, rank=3)] * GOAL_GAMES)
    assert not slow.rank_ok


def test_add_record_keeps_the_newest():
    base = GameRecord(time=1, seed=1, length="east", deal=0, draw=0, cpu_deal=0, cpu_draw=0, cpu_level="normal",
                      hinted=False, rank=2, score=26_000, hands=5)
    records = []
    for index in range(310):
        records = add_record(records, replace(base, seed=index))
    assert len(records) == 300 and records[-1].seed == 309


def test_rules_text_names_the_changed_rules():
    assert rules_text([("tobi", False), ("multiple_ron", False)]) == "飛びなし・頭ハネ"
    assert rules_text({"double_wind_pair_fu": 2}) == "連風牌の雀頭 2 符"


def test_config_values_are_recorded():
    game = _finished(5, length=Length.EAST, cpu_level=CpuLevel.WEAK, cpu_luck=LuckSettings(10, 20))
    record = record_of(game, Tally(), time=0, hinted=False)
    assert (record.cpu_level, record.cpu_deal, record.cpu_draw) == ("weak", 10, 20)
    assert not record.plain


def test_only_real_oversights_count_as_misses():
    """見落としに数えるのは、役なし・捨て牌のフリテン。自分で見送ったことと、その結果のフリテンは数えない"""
    from engine.game import Furiten, Miss, RonCheck
    from engine.game_records import is_oversight

    def miss(furiten=None, yaku=True, passed=False, seat=0):
        return Miss(seat=seat, from_seat=1, tile=0, check=RonCheck(True, furiten, yaku), passed=passed)

    assert is_oversight(miss(yaku=False))                       # 役が無くてロンできなかった
    assert is_oversight(miss(Furiten.RIVER))                    # 自分の捨て牌にあがり牌（捨て牌のフリテン）
    assert not is_oversight(miss(passed=True))                  # 自分で見送った
    assert not is_oversight(miss(Furiten.MISSED))               # 見送ったあとの同巡内フリテン
    assert not is_oversight(miss(Furiten.RIICHI))               # リーチ後の見逃しのあと
    assert not is_oversight(miss(yaku=False, seat=2))           # 自分以外

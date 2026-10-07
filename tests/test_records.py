"""成績の記録と集計（engine/records.py）のテスト"""
from __future__ import annotations

import json

import pytest
from practice_helpers import TENPAI_HAND, crafted_wall, start_on, tile, tsumogiri

from engine import practice
from engine.practice import TSUMO, discard, riichi
from engine.records import (
    MAX_RECORDS,
    HandRecord,
    add_record,
    dump_history,
    dump_record,
    load_history,
    record_of,
    summarize,
    yaku_counts,
)


def play_with_decisions(state, actions):
    decisions = []
    for make in actions:
        action = make(state)
        decision = practice.assess(state, action)
        if decision is not None:
            decisions.append(decision)
        state = practice.apply(state, action)
    return state, decisions


def record(**kwargs) -> HandRecord:
    base = {"time": 1000, "seed": 1, "deal": 0, "draw": 0, "hinted": False, "win": False, "turn": 18, "riichi": False, "tenpai": False}
    return HandRecord(**{**base, **kwargs})


# ---------------------------------------------------------------- 記録を作る


def test_record_of_a_riichi_win():
    state = start_on(crafted_wall(TENPAI_HAND, "5z6z7z1s"))
    state, decisions = play_with_decisions(state, [lambda s: discard(tile(s, "2s")), lambda s: riichi(s.drawn) if s.riichi_discards else discard(s.drawn)])
    # 1 巡目に 2索 を切って聴牌をくずし（悪い打牌）、2 巡目はツモ切り（リーチできない）
    assert not state.finished and [d.verdict.is_best for d in decisions] == [False, True]

    state = start_on(crafted_wall(TENPAI_HAND, "5z6z7z1s"))
    state, decisions = play_with_decisions(state, [lambda s: discard(s.drawn), lambda s: riichi(s.drawn)])
    made = record_of(state, decisions, time=1234.9, hinted=True)
    assert made == HandRecord(
        time=1234, seed=0, deal=0, draw=0, hinted=True, win=True, turn=4, riichi=True, tenpai=True,
        points=2700, han=3, fu=20, yaku=("riichi", "menzen_tsumo", "pinfu"), decisions=2, best=2,
    )
    assert made.luck_key == (0, 0)


def test_record_of_a_quiet_win_and_of_exhaustive_draws():
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s"))
    state, decisions = play_with_decisions(state, [lambda s: discard(tile(s, "9m")), lambda s: TSUMO])
    made = record_of(state, decisions, time=5, hinted=False)
    assert (made.win, made.riichi, made.turn, made.points, made.han, made.fu) == (True, False, 2, 1500, 2, 20)
    assert made.yaku == ("menzen_tsumo", "pinfu") and (made.decisions, made.best) == (1, 1)

    state = start_on(crafted_wall(TENPAI_HAND, "9m5555z6666z7777z1111z2z"))
    decisions = []
    while not state.finished:
        action = tsumogiri(state)
        decisions.append(practice.assess(state, action))
        state = practice.apply(state, action)
    made = record_of(state, decisions, time=5, hinted=False)
    assert (made.win, made.tenpai, made.turn, made.points, made.yaku) == (False, True, 18, 0, ())
    assert (made.decisions, made.best) == (18, 18)             # 聴牌を保つツモ切りは、どれも最善

    with pytest.raises(ValueError, match="終わっていない"):
        record_of(start_on(crafted_wall(TENPAI_HAND, "9m4s")), [], time=0, hinted=False)


# ---------------------------------------------------------------- 変換


def test_record_roundtrip_and_validation():
    made = record(win=True, tenpai=True, turn=7, points=3900, han=3, fu=30, yaku=("riichi", "pinfu"), decisions=6, best=4, deal=50, draw=25, hinted=True)
    assert HandRecord.from_dict(json.loads(json.dumps(made.to_dict()))) == made
    assert HandRecord.from_dict({"t": 1, "seed": 2, "deal": 0, "draw": 0, "turn": 18}) == record(time=1, seed=2)
    good = made.to_dict()
    for broken in (
        None, [], "x",
        {**good, "deal": 101}, {**good, "draw": -1}, {**good, "t": "いつか"}, {**good, "turn": True},
        {**good, "best": 7},                    # 選んだ打牌の回数より多い
        {**good, "yaku": "riichi"}, {**good, "yaku": [1, 2]}, {k: v for k, v in good.items() if k != "seed"},
        {**good, "win": "false"}, {**good, "hinted": 1}, {**good, "riichi": None}, {**good, "tenpai": []},   # 真偽値は True / False だけ
        {**good, "pts": 1.5}, {**good, "t": float("inf")},
    ):
        with pytest.raises(ValueError):
            HandRecord.from_dict(broken)


def test_history_roundtrip_and_tolerance():
    records = [record(seed=n, time=n) for n in range(3)]
    text = dump_history(records)
    assert load_history(text) == records
    assert load_history(None) == [] and load_history("") == [] and load_history("{こわれている") == []
    assert load_history(json.dumps([1, 2])) == [] and load_history(json.dumps({"v": 99, "hands": []})) == []
    assert load_history(json.dumps({"v": 1, "hands": "x"})) == [] and load_history(json.dumps("x")) == []
    # 壊れた 1 件だけを読み飛ばす
    data = json.loads(text)
    data["hands"].insert(1, {"seed": "だめ"})
    assert load_history(json.dumps(data)) == records
    # 入れ子が深すぎて JSON として読めないものも、空として扱う（例外を出さない）
    assert load_history("[" * 100_000) == [] and load_history('{"v":1,"hands":' + "[" * 100_000) == []


def test_history_is_also_read_as_a_bare_list_of_records():
    """ブラウザには、記録の配列をそのまま置く（末尾に 1 件ずつ足していけるように）"""
    records = [record(seed=n, time=n, win=n % 2 == 0, tenpai=n % 2 == 0) for n in range(4)]
    text = "[" + ",".join(dump_record(r) for r in records) + "]"
    assert load_history(text) == records
    assert json.loads(dump_record(records[0])) == records[0].to_dict()
    mixed = json.loads(text)
    mixed.insert(2, "こわれた 1 件")
    assert load_history(json.dumps(mixed)) == records
    assert len(load_history("[" + ",".join(dump_record(record(seed=n)) for n in range(MAX_RECORDS + 7)) + "]")) == MAX_RECORDS


def test_history_keeps_only_the_latest_records():
    records: list[HandRecord] = []
    for n in range(MAX_RECORDS + 5):
        records = add_record(records, record(seed=n, time=n))
    assert len(records) == MAX_RECORDS and records[0].seed == 5 and records[-1].seed == MAX_RECORDS + 4
    assert len(load_history(dump_history([record(seed=n) for n in range(MAX_RECORDS + 20)]))) == MAX_RECORDS


# ---------------------------------------------------------------- 集計


def test_summary_is_split_by_luck_and_hints_with_skill_first():
    records = [
        record(deal=75, draw=75, win=True, tenpai=True, turn=6, points=8000, riichi=True, decisions=5, best=5, hinted=True),
        record(deal=75, draw=75, win=True, tenpai=True, turn=10, points=2000, decisions=9, best=6),
        record(deal=0, draw=0, win=False, tenpai=True, turn=18, decisions=18, best=9),
        record(deal=0, draw=0, win=True, tenpai=True, turn=12, points=1300, riichi=True, decisions=11, best=11),
        record(deal=0, draw=0, win=True, tenpai=True, turn=9, points=7700, decisions=8, best=8, hinted=True),
        record(deal=25, draw=0, win=False, turn=18, decisions=0, best=0),
    ]
    skill, guided, weak, strong, strong_guided = summarize(records)
    keys = [(s.deal, s.draw, s.hinted) for s in (skill, guided, weak, strong, strong_guided)]
    assert keys == [(0, 0, False), (0, 0, True), (25, 0, False), (75, 75, False), (75, 75, True)]
    # 実力として見るのは、補正なしで、打つ前のヒントも見ていない局だけ
    assert [s.is_skill for s in (skill, guided, weak, strong, strong_guided)] == [True, False, False, False, False]
    assert [s.no_luck for s in (skill, guided, weak, strong, strong_guided)] == [True, True, False, False, False]

    assert (skill.hands, skill.wins, skill.riichi, skill.tenpai) == (2, 1, 1, 2)
    assert skill.win_rate == pytest.approx(1 / 2) and skill.tenpai_rate == 1.0
    assert skill.average_turn == 12 and skill.average_points == 1300
    assert (skill.decisions, skill.best) == (29, 20) and skill.best_rate == pytest.approx(20 / 29)

    # ヒントを見た局は、あがり率などは出すが、打牌の一致率は数えない（おすすめをなぞれば 100% になるので）
    assert (guided.hands, guided.wins, guided.average_turn, guided.average_points) == (1, 1, 9, 7700)
    assert (guided.decisions, guided.best) == (8, 8) and guided.best_rate is None
    assert (strong.hands, strong.wins, strong.average_points, strong.best_rate) == (1, 1, 2000, pytest.approx(6 / 9))
    assert (strong_guided.hands, strong_guided.average_points, strong_guided.best_rate) == (1, 8000, None)
    assert (weak.hands, weak.wins, weak.win_rate) == (1, 0, 0.0)
    assert weak.average_turn is None and weak.average_points is None and weak.best_rate is None
    assert summarize([]) == []


def test_yaku_counts():
    records = [record(yaku=("riichi", "pinfu")), record(yaku=("riichi",)), record(yaku=("tanyao", "pinfu")), record()]
    assert yaku_counts(records) == {"pinfu": 2, "riichi": 2, "tanyao": 1}
    assert list(yaku_counts(records)) == ["pinfu", "riichi", "tanyao"]

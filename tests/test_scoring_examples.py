"""点数計算ラボの例題と、ランダム出題のテスト"""
from __future__ import annotations

import pytest

from engine.scoring.examples import EXAMPLES, EXAMPLES_BY_KEY
from engine.scoring.explain import Status, explain
from engine.scoring.judge import Level
from engine.scoring.notation import make_context, to_notation
from engine.scoring.random_hand import KINDS, random_win
from engine.tiles import counts34


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.key)
def test_example_matches_hand_computed_answer(example):
    result = explain(example.context(), example.rules)
    assert result.consistent, result.mismatches
    if example.han is None:
        assert result.status is Status.NO_YAKU
        return
    assert result.status is Status.WIN
    best = result.best
    assert (best.han, best.fu.fu) == (example.han, example.fu)
    assert best.points.declaration == example.say


def test_example_keys_are_unique_and_ordered():
    keys = [e.key for e in EXAMPLES]
    assert len(set(keys)) == len(keys)
    assert keys == sorted(keys)
    assert set(EXAMPLES_BY_KEY) == set(keys)
    assert all(e.lesson.endswith("。") for e in EXAMPLES)


@pytest.mark.parametrize("kind", list(KINDS))
def test_random_win_is_valid_and_reproducible(kind):
    for seed in range(40):
        ctx = random_win(seed, kind)
        assert ctx == random_win(seed, kind)          # 同じシードなら同じ手
        result = explain(ctx)
        assert result.status is Status.WIN and result.consistent
        # 手牌・副露・ドラ表示牌を合わせても、同じ種類の牌は 4 枚まで（牌IDの重複もない）
        everything = [*ctx.all_tiles, *ctx.dora_indicators, *ctx.ura_indicators]
        assert len(set(everything)) == len(everything)
        assert max(counts34(everything)) <= 4
        assert len(ctx.dora_indicators) >= 1
        assert bool(ctx.ura_indicators) == ctx.riichi
        best = result.best
        if kind == "menzen":
            assert ctx.is_menzen
        elif kind == "open":
            assert not ctx.is_menzen
        elif kind == "fu":
            assert best.points.level is Level.NONE and best.fu.fu not in (20, 30)
        elif kind == "big":
            assert best.points.level is not Level.NONE


def test_random_win_differs_by_seed_and_kind():
    hands = {to_notation(random_win(seed, "any"))["hand"] for seed in range(30)}
    assert len(hands) >= 28
    assert random_win(1, "any") != random_win(1, "big")


def test_random_win_rejects_unknown_kind():
    with pytest.raises(ValueError):
        random_win(1, "nothing")


def test_notation_round_trip():
    """to_notation で書き戻した内容から、同じ状況を作り直せる"""
    for seed in range(60):
        ctx = random_win(seed, "any")
        again = make_context(**to_notation(ctx))
        first, second = explain(ctx), explain(again)
        assert counts34(again.all_tiles) == counts34(ctx.all_tiles)
        assert again.win_kind == ctx.win_kind and again.is_tsumo == ctx.is_tsumo
        assert (second.best.han, second.best.fu.fu, second.best.points.total) == (first.best.han, first.best.fu.fu, first.best.points.total)

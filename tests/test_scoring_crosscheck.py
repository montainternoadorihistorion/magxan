"""自前の点数計算と判定ライブラリの突き合わせ（ランダムな和了形）。

件数は環境変数 MJDOJO_CROSSCHECK_CASES で増やせる（開発時は 40 万件で食い違いなしを確認）。
"""
from __future__ import annotations

import os
import random
from collections import Counter

from stress_hands import random_case

from engine.scoring.explain import Status, explain
from engine.scoring.notation import to_notation
from engine.yaku_table import YAKU

CASES = int(os.environ.get("MJDOJO_CROSSCHECK_CASES", "5000"))


def test_random_hands_match_library():
    rnd = random.Random(20261007)
    statuses: Counter[Status] = Counter()
    yaku_seen: Counter[str] = Counter()
    alternatives = 0
    made = 0
    while made < CASES:
        case = random_case(rnd)
        if case is None:
            continue
        made += 1
        ctx, rules = case
        result = explain(ctx, rules)
        assert result.consistent, (result.mismatches, to_notation(ctx), rules)
        statuses[result.status] += 1
        if result.best is not None:
            alternatives += result.has_alternatives
            for item in result.best.evaluation.yaku:
                yaku_seen[item.key] += 1

    # 入力がきちんと散らばっていること（和了・役なし・和了でない形、複数の読み方、ほぼすべての役）
    assert statuses[Status.WIN] > CASES * 0.7
    assert statuses[Status.NO_YAKU] > 0 and statuses[Status.NOT_WINNING] > 0
    assert alternatives > CASES * 0.05
    assert len(yaku_seen) >= len(YAKU) - 3

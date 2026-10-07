"""役指定練習の効き具合を測るスクリプト（開発用）。

狙う役ごとに、機械的な打ち手で何局も打って、「その役が付いたあがり」の割合を表にする。

    打ち手：役指定練習のコーチのおすすめ（狙う役に近づく切り方）を切る。
            狙った役（か、その上位の役）が付くあがりの形になったら、あがる。付かないあがりは見送って、役を狙い続ける。
            ただし、最後のツモと、手の形を問わない役（立直・一発など）を狙うときは、付かなくてもあがる。
            リーチは、立直・一発・ダブル立直を狙うときだけ、聴牌したらすぐかける。

実行:  python tools/measure_target.py [局数（既定 30）] [役の鍵 …]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import practice  # noqa: E402
from engine.analysis.target import SHAPELESS_KEYS, TARGET_KEYS  # noqa: E402
from engine.content import yaku_page_map  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402
from engine.scoring.explain import explain  # noqa: E402
from engine.target_coach import target_advice, target_result  # noqa: E402

RIICHI_TARGETS = ("riichi", "ippatsu", "double_riichi")
LEVELS = (("中", 50), ("強", 75), ("最大", 100))


def choose(state: practice.PracticeState) -> practice.Action:
    """機械的な打ち手の 1 手"""
    key = state.config.target
    if state.can_tsumo:
        win = practice.apply(state, practice.TSUMO).result.win
        if target_result(explain(win, state.config.rules), key).achieved or state.draws_left == 0 or key in SHAPELESS_KEYS:
            return practice.TSUMO
    advice = target_advice(practice.position_of(state), key)
    if advice.pick is None:                     # もう作れない（か、付かないあがりの形）：速さのおすすめを切る
        kind = advice.speed_kind
        tile = next(t for t in state.tiles if t // 4 == kind)
        return practice.discard(tile)
    tile = advice.pick.tile
    if key in RIICHI_TARGETS and advice.pick.distance == 0 and tile in state.riichi_discards:
        return practice.riichi(tile)
    return practice.discard(tile)


def play(config: practice.PracticeConfig) -> practice.PracticeState:
    state = practice.start(config)
    while not state.finished:
        state = practice.apply(state, choose(state))
    return state


def feasible_config(key: str, level: int, seed: int) -> practice.PracticeConfig:
    """その山で役が作れる局を選ぶ（作れない山なら、番号を 1000 ずつ進めて探す。画面の「次の局」と同じ考え方）"""
    while True:
        config = practice.PracticeConfig(seed=seed, luck=LuckSettings(level, level), target=key)
        deal = practice.start(config).deal
        if not deal.target or deal.chosen_distance is not None:
            return config
        seed += 1000


def measure(key: str, level: int, hands: int) -> dict:
    made = wins = turns = swaps = 0
    start_distance = 0
    for seed in range(hands):
        state = play(feasible_config(key, level, seed))
        swaps += state.deal.swaps
        start_distance += state.deal.chosen_distance if state.deal.chosen_distance is not None else state.deal.chosen_shanten
        if state.result.outcome is practice.Outcome.TSUMO:
            wins += 1
            if target_result(explain(state.result.win, config_rules(state)), key).achieved:
                made += 1
                turns += state.result.turn
    return {
        "made": made / hands,
        "wins": wins / hands,
        "turn": turns / made if made else 0.0,
        "swaps": swaps / hands,
        "start": start_distance / hands,
    }


def config_rules(state: practice.PracticeState):
    return state.config.rules


def main() -> None:
    args = sys.argv[1:]
    hands = int(args[0]) if args and args[0].isdigit() else 30
    keys = [a for a in args if not a.isdigit()] or list(TARGET_KEYS)
    pages = yaku_page_map()
    print(f"各 {hands} 局（シード 0〜{hands - 1}）。数字は「狙った役（か上位の役）が付いたあがり」の割合／平均の巡目\n")
    print("| 役 | " + " | ".join(f"{name}（{level}）" for name, level in LEVELS) + " | 配牌の距離（強） | 秒 |")
    print("|---|" + "---|" * (len(LEVELS) + 2))
    for key in keys:
        started = time.perf_counter()
        cells = []
        strong = None
        for name, level in LEVELS:
            r = measure(key, level, hands)
            if name == "強":
                strong = r
            cells.append(f"{r['made'] * 100:.0f}%／{r['turn']:.1f}")
        print(f"| {pages[key].name} | " + " | ".join(cells) + f" | {strong['start']:.1f} | {time.perf_counter() - started:.0f} |", flush=True)


if __name__ == "__main__":
    main()

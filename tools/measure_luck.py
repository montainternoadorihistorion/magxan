"""ツキ補正の効き具合を測るスクリプト（開発用）。

一人練習のエンジンをそのまま使い、機械的な打ち手で何局も打って、補正の段階ごとの結果を表にする。

    打ち手：受け入れがいちばん広い牌を切る（同じなら使いにくい牌から）。聴牌したら必ずリーチ。あがれるときは必ずあがる。

実行:  python tools/measure_luck.py [局数（既定 400）]
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import practice  # noqa: E402
from engine.analysis.advice import advise, tile_for_discard  # noqa: E402
from engine.luck import PRESETS, LuckSettings, deal_candidates, draw_probability  # noqa: E402
from engine.scoring.dora import dora_kind_of  # noqa: E402
from engine.scoring.explain import explain  # noqa: E402
from engine.tiles import CHUN, HAKU, HATSU, counts34, kind_of  # noqa: E402
from engine.yaku_table import YAKU  # noqa: E402


def play(config: practice.PracticeConfig) -> practice.PracticeState:
    """機械的な打ち手で 1 局打つ"""
    state = practice.start(config)
    while not state.finished:
        if state.can_tsumo:
            state = practice.apply(state, practice.TSUMO)
            continue
        value_kinds = (HAKU, HATSU, CHUN, state.seat_wind, config.round_wind)
        dora_kinds = [dora_kind_of(kind_of(t)) for t in state.dora_indicators]
        advice = advise(counts34(state.tiles), state.remaining, value_kinds=value_kinds, dora_kinds=dora_kinds)
        tile = tile_for_discard(state.tiles, advice.pick.kind, drawn=state.drawn)
        if advice.pick.shanten == 0 and tile in state.riichi_discards:
            state = practice.apply(state, practice.riichi(tile))
        else:
            state = practice.apply(state, practice.discard(tile))
    return state


def measure(deal: int, draw: int, hands: int) -> dict:
    wins = turns = swapped = draws = 0
    deal_shanten = 0
    yaku: Counter[str] = Counter()
    points = 0
    for seed in range(hands):
        state = play(practice.PracticeConfig(seed=seed, luck=LuckSettings(deal, draw)))
        deal_shanten += state.deal.chosen_shanten
        draws += len(state.draws)
        swapped += sum(1 for d in state.draws if d.luck.swapped)
        result = state.result
        if result.outcome is practice.Outcome.TSUMO:
            wins += 1
            turns += result.turn
            best = explain(result.win).best
            points += best.points.total
            for item in best.evaluation.yaku:
                yaku[item.key] += 1
    return {
        "deal_shanten": deal_shanten / hands,
        "win_rate": wins / hands,
        "win_turn": turns / wins if wins else 0.0,
        "points": points / wins if wins else 0.0,
        "swap_rate": swapped / draws,
        "yaku": {key: count / wins for key, count in yaku.most_common(8)} if wins else {},
    }


def main() -> None:
    hands = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    print(f"各 {hands} 局（シード 0〜{hands - 1}）。一人練習・ツモあがりのみ・最大 {practice.MAX_DRAWS} 回のツモ\n")
    print("| 段階 | 値 | 候補数 N | ツモ補正の確率 p | 配牌の平均向聴数 | あがり率 | あがりの平均巡目 | 平均点 | 入れ替えたツモ |")
    print("|---|---|---|---|---|---|---|---|---|")
    details = []
    for name, level in PRESETS:
        started = time.perf_counter()
        r = measure(level, level, hands)
        seconds = time.perf_counter() - started
        print(
            f"| {name} | {level} | {deal_candidates(level)} | {draw_probability(level):.2f} | {r['deal_shanten']:.2f} | "
            f"{r['win_rate'] * 100:.0f}% | {r['win_turn']:.1f} | {r['points']:,.0f} | {r['swap_rate'] * 100:.0f}% |"
        )
        details.append((name, r["yaku"], seconds))
    print("\nあがった手の役（あがり 1 回あたりの出現率、上位 8 つ）")
    for name, yaku, seconds in details:
        text = "、".join(f"{YAKU[key].name} {rate * 100:.0f}%" for key, rate in yaku.items())
        print(f"- {name}: {text}（{seconds:.0f} 秒）")


if __name__ == "__main__":
    main()

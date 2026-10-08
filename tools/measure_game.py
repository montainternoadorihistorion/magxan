"""CPU どうしの対局を何回も打たせて、成績の基準を測る（開発用）。

    python3 tools/measure_game.py --games 200 --subject normal
    python3 tools/measure_game.py --games 200 --subject weak --others normal

席 0（自分の席）に subject の打ち手を、ほかの 3 席に others の CPU を座らせて、東風戦を打たせる（CPU の補正は 0。
席 0 の補正は --luck で変えられる。初期値 0）。
席 0 の成績（平均順位・和了率・放銃率など）を出す。卒業条件の目標値を決めるための基準に使う。

    subject  normal（CPU ふつう）／ weak（CPU 弱い）／ coach（対局中コーチのおすすめどおりに打つ）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import game as g  # noqa: E402
from engine.cpu import advance, all_cpu  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402


def _subject_action(game: g.GameState, subject: str) -> g.Action:
    from engine.game_coach import coach_action  # 対局中コーチ（あとで作る）

    return coach_action(game.current, g.HUMAN)


def play(args: tuple[int, str, str, str, int]) -> dict:
    seed, subject, others, length, luck = args
    config = g.GameConfig(seed=seed, length=g.Length(length), cpu_level=g.CpuLevel(others), luck=LuckSettings(luck, luck))
    game = g.start_game(config)
    levels = {} if subject == "coach" else {g.HUMAN: g.CpuLevel(subject)}
    seats = (1, 2, 3) if subject == "coach" else all_cpu()
    while not game.finished:
        if game.between_hands:
            game = g.next_hand(game)
        game = advance(game, cpu_seats=seats, levels=levels)
        if subject == "coach" and not game.finished and game.current.result is None:
            game = g.apply(game, _subject_action(game, subject))
    stats = Counter()
    for hand in game.hands:
        result = hand.result
        assert result is not None
        stats["hands"] += 1
        stats[f"end_{result.kind.value}"] += 1
        me = hand.players[g.HUMAN]
        if me.riichi_paid:
            stats["riichi"] += 1
        if any(hand.players[seat].riichi_at is not None for seat in range(1, g.NUM_PLAYERS)):
            stats["threat_hands"] += 1          # CPU のリーチを受けた局（守備の練習になる局）
        for win in result.wins:
            if win.seat == g.HUMAN:
                stats["wins"] += 1
                stats["win_points"] += sum(p for p in win.payments if p > 0) - win.judgement.kyotaku_bonus
                stats["tsumo" if win.from_seat is None else "ron"] += 1
            if win.from_seat == g.HUMAN:
                stats["deal_ins"] += 1
                stats["deal_in_points"] -= win.payments[g.HUMAN]
        if result.kind is g.EndKind.EXHAUSTED:
            stats["draws"] += 1
            stats["draw_tenpai"] += result.tenpai[g.HUMAN]
    final = game.result
    assert final is not None
    stats["rank"] = final.ranks[g.HUMAN]
    stats["score"] = final.scores[g.HUMAN]
    stats[f"rank{final.ranks[g.HUMAN]}"] = 1
    stats[f"reason_{final.reason}"] = 1
    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--subject", default="normal", choices=["normal", "weak", "coach"])
    parser.add_argument("--others", default="normal", choices=["normal", "weak"])
    parser.add_argument("--length", default="east", choices=["east", "south"])
    parser.add_argument("--luck", type=int, default=0, help="席 0 のツキ補正（配牌・ツモとも、この値）")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", default="")
    options = parser.parse_args()
    began = time.time()
    jobs = [(seed, options.subject, options.others, options.length, options.luck)
            for seed in range(options.start, options.start + options.games)]
    with Pool(options.workers) as pool:
        rows = pool.map(play, jobs, chunksize=1)
    total = Counter()
    for row in rows:
        total.update(row)
    games, hands = len(rows), total["hands"]
    ranks = [row["rank"] for row in rows]
    mean = sum(ranks) / games
    sd = (sum((r - mean) ** 2 for r in ranks) / max(1, games - 1)) ** 0.5
    report = {
        "subject": options.subject,
        "luck": options.luck,
        "others": options.others,
        "length": options.length,
        "games": games,
        "hands": hands,
        "hands_per_game": round(hands / games, 2),
        "average_rank": round(mean, 3),
        "rank_sd": round(sd, 3),
        "rank_share": {r: round(total[f"rank{r}"] / games, 3) for r in (1, 2, 3, 4)},
        "average_score": round(total["score"] / games),
        "win_rate": round(total["wins"] / hands, 3),
        "deal_in_rate": round(total["deal_ins"] / hands, 3),
        "riichi_rate": round(total["riichi"] / hands, 3),
        "threat_hand_rate": round(total["threat_hands"] / hands, 3),
        "average_win": round(total["win_points"] / max(1, total["wins"])),
        "average_deal_in": round(total["deal_in_points"] / max(1, total["deal_ins"])),
        "tsumo_share": round(total["tsumo"] / max(1, total["wins"]), 3),
        "draw_tenpai_rate": round(total["draw_tenpai"] / max(1, total["draws"]), 3),
        "ends": {key[4:]: value for key, value in total.items() if key.startswith("end_")},
        "reasons": {key[7:]: value for key, value in total.items() if key.startswith("reason_")},
        "seconds": round(time.time() - began, 1),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if options.out:
        Path(options.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

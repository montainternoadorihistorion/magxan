"""一人練習の成績の記録と集計。

成績は、ツキ補正の強さ、それに「打つ前のヒントを見たか」とセットで残す。条件が違う局の成績を混ぜると
意味がなくなるので、集計は条件ごとに分ける。補正 0（通常の麻雀）で、ヒントも見ずに打ったぶんだけを
「実力」として別に出す。

    record_of(state, decisions, ...)   終わった局 1 つぶんの記録を作る
    summarize(records)                 条件（補正の強さ・ヒントの有無）ごとに集計する（実力が先頭）
    target_stats(records)              役指定練習の局を、狙った役ごとに集計する
    dump_record / dump_history / load_history   ブラウザや JSON に残すための変換（壊れたデータは読み飛ばす）

役指定練習（狙う役を決めて、その役に近い配牌・ツモで打つ局）は、ふつうの局と打ち方も補正のかかり方も違う。
だから、summarize の集計には入れず、狙った役ごとに「何回挑戦して、何回その役が付いたか」を別に数える。
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from engine.practice import Decision, Outcome, PracticeState
from engine.scoring.explain import explain
from engine.target_coach import target_result

HISTORY_VERSION = 1
#: 残す局数の上限（古いものから捨てる）
MAX_RECORDS = 500


@dataclass(frozen=True)
class HandRecord:
    time: int                  # 終わった時刻（UNIX 秒）
    seed: int                  # 局の番号
    deal: int                  # 配牌の良さ（0〜100）
    draw: int                  # ツモの良さ（0〜100）
    hinted: bool               # 打つ前のヒント（おすすめ）が 1 回でも表示された局か
    win: bool                  # あがったか
    turn: int                  # 終わったときのツモ回数
    riichi: bool               # リーチしたか
    tenpai: bool               # 終わったとき聴牌していたか（あがった局は True）
    points: int = 0            # あがったときに受け取った点
    han: int = 0
    fu: int = 0
    yaku: tuple[str, ...] = () # 成立した役（役の名前の鍵）
    decisions: int = 0         # 自分で選んだ打牌の回数
    best: int = 0              # そのうち、いちばん速い打牌（おすすめと同じ速さ）だった回数
    target: str = ""           # 役指定練習で狙った役（図鑑のページの鍵）。ふつうの局は空
    made: bool = False         # 狙った役（か、その上位の役）が付いたか

    @property
    def luck_key(self) -> tuple[int, int]:
        return (self.deal, self.draw)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "t": self.time, "seed": self.seed, "deal": self.deal, "draw": self.draw, "hinted": self.hinted,
            "win": self.win, "turn": self.turn, "riichi": self.riichi, "tenpai": self.tenpai,
            "pts": self.points, "han": self.han, "fu": self.fu, "yaku": list(self.yaku),
            "n": self.decisions, "best": self.best,
        }
        if self.target:             # ふつうの局の記録は、前と同じ形のまま
            data["target"] = self.target
            data["made"] = self.made
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandRecord:
        """形がおかしければ ValueError"""
        if not isinstance(data, dict):
            raise ValueError("記録の形が違います")

        def number(name: str, low: int, high: int, default: int | None = None) -> int:
            value = data.get(name, default)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"記録の値がおかしい: {name}={value!r}")
            return value

        def flag(name: str) -> bool:
            value = data.get(name, False)
            if not isinstance(value, bool):
                raise ValueError(f"記録の値がおかしい: {name}={value!r}")
            return value

        yaku = data.get("yaku", [])
        if not isinstance(yaku, list) or not all(isinstance(key, str) for key in yaku):
            raise ValueError("記録の値がおかしい: yaku")
        decisions = number("n", 0, 100, 0)
        target = data.get("target", "")
        if not isinstance(target, str) or len(target) > 40:
            raise ValueError("記録の値がおかしい: target")
        return cls(
            target=target,
            made=flag("made"),
            time=number("t", 0, 10**11),
            seed=number("seed", 0, 10**12),
            deal=number("deal", 0, 100),
            draw=number("draw", 0, 100),
            hinted=flag("hinted"),
            win=flag("win"),
            turn=number("turn", 0, 100),
            riichi=flag("riichi"),
            tenpai=flag("tenpai"),
            points=number("pts", 0, 10**7, 0),
            han=number("han", 0, 200, 0),
            fu=number("fu", 0, 200, 0),
            yaku=tuple(yaku),
            decisions=decisions,
            best=number("best", 0, decisions, 0),
        )


def record_of(state: PracticeState, decisions: Sequence[Decision], *, time: int, hinted: bool) -> HandRecord:
    """終わった局の記録を作る"""
    result = state.result
    if result is None:
        raise ValueError("まだ終わっていない局は記録できません")
    luck = state.config.luck
    target = state.config.target or ""
    common = {
        "time": int(time), "seed": state.config.seed, "deal": luck.deal, "draw": luck.draw, "hinted": hinted,
        "turn": result.turn, "riichi": state.in_riichi,
        "decisions": len(decisions), "best": sum(1 for d in decisions if d.verdict.is_best), "target": target,
    }
    if result.outcome is Outcome.TSUMO and result.win is not None:
        explanation = explain(result.win, state.config.rules)
        best = explanation.best
        if best is not None and best.points is not None:
            made = bool(target) and target_result(explanation, target).achieved
            return HandRecord(
                win=True, tenpai=True, points=best.points.total, han=best.han, fu=best.fu.fu,
                yaku=tuple(item.key for item in best.evaluation.yaku), made=made, **common,
            )
    return HandRecord(win=False, tenpai=result.tenpai, **common)


# ---------------------------------------------------------------- 集計


@dataclass(frozen=True)
class Summary:
    """同じ条件（ツキ補正の強さ・ヒントの有無）で打った局の集計"""

    deal: int
    draw: int
    hinted: bool               # 打つ前のヒントを見た局の集計か
    hands: int                 # 局数
    wins: int                  # あがった局数
    win_turns: int             # あがった局の、あがり巡目の合計
    win_points: int            # あがった局の、点の合計
    riichi: int                # リーチした局数
    tenpai: int                # 聴牌かあがりで終わった局数
    decisions: int             # 自分で選んだ打牌の回数
    best: int                  # そのうち、いちばん速い打牌だった回数

    @property
    def no_luck(self) -> bool:
        """補正なし（通常の麻雀）か"""
        return self.deal == 0 and self.draw == 0

    @property
    def is_skill(self) -> bool:
        """実力として見てよい成績か（補正なしで、打つ前のヒントも見ていない）"""
        return self.no_luck and not self.hinted

    @property
    def win_rate(self) -> float:
        return self.wins / self.hands if self.hands else 0.0

    @property
    def average_turn(self) -> float | None:
        return self.win_turns / self.wins if self.wins else None

    @property
    def average_points(self) -> float | None:
        return self.win_points / self.wins if self.wins else None

    @property
    def tenpai_rate(self) -> float:
        return self.tenpai / self.hands if self.hands else 0.0

    @property
    def best_rate(self) -> float | None:
        """自分で選んだ打牌のうち、いちばん速い打牌だった割合。

        打つ前のヒントを見た局では、おすすめをなぞれば 100% になるので、数えない（None）。
        """
        return self.best / self.decisions if self.decisions and not self.hinted else None


def summarize(records: Iterable[HandRecord]) -> list[Summary]:
    """条件ごとに集計する。並びは、補正の弱い順（補正 0 が先頭）。同じ補正なら、ヒントなしが先。

    役指定練習の局は入れない（target_stats で、狙った役ごとに数える）。
    """
    groups: dict[tuple[int, int, bool], list[HandRecord]] = {}
    for record in records:
        if record.target:
            continue
        groups.setdefault((record.deal, record.draw, record.hinted), []).append(record)
    result = []
    for (deal, draw, hinted), items in sorted(groups.items()):
        wins = [r for r in items if r.win]
        result.append(
            Summary(
                deal=deal,
                draw=draw,
                hinted=hinted,
                hands=len(items),
                wins=len(wins),
                win_turns=sum(r.turn for r in wins),
                win_points=sum(r.points for r in wins),
                riichi=sum(1 for r in items if r.riichi),
                tenpai=sum(1 for r in items if r.tenpai),
                decisions=sum(r.decisions for r in items),
                best=sum(r.best for r in items),
            )
        )
    return result


@dataclass(frozen=True)
class TargetStat:
    """役指定練習で、ある役を狙った局の集計"""

    tries: int = 0      # 挑戦した局数
    wins: int = 0       # あがった局数（狙った役が付かなかったあがりも含む）
    made: int = 0       # 狙った役（か、その上位の役）が付いた局数

    @property
    def made_rate(self) -> float:
        return self.made / self.tries if self.tries else 0.0


def target_stats(records: Iterable[HandRecord]) -> dict[str, TargetStat]:
    """役指定練習の局を、狙った役（図鑑のページの鍵）ごとに集計する"""
    stats: dict[str, TargetStat] = {}
    for record in records:
        if not record.target:
            continue
        old = stats.get(record.target, TargetStat())
        stats[record.target] = TargetStat(old.tries + 1, old.wins + record.win, old.made + record.made)
    return stats


def yaku_counts(records: Iterable[HandRecord]) -> dict[str, int]:
    """成立させた役の回数（多い順）"""
    counts: dict[str, int] = {}
    for record in records:
        for key in record.yaku:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


# ---------------------------------------------------------------- 保存


def add_record(records: Sequence[HandRecord], record: HandRecord) -> list[HandRecord]:
    """記録を 1 つ足す（上限を超えたら、古いものから捨てる）"""
    return [*records, record][-MAX_RECORDS:]


def dump_record(record: HandRecord) -> str:
    """記録 1 件を JSON の文字列にする（ブラウザに残っている配列の末尾に足すときに使う）"""
    return json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))


def dump_history(records: Sequence[HandRecord]) -> str:
    """記録の一覧を JSON の文字列にする（版の番号つき。ファイルに書き出すときの形）"""
    return json.dumps({"v": HISTORY_VERSION, "hands": [r.to_dict() for r in records]}, ensure_ascii=False, separators=(",", ":"))


def load_history(text: str | None) -> list[HandRecord]:
    """保存した文字列から記録を読む。全体が壊れていれば空、壊れた 1 件はその 1 件だけ読み飛ばす。

    読める形は 2 つ：記録の配列そのもの（ブラウザに残す形）と、版の番号つきの形（dump_history）。
    """
    if not text:
        return []
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):        # JSON でない／入れ子が深すぎる
        return []
    if isinstance(data, dict):
        if data.get("v") != HISTORY_VERSION:
            return []
        data = data.get("hands")
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        try:
            records.append(HandRecord.from_dict(item))
        except ValueError:
            continue
    return records[-MAX_RECORDS:]

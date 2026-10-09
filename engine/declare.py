"""あがったときの点数の申告の練習（解説を見る前に、自分で点数を答える）。

実際の卓では、あがった人が自分で点数を言う（「3900」「1000・2000」）。対局と一人練習であがったとき、
解説を開く前に、点数を 4 つの中から選んでもらう。本場と供託は除いた点（あがりの点そのもの）を答える。

答えは engine.srs.Deck の形で記録する。問題の鍵は、点数の場面（例：c-r-30-3 ＝ 子のロン 30 符 3 翻、p-t-mangan ＝ 親のツモの満貫）。
卒業判定では、直近 20 回の正答率を見る（engine/graduation.py）。記録するのは、成績に入れる局で、打つ前のヒントを
見ずに打った局の申告だけ（ヒントの表には、聴牌したときの点数が出ているため。ui/declare_state.py）。
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.drills import near_points, pay_text
from engine.rng import Rng
from engine.scoring.explain import Explanation
from engine.scoring.judge import Level
from engine.scoring.points import PointsResult, calculate_points

_LEVEL_KEYS = {
    Level.MANGAN: "mangan", Level.HANEMAN: "haneman", Level.BAIMAN: "baiman", Level.SANBAIMAN: "sanbaiman",
    Level.KAZOE_YAKUMAN: "kazoe", Level.YAKUMAN: "yakuman",
}


@dataclass(frozen=True)
class DeclareQuiz:
    item: str                       # 記録の鍵（点数の場面）
    choices: tuple[str, ...]        # 点数の書き方（例：3,900 点・1,000・2,000 点・2,000 点オール）。小さい順
    answer: str                     # 正しい選択肢
    why: str                        # 答えの理由（例：立直・平和・断么九 で 30 符 3 翻。子のロンなので 3,900 点）
    note: str                       # 答え方の注意

    def correct(self, picked: str) -> bool:
        return picked == self.answer


def plain_points(explanation: Explanation) -> PointsResult | None:
    """本場と供託を除いた点数（あがれなければ None）"""
    best = explanation.best
    if best is None or best.points is None:
        return None
    points, ctx = best.points, explanation.ctx
    return calculate_points(
        points.han, points.fu, yakuman_times=points.yakuman_times, is_dealer=ctx.is_dealer, is_tsumo=ctx.is_tsumo,
        honba=0, kyotaku=0, rules=explanation.rules,
    )


def declare_item(points: PointsResult, *, dealer: bool, tsumo: bool) -> str:
    """点数の場面の鍵（例：c-r-30-3、p-t-mangan、c-r-yakuman2）"""
    head = f"{'p' if dealer else 'c'}-{'t' if tsumo else 'r'}"
    if points.level is Level.NONE:
        return f"{head}-{points.fu}-{points.han}"
    key = _LEVEL_KEYS[points.level]
    return f"{head}-{key}{points.yakuman_times if points.level is Level.YAKUMAN and points.yakuman_times > 1 else ''}"


def declare_quiz(explanation: Explanation, token: str) -> DeclareQuiz | None:
    """あがった手の、点数の申告の問題（あがれない手なら None）。token で、はずれの選択肢の選び方が決まる"""
    best = explanation.best
    points = plain_points(explanation)
    if best is None or points is None:
        return None
    ctx = explanation.ctx
    dealer, tsumo = ctx.is_dealer, ctx.is_tsumo
    label = pay_text(points, tsumo=tsumo, dealer=dealer)
    others = near_points(label, points.total, dealer=dealer, tsumo=tsumo, rng=Rng(token, "declare"))
    choices = tuple(text for _, text, _ in sorted([(points.total, label, ""), *others]))
    if best.is_yakuman:
        size = points.level_name
    elif points.level is Level.NONE:
        size = f"{points.fu} 符 {points.han} 翻"
    elif points.han >= 5:
        size = f"{points.han} 翻（{points.level_name}）"
    else:
        size = f"{points.fu} 符 {points.han} 翻（{points.level_name}）"     # 4 翻以下の満貫は、符も効いている（40 符 4 翻など）
    names = "・".join(item.name for item in best.evaluation.yaku)
    dora = "".join(f"・{word}" for word in explanation.dora_words) if not best.is_yakuman else ""
    who, how = ("親" if dealer else "子"), ("ツモ" if tsumo else "ロン")
    why = f"{names}{dora} で {size}。{who}の{how}なので、{label}。"
    note = ("本場と供託は除いて、あがりの点だけを答える。" if ctx.honba or ctx.kyotaku else "") + (
        "ツモの点は「子が払う点・親が払う点」の順。" if tsumo and not dealer else "")
    return DeclareQuiz(declare_item(points, dealer=dealer, tsumo=tsumo), choices, label, why, note)

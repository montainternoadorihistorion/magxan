"""和了の解説データを組み立てる（自前の途中計算）。

流れ
    1. 手牌の読み方（分解 × 和了牌の入り方）をすべて挙げる            decompose.py
    2. 読み方ごとに、符・役・点数を計算する                            fu.py / yaku_eval.py / points.py
    3. 点数が最も高い読み方を採用する（高点法）
    4. 採用した読み方の翻・符・役・点数を、judge（mahjong ライブラリ）の結果と突き合わせる

4 で食い違ったら consistent が False になる。画面はそのとき内訳を出さず、ライブラリの値だけを見せる
（誤った内訳を教えないため）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.decompose import Interpretation, interpretations
from engine.scoring.dora import DoraResult, count_dora
from engine.scoring.fu import FuResult, calculate_fu
from engine.scoring.judge import JudgeError, Judgement, judge
from engine.scoring.points import PointsResult, calculate_points
from engine.scoring.yaku_eval import Evaluation, YakuResult, evaluate, near_misses, why_not
from engine.tiles import EAST, NORTH, SOUTH, WEST, is_yaochu_kind, kind_of
from engine.yaku_table import DOUBLE_YAKUMAN_KEYS, YAKU, YAKUMAN_HAN

#: 卓で風牌の役を言うときの呼び方
WIND_SPOKEN = {EAST: "トン", SOUTH: "ナン", WEST: "シャー", NORTH: "ペー"}


class Status(StrEnum):
    WIN = "win"                   # 和了
    NO_YAKU = "no_yaku"           # 形はできているが役がない（和了れない）
    NOT_WINNING = "not_winning"   # 和了の形になっていない


@dataclass(frozen=True)
class Candidate:
    """読み方 1 つぶんの計算結果"""

    interp: Interpretation
    fu: FuResult
    evaluation: Evaluation
    dora_han: int                    # この読み方で数えるドラの翻数（役がない・役満のときは 0）
    han: int                         # 役＋ドラの翻数（役がなければ 0。役満は 13 × 倍数）
    points: PointsResult | None      # 役がなければ None
    near: tuple[YakuResult, ...]     # 惜しくも成立しなかった役

    @property
    def has_yaku(self) -> bool:
        return self.points is not None

    @property
    def yaku_han(self) -> int:
        return self.evaluation.han

    @property
    def is_yakuman(self) -> bool:
        return self.evaluation.yakuman_times > 0

    @property
    def rank_key(self) -> tuple[int, int, int, int, int]:
        """高点法の並べ方: 受け取る点 → 役満かどうか → 翻 → 符 → 切り上げ前の符。

        同じ点なら役満の読み方を先にする（四暗刻と数え役満が同点なら、四暗刻と呼ぶ）。
        """
        if self.points is None:
            return (-1, 0, 0, self.fu.fu, self.fu.raw_total)
        return (self.points.total, int(self.is_yakuman), self.han, self.fu.fu, self.fu.raw_total)


@dataclass(frozen=True)
class Explanation:
    ctx: WinContext
    rules: Rules
    status: Status
    candidates: tuple[Candidate, ...]   # すべての読み方。点数の高い順（先頭が採用する読み方）
    dora: DoraResult
    judgement: Judgement                # ライブラリによる判定（正解）
    consistent: bool                    # 自前の計算がライブラリと一致したか
    mismatches: tuple[str, ...]         # 食い違った項目（一致していれば空）

    @property
    def best(self) -> Candidate | None:
        """採用する読み方（和了でなければ None）"""
        return self.candidates[0] if self.status is Status.WIN else None

    @property
    def has_alternatives(self) -> bool:
        return len(self.candidates) > 1

    def yaku_check(self, key: str) -> YakuResult | None:
        """ある役の成立条件を、1 つずつ確かめた結果（役図鑑・ドリルで「なぜ付く／付かないか」を見せる）。

        採用した読み方（先頭の候補）で確かめる。和了の形になっていなければ None。
        数えている役なら ok が True。役満があるために数えない通常の役も、条件を満たしていれば ok は True で、
        note に「役満があるので数えない」と入る。別の読み方でなら成立する役は、note にそのことが入る。
        """
        if not self.candidates:
            return None
        first = self.candidates[0]
        for item in first.evaluation.yaku:
            if item.key == key:
                return item
        for item in first.evaluation.ignored:
            if item.key == key:
                return replace(item, note="役満があるので、この役は数えない")
        result = why_not(key, first.interp, self.ctx, self.rules, first.fu)
        if result.ok:          # 条件は満たしているが、上位の役として数えている（一盃口 → 二盃口 など）
            return result
        for other in self.candidates[1:]:
            if any(item.key == key for item in (*other.evaluation.yaku, *other.evaluation.ignored)):
                return replace(result, note="別の読み方をすれば成立するが、点の高い読み方で数えるので、この役は数えない")
        return result

    @property
    def spoken_yaku(self) -> tuple[str, ...]:
        """卓で役を数え上げるときの言い方（例: リーチ、ピンフ、ドラ 1）。和了でなければ空"""
        best = self.best
        if best is None:
            return ()
        ctx = self.ctx
        keys = {y.key for y in best.evaluation.yaku}
        double_wind = {"yakuhai_seat", "yakuhai_round"} <= keys and ctx.seat_wind == ctx.round_wind
        words: list[str] = []
        for item in best.evaluation.yaku:
            if item.key == "yakuhai_seat":
                words.append(("ダブ" if double_wind else "") + WIND_SPOKEN[ctx.seat_wind])
            elif item.key == "yakuhai_round":
                if not double_wind:
                    words.append(WIND_SPOKEN[ctx.round_wind])
            else:
                words.append(YAKU[item.key].spoken)
        if best.dora_han:
            for label, count in (("ドラ", self.dora.dora), ("赤", self.dora.aka), ("裏", self.dora.ura)):
                if count:
                    words.append(f"{label} {count}")
        return tuple(words)

    @property
    def declaration(self) -> str:
        """卓での申告のしかた（発声 → 役 → 点数）。例: ロン。リーチ・ピンフ・ドラ 1。3900。

        役が 1 つだけでドラも無い手は「リーチのみ」「ツモのみ」のように言う（役満は除く）。
        """
        best = self.best
        if best is None or best.points is None:
            return ""
        call = "ツモ" if self.ctx.is_tsumo else "ロン"
        words = self.spoken_yaku
        yaku = "・".join(words)
        if len(words) == 1 and not best.is_yakuman:
            yaku += "のみ"
        return f"{call}。{yaku}。{best.points.declaration}。"

    @property
    def rule_notes(self) -> tuple[str, ...]:
        """この手の結果が、流派（ルールの違い）で変わるところ。変わるところが無ければ空"""
        if self.status is Status.NOT_WINNING:
            return ()
        rules, ctx = self.rules, self.ctx
        first = self.candidates[0]
        keys = {y.key for y in first.evaluation.yaku}
        notes: list[str] = []

        all_simples = not any(is_yaochu_kind(kind_of(t)) for t in ctx.all_tiles)
        if not ctx.is_menzen and all_simples:
            if rules.kuitan:
                notes.append("鳴いた断么九（喰いタン）を認めないルールもある。そのルールでは、この手の断么九は役にならない。")
            else:
                notes.append("いまの設定は「喰いタンなし」。喰いタンありのルールなら、この手に断么九（1 翻）が付く。")

        pair = first.interp.pair
        if pair is not None and pair.first == ctx.seat_wind == ctx.round_wind:
            other = 2 if rules.double_wind_pair_fu == 4 else 4
            notes.append(
                f"連風牌（場風と自風が同じ牌）の雀頭は、4 符とするルールと 2 符とするルールがある。"
                f"いまの設定は {rules.double_wind_pair_fu} 符（{other} 符のルールでは、符の合計が変わることがある）。"
            )

        if first.points is not None:
            if not first.is_yakuman and (first.han, first.fu.fu) in ((4, 30), (3, 60)):
                shape = f"{first.fu.fu} 符 {first.han} 翻"
                if rules.kiriage_mangan:
                    notes.append(
                        f"{shape}を満貫として扱うのは「切り上げ満貫あり」のルール。"
                        "なしのルールでは満貫にならない（子のロンなら 8000 → 7700、親のロンなら 12000 → 11600）。"
                    )
                else:
                    notes.append(
                        f"{shape}は、満貫にわずかに届かない。満貫に切り上げるルール（切り上げ満貫）もある"
                        "（その場合、子のロンなら 7700 → 8000、親のロンなら 11600 → 12000）。"
                    )
            if keys & DOUBLE_YAKUMAN_KEYS:
                names = "・".join(YAKU[key].name for key in sorted(keys & DOUBLE_YAKUMAN_KEYS))
                how = "ダブル役満（役満 2 つぶん）" if rules.double_yakuman else "ふつうの役満（1 つぶん）"
                notes.append(f"{names}をダブル役満にするかどうかは、ルールによって異なる。いまの設定では{how}として数えている。")
            if not first.is_yakuman and first.han >= YAKUMAN_HAN:
                how = "数え役満" if rules.kazoe_yakuman else "三倍満"
                notes.append(f"13 翻以上を数え役満にするか、三倍満までとするかは、ルールによって異なる。いまの設定では{how}。")
            if first.dora_han and self.dora.aka:
                notes.append("赤ドラ（赤い 5）を使わないルールもある。使う枚数もルールによって異なる（このアプリは各色 1 枚ずつ）。")
        return tuple(notes)

    @property
    def advice(self) -> tuple[str, ...]:
        """役がなくてあがれないときの、ひとこと助言"""
        if self.status is not Status.NO_YAKU:
            return ()
        ctx = self.ctx
        if ctx.is_menzen:
            lines = ["門前（鳴いていない手）なので、聴牌したときにリーチを宣言していれば、立直（1 翻）が付いてあがれた。"]
            if not ctx.is_tsumo:
                lines.append("門前なら、ツモであがれば門前清自摸和（1 翻）が付く。ロンでは役なしのまま。")
            return tuple(lines)
        return (
            "鳴いた手ではリーチができず、門前限定の役（平和・一盃口など）も付かない。",
            "鳴いても成立する役（断么九・役牌・対々和・三色同順・一気通貫・混一色など）を 1 つ作る必要がある。",
        )


def _candidate(interp: Interpretation, ctx: WinContext, rules: Rules, dora: DoraResult) -> Candidate:
    fu = calculate_fu(interp, ctx, rules)
    evaluation = evaluate(interp, ctx, rules, fu)
    if not evaluation.yaku:
        near = near_misses(interp, ctx, rules, fu, set())
        return Candidate(interp, fu, evaluation, 0, 0, None, near)

    if evaluation.yakuman_times:
        dora_han = 0
        near: tuple[YakuResult, ...] = ()
    else:
        dora_han = dora.total
        near = near_misses(interp, ctx, rules, fu, {y.key for y in evaluation.yaku})
    han = evaluation.han + dora_han
    points = calculate_points(
        han,
        fu.fu,
        yakuman_times=evaluation.yakuman_times,
        is_dealer=ctx.is_dealer,
        is_tsumo=ctx.is_tsumo,
        honba=ctx.honba,
        kyotaku=ctx.kyotaku,
        rules=rules,
    )
    return Candidate(interp, fu, evaluation, dora_han, han, points, near)


def _compare(best: Candidate | None, has_shape: bool, verdict: Judgement) -> tuple[str, ...]:
    """自前の結果とライブラリの結果を比べ、食い違った項目を返す"""
    if verdict.error is JudgeError.INVALID:
        return ("ライブラリが状況の指定を受け付けなかった",)
    if verdict.error is JudgeError.NOT_WINNING:
        return ("和了形かどうか",) if has_shape else ()
    if verdict.error is JudgeError.NO_YAKU:
        return ("役があるかどうか",) if (best is not None or not has_shape) else ()
    if best is None or best.points is None:
        return ("和了できるかどうか",)

    points = best.points
    pairs = [
        ("翻", best.han, verdict.han),
        ("符", best.fu.fu, verdict.fu),
        ("役満の倍数", best.evaluation.yakuman_times, verdict.yakuman_times),
        ("点数の区分", points.level, verdict.level),
        ("支払い（主）", points.main, verdict.main),
        ("支払い（副）", points.additional, verdict.additional),
        ("本場ぶん（主）", points.honba_main, verdict.honba_main),
        ("本場ぶん（副）", points.honba_additional, verdict.honba_additional),
        ("供託", points.kyotaku_bonus, verdict.kyotaku_bonus),
        ("受け取る合計", points.total, verdict.total),
        ("役", sorted((y.key, y.han) for y in best.evaluation.yaku), sorted((y.key, y.han) for y in verdict.yaku)),
        ("ドラの翻数", best.dora_han, verdict.dora + verdict.aka_dora + verdict.ura_dora),
    ]
    return tuple(f"{name}: 自前 {mine!r} ／ ライブラリ {theirs!r}" for name, mine, theirs in pairs if mine != theirs)


def ranked_candidates(ctx: WinContext, rules: Rules = DEFAULT_RULES) -> tuple[Candidate, ...]:
    """読み方ごとの計算結果を、採用する順（高点法）に並べる。ライブラリとの突き合わせはしない（そのぶん速い）。

    画面に出す解説には explain を使う。これは、コーチが「この牌であがると、その役が付くか」を確かめるときに使う。
    """
    dora = count_dora(ctx, rules)
    readings = interpretations(ctx.closed_tiles, ctx.melds, ctx.win_kind, is_tsumo=ctx.is_tsumo)
    return tuple(sorted((_candidate(r, ctx, rules, dora) for r in readings), key=lambda c: c.rank_key, reverse=True))


def explain(ctx: WinContext, rules: Rules = DEFAULT_RULES) -> Explanation:
    """和了の状況から、解説に必要な事実をすべて計算する"""
    dora = count_dora(ctx, rules)
    candidates = list(ranked_candidates(ctx, rules))

    if not candidates:
        status = Status.NOT_WINNING
    elif not candidates[0].has_yaku:
        status = Status.NO_YAKU
    else:
        status = Status.WIN

    verdict = judge(ctx, rules)
    best = candidates[0] if status is Status.WIN else None
    mismatches = _compare(best, bool(candidates), verdict)
    return Explanation(ctx, rules, status, tuple(candidates), dora, verdict, not mismatches, mismatches)

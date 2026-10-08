"""対局中のコーチ：牌効率（engine/coach.py）に、守備・リーチ判断・役の候補・事故防止の注意を加える。

    advice = turn_advice(hand, seat)     自分の打牌の前に：おすすめの牌（速さ・打点・安全度のバランス）と、その理由
    judge_turn(advice, action)           実際の打牌を評価する（速さの評価に、守備の評価を加える）
    ron_preview(hand, seat)              ロンできる牌が出たとき：あがるとどうなるか（点数の解説）
    coach_action(hand, seat)             コーチのおすすめどおりに打つときの行動（計測用）

おすすめの決め方（よく言われる目安。docs/DESIGN.md の 6 章）
    リーチした人がいない      牌効率でいちばん速い牌。同じ速さなら、聴牌したときにフリテンにならない牌、
                              ロンでも役がある牌を先に（牌効率のコーチの順番で、ドラは残す）
    リーチを受けて、聴牌していない（1 向聴以上）
                              オリる（ベタオリ）：いちばん安全な牌。同じ安全度なら、速さを残せる牌
    リーチを受けて、聴牌している
                              押す：速さが同じ候補の中で、いちばん安全な牌。待ち牌が残っていなければオリる
リーチ判断（リーチかダマか）は、役の有無・待ちの形と残り枚数・打点を並べて比べる。
    ロンで役が無い（ダマではツモでしかあがれない）       リーチをすすめる
    ダマでも全部の待ちで役があり、満貫以上               ダマもすすめる（リーチしなくても十分高い）
    それ以外                                             リーチをすすめる（打点が上がる）
数値（向聴数・受け入れ・危険度の根拠・点数）は、すべてエンジンの計算。文章は、その数値から組み立てる。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache

from engine.analysis.shanten import TENPAI
from engine.analysis.target import IMPOSSIBLE, target_plan
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.coach import Analysis, Candidate, Position, Verdict, analyze, judge_discard
from engine.content import yaku_page_map
from engine.defense import LEVEL_NAMES, Threat, TileDanger, danger_table, threats
from engine.game import (
    RIICHI_MIN_WALL,
    RIICHI_STICK,
    Action,
    Furiten,
    HandState,
    Move,
    Phase,
    auto_action,
    discard,
    nine,
    nine_kinds,
    ron,
    ron_context,
    tsumo,
    tsumo_context,
)
from engine.game import riichi as riichi_action
from engine.scoring.context import WinContext
from engine.scoring.decompose import WAIT_NAMES
from engine.scoring.explain import Explanation, explain, ranked_candidates
from engine.scoring.judge import judge
from engine.scoring.texts import kind_text
from engine.tiles import counts34, kind_of

#: 九種九牌：么九牌がこの種類数以上なら、流局にせず国士無双を目指す（CPU と同じ）
KOKUSHI_KINDS = 11
#: 役の候補として調べる役（手の形で決まる、門前でよく狙う役）
HINT_KEYS = ("tanyao", "pinfu", "yakuhai", "iipeikou", "chiitoitsu", "sanshoku", "ittsu", "honitsu", "chanta", "chinitsu", "junchan")
#: 役の候補に出すのは、役までの距離がこれ以下で、いちばん速い形から 1 枚以内のもの
HINT_MAX_DISTANCE = 3
HINT_LIMIT = 3


class Stance(StrEnum):
    FREE = "free"       # リーチした人がいない
    FOLD = "fold"       # オリる（ベタオリ）
    PUSH = "push"       # 押す（聴牌している）


# ---------------------------------------------------------------- 局面


def position_of(hand: HandState, seat: int) -> Position:
    """自分の局面を、牌効率のコーチに見せる形にする（打牌の前だけ）"""
    player = hand.players[seat]
    if hand.phase is not Phase.DRAW or hand.turn != seat or player.drawn is None:
        raise ValueError("打牌の前の局面ではありません")
    return Position(
        tiles=player.tiles,
        visible=hand.visible_to(seat),
        seat_wind=hand.seat_wind(seat),
        round_wind=hand.round_wind,
        dora_indicators=hand.dora_indicators,
        draws_left=hand.draws_left(seat),
        drawn=player.drawn,
        can_riichi=not player.in_riichi and hand.live_remaining >= RIICHI_MIN_WALL and hand.scores[seat] >= RIICHI_STICK,
        rules=hand.rules,
    )


# ---------------------------------------------------------------- リーチ判断


@dataclass(frozen=True)
class WaitView:
    """待ち牌 1 種類ぶんの比較（点数は、本場・供託・裏ドラ・一発を除いた、あがった人が受け取る点）"""

    kind: int
    remaining: int                  # 残り枚数（見えていない枚数）
    shape: str                      # 待ちの形（両面・嵌張など。高点法で採る読み方のもの）
    dama_ron: int | None            # ダマでロンしたとき（役が無ければ None）
    dama_tsumo: int | None          # ダマでツモったとき（門前なので、門前清自摸和が付く）
    riichi_ron: int | None
    riichi_tsumo: int | None


@dataclass(frozen=True)
class RiichiView:
    """ある牌を切って聴牌するとき、リーチとダマ（黙聴）を比べたもの"""

    tile: int
    waits: tuple[WaitView, ...]
    can_riichi: bool                # いまリーチを宣言できるか
    dama_yaku_all: bool             # ダマでも、どの待ちでもロンできる（役がある）
    dama_yaku_any: bool             # ダマでもロンできる待ちがある
    furiten: bool                   # 待ち牌を自分で捨てている（ロンできない）
    recommend_riichi: bool          # 目安として、リーチをすすめるか
    advice: str                     # 目安のひとこと

    @property
    def live(self) -> int:
        return sum(w.remaining for w in self.waits)

    @property
    def kinds(self) -> int:
        return sum(1 for w in self.waits if w.remaining > 0)

    @property
    def dead(self) -> bool:
        """待ち牌が 1 枚も残っていない（空聴。リーチしてもダマでも、あがれない）"""
        return self.live == 0


def _received(ctx: WinContext, hand: HandState) -> int | None:
    """そのあがりで受け取る点（本場・供託を除く）。役が無ければ None"""
    judgement = judge(replace(ctx, honba=0, kyotaku=0), hand.rules)
    if not judgement.ok:
        return None
    if not ctx.is_tsumo:
        return judgement.main
    if ctx.is_dealer:
        return judgement.main * 3
    return judgement.main + judgement.additional * 2


def _wait_tile(kind: int, seen: set[int]) -> int | None:
    ids = [kind * 4 + i for i in range(4) if kind * 4 + i not in seen]
    plain = [t for t in ids if t not in (16, 52, 88)]
    return (plain or ids or [None])[0]


def _mangan(hand: HandState, seat: int) -> int:
    return 12_000 if hand.seat_wind(seat) == 27 else 8_000


def riichi_view(hand: HandState, seat: int, tile: int) -> RiichiView | None:
    """tile を切ると聴牌するとき、リーチとダマを比べる。聴牌しなければ None"""
    player = hand.players[seat]
    rest = [t for t in player.tiles if t != tile]
    counts = counts34(rest)
    visible = (*hand.visible_to(seat), tile)
    result = acceptance(counts, remaining_counts(rest, visible))
    if result.shanten != TENPAI:
        return None
    seen = {*player.tiles, *visible}
    river = player.river_kinds | {kind_of(tile)}
    waits = []
    for kind, left in result.tiles:
        win_tile = _wait_tile(kind, seen)
        if win_tile is None:          # 4 枚とも自分の手と河にある（あがれない待ち）
            waits.append(WaitView(kind, 0, "", None, None, None, None))
            continue
        base = WinContext(
            closed_tiles=(*rest, win_tile), win_tile=win_tile, is_tsumo=False,
            seat_wind=hand.seat_wind(seat), round_wind=hand.round_wind, dora_indicators=hand.dora_indicators,
        )
        tsumo_ctx = replace(base, is_tsumo=True)
        best = ranked_candidates(tsumo_ctx, hand.rules)
        shape = WAIT_NAMES.get(best[0].interp.wait, "") if best else ""
        waits.append(
            WaitView(
                kind=kind,
                remaining=left,
                shape=shape,
                dama_ron=_received(base, hand),
                dama_tsumo=_received(tsumo_ctx, hand),
                riichi_ron=_received(replace(base, riichi=True), hand),
                riichi_tsumo=_received(replace(tsumo_ctx, riichi=True), hand),
            )
        )
    live = [w for w in waits if w.remaining > 0] or waits
    dama_all = all(w.dama_ron is not None for w in live)
    dama_any = any(w.dama_ron is not None for w in live)
    furiten = any(w.kind in river for w in waits)
    can = tile in hand.riichi_tiles(seat)
    mangan = _mangan(hand, seat)
    cheapest = min((w.dama_ron for w in live if w.dama_ron is not None), default=0)
    if not any(w.remaining > 0 for w in waits):
        recommend = False
        text = "待ち牌が、もう 1 枚も残っていない（空聴）。リーチしてもダマでも、あがれない。流局まで残れば、聴牌として数える（形式聴牌）。"
    elif not dama_any:
        recommend = True
        text = "ダマ（リーチしない）では、ロンであがれない（役がない。ツモなら門前清自摸和であがれる）。リーチをすすめる。"
    elif not dama_all:
        recommend = True
        text = "待ちの一部は、ダマではロンであがれない（役がない）。リーチをかけると、どの待ちでもロンできる。"
    elif cheapest >= mangan:
        recommend = False
        text = f"ダマでも、どの待ちでも {cheapest:,} 点以上（満貫以上）。リーチしなくても十分高いので、ダマで待つのも一般的。"
    else:
        recommend = True
        text = "ダマでも役はあるが、リーチすると打点が上がる（リーチ 1 翻。裏ドラ・一発の可能性も）。よく言われる目安は「迷ったらリーチ」。"
    if furiten and any(w.remaining > 0 for w in waits):
        text += " ただし、待ち牌を自分で捨てているので、フリテン（ロンできない。ツモならあがれる）。"
    if not can:
        recommend = False
    return RiichiView(tile, tuple(waits), can, dama_all, dama_any, furiten, recommend, text)


# ---------------------------------------------------------------- 役の候補


@dataclass(frozen=True)
class YakuHint:
    key: str
    name: str
    distance: int                   # 0 ＝ その役の聴牌、n ＝ その聴牌まであと n 枚
    spare: tuple[int, ...]          # めざす形に入らない牌（種類）：切る候補
    need: tuple[int, ...]           # 足りない牌（種類）


@lru_cache(maxsize=256)
def _hints(counts: tuple[int, ...], seat_wind: int, round_wind: int, available: tuple[int, ...], limit: int) -> tuple[YakuHint, ...]:
    pages = yaku_page_map()
    found = []
    for key in HINT_KEYS:
        plan = target_plan(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available)
        if not plan.possible or plan.distance >= IMPOSSIBLE or plan.distance > limit:
            continue
        found.append(
            YakuHint(
                key=key,
                name=pages[key].name,
                distance=max(0, plan.distance),
                spare=tuple(kind for kind, _ in plan.spare),
                need=tuple(kind for kind, _ in plan.need),
            )
        )
    found.sort(key=lambda h: (h.distance, HINT_KEYS.index(h.key)))
    return tuple(found[:HINT_LIMIT])


def yaku_hints(hand: HandState, seat: int, analysis: Analysis) -> tuple[YakuHint, ...]:
    """見えている役の候補（いちばん速い形から、あと 1 枚以内で作れる役）"""
    player = hand.players[seat]
    counts = tuple(counts34(player.tiles))
    available = tuple(remaining_counts(player.tiles, hand.visible_to(seat)))
    limit = min(HINT_MAX_DISTANCE, max(analysis.pick.shanten, 0) + 1)
    return _hints(counts, hand.seat_wind(seat), hand.round_wind, available, limit)


# ---------------------------------------------------------------- おすすめ


@dataclass(frozen=True)
class TurnAdvice:
    analysis: Analysis                      # 牌効率（速さ）
    threats: tuple[Threat, ...]             # リーチしている人
    table: tuple[TileDanger, ...]           # 守備：手牌の種類ごとの危険度（リーチした人がいなければ空）
    stance: Stance
    pick: int                               # おすすめの牌（牌ID）
    reason: str                             # おすすめの理由（ひとこと）
    riichi: RiichiView | None               # おすすめを切ると聴牌するときの、リーチとダマの比較
    yaku: tuple[YakuHint, ...]              # 役の候補
    tenpai_views: tuple[RiichiView, ...]    # 切ると聴牌する牌ごとの比較（フリテン・役なしの注意に使う）

    @property
    def level_of(self) -> dict[int, int]:
        return {row.kind: row.level for row in self.table}

    @property
    def safest_level(self) -> int | None:
        return min((row.level for row in self.table), default=None)

    def view_for(self, tile: int) -> RiichiView | None:
        return next((v for v in self.tenpai_views if kind_of(v.tile) == kind_of(tile)), None)

    @property
    def recommend_riichi(self) -> bool:
        return self.riichi is not None and self.riichi.recommend_riichi and self.stance is not Stance.FOLD


def _speed_rank(analysis: Analysis) -> dict[int, int]:
    """速さで切りたい順（牌効率のコーチのおすすめが先頭。ほかは候補の表の順）"""
    rank = {c.kind: index + 1 for index, c in enumerate(analysis.candidates)}
    rank[analysis.pick.kind] = 0
    return rank


def turn_advice(hand: HandState, seat: int) -> TurnAdvice:
    """自分の打牌の前に、おすすめを決める"""
    position = position_of(hand, seat)
    analysis = analyze(position)
    player = hand.players[seat]
    found = threats(hand, seat)
    table = danger_table(player.tiles, hand.visible_to(seat), found, dora_indicators=hand.dora_indicators)
    level = {row.kind: row.level for row in table}
    rank = _speed_rank(analysis)

    # 切ると聴牌する牌ごとに、リーチとダマを比べる（フリテン・役なしの注意にも使う）
    tenpai = [c for c in analysis.candidates if c.shanten == TENPAI]
    views = tuple(v for v in (riichi_view(hand, seat, c.tile) for c in tenpai) if v is not None)
    view_of = {kind_of(v.tile): v for v in views}

    def tenpai_key(candidate: Candidate) -> tuple[int, int]:
        """同じ速さの中で：フリテンにならない牌 → ロンでも役がある牌、の順"""
        view = view_of.get(candidate.kind)
        if view is None:
            return (0, 0)
        return (int(view.furiten), int(not view.dama_yaku_any and not view.can_riichi))

    best = list(analysis.best)
    if not found:
        stance = Stance.FREE
        choice = min(best, key=lambda c: (*tenpai_key(c), rank[c.kind]))
        reason = _free_reason(analysis, choice)
    elif analysis.pick.shanten == TENPAI and analysis.pick.total > 0:
        stance = Stance.PUSH
        choice = min(best, key=lambda c: (level[c.kind], *tenpai_key(c), rank[c.kind]))
        reason = (
            f"聴牌しているので、押す（あがりを目指す）のも有力。速さが同じ牌の中で、いちばん安全な {kind_text(choice.kind)}"
            f"（{LEVEL_NAMES[level[choice.kind]]}）。"
        )
    else:
        stance = Stance.FOLD
        choice = min(analysis.candidates, key=lambda c: (level[c.kind], rank[c.kind]))
        reason = (
            f"リーチを受けていて、聴牌していない（{_stage(analysis.pick.shanten)}）。あがりをあきらめて、"
            f"いちばん安全な {kind_text(choice.kind)}（{LEVEL_NAMES[level[choice.kind]]}）を切る（ベタオリ）。"
        )
    view = view_of.get(choice.kind)
    hints = yaku_hints(hand, seat, analysis) if stance is Stance.FREE else ()
    return TurnAdvice(analysis, found, table, stance, choice.tile, reason, view, hints, views)


def _stage(shanten: int) -> str:
    return "聴牌" if shanten == TENPAI else f"{shanten} 向聴"


def _free_reason(analysis: Analysis, choice: Candidate) -> str:
    if choice.shanten == TENPAI and choice.total > 0:
        return f"{kind_text(choice.kind)}を切ると聴牌。待ちは {choice.kinds} 種 {choice.total} 枚。"
    if choice.total == 0:
        return f"{kind_text(choice.kind)}切り（どれを切っても、有効牌は残っていない）。"
    return f"{kind_text(choice.kind)}切りが、いちばん受け入れが広い（{_stage(choice.shanten)}・{choice.kinds} 種 {choice.total} 枚）。"


# ---------------------------------------------------------------- 打牌の評価


class SafetyGrade(StrEnum):
    SAFE = "safe"           # いちばん安全な牌を切れた（または、それと同じ安全度）
    RISKY = "risky"         # もっと安全な牌があった
    PUSHED = "pushed"       # 聴牌していて押した（守備は問わない）


@dataclass(frozen=True)
class Safety:
    """リーチを受けているときの、切った牌の安全度の評価"""

    grade: SafetyGrade
    level: int                  # 切った牌の危険度
    best_level: int             # いちばん安全な牌の危険度
    safest: tuple[int, ...]     # いちばん安全な牌（種類）
    text: str


@dataclass(frozen=True)
class TurnDecision:
    """自分の打牌 1 回ぶんの評価"""

    number: int                 # 自分の何回目のツモのあとか（1 始まり）
    action: Action
    advice: TurnAdvice          # 切る前の局面のおすすめ（答え合わせで、表を見せるため）
    verdict: Verdict            # 速さの評価（牌効率のコーチ）
    safety: Safety | None       # 守備の評価（リーチを受けていなければ None）
    notes: tuple[str, ...]      # 事故防止の注意（フリテン・役なしの聴牌）

    @property
    def followed(self) -> bool:
        """おすすめどおりに打ったか（おすすめの牌と同じ種類を切った。リーチをすすめたときは、リーチもした）"""
        assert self.action.tile is not None
        return kind_of(self.action.tile) == kind_of(self.advice.pick) and not self.skipped_riichi

    @property
    def skipped_riichi(self) -> bool:
        """リーチをすすめる聴牌なのに、リーチせずに切った"""
        if self.action.move is Move.RIICHI or self.advice.stance is Stance.FOLD or self.verdict.chosen.shanten != TENPAI:
            return False
        assert self.action.tile is not None
        view = self.advice.view_for(self.action.tile)
        return view is not None and view.recommend_riichi


def judge_turn(advice: TurnAdvice, action: Action, *, number: int) -> TurnDecision:
    """実際の打牌を評価する"""
    assert action.tile is not None
    declared = action.move is Move.RIICHI
    verdict = judge_discard(advice.analysis, action.tile, riichi=declared)
    kind = kind_of(action.tile)
    safety = None
    if advice.table:
        level = advice.level_of[kind]
        best_level = advice.safest_level or 0
        safest = tuple(row.kind for row in advice.table if row.level == best_level)
        if advice.stance is Stance.PUSH and verdict.chosen.shanten == TENPAI:
            grade = SafetyGrade.PUSHED
            text = f"聴牌を保って押した（切った {kind_text(kind)} は {LEVEL_NAMES[level]}）。"
        elif level <= best_level:
            grade = SafetyGrade.SAFE
            text = f"{kind_text(kind)}は{LEVEL_NAMES[level]}。いちばん安全な牌を選べた。"
        else:
            grade = SafetyGrade.RISKY
            names = "・".join(kind_text(k) for k in safest)
            text = f"{kind_text(kind)}は{LEVEL_NAMES[level]}。もっと安全な牌があった（{names}：{LEVEL_NAMES[best_level]}）。"
        safety = Safety(grade, level, best_level, safest, text)
    notes = []
    view = advice.view_for(action.tile)
    if view is not None and verdict.chosen.shanten == TENPAI and not view.dead:      # 空聴（待ち牌が残っていない）は、速さの評価で伝える
        if view.furiten:
            notes.append("この聴牌は、待ち牌を自分で捨てているのでフリテン。ロンではあがれない（ツモならあがれる）。")
        if not declared and not view.dama_yaku_all:
            if view.dama_yaku_any:
                notes.append("この聴牌は、待ちの一部でロンしても役がない（その牌ではロンできない）。リーチすれば、どの待ちでもロンできた。")
            else:
                notes.append("この聴牌は、ロンでは役がない（ツモならあがれる）。リーチすれば、ロンでもあがれた。")
        elif not declared and view.recommend_riichi and advice.stance is not Stance.FOLD:
            notes.append("リーチをすすめる聴牌だった（リーチすると打点が上がる）。")
    return TurnDecision(number, action, advice, verdict, safety, tuple(notes))


# ---------------------------------------------------------------- ロン


def ron_ahead(hand: HandState, seat: int) -> tuple[int, ...]:
    """同じ牌でロンを宣言した人のうち、捨てた人から見て seat より順番が先の人（その人が本場・供託をもらう）"""
    distance = (seat - hand.turn) % 4
    return tuple(s for s in hand.rons if (s - hand.turn) % 4 < distance)


def _before_win(ctx: WinContext) -> WinContext:
    """あがる前に分かることだけで数える状況：裏ドラ（あがったあとにめくる）と、本場・供託を除く。

    リーチとダマの比べ方の表と同じ基準。本場・供託の内訳は、あがったあとの結果に出す。
    """
    return replace(ctx, ura_indicators=(), honba=0, kyotaku=0)


def ron_preview(hand: HandState, seat: int) -> Explanation | None:
    """いちばん最近の捨て牌でロンしたときの解説（ロンできなければ None）。裏ドラと本場・供託は入れない"""
    last = hand.last_discard
    if last is None or not hand.ron_check(seat).ok:
        return None
    return explain(_before_win(ron_context(hand, seat, last[1].tile)), hand.rules)


def tsumo_preview(hand: HandState, seat: int) -> Explanation | None:
    """いまツモであがったときの解説（あがれなければ None）。ハイテイ・天和などは局の進行と同じ。裏ドラと本場・供託は入れない"""
    if not hand.can_tsumo(seat):
        return None
    return explain(_before_win(tsumo_context(hand, seat)), hand.rules)


FURITEN_SHORT = {
    Furiten.RIVER: "自分の河に待ち牌がある（フリテン）",
    Furiten.MISSED: "この巡にあがり牌を見逃した（同巡内フリテン）",
    Furiten.RIICHI: "リーチのあとにあがり牌を見逃した（フリテン）",
}


# ---------------------------------------------------------------- 計測用：おすすめどおりに打つ


def coach_action(hand: HandState, seat: int) -> Action:
    """コーチのおすすめどおりに打つときの行動（ロン・ツモはいつもあがる）"""
    if hand.phase is Phase.CLAIM:
        return ron(seat) if hand.ron_check(seat).ok else Action(seat, Move.PASS)
    auto = auto_action(hand, seat)
    if auto is not None:
        return auto
    if hand.can_tsumo(seat):
        return tsumo(seat)
    player = hand.players[seat]
    if hand.can_nine(seat) and nine_kinds(player.tiles) < KOKUSHI_KINDS:
        return nine(seat)
    advice = turn_advice(hand, seat)
    if advice.recommend_riichi:
        return riichi_action(seat, advice.pick)
    return discard(seat, advice.pick)


def tiles_of_kinds(tiles: Sequence[int], kinds: Sequence[int]) -> tuple[int, ...]:
    """手牌の中の、その種類の牌"""
    wanted = set(kinds)
    return tuple(t for t in tiles if kind_of(t) in wanted)

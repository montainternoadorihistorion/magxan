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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import lru_cache

from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.target import IMPOSSIBLE, target_plan
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.analysis.waits import wait_kinds
from engine.call_coach import STATUS_RANK, Outlook, YakuStatus, call_advice, open_hand_discard
from engine.coach import Analysis, Candidate, Grade, Position, Verdict, analyze, judge_discard, rebase
from engine.content import yaku_page_map
from engine.defense import LEVEL_NAMES, Threat, TileDanger, danger_table, threats
from engine.game import (
    RIICHI_MIN_WALL,
    RIICHI_STICK,
    Action,
    ClaimKind,
    Furiten,
    HandState,
    Move,
    Phase,
    ankan,
    auto_action,
    discard,
    kakan,
    nine,
    nine_kinds,
    ron,
    ron_context,
    tsumo,
    tsumo_context,
)
from engine.game import riichi as riichi_action
from engine.melds import Meld
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
#: 鳴いた手で、役の候補として調べる役
OPEN_HINT_KEYS = ("yakuhai", "tanyao", "toitoi", "honitsu", "ittsu", "sanshoku", "chanta", "chinitsu", "junchan", "shousangen", "honroutou")
#: 役の候補に出すのは、役までの距離がこれ以下で、いちばん速い形から 1 枚以内のもの
HINT_MAX_DISTANCE = 3
HINT_LIMIT = 3


class Stance(StrEnum):
    FREE = "free"       # リーチした人がいない
    FOLD = "fold"       # オリる（ベタオリ）
    PUSH = "push"       # 押す（聴牌している）


# ---------------------------------------------------------------- 局面


def position_of(hand: HandState, seat: int) -> Position:
    """自分の局面を、牌効率のコーチに見せる形にする（打牌の前だけ。ツモったあとと、鳴いた直後）"""
    player = hand.players[seat]
    if hand.phase is not Phase.DRAW or hand.turn != seat or len(player.tiles) % 3 != 2:
        raise ValueError("打牌の前の局面ではありません")
    return Position(
        tiles=player.tiles,
        visible=hand.visible_to(seat),
        seat_wind=hand.seat_wind(seat),
        round_wind=hand.round_wind,
        dora_indicators=hand.dora_indicators,
        draws_left=hand.draws_left(seat),
        drawn=player.drawn,
        can_riichi=(
            player.menzen and player.drawn is not None and not player.in_riichi
            and hand.live_remaining >= RIICHI_MIN_WALL and hand.scores[seat] >= RIICHI_STICK
        ),
        rules=hand.rules,
        melds=player.melds,
        forbidden=hand.forbidden,
        called=player.drawn is None,
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

    @property
    def winnable(self) -> bool:
        """この聴牌であがれる見込みがある（待ち牌が残っていて、リーチできるか、ダマでも役が付く待ちがある）。
        鳴いた手で役が無い聴牌は、リーチもできないので、あがれない"""
        if self.dead:
            return False
        return self.can_riichi or any(
            w.remaining > 0 and (w.dama_ron is not None or w.dama_tsumo is not None) for w in self.waits
        )


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


def formal_tenpai(hand: HandState, seat: int) -> bool:
    """鳴いた手の聴牌（13 − 3n 枚）で、どの待ちでも役が付かないか（あがれない。流局まで残れば、聴牌として数える＝形式聴牌）"""
    player = hand.players[seat]
    if player.menzen:
        return False
    waits = wait_kinds(player.hand)
    if not waits:
        return False
    seen = set(player.hand)
    for kind in waits:
        win_tile = _wait_tile(kind, seen)
        if win_tile is None:
            continue
        ron_ctx = WinContext(
            closed_tiles=(*player.hand, win_tile), win_tile=win_tile, is_tsumo=False, melds=player.melds,
            seat_wind=hand.seat_wind(seat), round_wind=hand.round_wind, dora_indicators=hand.dora_indicators,
        )
        if _received(ron_ctx, hand) is not None or _received(replace(ron_ctx, is_tsumo=True), hand) is not None:
            return False
    return True


def riichi_view(hand: HandState, seat: int, tile: int) -> RiichiView | None:
    """tile を切ると聴牌するとき、リーチとダマを比べる（鳴いた手はリーチできないので、ダマだけ）。聴牌しなければ None"""
    player = hand.players[seat]
    rest = [t for t in player.tiles if t != tile]
    counts = counts34(rest)
    visible = (*hand.visible_to(seat), tile)
    result = acceptance(counts, remaining_counts(rest, visible))
    if result.shanten != TENPAI:
        return None
    seen = {*player.tiles, *visible}
    river = player.river_kinds | {kind_of(tile)}
    menzen = player.menzen
    waits = []
    for kind, left in result.tiles:
        win_tile = _wait_tile(kind, seen)
        if win_tile is None:          # 4 枚とも見えている（あがれない待ち）
            waits.append(WaitView(kind, 0, "", None, None, None, None))
            continue
        base = WinContext(
            closed_tiles=(*rest, win_tile), win_tile=win_tile, is_tsumo=False, melds=player.melds,
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
                riichi_ron=_received(replace(base, riichi=True), hand) if menzen else None,
                riichi_tsumo=_received(replace(tsumo_ctx, riichi=True), hand) if menzen else None,
            )
        )
    live = [w for w in waits if w.remaining > 0] or waits
    dama_all = all(w.dama_ron is not None for w in live)
    dama_any = any(w.dama_ron is not None for w in live)
    tsumo_any = any(w.dama_tsumo is not None for w in live)
    furiten = any(w.kind in river for w in waits)
    can = tile in hand.riichi_tiles(seat)
    mangan = _mangan(hand, seat)
    cheapest = min((w.dama_ron for w in live if w.dama_ron is not None), default=0)
    if not any(w.remaining > 0 for w in waits):
        recommend = False
        text = "待ち牌が、もう 1 枚も残っていない（空聴）。リーチしてもダマでも、あがれない。流局まで残れば、聴牌として数える（形式聴牌）。"
        if not menzen:
            text = "待ち牌が、もう 1 枚も残っていない（空聴）。あがれない。流局まで残れば、聴牌として数える（形式聴牌）。"
    elif not menzen:
        recommend = False
        if not dama_any and not tsumo_any:
            text = "役がない聴牌（鳴いているので、リーチもできない）。このままでは、ロンでもツモでもあがれない。流局まで残れば、聴牌として数える（形式聴牌）。"
        elif not dama_all:
            text = "待ちの一部では役が付かない（その牌ではあがれない）。役が付く牌であがる（片あがり）。"
        else:
            text = "鳴いた手なので、リーチはできない（ダマで待つ）。どの待ちでも役がある。"
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
def _hints(
    counts: tuple[int, ...], seat_wind: int, round_wind: int, available: tuple[int, ...], limit: int,
    melds: tuple[Meld, ...] = (), kuitan: bool = True,
) -> tuple[YakuHint, ...]:
    pages = yaku_page_map()
    found = []
    open_hand = any(m.is_open for m in melds)
    keys = OPEN_HINT_KEYS if open_hand else HINT_KEYS
    for key in keys:
        if open_hand and key == "tanyao" and not kuitan:
            continue                                    # 喰いタンなしのルールでは、鳴いた断么九は付かない
        plan = target_plan(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available, melds=melds)
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
    found.sort(key=lambda h: (h.distance, keys.index(h.key)))
    return tuple(found[:HINT_LIMIT])


def yaku_hints(hand: HandState, seat: int, analysis: Analysis) -> tuple[YakuHint, ...]:
    """見えている役の候補（いちばん速い形から、あと 1 枚以内で作れる役。鳴いた手は、鳴いても付く役から）"""
    player = hand.players[seat]
    counts = tuple(counts34(player.tiles))
    available = tuple(remaining_counts(player.tiles, hand.visible_to(seat)))
    limit = min(HINT_MAX_DISTANCE, max(analysis.pick.shanten, 0) + 1)
    return _hints(counts, hand.seat_wind(seat), hand.round_wind, available, limit, player.melds, hand.rules.kuitan)


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
    open_outlooks: Mapping[int, Outlook] = field(default_factory=dict)   # 鳴いた手：切り方（種類）ごとの、役の見込み
    keeps_yaku: bool = False                # 鳴いた手で、役を残すために、速さだけで選ぶ牌と違う牌をすすめたか
    fastest: int | None = None              # そのうち、役を残すぶん遅くなるとき：速さだけならこの牌

    @property
    def kept_yaku(self) -> str:
        """役を残す切り方をすすめたとき、残す役の名前（例：断么九）。案内の 1 行に収めるため、1 つだけ（確定した役を先に）"""
        outlook = self.open_outlooks.get(kind_of(self.pick))
        if outlook is None:
            return ""
        found = (*outlook.secured, *outlook.path_yaku)
        if found:
            return found[0].name
        return outlook.nearest.name if outlook.nearest is not None else ""

    @property
    def equal_tiles(self) -> tuple[int, ...]:
        """おすすめと同じくらい良い牌（牌ID。手牌に「○ おすすめと同じ速さ」を付ける）。
        リーチを受けていない局面で、おすすめと同じ速さ（実質の向聴数と受け入れ）の牌。鳴いた手では、役の見込みも同じもの"""
        if self.stance is not Stance.FREE:
            return ()
        pick = self.analysis.candidate(kind_of(self.pick))
        if pick is None:
            return ()
        same = [c for c in self.analysis.candidates
                if c.kind != pick.kind and (c.option.reach, c.total) == (pick.option.reach, pick.total)]
        if self.open_outlooks:
            mine = self.open_outlooks.get(pick.kind)
            if mine is None:
                return ()
            same = [c for c in same
                    if c.kind in self.open_outlooks and STATUS_RANK[self.open_outlooks[c.kind].status] == STATUS_RANK[mine.status]]
        return tuple(c.tile for c in same)

    @property
    def level_of(self) -> dict[int, int]:
        return {row.kind: row.level for row in self.table}

    @property
    def usable_table(self) -> tuple[TileDanger, ...]:
        """切れる牌の危険度（鳴いた直後の喰い替えで切れない牌を除く）"""
        forbidden = set(self.analysis.position.forbidden)
        return tuple(row for row in self.table if row.kind not in forbidden)

    @property
    def safest_level(self) -> int | None:
        """切れる牌の中で、いちばん安全な危険度"""
        return min((row.level for row in self.usable_table), default=None)

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
    keeps_yaku = False
    fastest = None
    # 鳴いた手：役を残せる切り方を先に選ぶ（鳴きの判断の表の「鳴いたら ○ 切り」と同じ決め方）
    open_pick = None
    if not position.menzen:
        open_pick = open_hand_discard(
            player.tiles, player.melds, hand=hand, seat=seat, forbidden=position.forbidden, drawn=player.drawn,
            extra=lambda kind: tenpai_key(next(c for c in analysis.candidates if c.kind == kind)),
        )
    # あがれる見込みのある聴牌（鳴いた手で役の無い聴牌・空聴は、押す理由にならない）
    pushable = [c for c in analysis.candidates if c.shanten == TENPAI and view_of.get(c.kind) is not None and view_of[c.kind].winnable]
    if not found:
        stance = Stance.FREE
        choice = min(best, key=lambda c: (*tenpai_key(c), rank[c.kind]))
        reason = _free_reason(analysis, choice)
        if open_pick is not None:
            kept = next(c for c in analysis.candidates if c.kind == kind_of(open_pick.tile))
            if kept.kind != choice.kind:
                if STATUS_RANK[open_pick.outlook.status] < STATUS_RANK[open_pick.outlooks[choice.kind].status]:
                    keeps_yaku = True
                    reason = _keep_yaku_reason(kept, open_pick.outlook)
                    if not kept.is_best:
                        fastest = choice.tile           # 役を残すぶん、遅くなる（速さが同じなら、速さだけの牌は出さない）
                else:
                    # 役の見込みは同じで、フリテンにならない待ち・打点などで選び直したとき
                    reason = _free_reason(analysis, kept)
            choice = kept
    elif pushable:
        stance = Stance.PUSH
        choice = min(pushable, key=lambda c: (c.shanten, -c.total, level[c.kind], *tenpai_key(c), rank[c.kind]))
        top = [c for c in pushable if (c.shanten, c.total) == (choice.shanten, choice.total)]
        choice = min(top, key=lambda c: (level[c.kind], *tenpai_key(c), rank[c.kind]))
        among = "速さが同じ牌の中で" if choice.is_best else "あがれる聴牌の中で、待ちがいちばん広い牌から"
        reason = (
            f"聴牌しているので、押す（あがりを目指す）のも有力。{among}、いちばん安全な {kind_text(choice.kind)}"
            f"（{LEVEL_NAMES[level[choice.kind]]}）。"
        )
    else:
        stance = Stance.FOLD
        choice = min(analysis.candidates, key=lambda c: (level[c.kind], rank[c.kind]))
        if analysis.pick.shanten == TENPAI:
            why = "聴牌にとれるが、あがれない形（役が無い、または待ち牌が残っていない）"
        else:
            why = f"聴牌していない（{_stage(analysis.pick.shanten)}）"
        reason = (
            f"リーチを受けていて、{why}。あがりをあきらめて、"
            f"いちばん安全な {kind_text(choice.kind)}（{LEVEL_NAMES[level[choice.kind]]}）を切る（ベタオリ）。"
        )
    view = view_of.get(choice.kind)
    hints = yaku_hints(hand, seat, analysis) if stance is Stance.FREE else ()
    outlooks = open_pick.outlooks if open_pick is not None else {}
    return TurnAdvice(analysis, found, table, stance, choice.tile, reason, view, hints, views, outlooks, keeps_yaku, fastest)


def _keep_yaku_reason(choice: Candidate, outlook: Outlook) -> str:
    """鳴いた手で、役を残すために、いちばん速い牌ではない牌をすすめるときの理由"""
    names = "・".join(c.name for c in (*outlook.secured, *outlook.path_yaku)[:2])
    if not names and outlook.nearest is not None:
        names = outlook.nearest.name
    keep = f"役（{names}）を残す" if names else "役を残す"
    width = "待ち" if choice.shanten == TENPAI else "受け入れ"
    among = "速さが同じ牌の中で、" if choice.is_best else ""
    return (
        f"鳴いた手は、役が無いとあがれない。{among}{keep}ために {kind_text(choice.kind)}切り"
        f"（{_stage(choice.shanten)}・{width} {choice.kinds} 種 {choice.total} 枚）。"
    )


def _stage(shanten: int) -> str:
    return "聴牌" if shanten == TENPAI else f"{shanten} 向聴"


def _free_reason(analysis: Analysis, choice: Candidate) -> str:
    if choice.shanten == TENPAI and choice.total > 0:
        return f"{kind_text(choice.kind)}を切ると聴牌。待ちは {choice.kinds} 種 {choice.total} 枚。"
    if choice.total == 0:
        return f"{kind_text(choice.kind)}切り（どれを切っても、有効牌は残っていない）。"
    if not choice.is_best:
        return f"{kind_text(choice.kind)}切り（{_stage(choice.shanten)}・{choice.kinds} 種 {choice.total} 枚）。"
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
    lost_yaku: bool = False     # 鳴いた手で、役を残せたのに、役が見えなくなる牌を切った
    yaku_detour: bool = False   # 鳴いた手で、役を残せたのに、役まで遠回りになる牌を切った

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
    """実際の打牌を評価する。

    速さの評価は、コーチのおすすめと比べて作る。おすすめが速さだけの牌と違う（鳴いた手で役を残す・押す局面で、あがれる聴牌や
    安全な牌を選ぶ）ときは、おすすめを基準に付け直した分析（rebase）と比べる。おすすめより速い牌（コーチが役などのために避けた牌）を
    切ったときだけは、速さだけの分析と比べ、役の見込みの注意（役が見えなくなった・遠回りになった）で評価する。
    """
    assert action.tile is not None
    declared = action.move is Move.RIICHI
    kind = kind_of(action.tile)
    speed = advice.analysis
    coach_kind = kind_of(advice.pick)
    differs = advice.stance is not Stance.FOLD and coach_kind != speed.pick.kind and not speed.can_win
    chosen_candidate, coach_candidate = speed.candidate(kind), speed.candidate(coach_kind)
    assert chosen_candidate is not None and coach_candidate is not None
    faster = differs and (chosen_candidate.option.reach, -chosen_candidate.total) < (coach_candidate.option.reach, -coach_candidate.total)
    verdict = judge_discard(rebase(speed, coach_kind) if differs and not faster else speed, action.tile, riichi=declared)
    if differs and kind == coach_kind and (advice.keeps_yaku or not coach_candidate.is_best):
        # おすすめどおり。速さだけの牌と違う牌をすすめた理由と、速さだけの牌との違いを書く
        label = "役を残す打牌" if advice.keeps_yaku else "おすすめどおり"
        verdict = replace(verdict, grade=Grade.BEST, label=label, text=advice.reason + _speed_note(advice))
    safety = None
    if advice.table:
        level = advice.level_of[kind]
        best_level = advice.safest_level or 0
        safest = tuple(row.kind for row in advice.usable_table if row.level == best_level)      # 喰い替えで切れない牌は比べない
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
    lost_yaku = yaku_detour = False
    if advice.stance is not Stance.FOLD and advice.open_outlooks:
        # 鳴いた手：おすすめの切り方より、役の見込みが悪くなる牌を切った（役が見えなくなる・役まで遠回りになる）
        chosen_outlook = advice.open_outlooks.get(kind)
        pick_outlook = advice.open_outlooks.get(coach_kind)
        if (chosen_outlook is not None and pick_outlook is not None
                and STATUS_RANK[chosen_outlook.status] > STATUS_RANK[pick_outlook.status]):
            keep = f"役を残すなら {kind_text(coach_kind)}切り。"
            if chosen_outlook.status is YakuStatus.NONE:
                lost_yaku = True
                notes.append(f"この牌を切ると、役が見えなくなる（鳴いた手は、役が無いとあがれない）。{keep}")
            else:
                yaku_detour = True
                notes.append(f"この牌を切ると、役まで遠回りになる（役を付けるのに、1 枚の遠回りが要る）。{keep}")
    view = advice.view_for(action.tile)
    menzen = advice.analysis.position.menzen
    if view is not None and verdict.chosen.shanten == TENPAI and not view.dead:      # 空聴（待ち牌が残っていない）は、速さの評価で伝える
        if view.furiten:
            notes.append("この聴牌は、待ち牌を自分で捨てているのでフリテン。ロンではあがれない（ツモならあがれる）。")
        if not menzen:
            if not view.dama_yaku_any and not any(w.dama_tsumo is not None for w in view.waits if w.remaining > 0):
                notes.append("この聴牌は役がない（鳴いているので、リーチもできない）。このままでは、ロンでもツモでもあがれない。")
            elif not view.dama_yaku_all:
                notes.append("この聴牌は、待ちの一部で役が付かない（その牌ではあがれない）。")
        elif not declared and not view.dama_yaku_all:
            if view.dama_yaku_any:
                notes.append("この聴牌は、待ちの一部でロンしても役がない（その牌ではロンできない）。リーチすれば、どの待ちでもロンできた。")
            else:
                notes.append("この聴牌は、ロンでは役がない（ツモならあがれる）。リーチすれば、ロンでもあがれた。")
        elif not declared and view.recommend_riichi and advice.stance is not Stance.FOLD:
            notes.append("リーチをすすめる聴牌だった（リーチすると打点が上がる）。")
    return TurnDecision(number, action, advice, verdict, safety, tuple(notes), lost_yaku, yaku_detour)


def _speed_note(advice: TurnAdvice) -> str:
    """おすすめが、速さだけで選ぶ牌と違うときの、速さだけの牌との違い（評価の文に添える）"""
    fast = advice.analysis.pick
    width = "待ち" if fast.shanten == TENPAI else "受け入れ"
    head = f"速さだけなら {kind_text(fast.kind)}切り（{_stage(fast.shanten)}・{width} {fast.kinds} 種 {fast.total} 枚）"
    outlook = advice.open_outlooks.get(fast.kind)
    view = advice.view_for(fast.tile)
    if advice.keeps_yaku and outlook is not None:
        why = "役が見えなくなる" if outlook.status is YakuStatus.NONE else "役まで遠回りになる"
    elif view is not None and not view.winnable:
        why = "その聴牌は、待ち牌が残っていない" if view.dead else "その聴牌は役が無く、あがれない"
    elif view is not None and view.furiten:
        why = "その聴牌はフリテン（ロンできない）"
    else:
        return f"{head}。"
    return f"{head}だが、{why}。"


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
    """いま返事を求められている牌（捨て牌・加槓の牌・暗槓の牌）でロンしたときの解説（ロンできなければ None）。
    裏ドラと本場・供託は入れない"""
    claim = hand.claim
    if claim is None or hand.phase is not Phase.CLAIM or not hand.ron_check(seat).ok:
        return None
    ctx = ron_context(hand, seat, claim.tile, chankan=claim.kind is not ClaimKind.DISCARD)
    return explain(_before_win(ctx), hand.rules)


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


# ---------------------------------------------------------------- カン（自分の番の暗槓・加槓）


@dataclass(frozen=True)
class KanAdvice:
    """自分の番にカンできるときの、するかどうかの目安（よく言われる目安。手が遅くならず、リーチを受けていなければ、してよい）"""

    tile: int               # カンする牌（ボタンに出す牌）
    added: bool             # 加槓か（偽なら暗槓）
    recommend: bool
    reason: str


def kan_advice(hand: HandState, seat: int) -> tuple[KanAdvice, ...]:
    """暗槓・加槓できる牌ごとの目安（リーチのあとは、カンしても待ちが変わらないときだけできる。目安は出さない）"""
    if hand.phase is not Phase.DRAW or hand.turn != seat or hand.players[seat].in_riichi:
        return ()
    player = hand.players[seat]
    counts = counts34(player.tiles)
    now = shanten_of(counts)
    threatened = bool(threats(hand, seat))
    found = []
    for tile, added in [*((t, False) for t in hand.ankan_tiles(seat)), *((t, True) for t in hand.kakan_tiles(seat))]:
        kind = kind_of(tile)
        used = 1 if added else 4
        counts[kind] -= used
        after = shanten_of(counts)
        counts[kind] += used
        name = kind_text(kind)
        robbed = "加槓した牌は、ほかの人がロンできる（槍槓）。" if added else ""
        if threatened:
            found.append(KanAdvice(tile, added, False, (
                f"{name}のカン：リーチを受けている。カンすると増えるドラが、リーチした人にも乗ることがある。守るなら、カンしない。{robbed}"
            )))
        elif after > now:
            found.append(KanAdvice(tile, added, False, f"{name}のカン：カンすると手が遅くなる（{_stage(now)} → {_stage(after)}）。{robbed}"))
        else:
            found.append(KanAdvice(tile, added, True, (
                f"{name}のカン：手は遅くならない。嶺上牌を 1 枚引けて、ドラが 1 枚増える（増えたドラは、ほかの人にも乗る）。{robbed}"
            )))
    return tuple(found)


# ---------------------------------------------------------------- 計測用：おすすめどおりに打つ


def coach_action(hand: HandState, seat: int) -> Action:
    """コーチのおすすめどおりに打つときの行動（ロン・ツモはいつもあがる。鳴きは、鳴きの判断のコーチのおすすめどおり。
    カンは、カンの目安（kan_advice）がすすめるときにする。リーチのあとの暗槓は、できればする）"""
    if hand.phase is Phase.CLAIM:
        if hand.ron_check(seat).ok:
            return ron(seat)
        advice = call_advice(hand, seat)
        if advice is not None and advice.recommend is not None:
            return advice.recommend
        return Action(seat, Move.PASS)
    auto = auto_action(hand, seat)
    if auto is not None:
        return auto
    if hand.can_tsumo(seat):
        return tsumo(seat)
    player = hand.players[seat]
    if player.in_riichi:
        kans = hand.ankan_tiles(seat)
        assert player.drawn is not None
        return ankan(seat, kans[0]) if kans else discard(seat, player.drawn)
    if hand.can_nine(seat) and nine_kinds(player.tiles) < KOKUSHI_KINDS:
        return nine(seat)
    for kan in kan_advice(hand, seat):
        if kan.recommend:
            return kakan(seat, kan.tile) if kan.added else ankan(seat, kan.tile)
    advice = turn_advice(hand, seat)
    if advice.recommend_riichi:
        return riichi_action(seat, advice.pick)
    return discard(seat, advice.pick)


def tiles_of_kinds(tiles: Sequence[int], kinds: Sequence[int]) -> tuple[int, ...]:
    """手牌の中の、その種類の牌"""
    wanted = set(kinds)
    return tuple(t for t in tiles if kind_of(t) in wanted)

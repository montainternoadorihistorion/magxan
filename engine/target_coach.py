"""役指定練習のコーチ：狙っている役に近づく切り方を調べ、切った牌を評価する。

    advice = target_advice(position, "sanshoku")     いまの 14 枚で、どれを切ると役に近いか
    judge_target(advice, tile)                       実際に切った牌を、おすすめと比べる
    target_result(explanation, "sanshoku")           あがったとき、狙った役が付いたか
    approach_tiles(counts, "sanshoku", …)            13 枚の手で、引くと役に近づく牌（聴牌なら、役が付くあがり牌）
    wants_riichi(analysis, "ippatsu", first=…)       リーチが要る役を狙う局で、いま「リーチして切る」を勧めるか
    judge_riichi_target(verdict, "ippatsu", …)       リーチせずに聴牌をとった打牌を、狙いから見て評価し直す

牌効率のコーチ（engine/coach.py）が「速さ」だけを見るのに対して、こちらは「狙った役までの距離」を見る。
距離の計算は engine/analysis/target.py。見えている牌（河・ドラ表示牌）は「もう手に入らない」として数える。

距離の計算は牌の組み合わせだけを見るので、「聴牌」「あがり」と言う前に、点数計算で確かめる。
    聴牌（距離 0）   役が付くあがり牌が 1 つも無ければ、その役の聴牌とは言わない（距離 1 として扱う）
    あがり           いまツモったとして点数計算をし、その役が付くときだけ「あがり」とする
高点法でほかの読み方が選ばれて、その役が付かないことがある（111222333 を三暗刻と読む、など）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache

from engine.analysis.advice import tile_for_discard
from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.target import (
    IMPOSSIBLE,
    SHAPELESS_KEYS,
    BlockKind,
    Plan,
    PlanBlock,
    target_distance,
    target_plan,
    target_tiles,
)
from engine.analysis.ukeire import remaining_counts
from engine.coach import MISSED_RIICHI_REASON, Analysis, Grade, Position, Verdict, analyze
from engine.content import yaku_page_map
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.explain import Explanation, Status, ranked_candidates
from engine.scoring.texts import kind_text, kinds_text
from engine.scoring.yaku_eval import YakuResult
from engine.tiles import counts34, is_red, kind_of

#: 狙った役の代わりに付くことがある、上位の役（図鑑のページの鍵）
UPGRADES: dict[str, tuple[str, ...]] = {
    "riichi": ("double_riichi",),
    "iipeikou": ("ryanpeikou",),
    "sanankou": ("suuankou",),
    "chanta": ("junchan",),
    "honitsu": ("chinitsu", "tsuuiisou"),
    "honroutou": ("chinroutou", "tsuuiisou"),
    "shousangen": ("daisangen",),
    "shousuushii": ("daisuushii",),
    "chinitsu": ("chuuren",),
}
BLOCK_NAMES = {BlockKind.SEQUENCE: "順子", BlockKind.SET: "刻子", BlockKind.PAIR: "雀頭", BlockKind.SINGLE: "1 枚", BlockKind.RYANMEN: "両面"}
#: リーチを宣言しないと付かない役（手の形を問わない役のうち）。狙う局では、聴牌にとれたら「リーチして切る」を勧める
RIICHI_TARGETS = frozenset({"riichi", "ippatsu", "double_riichi"})
#: リーチが要る役ごとの、リーチしなかったときのひとこと（役の条件そのものは、役図鑑と同じ言い方にする）
_NO_RIICHI_TEXTS = {
    "riichi": "{name}は、リーチを宣言しないと付かない。",
    "ippatsu": "{name}は、リーチのあと 1 巡以内に、誰も鳴かないうちにあがると付く（一人練習では、リーチのすぐ次のツモ）。まず、リーチが要る。",
    "double_riichi": "{name}は、最初の自分の番に、誰も鳴かないうちにリーチを宣言したときだけ付く。この局では、もう付かない。",
}


@dataclass(frozen=True)
class TargetCandidate:
    """打牌候補 1 つ（ある種類の牌を切る場合）"""

    kind: int
    tile: int                               # 切るならこの牌（赤でないほうを優先）
    distance: int                           # 切ったあとの、役までの距離（聴牌が 0）
    closer: tuple[tuple[int, int], ...]     # 引くと役に近づく牌（種類, 残り枚数）。いちばん近い切り方にだけ入れる
    shanten: int                            # 切ったあとの、ふつうの向聴数
    is_best: bool                           # おすすめと同じ良さか
    is_pick: bool

    @property
    def missing(self) -> int:
        """役の完成（あがり）までに要る枚数"""
        return self.distance + 1

    @property
    def total(self) -> int:
        return sum(count for _, count in self.closer)

    @property
    def kinds(self) -> int:
        return sum(1 for _, count in self.closer if count > 0)


@dataclass(frozen=True)
class TargetAdvice:
    key: str
    name: str                               # 役の名前
    shapeless: bool                         # 手の形を問わない役か（立直など。距離はふつうの向聴数と同じ）
    possible: bool                          # まだ作れるか（必要な牌が残っているか）
    won: bool                               # いまの 14 枚が、その役の形であがっているか
    candidates: tuple[TargetCandidate, ...] # 良い順（作れないときは空）
    pick: TargetCandidate | None
    plan: Plan                              # おすすめを切ったあとの、めざす形（あがっていれば、いまの形）
    before: Plan                            # 切る前（14 枚）の、めざす形
    speed_kind: int                         # 速さだけで選んだおすすめ（牌効率のコーチ）

    @property
    def distance(self) -> int:
        return self.plan.distance

    @property
    def best(self) -> tuple[TargetCandidate, ...]:
        return tuple(c for c in self.candidates if c.is_best)

    @property
    def differs_from_speed(self) -> bool:
        """速さだけのおすすめと、役を狙うおすすめが違うか"""
        return self.pick is not None and all(c.kind != self.speed_kind for c in self.best)

    def candidate(self, kind: int) -> TargetCandidate | None:
        return next((c for c in self.candidates if c.kind == kind), None)


# ---------------------------------------------------------------- 点数計算で確かめる


def _achievement(key: str, counted: set[str], ignored: set[str]) -> tuple[bool, str, bool]:
    """あがった手の役から、狙った役の扱いを決める →（その役が付いた, 代わりに付いた上位の役の名前, 役満があるので数えないだけか）

    counted は数えた役、ignored は役満があるために数えなかった役（どちらも役の表の鍵）。
    """
    pages = yaku_page_map()
    page = pages[key]
    made = any(yaku in counted for yaku in page.yaku)
    upgraded = ""
    if not made:
        for other in UPGRADES.get(key, ()):
            if any(yaku in counted for yaku in pages[other].yaku):
                upgraded = pages[other].name
                break
    superseded = not made and not upgraded and any(yaku in ignored for yaku in page.yaku)
    return made, upgraded, superseded


def _tiles_of(counts: Sequence[int]) -> tuple[int, ...]:
    """種類ごとの枚数を、牌の番号の並びにする（どの番号の牌かは、役に関係しない）"""
    return tuple(kind * 4 + i for kind in range(len(counts)) for i in range(counts[kind]))


def _credited(tiles: tuple[int, ...], win_tile: int, key: str, seat_wind: int, round_wind: int, rules: Rules) -> bool:
    """門前のツモで win_tile であがったとき、狙った役（か上位の役）が付くか。役満で数えないだけのときも「付く」とする"""
    ctx = WinContext(closed_tiles=tiles, win_tile=win_tile, is_tsumo=True, seat_wind=seat_wind, round_wind=round_wind)
    ranked = ranked_candidates(ctx, replace(rules, aka_dora=False))      # 赤ドラは役に関係しないので数えない
    if not ranked or not ranked[0].has_yaku:
        return False
    best = ranked[0].evaluation
    made, upgraded, superseded = _achievement(key, {y.key for y in best.yaku}, {y.key for y in best.ignored})
    return made or bool(upgraded) or superseded


@lru_cache(maxsize=4096)
def _winning_kinds(counts: tuple[int, ...], key: str, seat_wind: int, round_wind: int, rules: Rules, available: tuple[int, ...] | None) -> tuple[int, ...]:
    tiles = _tiles_of(counts)
    found = []
    for kind in range(len(counts)):
        if counts[kind] >= 4 or (available is not None and available[kind] <= 0):
            continue
        grown = list(counts)
        grown[kind] += 1
        if shanten_of(grown) != -1:
            continue
        if _credited((*tiles, kind * 4 + counts[kind]), kind * 4 + counts[kind], key, seat_wind, round_wind, rules):
            found.append(kind)
    return tuple(found)


def winning_kinds(
    counts: Sequence[int], key: str, *, seat_wind: int, round_wind: int, rules: Rules = DEFAULT_RULES,
    available: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """13 枚の手で、ツモると狙った役（か上位の役）が付く牌（種類）。available を渡したときは、手に入る牌だけ"""
    return _winning_kinds(tuple(counts), key, seat_wind, round_wind, rules, None if available is None else tuple(available))


def approach_tiles(
    counts: Sequence[int], key: str, *, seat_wind: int, round_wind: int, rules: Rules = DEFAULT_RULES,
    available: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """13 枚の手で、引くと狙った役に近づく牌（種類）。

    その役の聴牌（距離 0）なら、ツモると役が付くあがり牌（点数計算で確かめる）。役が付くあがり牌が無ければ空。
    まだ聴牌でなければ、引くと距離が縮む牌（engine.analysis.target.target_tiles）。
    手の形を問わない役（立直など）は、リーチなどの状況で付く役なので、点数計算では確かめない（あがり牌をそのまま返す）。
    """
    base = target_distance(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available)
    if base >= IMPOSSIBLE or base < 0:
        return ()
    if base == 0 and key not in SHAPELESS_KEYS:
        return winning_kinds(counts, key, seat_wind=seat_wind, round_wind=round_wind, rules=rules, available=available)
    return target_tiles(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available)


def wins_now(position: Position, key: str) -> bool:
    """いまの 14 枚でツモあがりすると、狙った役（か上位の役）が付くか（ツモった牌を、あがり牌とする）。

    手の形を問わない役（立直など）は、あがりの形になっていれば True（リーチなどの状況は、ここでは見ない）。
    """
    tiles = position.tiles
    if shanten_of(counts34(tiles)) != -1:
        return False
    if key in SHAPELESS_KEYS:
        return True
    win_tile = position.drawn if position.drawn is not None else tiles[-1]
    return _credited(tuple(tiles), win_tile, key, position.seat_wind, position.round_wind, position.rules)


# ---------------------------------------------------------------- 打つ前の局面


@lru_cache(maxsize=512)
def target_advice(position: Position, key: str) -> TargetAdvice:
    """狙う役について、いまの局面（打牌の前の 14 枚）を調べる"""
    tiles = position.tiles
    counts = counts34(tiles)
    available = remaining_counts(tiles, position.visible)          # 見えていない枚数（切った牌は戻ってこない）
    winds = {"seat_wind": position.seat_wind, "round_wind": position.round_wind}
    name = yaku_page_map()[key].name
    speed = analyze(position)
    order = {c.kind: index for index, c in enumerate(speed.candidates)}
    before = target_plan(counts, key, available=available, **winds)
    shapeless = key in SHAPELESS_KEYS
    common = {"key": key, "name": name, "shapeless": shapeless, "before": before, "speed_kind": speed.pick.kind}
    if wins_now(position, key):
        return TargetAdvice(possible=True, won=True, candidates=(), pick=None, plan=before, **common)

    rows = []
    for candidate in speed.candidates:
        counts[candidate.kind] -= 1
        rows.append((candidate, target_distance(counts, key, available=available, **winds)))
        counts[candidate.kind] += 1
    if min(distance for _, distance in rows) >= IMPOSSIBLE:
        return TargetAdvice(possible=False, won=False, candidates=(), pick=None, plan=before, **common)

    # 聴牌（距離 0）になる切り方は、役が付くあがり牌があるかを、点数計算で確かめる。
    # 1 つも無ければ、形は聴牌でも、その役の聴牌ではない。距離 1 として扱う（近づく牌は示さない）
    closer_of: dict[int, tuple[tuple[int, int], ...]] = {}
    adjusted = []
    for candidate, distance in rows:
        if distance == 0 and not shapeless:
            counts[candidate.kind] -= 1
            waits = winning_kinds(counts, key, rules=position.rules, available=available, **winds)
            counts[candidate.kind] += 1
            closer_of[candidate.kind] = tuple((kind, available[kind]) for kind in waits)
            if not waits:
                distance = 1
        adjusted.append((candidate, distance))
    nearest = min(distance for _, distance in adjusted)

    found = []
    for candidate, distance in adjusted:
        closer = closer_of.get(candidate.kind, ())
        if distance == nearest and candidate.kind not in closer_of:      # 聴牌を確かめた切り方は、上で決めてある
            counts[candidate.kind] -= 1
            closer = tuple((kind, available[kind]) for kind in target_tiles(counts, key, available=available, **winds))
            counts[candidate.kind] += 1
        tile = tile_for_discard(tiles, candidate.kind, aka=position.rules.aka_dora, drawn=position.drawn)
        found.append((candidate.kind, tile, distance, closer, candidate.shanten))
    # 良い順：役に近い → 近づく牌が多い → 速さのコーチの順（使いにくい牌から切る）
    found.sort(key=lambda row: (row[2], -sum(n for _, n in row[3]), -len(row[3]), order[row[0]]))
    top = found[0]
    top_total = sum(n for _, n in top[3])
    candidates = tuple(
        TargetCandidate(
            kind, tile, distance, closer, shanten,
            is_best=distance == top[2] and sum(n for _, n in closer) == top_total,
            is_pick=index == 0,
        )
        for index, (kind, tile, distance, closer, shanten) in enumerate(found)
    )
    counts[top[0]] -= 1
    plan = target_plan(counts, key, available=available, **winds)
    counts[top[0]] += 1
    return TargetAdvice(possible=True, won=False, candidates=candidates, pick=candidates[0], plan=plan, **common)


# ---------------------------------------------------------------- 切った牌の評価


class TargetGrade(StrEnum):
    BEST = "best"            # おすすめと同じ良さ
    NARROWER = "narrower"    # 距離は同じだが、近づく牌が少ない
    FARTHER = "farther"      # 役から遠ざかった
    LOST = "lost"            # その役が、もう作れなくなった


@dataclass(frozen=True)
class TargetVerdict:
    grade: TargetGrade
    chosen: TargetCandidate
    pick: TargetCandidate
    label: str                  # 評価の短い呼び方
    text: str                   # ひとことの評価
    reasons: tuple[str, ...]

    @property
    def is_best(self) -> bool:
        return self.grade is TargetGrade.BEST


def _tile_text(tile: int, position: Position) -> str:
    return ("赤" if is_red(tile, aka=position.rules.aka_dora) else "") + kind_text(kind_of(tile))


def _sp(text: str) -> str:
    return f" {text}" if text[:1].isdigit() else text


def block_text(block: PlanBlock) -> str:
    """めざす形の 1 組の書き方（例：2索・3索・4索 の順子）"""
    return f"{kinds_text(block.tiles)} の{BLOCK_NAMES[block.kind]}"


def judge_target(advice: TargetAdvice, tile: int, position: Position) -> TargetVerdict | None:
    """実際に切った牌を、役を狙うおすすめと比べる。その役がもう作れない・あがっている局面では None"""
    pick = advice.pick
    chosen = advice.candidate(kind_of(tile))
    if pick is None or chosen is None:
        return None
    name = advice.name
    mine, best = _tile_text(tile, position), _tile_text(pick.tile, position)
    reasons: list[str] = []
    if chosen.distance >= IMPOSSIBLE:
        grade = TargetGrade.LOST
        label = f"{name}が作れなくなった"
        text = f"{mine}を切ると、{name}に必要な牌が足りなくなる。{best}切りなら、あと {pick.missing} 枚で完成。"
    elif chosen.distance > pick.distance:
        grade = TargetGrade.FARTHER
        label = f"{name}から遠ざかった"
        text = f"{mine}を切ると、{name}の完成まで あと {chosen.missing} 枚になる。{best}切りなら、あと {pick.missing} 枚のまま。"
        block = next((b for b in advice.before.blocks if chosen.kind in b.have), None)
        if block is not None:
            reasons.append(f"{kind_text(chosen.kind)}は、めざす形の「{block_text(block)}」に使う牌。")
    elif chosen.is_best:
        grade = TargetGrade.BEST
        label = f"{name}に近い切り方"
        text = f"{mine}切り。{name}の完成まで、あと {chosen.missing} 枚。"
        if chosen.total:
            text += f"近づく牌は {chosen.kinds} 種 {chosen.total} 枚で、いちばん多い。"
    else:
        grade = TargetGrade.NARROWER
        fewer = pick.total - chosen.total
        label = f"近づく牌が {fewer} 枚少ない"
        text = (
            f"{mine}切りでも、{name}の完成まで あと {chosen.missing} 枚。ただし、近づく牌は {chosen.kinds} 種 {chosen.total} 枚。"
            f"{best}切りなら {pick.kinds} 種 {pick.total} 枚で、{fewer} 枚多い。"
        )
    return TargetVerdict(grade, chosen, pick, label, text, tuple(reasons))


# ---------------------------------------------------------------- リーチが要る役（立直・一発・ダブル立直）


def wants_riichi(analysis: Analysis, key: str | None, *, first: bool) -> bool:
    """リーチが要る役を狙う局で、いま「リーチして切る」を勧めるか。

    聴牌にとれて（待ち牌が 1 枚以上残っていて）、リーチできるとき。ダブル立直は、最初の打牌（first）のときだけ。
    """
    if key not in RIICHI_TARGETS or analysis.can_win or not analysis.position.can_riichi:
        return False
    if key == "double_riichi" and not first:
        return False
    pick = analysis.pick
    return pick.shanten == TENPAI and pick.total > 0


def judge_riichi_target(verdict: Verdict, key: str | None, tile: int, position: Position, *, first: bool) -> Verdict:
    """リーチが要る役を狙う局で、リーチできたのに宣言せずに聴牌をとった打牌を、狙いから見て評価し直す。

    そういう打牌は、速さだけなら良くても、狙った役から見ると逃している（Grade.NO_RIICHI）。ほかの打牌は、そのまま返す。
    ダブル立直は、最初の打牌だけを見る（2 打目からは、もう付かないので、ふつうに速さで評価する）。
    """
    if key not in RIICHI_TARGETS or not verdict.missed_riichi or (key == "double_riichi" and not first):
        return verdict
    name = yaku_page_map()[key].name
    text = f"{_tile_text(tile, position)}切りで聴牌したが、リーチを宣言しなかった。" + _NO_RIICHI_TEXTS[key].format(name=name)
    reasons = ["リーチするときは、先に「リーチ」を押してから、切る牌を選ぶ。"]
    # 次の巡でリーチできるのは、そのあとにもう 1 回以上ツモが残っているときだけ（リーチは、ツモが残っていないとできない）
    if key != "double_riichi" and position.draws_left >= 2:
        reasons.append("聴牌をくずさなければ、次の巡でもリーチできる。")
    if not verdict.is_best:             # 切った牌そのものも、速さで見て一番ではなかった
        reasons.append(verdict.text)
    reasons.extend(reason for reason in verdict.reasons if reason != MISSED_RIICHI_REASON)
    return replace(verdict, grade=Grade.NO_RIICHI, label="リーチしなかった", text=text, reasons=tuple(reasons))


# ---------------------------------------------------------------- あがったとき


@dataclass(frozen=True)
class TargetResult:
    key: str
    name: str
    made: bool                      # 狙った役が付いたか
    upgraded: str                   # 代わりに付いた上位の役の名前（無ければ空）
    check: YakuResult | None        # 付かなかったときの、成立条件の内訳（まとめて扱う役では None）
    superseded: str = ""            # 狙った役の条件は満たしたが、役満があるために数えないとき、その役満の名前

    @property
    def achieved(self) -> bool:
        """狙った役の形ができたか（その役が付いた／上位の役が付いた／役満があるので数えないだけ）"""
        return self.made or bool(self.upgraded) or bool(self.superseded)


def target_result(explanation: Explanation, key: str) -> TargetResult:
    """あがった手に、狙った役が付いたかを調べる"""
    page = yaku_page_map()[key]
    best = explanation.best.evaluation if explanation.status is Status.WIN else None
    counted = {item.key for item in best.yaku} if best is not None else set()
    ignored = {item.key for item in best.ignored} if best is not None else set()
    made, upgraded, superseded_flag = _achievement(key, counted, ignored)
    # 役満があるときは、ふつうの役を数えない。条件を満たしていれば、狙った形はできている
    superseded = "・".join(item.name for item in best.yaku) if superseded_flag and best is not None else ""
    check = None
    if not made and not superseded and len(page.yaku) == 1 and explanation.candidates:
        check = explanation.yaku_check(page.yaku[0])
    return TargetResult(key, page.name, made, upgraded, check, superseded)

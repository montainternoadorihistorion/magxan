"""役指定練習のコーチ：狙っている役に近づく切り方を調べ、切った牌を評価する。

    advice = target_advice(position, "sanshoku")     いまの 14 枚で、どれを切ると役に近いか
    judge_target(advice, tile)                       実際に切った牌を、おすすめと比べる
    target_result(explanation, "sanshoku")           あがったとき、狙った役が付いたか

牌効率のコーチ（engine/coach.py）が「速さ」だけを見るのに対して、こちらは「狙った役までの距離」を見る。
距離の計算は engine/analysis/target.py。見えている牌（河・ドラ表示牌）は「もう手に入らない」として数える。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from engine.analysis.advice import tile_for_discard
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
from engine.coach import Position, analyze
from engine.content import yaku_page_map
from engine.scoring.explain import Explanation, Status
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
BLOCK_NAMES = {BlockKind.SEQUENCE: "順子", BlockKind.SET: "刻子", BlockKind.PAIR: "雀頭", BlockKind.SINGLE: "1 枚"}


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
    if before.distance == -1:
        return TargetAdvice(possible=True, won=True, candidates=(), pick=None, plan=before, **common)

    rows = []
    for candidate in speed.candidates:
        counts[candidate.kind] -= 1
        rows.append((candidate, target_distance(counts, key, available=available, **winds)))
        counts[candidate.kind] += 1
    nearest = min(distance for _, distance in rows)
    if nearest >= IMPOSSIBLE:
        return TargetAdvice(possible=False, won=False, candidates=(), pick=None, plan=before, **common)

    found = []
    for candidate, distance in rows:
        closer: tuple[tuple[int, int], ...] = ()
        if distance == nearest:
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
    pages = yaku_page_map()
    page = pages[key]
    counted = {item.key: item for item in explanation.best.evaluation.yaku} if explanation.status is Status.WIN else {}
    made = any(yaku in counted for yaku in page.yaku)
    upgraded = ""
    if not made:
        for other in UPGRADES.get(key, ()):
            hit = next((counted[yaku] for yaku in pages[other].yaku if yaku in counted), None)
            if hit is not None:
                upgraded = pages[other].name
                break
    superseded = ""
    if not made and not upgraded and explanation.status is Status.WIN:
        best = explanation.best
        # 役満があるときは、ふつうの役を数えない。条件を満たしていれば、狙った形はできている
        if any(item.key in page.yaku for item in best.evaluation.ignored):
            superseded = "・".join(item.name for item in best.evaluation.yaku)
    check = None
    if not made and not superseded and len(page.yaku) == 1 and explanation.candidates:
        check = explanation.yaku_check(page.yaku[0])
    return TargetResult(key, page.name, made, upgraded, check, superseded)

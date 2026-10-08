"""守備：リーチした人に対して、自分の手牌の各牌がどれくらい危ないか（危険度）と、その根拠。

根拠には、見えている牌から確かめられる事実だけを使う。

    現物    リーチした人の河にある牌と、リーチのあとに誰かが切って通った牌。
            その人は、この牌ではロンできない（自分の河にある牌・リーチのあとに見逃した牌は、フリテンになるため）
    スジ    両面待ちは「n と n＋3」の 2 種類を待つ（23 の両面なら 1 と 4）。片方が現物なら、
            その両面待ちではもう片方でもロンできない（フリテン）。だから、その両面待ちには当たらない
    壁      ある牌が 4 枚とも見えていると、その牌を使う待ちの形は作れない（ノーチャンス）
    字牌    字牌の待ちは、単騎と双碰（と国士無双）だけ。見えていない枚数が少ないほど、待ちの形が減る

危険度（0〜5）は、その牌でまだ当たりうる待ちの形から決めた目安。よく知られた「安全度の順番」に合わせてある。
確率の計算ではないので、画面でも「目安」として出す。

    0  安全（現物）
    1  ほぼ安全       両面が無い 1・9（スジ・壁）、字牌で見えていないのが 1 枚以下（単騎だけ）
    2  比較的安全     両面が無い 2・8・3・7・4・5・6（スジ・両スジ・壁）、字牌で見えていないのが 2 枚
    3  やや危険       両面がある 1・9（無スジ）、字牌で見えていないのが 3 枚（自分の 1 枚のほかに見えていない）
    4  危険           両面がある 2・8・3・7、両面が片方だけ無い 4・5・6（片スジ）
    5  とても危険     両面が 2 つともある 4・5・6（無スジの真ん中の牌）
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from engine.game import HandState
from engine.scoring.dora import dora_kind_of
from engine.scoring.texts import kind_text, kinds_text
from engine.tiles import counts34, is_honor_kind, kind_of, number_of_kind

LEVEL_NAMES = ("安全", "ほぼ安全", "比較的安全", "やや危険", "危険", "とても危険")
MAX_LEVEL = len(LEVEL_NAMES) - 1


class Shape(StrEnum):
    """当たりうる待ちの形"""

    RYANMEN = "ryanmen"
    KANCHAN = "kanchan"
    PENCHAN = "penchan"
    SHANPON = "shanpon"
    TANKI = "tanki"


SHAPE_NAMES = {
    Shape.RYANMEN: "両面",
    Shape.KANCHAN: "嵌張",
    Shape.PENCHAN: "辺張",
    Shape.SHANPON: "双碰",
    Shape.TANKI: "単騎",
}


class Basis(StrEnum):
    """危険度を決めた、いちばん大きな根拠"""

    GENBUTSU = "genbutsu"       # 現物
    SUJI = "suji"               # スジ（両スジ）で、両面が無い
    KABE = "kabe"               # 壁（ノーチャンス）で、両面が無い（スジと壁の両方なら SUJI）
    HALF_SUJI = "half_suji"     # 片スジ（4・5・6 で、両面が片方だけ無い）
    NO_SUJI = "no_suji"         # 無スジ（両面がある）
    HONOR = "honor"             # 字牌（見えている枚数で決まる）


BASIS_NAMES = {
    Basis.GENBUTSU: "現物",
    Basis.SUJI: "スジ",
    Basis.KABE: "壁（ノーチャンス）",
    Basis.HALF_SUJI: "片スジ",
    Basis.NO_SUJI: "無スジ",
    Basis.HONOR: "字牌",
}


@dataclass(frozen=True)
class Threat:
    """リーチしている人 1 人"""

    seat: int
    river: frozenset[int]       # その人の河にある種類
    passed: frozenset[int]      # リーチのあとに切られて通った種類（その人の河にあるものも含む）
    riichi_index: int           # その人のリーチ宣言牌が、局の何枚目の打牌か（0 始まり）

    @property
    def safe(self) -> frozenset[int]:
        """現物の種類（その人はこの牌ではロンできない）"""
        return self.river | self.passed


@dataclass(frozen=True)
class Ryanmen:
    """ある牌を待ちに含む両面の形 1 つ（例：1萬を待つ 23萬）"""

    blocks: tuple[int, int]     # 手の中の 2 枚（種類）
    other: int                  # もう 1 つの待ち（種類）
    suji: bool                  # もう 1 つの待ちが現物なので、この両面では当たらない
    kabe: int | None            # 4 枚見えているので、この形が作れない種類（無ければ None）

    @property
    def open(self) -> bool:
        """この両面待ちに当たる可能性があるか"""
        return not self.suji and self.kabe is None


@dataclass(frozen=True)
class Danger:
    """リーチした人 1 人に対する、ある牌（種類）の危険度"""

    kind: int
    seat: int                           # リーチした人の席
    level: int                          # 0〜5（目安）
    basis: Basis
    shapes: tuple[Shape, ...]           # まだ当たりうる待ちの形（現物なら空）
    ryanmen: tuple[Ryanmen, ...] = ()   # この牌を待ちに含む両面の形（数牌だけ）
    unseen: int = 0                     # 自分から見えていない枚数（字牌の判断と、シャンポン・単騎の有無に使う）
    after_riichi: bool = False          # 現物のうち、リーチのあとに通った牌（その人の河には無い）

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]


@dataclass(frozen=True)
class TileDanger:
    """自分の手牌の 1 種類について、リーチした全員に対する危険度"""

    kind: int
    level: int                          # いちばん危ない相手に対する危険度
    each: tuple[Danger, ...]            # 相手ごと（席の順）
    dora: bool = False                  # ドラ（当たると点が高くなる）

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]

    @property
    def worst(self) -> Danger:
        return max(self.each, key=lambda d: d.level)


# ---------------------------------------------------------------- リーチした人を調べる


def threats(hand: HandState, viewer: int) -> tuple[Threat, ...]:
    """viewer から見て、リーチが成立している人（自分以外）"""
    found = []
    for seat, player in enumerate(hand.players):
        if seat == viewer or not player.riichi_paid or player.riichi_at is None:
            continue
        index = player.river[player.riichi_at].order
        passed = frozenset(kind_of(d.tile) for p in hand.players for d in p.river if d.order > index)
        found.append(Threat(seat, player.river_kinds, passed, index))
    return tuple(found)


# ---------------------------------------------------------------- 1 種類の危険度


def _ryanmen_shapes(kind: int, safe: frozenset[int], seen: Sequence[int]) -> tuple[Ryanmen, ...]:
    """kind を待ちに含む両面の形（数牌だけ）。両面は 23〜78 の形で、両側の 2 種類を待つ"""
    number = number_of_kind(kind)
    base = kind - number + 1             # その色の 1 の種類
    shapes = []
    # kind が「下側の待ち」になる形（n＋1, n＋2）。もう 1 つの待ちは n＋3
    if number <= 6:
        blocks = (base + number, base + number + 1)
        shapes.append((blocks, base + number + 2))
    # kind が「上側の待ち」になる形（n−2, n−1）。もう 1 つの待ちは n−3
    if number >= 4:
        blocks = (base + number - 3, base + number - 2)
        shapes.append((blocks, base + number - 4))
    result = []
    for blocks, other in shapes:
        kabe = next((k for k in blocks if seen[k] >= 4), None)
        result.append(Ryanmen(blocks, other, other in safe, kabe))
    return tuple(result)


def danger_of(kind: int, threat: Threat, seen: Sequence[int]) -> Danger:
    """リーチした人 1 人に対する、ある種類の牌の危険度。

    seen は、自分から見えている枚数（種類ごと。自分の手牌・全員の河・ドラ表示牌）。
    """
    unseen = max(0, 4 - seen[kind])
    if kind in threat.safe:
        # 現物：その人の河に無ければ、リーチのあとに通った牌
        return Danger(kind, threat.seat, 0, Basis.GENBUTSU, (), unseen=unseen, after_riichi=kind not in threat.river)
    singles: list[Shape] = []
    if unseen >= 2:
        singles.append(Shape.SHANPON)
    if unseen >= 1:
        singles.append(Shape.TANKI)
    if is_honor_kind(kind):
        level = 1 if unseen <= 1 else (2 if unseen == 2 else 3)
        return Danger(kind, threat.seat, level, Basis.HONOR, tuple(singles), unseen=unseen)

    number = number_of_kind(kind)
    ryanmen = _ryanmen_shapes(kind, threat.safe, seen)
    shapes: list[Shape] = []
    if any(r.open for r in ryanmen):
        shapes.append(Shape.RYANMEN)
    if 2 <= number <= 8 and seen[kind - 1] < 4 and seen[kind + 1] < 4:
        shapes.append(Shape.KANCHAN)
    if number == 3 and seen[kind - 2] < 4 and seen[kind - 1] < 4:
        shapes.append(Shape.PENCHAN)
    if number == 7 and seen[kind + 1] < 4 and seen[kind + 2] < 4:
        shapes.append(Shape.PENCHAN)
    shapes.extend(singles)

    # 数牌には、その牌を待ちに含む両面の形が 1 つ（1〜3・7〜9）か 2 つ（4〜6）ある
    opened = sum(1 for r in ryanmen if r.open)
    if opened == 0:                       # 両面には当たらない（スジ・壁）
        basis = Basis.SUJI if any(r.suji for r in ryanmen) else Basis.KABE
        level = 1 if number in (1, 9) else 2
    elif opened < len(ryanmen):           # 4・5・6 で、両面が片方だけ無い
        basis = Basis.HALF_SUJI if any(r.suji for r in ryanmen) else Basis.NO_SUJI
        level = 4
    else:
        basis = Basis.NO_SUJI
        level = 3 if number in (1, 9) else (5 if len(ryanmen) == 2 else 4)
    return Danger(kind, threat.seat, level, basis, tuple(shapes), ryanmen=ryanmen, unseen=unseen)


# ---------------------------------------------------------------- 手牌すべて


def seen_counts(tiles: Iterable[int], visible: Iterable[int]) -> list[int]:
    """自分から見えている枚数（種類ごと）。tiles は自分の手牌、visible は河とドラ表示牌"""
    return counts34([*tiles, *visible])


def danger_table(
    tiles: Sequence[int],
    visible: Sequence[int],
    found: Sequence[Threat],
    *,
    dora_indicators: Sequence[int] = (),
) -> tuple[TileDanger, ...]:
    """自分の手牌の種類ごとの危険度（安全な順。同じなら種類の順）。リーチした人がいなければ空"""
    if not found:
        return ()
    seen = seen_counts(tiles, visible)
    dora_kinds = {dora_kind_of(kind_of(t)) for t in dora_indicators}
    rows = []
    for kind in sorted({kind_of(t) for t in tiles}):
        each = tuple(danger_of(kind, threat, seen) for threat in found)
        rows.append(TileDanger(kind, max(d.level for d in each), each, dora=kind in dora_kinds))
    rows.sort(key=lambda row: (row.level, row.kind))
    return tuple(rows)


# ---------------------------------------------------------------- 根拠の文


def _kinds(kinds: Iterable[int]) -> str:
    return "・".join(kind_text(k) for k in kinds)


def reasons(danger: Danger, who: str) -> tuple[str, ...]:
    """危険度の根拠（事実だけ）。who は、リーチした人の呼び方（下家・対面・上家）"""
    name = kind_text(danger.kind)
    if danger.basis is Basis.GENBUTSU:
        if danger.after_riichi:
            return (f"{who}のリーチのあとに切られて、通った牌。{who}は見逃したので、{name}ではロンできない（フリテン）。",)
        return (f"{who}の河にある牌（現物）。{who}は、自分の河にある牌ではロンできない（フリテン）。",)
    lines: list[str] = []
    if danger.basis is Basis.HONOR:
        seen = 4 - danger.unseen
        if danger.unseen == 0:
            lines.append(f"{name}は 4 枚とも見えている（自分の手牌を含む）。当たるのは国士無双だけ。")
        elif danger.unseen == 1:
            lines.append(
                f"{name}は {seen} 枚見えていて（自分の手牌を含む）、見えていないのは 1 枚。字牌の待ちは単騎と双碰だけで、"
                "双碰には同じ牌が 2 枚要るので、当たるのは単騎だけ。"
            )
        else:
            lines.append(
                f"{name}は {seen} 枚見えていて（自分の手牌を含む）、見えていないのは {danger.unseen} 枚。"
                "字牌の待ちは単騎と双碰（どちらもありうる）。"
            )
        return tuple(lines)
    for shape in danger.ryanmen:
        blocks = kinds_text(shape.blocks)
        waits = f"{_kinds(sorted((danger.kind, shape.other)))}待ち"
        if shape.suji:
            lines.append(f"{blocks}の両面（{waits}）は無い：{kind_text(shape.other)}が{who}の現物なので、ロンできない（スジ）。")
        elif shape.kabe is not None:
            lines.append(f"{blocks}の両面（{waits}）は無い：{kind_text(shape.kabe)}が 4 枚とも見えているので、この形は作れない（壁）。")
        else:
            lines.append(f"{blocks}の両面（{waits}）に当たる可能性がある。")
    others = [SHAPE_NAMES[s] for s in danger.shapes if s is not Shape.RYANMEN]
    if others:
        lines.append(f"両面のほかに、{'・'.join(others)}の待ちには当たる可能性がある（スジや壁では防げない）。")
    return tuple(lines)


def summary(danger: Danger) -> str:
    """根拠を短く（表の 1 行に入れる）。例：「スジ（4萬）」「字牌・残り 1 枚」「無スジ」"""
    if danger.basis is Basis.GENBUTSU:
        return "現物（リーチのあとに通った）" if danger.after_riichi else "現物"
    if danger.basis is Basis.HONOR:
        return f"字牌・見えていない {danger.unseen} 枚"
    suji = [kind_text(kind) for kind in sorted(r.other for r in danger.ryanmen if r.suji)]
    kabe = [kind_text(kind) for kind in sorted({r.kabe for r in danger.ryanmen if r.kabe is not None and not r.suji})]
    parts = []
    if suji:
        label = "両スジ" if len(suji) == 2 else ("片スジ" if danger.basis is Basis.HALF_SUJI else "スジ")
        parts.append(f"{label}（{'・'.join(suji)}）")
    if kabe:
        parts.append(f"壁（{'・'.join(kabe)}）")
    if not parts:
        parts.append("無スジ")
    return "・".join(parts)

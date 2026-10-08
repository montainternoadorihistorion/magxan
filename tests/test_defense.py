"""守備（危険度と根拠。engine/defense.py）のテスト"""
from __future__ import annotations

from engine.defense import (
    Basis,
    Shape,
    Threat,
    danger_of,
    danger_table,
    reasons,
    seen_counts,
    summary,
    threats,
)
from engine.tiles import kind_of, parse_tiles
from tests.game_helpers import build_hand


def k(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def threat_of(river: str, passed: str = "") -> Threat:
    river_kinds = frozenset(kind_of(t) for t in parse_tiles(river))
    passed_kinds = frozenset(kind_of(t) for t in parse_tiles(passed)) if passed else frozenset()
    return Threat(1, river_kinds, passed_kinds, 3)


def danger(tile: str, river: str, *, mine: str = "", visible: str = "", passed: str = ""):
    """自分の手牌 mine（tile を含める）、見えている牌 visible（リーチした人の河を含める）で、tile の危険度"""
    hand = parse_tiles(mine or tile)
    used = set(hand)
    shown = parse_tiles(visible or river, used=used)
    return danger_of(k(tile), threat_of(river, passed), seen_counts(hand, shown))


def test_genbutsu_is_safe():
    d = danger("4m", "4m9p", mine="4m")
    assert d.level == 0 and d.basis is Basis.GENBUTSU and d.shapes == () and not d.after_riichi
    assert "河にある" in reasons(d, "下家")[0]


def test_tile_passed_after_riichi_is_genbutsu():
    d = danger("5p", "1m", mine="5p", visible="1m5p", passed="5p")
    assert d.level == 0 and d.after_riichi
    assert "リーチのあと" in reasons(d, "対面")[0]
    assert summary(d) == "現物（リーチのあとに通った）"


def test_suji_terminal_and_middle():
    one = danger("1m", "4m")
    assert one.level == 1 and one.basis is Basis.SUJI
    assert Shape.RYANMEN not in one.shapes and set(one.shapes) == {Shape.SHANPON, Shape.TANKI}
    assert summary(one) == "スジ（4萬）"
    seven = danger("7m", "4m")
    assert seven.level == 2 and seven.basis is Basis.SUJI
    assert {Shape.KANCHAN, Shape.PENCHAN} <= set(seven.shapes)        # スジでも嵌張・辺張には当たる
    two = danger("2p", "5p")
    assert two.level == 2 and Shape.KANCHAN in two.shapes


def test_double_and_half_suji():
    both = danger("4s", "1s7s")
    assert both.level == 2 and both.basis is Basis.SUJI and summary(both) == "両スジ（1索・7索）"
    half = danger("4s", "7s")
    assert half.level == 4 and half.basis is Basis.HALF_SUJI and summary(half) == "片スジ（7索）"
    lines = reasons(half, "下家")
    assert any("無い" in line and "7索" in line for line in lines)
    assert any("23索の両面" in line and "当たる可能性" in line for line in lines)


def test_no_suji_levels():
    assert danger("5m", "9p").level == 5
    assert danger("1m", "9p").level == 3
    assert danger("2m", "9p").level == 4
    assert danger("3m", "9p").level == 4
    assert danger("5m", "9p").basis is Basis.NO_SUJI


def test_kabe_no_chance():
    # 2索 が 4 枚見えている（自分が 3 枚、河に 1 枚）→ 23索 の両面は作れないので、1索 は両面に当たらない
    d = danger("1s", "2s", mine="1s2s2s2s", visible="2s")
    assert d.level == 1 and d.basis is Basis.KABE and summary(d) == "壁（2索）"
    assert any("4 枚とも見えている" in line for line in reasons(d, "上家"))
    # 3索 には 45索 の両面が残る
    assert danger("3s", "2s", mine="3s2s2s2s", visible="2s").level == 4


def test_honor_levels_by_unseen_count():
    assert danger("5z", "1m", mine="5z", visible="1m5z5z").level == 1      # 見えていないのは 1 枚：単騎だけ
    assert danger("5z", "1m", mine="5z", visible="1m5z").level == 2        # 2 枚
    assert danger("5z", "1m", mine="5z").level == 3                        # 3 枚（自分の 1 枚のほかは見えていない）
    last = danger("5z", "1m", mine="5z", visible="1m5z5z5z")
    assert last.level == 1 and last.shapes == ()
    assert "国士無双" in reasons(last, "下家")[0]


def test_threats_include_tiles_passed_after_riichi():
    # 親（席 0）から順に切った河：席 0 東 → 席 1 2索（リーチ）→ 席 2 5筒 → 席 3 9萬 → 席 0 西
    hand = build_hand(
        ["123m456p789s1122z", "234m567m78p345s66s", "22z33z44z55z66z7z1m2m", "258p369s147m3z4z6z7z"],
        turn=1, drawn="9s", rivers=("1z3z", "2s", "5p", "9m"), riichi=(None, 0, None, None),
        kyotaku=1, scores=(25_000, 24_000, 25_000, 25_000),
    )
    found = threats(hand, 0)
    assert [t.seat for t in found] == [1]
    threat = found[0]
    assert threat.river == frozenset({k("2s")})
    assert threat.passed == frozenset({k("5p"), k("9m"), k("3z")})       # 東は、リーチの前に切られた
    assert k("1z") not in threat.safe
    assert threats(hand, 1) == ()                                         # 自分のリーチは数えない


def test_danger_table_sorts_safe_first_and_takes_the_worst_threat():
    mine = parse_tiles("4m5m1p9s1z")
    shown = parse_tiles("4m9s", used=set(mine))
    first = Threat(1, frozenset({k("4m")}), frozenset(), 0)
    second = Threat(2, frozenset({k("9s")}), frozenset(), 1)
    table = danger_table(mine, shown, [first, second])
    by_kind = {row.kind: row for row in table}
    assert by_kind[k("4m")].level == max(d.level for d in by_kind[k("4m")].each)
    assert [row.level for row in table] == sorted(row.level for row in table)
    assert danger_table(mine, shown, []) == ()

"""手牌の分析（向聴数・受け入れ・分け方・打牌の助言・待ち）のテスト"""
from __future__ import annotations

import random

import pytest
from mahjong.shanten import Shanten

from engine.analysis.advice import advise, loose_rank, tile_for_discard
from engine.analysis.blocks import (
    PartType,
    best_layout,
    chiitoi_layout,
    formula_shanten,
    kokushi_layout,
    regular_layout,
)
from engine.analysis.shanten import shanten_info, shanten_meaning, shanten_of, shanten_text
from engine.analysis.ukeire import acceptance, chance_within, discard_options, draw_chance, remaining_counts
from engine.analysis.waits import is_win_shape, wait_kinds, waits_of
from engine.rules import Rules
from engine.scoring.decompose import Form
from engine.scoring.explain import Status
from engine.scoring.texts import kind_text
from engine.tiles import CHUN, EAST, HAKU, HATSU, SOUTH, counts34, parse_tiles


def counts(text: str) -> list[int]:
    return counts34(parse_tiles(text))


def names(kinds) -> list[str]:
    return [kind_text(k) for k in kinds]


def random_counts(rnd: random.Random, size: int, kinds=range(34)) -> list[int]:
    pool = [k for k in kinds for _ in range(4)]
    rnd.shuffle(pool)
    result = [0] * 34
    for kind in pool[:size]:
        result[kind] += 1
    return result


# ---------------------------------------------------------------- 向聴数


@pytest.mark.parametrize(
    ("hand", "value", "text"),
    [
        ("123m456p789s234s44z", -1, "和了形"),
        ("123m456p789s23s44z", 0, "聴牌"),
        ("123m456p789s13s44z", 0, "聴牌"),
        ("123m456p789s2s144z", 1, "1 向聴"),
        ("1345m2289p3467s1z", 2, "2 向聴"),
        ("1133m5577p2299s1z", 0, "聴牌"),              # 七対子の聴牌
        ("19m19p19s1234567z", 0, "聴牌"),              # 国士無双の十三面待ち
        ("19m19p19s123456z5m", 1, "1 向聴"),
        ("147m258p369s1234z", 6, "6 向聴"),            # ばらばらの手。七対子として数えた 6 向聴がいちばん近い
        ("159m159p159s1234z", 3, "3 向聴"),            # 么九牌が 10 種類。国士無双まで 13 − 10 ＝ 3
    ],
)
def test_shanten_values(hand, value, text):
    assert shanten_of(counts(hand)) == value
    assert shanten_text(value) == text
    assert shanten_meaning(value)


def test_shanten_info_by_form():
    info = shanten_info(counts("1133m5577p2299s1z"))
    assert (info.value, info.chiitoi) == (0, 0) and info.regular > 0 and info.forms == (Form.CHIITOI,)
    info = shanten_info(counts("123m456p789s23s44z"))
    assert (info.value, info.regular, info.forms) == (0, 0, (Form.REGULAR,))
    # 二盃口の形は、4 面子 1 雀頭としても七対子としても聴牌
    info = shanten_info(counts("223344m556677p8s"))
    assert info.forms == (Form.REGULAR, Form.CHIITOI)
    # 鳴いている手（門前の牌が 10 枚）は、七対子と国士無双を数えない
    info = shanten_info(counts("123m456p78s22p"))
    assert (info.value, info.chiitoi, info.kokushi) == (0, None, None)


def test_shanten_meaning_text():
    assert shanten_meaning(2) == "聴牌まで、有効牌があと 2 枚。"
    assert shanten_meaning(0) == "あと 1 枚であがり。"
    assert shanten_meaning(-1) == "あがりの形になっている。"


# ---------------------------------------------------------------- 受け入れ


def test_acceptance_of_a_ryanmen_tenpai():
    hand = parse_tiles("123m456p789s23s44z")
    result = acceptance(counts34(hand), remaining_counts(hand))
    assert result.shanten == 0
    assert [(kind_text(k), n) for k, n in result.tiles] == [("1索", 4), ("4索", 4)]
    assert (result.kinds, result.total) == (2, 8)


def test_acceptance_subtracts_visible_tiles():
    hand = parse_tiles("123m456p789s23s44z")
    visible = parse_tiles("1s1s4s")                  # 河に 1索 が 2 枚、ドラ表示牌に 4索
    result = acceptance(counts34(hand), remaining_counts(hand, visible))
    assert dict(result.tiles) == {18: 2, 21: 3}
    assert result.total == 5


def test_acceptance_keeps_dead_waits_with_zero_count():
    hand = parse_tiles("123m456p789s13s44z")
    visible = parse_tiles("2222s")
    result = acceptance(counts34(hand), remaining_counts(hand, visible))
    assert result.tiles == ((19, 0),) and result.live == () and (result.kinds, result.total) == (0, 0)


def test_acceptance_never_counts_a_fifth_tile():
    # 1111萬 を持っている。形の上では 1萬 が有効でも、5 枚目は無い
    hand = parse_tiles("1111m23m456p789s4z")
    result = acceptance(counts34(hand), remaining_counts(hand))
    assert 0 not in dict(result.tiles)


def test_one_shanten_acceptance():
    hand = parse_tiles("123m456p789s2s144z")          # 2索・東・北北 が浮いている 1 向聴
    result = acceptance(counts34(hand), remaining_counts(hand))
    assert result.shanten == 1
    assert names(k for k, _ in result.tiles) == ["1索", "2索", "3索", "4索", "東", "北"]
    assert dict(result.tiles)[30] == 2                 # 北 は手に 2 枚あるので、残りは 2 枚


def test_discard_options_are_sorted_best_first():
    hand = parse_tiles("1345m2289p3467s15z")
    options = discard_options(counts34(hand), remaining_counts(hand))
    assert len(options) == 13                           # 2筒 が 2 枚あるので、切る種類は 13
    keys = [(o.shanten, -o.total, -o.kinds) for o in options]
    assert keys == sorted(keys)
    best = [o for o in options if (o.shanten, o.total) == (options[0].shanten, options[0].total)]
    assert names(o.kind for o in best) == ["1萬", "東", "白"]
    assert (options[0].shanten, options[0].kinds, options[0].total) == (2, 4, 16)
    worst = options[-1]
    assert worst.shanten == 3                           # 面子の 345萬 を崩すと 1 つ遠ざかる


def test_discard_from_a_complete_hand_keeps_tenpai():
    hand = parse_tiles("123m456p789s234s44z")
    options = discard_options(counts34(hand), remaining_counts(hand))
    assert options[0].shanten == 0


def test_chances():
    assert draw_chance(4, 100) == 0.04
    assert draw_chance(0, 100) == 0 and draw_chance(5, 0) == 0
    # 2 回のうちに 1 回以上引く ＝ 1 − 96/100 × 95/99
    assert chance_within(4, 100, 2) == pytest.approx(1 - 96 / 100 * 95 / 99)
    assert chance_within(4, 100, 1) == pytest.approx(0.04)
    assert chance_within(4, 100, 0) == 0 and chance_within(0, 100, 5) == 0
    assert chance_within(4, 4, 1) == 1.0 and chance_within(3, 5, 5) == 1.0
    values = [chance_within(8, 120, n) for n in range(1, 19)]
    assert values == sorted(values) and 0 < values[0] < values[-1] < 1


# ---------------------------------------------------------------- 分け方（分解図）


def parts_text(layout) -> list[tuple[str, str]]:
    return [(p.type.value, "".join(kind_text(k) for k in p.kinds)) for p in layout.parts]


def test_regular_layout_of_a_two_shanten_hand():
    layout = regular_layout(counts("1345m2289p3467s15z"))
    assert layout.form is Form.REGULAR and layout.shanten == 2
    assert parts_text(layout) == [
        ("float", "1萬"), ("shuntsu", "3萬4萬5萬"), ("toitsu", "2筒2筒"), ("penchan", "8筒9筒"),
        ("ryanmen", "3索4索"), ("ryanmen", "6索7索"), ("float", "東"), ("float", "白"),
    ]
    assert layout.count(PartType.SHUNTSU, PartType.KOUTSU) == 1


def test_layout_names_the_taatsu_shapes():
    layout = regular_layout(counts("12m46m89m13p79p2s5s1z"))
    kinds = [p.type for p in layout.parts if p.is_taatsu]
    assert kinds.count(PartType.PENCHAN) == 2 and kinds.count(PartType.KANCHAN) >= 2
    layout = regular_layout(counts("111m456p789s13s44z"))
    assert layout.shanten == 0 and ("koutsu", "1萬1萬1萬") in parts_text(layout) and ("kanchan", "1索3索") in parts_text(layout)


def test_layout_parts_cover_the_hand_exactly():
    rnd = random.Random(3)
    for _ in range(300):
        hand = random_counts(rnd, rnd.choice([13, 14, 10, 7]))
        for layout in (regular_layout(hand), chiitoi_layout(hand), kokushi_layout(hand), best_layout(hand)):
            covered = [0] * 34
            for part in layout.parts:
                for kind in part.kinds:
                    covered[kind] += 1
            assert covered == hand


def test_formula_matches_library_on_random_hands():
    """分け方から数えた向聴数が、ライブラリ（4 面子 1 雀頭）と一致する"""
    rnd = random.Random(20261007)
    checked = 0
    for kinds in (range(34), range(34), range(9), range(18), range(9, 34), [*range(9), *range(27, 34)]):
        for size in (13, 14, 13, 10, 11, 7, 4, 1):
            for _ in range(60):
                hand = random_counts(rnd, size, kinds)
                mine = regular_layout(hand).shanten
                theirs = Shanten.calculate_shanten_for_regular_hand(hand)
                if max(hand) == 4:
                    assert mine <= theirs          # 同じ牌 4 枚持ちは、ライブラリが細かい補正をすることがある
                else:
                    assert mine == theirs, hand
                checked += 1
    assert checked == 6 * 8 * 60


def test_parts_know_which_tiles_complete_them():
    layout = regular_layout(counts("12m46m89m13p79p2s5s1z5m"))
    needs = {"".join(kind_text(k) for k in p.kinds): [kind_text(k) for k in p.completing_kinds] for p in layout.parts}
    assert needs["1萬2萬"] == ["3萬"] and needs["8萬9萬"] == ["7萬"]          # 辺張
    assert needs["1筒3筒"] == ["2筒"] and needs["7筒9筒"] == ["8筒"]          # 嵌張
    assert needs["4萬5萬6萬"] == [] and needs["東"] == []                     # 面子と孤立牌は、もう待たない
    layout = regular_layout(counts("1345m2289p3467s15z"))
    needs = {"".join(kind_text(k) for k in p.kinds): [kind_text(k) for k in p.completing_kinds] for p in layout.parts}
    assert needs["3索4索"] == ["2索", "5索"] and needs["6索7索"] == ["5索", "8索"]    # 両面
    assert needs["2筒2筒"] == ["2筒"]                                         # 対子は、同じ牌で刻子になる


def test_layout_assigns_real_tiles_and_keeps_red_fives_in_blocks():
    tiles = parse_tiles("406m123p55s789s1z5m")          # 456萬（赤 5 入り）＋浮いた 5萬
    layout = best_layout(counts34(tiles))
    groups = layout.assign(tiles)
    assert len(groups) == len(layout.parts)
    assert sorted(t for group in groups for t in group) == sorted(tiles)
    for part, group in zip(layout.parts, groups, strict=True):
        assert tuple(t // 4 for t in group) == part.kinds
    red = parse_tiles("0m")[0]
    by_type = {part.type: group for part, group in zip(layout.parts, groups, strict=True) if 4 in part.kinds}
    assert red in by_type[PartType.SHUNTSU] and red not in by_type[PartType.FLOAT]
    with pytest.raises(ValueError):
        layout.assign(tiles[:-1])


def test_layout_finds_the_block_that_uses_a_tile():
    layout = regular_layout(counts("1345m2289p3467s15z"))
    assert layout.part_with(counts("3m").index(1)).type is PartType.SHUNTSU
    assert layout.part_with(counts("2p").index(1)).type is PartType.TOITSU
    assert layout.part_with(counts("9p").index(1)).type is PartType.PENCHAN
    assert layout.part_with(counts("1m").index(1)) is None            # 孤立牌は、どのまとまりにも入っていない
    assert layout.part_with(counts("9s").index(1)) is None            # 持っていない牌


def test_layout_formula_text():
    assert regular_layout(counts("1345m2289p3467s15z")).formula == "8 − 2 × 面子 1 組 − 搭子 3 組 − 対子 1 組 ＝ 2"
    crowded = regular_layout(counts("12m46m89m13p79p2s5s1z5m"))
    assert crowded.formula == "8 − 2 × 面子 1 組 − 搭子 4 組 − 対子 0 組 ＋ 数えすぎ 1 組 ＝ 3"
    assert "4 組までしか数えない" in crowded.formula_note and "余った 1 組" in crowded.formula_note
    assert regular_layout(counts("1345m2289p3467s15z")).formula_note == ""
    assert best_layout(counts("1133m5577p2299s1z")).formula == "七対子まで：6 − 対子 6 組 ＝ 0"
    assert chiitoi_layout(counts("1111m2233p4455s66z")).formula == "七対子まで：6 − 対子 6 組 ＋ 種類の不足 1 ＝ 1"
    assert best_layout(counts("19m19p1s12345677z3m")).formula == "国士無双まで：13 − 么九牌 12 種類 − 対子 1 組 ＝ 0"
    assert regular_layout(counts("123m456p789s234s44z")).formula.endswith("＝ −1")


def test_formula_shanten():
    assert formula_shanten(4, 1, 0) == -1          # 4 面子 1 雀頭
    assert formula_shanten(3, 1, 1) == 0           # 3 面子＋搭子＋雀頭 ＝ 聴牌
    assert formula_shanten(3, 2, 0) == 0           # 3 面子＋対子 2 組（双碰）
    assert formula_shanten(4, 0, 0) == 0           # 4 面子＋単騎
    assert formula_shanten(0, 0, 0) == 8
    assert formula_shanten(1, 1, 5) == 2           # 面子候補は 4 組までしか数えない: 8 − 2 − 5 − 1 ＋ (1 ＋ 5 − 4) ＝ 2


def test_chiitoi_and_kokushi_layouts():
    layout = best_layout(counts("1133m5577p2299s1z"))
    assert layout.form is Form.CHIITOI and layout.shanten == 0
    assert layout.count(PartType.TOITSU) == 6 and layout.count(PartType.FLOAT) == 1

    # 14 枚。3萬 を切れば、9索 待ちの国士無双の聴牌
    layout = best_layout(counts("19m19p1s12345677z3m"))
    assert layout.form is Form.KOKUSHI and layout.shanten == 0
    assert layout.count(PartType.YAOCHU) == 11 and layout.count(PartType.TOITSU) == 1 and layout.count(PartType.FLOAT) == 1

    # 同じ牌 4 枚は、七対子では 1 組にしかならない
    layout = chiitoi_layout(counts("1111m2233p4455s66z"))
    assert layout.count(PartType.TOITSU) == 6 and layout.count(PartType.FLOAT) == 2 and layout.shanten == 1


def test_best_layout_prefers_regular_on_ties():
    assert best_layout(counts("223344m556677p8s")).form is Form.REGULAR


def test_layout_shanten_agrees_with_library_for_best_form():
    rnd = random.Random(11)
    for _ in range(400):
        hand = random_counts(rnd, 13)
        layout = best_layout(hand)
        if max(hand) < 4:
            assert layout.shanten == shanten_of(hand)


# ---------------------------------------------------------------- 打牌の助言


VALUE = (HAKU, HATSU, CHUN, EAST, SOUTH)


def test_advice_lists_all_equally_good_discards():
    hand = parse_tiles("1345m2289p3467s15z")
    advice = advise(counts34(hand), remaining_counts(hand), value_kinds=VALUE)
    assert names(o.kind for o in advice.best) == ["1萬", "東", "白"]
    assert kind_text(advice.pick.kind) == "東" and advice.shanten == 2      # 役牌の字牌 2 種は、種類の順で東が先
    assert advice.option(0).total == 16 and advice.option(33) is None


def test_loose_rank_order():
    west, east, one, two, five = 29, EAST, 0, 1, 4
    ranks = [loose_rank(k, value_kinds=VALUE) for k in (west, east, one, two, five)]
    assert ranks == sorted(ranks)                                   # 客風 → 役牌 → 1・9 → 2・8 → 3〜7
    assert loose_rank(west, dora_kinds=(west,)) > loose_rank(five)  # ドラは最後まで残す


def test_advice_keeps_dora_when_choices_are_equal():
    hand = parse_tiles("1345m2289p3467s15z")
    advice = advise(counts34(hand), remaining_counts(hand), value_kinds=VALUE, dora_kinds=(EAST,))
    assert kind_text(advice.pick.kind) == "白"


def test_dead_shapes_rank_below_live_ones():
    """有効牌が 1 枚も残っていない形は、向聴数が 1 つ大きいものとして並べる"""
    hand = parse_tiles("123m456p789s13s44z9m")        # 9萬 を切れば 2索 待ちの聴牌
    visible = parse_tiles("2222s")                      # …だが、2索 は 4 枚とも見えている
    remaining = remaining_counts(hand, visible)
    options = discard_options(counts34(hand), remaining)
    dead = next(o for o in options if kind_text(o.kind) == "9萬")
    assert (dead.shanten, dead.total, dead.reach) == (0, 0, 1)
    top = options[0]
    assert (top.shanten, top.reach) == (1, 1) and top.total > 0      # 有効牌が残っている 1 向聴のほうが先
    assert options.index(dead) > 0
    advice = advise(counts34(hand), remaining)
    assert advice.pick.total > 0 and dead not in advice.best
    # 2索 が 1 枚でも残っていれば、聴牌をとるのがいちばん良い
    remaining = remaining_counts(hand, parse_tiles("222s"))
    assert kind_text(advise(counts34(hand), remaining).pick.kind) == "9萬"


def test_tile_for_discard_keeps_the_red_five():
    hand = parse_tiles("123m456p789s05s44z1z")          # 赤 5索 と、赤でない 5索
    red, plain = parse_tiles("0s")[0], parse_tiles("5s")[0]
    assert tile_for_discard(hand, 22) == plain
    assert tile_for_discard(hand, 22, drawn=red) == plain             # ツモ牌が赤なら、手の中の赤でないほうを切る
    assert tile_for_discard(hand, 22, aka=False) == plain             # 赤ドラなしなら、どちらでもよい（並びの後ろ）
    only_red = parse_tiles("123m456p789s0s44z11z")
    assert tile_for_discard(only_red, 22) == red                      # 赤しか無ければ、赤を切るしかない
    pair = parse_tiles("123m456p789s2s44z111z")
    north = [t for t in pair if kind_text(t // 4) == "北"]
    assert tile_for_discard(pair, 30) == north[-1] and tile_for_discard(pair, 30, drawn=north[0]) == north[0]
    with pytest.raises(ValueError):
        tile_for_discard(hand, 0 + 8)                                 # 9萬 は持っていない


# ---------------------------------------------------------------- 待ち


def test_waits_with_and_without_riichi():
    hand = parse_tiles("123m456p789s23s44z")
    waits = waits_of(hand, remaining_counts(hand), seat_wind=SOUTH, round_wind=EAST)
    assert names(w.kind for w in waits) == ["1索", "4索"] and [w.remaining for w in waits] == [4, 4]
    for wait in waits:
        assert wait.plain.status is Status.WIN and wait.plain.consistent
        assert wait.plain.declaration == "ツモ。ツモ・ピンフ。400・700。"
        assert wait.riichi.declaration == "ツモ。リーチ・ツモ・ピンフ。700・1300。"


def test_waits_differ_by_tile():
    # 高目と安目: 4索 なら三色同順、1索 なら付かない
    hand = parse_tiles("234m234p23s789m44z")
    waits = {kind_text(w.kind): w for w in waits_of(hand, remaining_counts(hand), seat_wind=SOUTH, round_wind=EAST)}
    assert "サンショク" in waits["4索"].plain.declaration and "サンショク" not in waits["1索"].plain.declaration
    assert waits["4索"].plain.best.han > waits["1索"].plain.best.han


def test_waits_use_unseen_tiles_and_respect_visibility():
    hand = parse_tiles("123m456p789s46s44z")          # 5索 の嵌張待ち
    visible = parse_tiles("555s")                      # 赤でない 5索 は 3 枚とも見えている
    (wait,) = waits_of(hand, remaining_counts(hand, visible), visible=visible, seat_wind=SOUTH, round_wind=EAST)
    assert wait.remaining == 1 and wait.tile == 88     # 残っているのは赤 5索 だけ
    assert wait.plain.dora.aka == 1
    assert waits_of(hand, remaining_counts(hand, visible), visible=visible, seat_wind=SOUTH, round_wind=EAST, rules=Rules(aka_dora=False))[0].plain.dora.aka == 0

    all_seen = parse_tiles("0555s")
    (dead,) = waits_of(hand, remaining_counts(hand, all_seen), visible=all_seen, seat_wind=SOUTH, round_wind=EAST)
    assert dead.remaining == 0 and dead.tile is None and dead.plain is None and dead.riichi is None


def test_waits_after_riichi_and_for_non_tenpai_hands():
    hand = parse_tiles("123m456p789s23s44z")
    waits = waits_of(hand, remaining_counts(hand), seat_wind=SOUTH, round_wind=EAST, riichi_already=True)
    assert all("リーチ" in w.plain.declaration for w in waits)
    not_tenpai = parse_tiles("123m456p789s2s144z")
    assert waits_of(not_tenpai, remaining_counts(not_tenpai), seat_wind=SOUTH, round_wind=EAST) == ()


def test_wait_kinds_and_win_shape():
    assert names(wait_kinds(parse_tiles("123m456p789s23s44z"))) == ["1索", "4索"]
    assert names(wait_kinds(parse_tiles("1112345678999m"))) == [f"{n}萬" for n in range(1, 10)]
    assert len(wait_kinds(parse_tiles("19m19p19s1234567z"))) == 13
    assert wait_kinds(parse_tiles("123m456p789s2s144z")) == ()
    assert is_win_shape(parse_tiles("123m456p789s234s44z"))
    assert is_win_shape(parse_tiles("1133m5577p2299s11z"))
    assert not is_win_shape(parse_tiles("123m456p789s235s44z"))

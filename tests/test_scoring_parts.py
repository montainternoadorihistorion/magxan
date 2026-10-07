"""点数計算の部品ごとのテスト（分解・待ち・符・点数の式・ドラ・副露・状況の検査）"""
from __future__ import annotations

import pytest

from engine.melds import Meld, MeldError, MeldType, ankan, chi, kakan, minkan, pon
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import ContextError, WinContext
from engine.scoring.decompose import BlockType, Form, WaitType, interpretations
from engine.scoring.dora import count_dora, dora_kind_of
from engine.scoring.explain import explain
from engine.scoring.fu import calculate_fu, round_up_fu
from engine.scoring.judge import Level, level_of
from engine.scoring.layout import block_tiles, meld_of_block
from engine.scoring.notation import make_context, parse_meld
from engine.scoring.points import calculate_points, ceil100
from engine.scoring.random_hand import random_win
from engine.tiles import CHUN, EAST, HAKU, HATSU, NORTH, SOUTH, WEST, TileError, kind_of, parse_tiles

CHILD = {"seat_wind": SOUTH, "round_wind": EAST}


def readings(hand: str, win: str, **kw):
    ctx = make_context(hand, win, **{**CHILD, **kw})
    return ctx, interpretations(ctx.closed_tiles, ctx.melds, ctx.win_kind, is_tsumo=ctx.is_tsumo)


# ---------------------------------------------------------------- 分解と待ち


def test_two_decompositions_of_111222333():
    _, found = readings("111222333m78p99s", "9p")
    shapes = sorted(sorted(b.text() for b in r.blocks) for r in found)
    assert shapes == [
        sorted(["111萬", "222萬", "333萬", "789筒", "99索"]),
        sorted(["123萬", "123萬", "123萬", "789筒", "99索"]),
    ]
    assert all(r.wait is WaitType.RYANMEN for r in found)


def test_same_decomposition_two_waits():
    _, found = readings("4566m123p789s111z", "6m")
    assert sorted(r.wait.value for r in found) == ["ryanmen", "tanki"]
    assert len({r.blocks for r in found}) == 1          # 分解は同じで、和了牌の入り方だけが違う


def test_ryanpeikou_shape_is_also_seven_pairs():
    _, found = readings("223344m556677p8s", "8s")
    assert sorted(r.form.value for r in found) == ["chiitoi", "regular"]


def test_four_of_a_kind_is_not_two_pairs():
    tiles = parse_tiles("1111m2233p4455s66z")
    assert interpretations(tiles, (), kind_of(tiles[0]), is_tsumo=True) == []


def test_kokushi_waits():
    _, single = readings("119m19p19s123456z", "7z")
    assert [(r.form, r.wait) for r in single] == [(Form.KOKUSHI, WaitType.KOKUSHI)]
    _, thirteen = readings("19m19p19s1234567z", "1m")
    assert [(r.form, r.wait) for r in thirteen] == [(Form.KOKUSHI, WaitType.KOKUSHI_13)]


def test_not_winning_has_no_reading():
    _, found = readings("123m456p789s23s19p", "4s")
    assert found == []


@pytest.mark.parametrize(
    ("held", "win", "wait"),
    [
        ("12s", "3s", WaitType.PENCHAN),     # 12 で 3 を待つ
        ("89s", "7s", WaitType.PENCHAN),     # 89 で 7 を待つ
        ("13s", "2s", WaitType.KANCHAN),
        ("79s", "8s", WaitType.KANCHAN),
        ("23s", "1s", WaitType.RYANMEN),
        ("23s", "4s", WaitType.RYANMEN),
        ("78s", "9s", WaitType.RYANMEN),     # 78 は 6 と 9 の両面（9 で完成しても辺張ではない）
        ("78s", "6s", WaitType.RYANMEN),
    ],
)
def test_sequence_wait_types(held, win, wait):
    _, found = readings(f"123m456p789m{held}44z", win)
    assert [r.wait for r in found] == [wait]


def test_ron_completed_triplet_is_marked():
    _, ron = readings("123m456p789s22s44z", "2s")
    assert [r.wait for r in ron] == [WaitType.SHANPON]
    assert ron[0].win_block.ron_completed and not ron[0].win_block.is_concealed_set
    _, tsumo = readings("123m456p789s22s44z", "2s", is_tsumo=True)
    assert not tsumo[0].win_block.ron_completed and tsumo[0].win_block.is_concealed_set


def test_win_tile_never_goes_into_a_called_set():
    # 234萬 をチーしていて、手の中にも 23萬 ＋ 4萬。和了牌は門前の 234萬 に入る
    _, found = readings("23m55p", "4m", melds=["chi 234m", "pon 888p", "chi 567s"])
    assert len(found) == 1
    assert not found[0].win_block.open and found[0].win_block.type is BlockType.SHUNTSU


# ---------------------------------------------------------------- 符


def fu_of(hand: str, win: str, rules: Rules = DEFAULT_RULES, **kw):
    ctx, found = readings(hand, win, **kw)
    assert len(found) == 1, "このテストは読み方が 1 通りの手で書く"
    return calculate_fu(found[0], ctx, rules)


def lines(result) -> list[tuple[str, int]]:
    return [(line.label, line.fu) for line in result.lines]


def test_fu_lines_closed_ron_with_ankan():
    result = fu_of("123m456p78s22p", "9s", melds=["ankan 1111z"], riichi=True)
    assert lines(result) == [
        ("副底", 20),
        ("門前ロン", 10),
        ("待ち：両面", 0),
        ("雀頭", 0),
        ("順子", 0),
        ("順子", 0),
        ("順子", 0),
        ("暗槓（么九牌）", 32),
    ]
    assert (result.raw_total, result.fu) == (62, 70)


def test_fu_pinfu_tsumo_is_20():
    result = fu_of("123456m234p67s55s", "8s", is_tsumo=True)
    assert ("ツモ", 0) in lines(result)
    assert (result.raw_total, result.fu, result.is_pinfu_shape) == (20, 20, True)
    assert "平和のツモ" in result.note


def test_fu_pinfu_ron_is_30():
    result = fu_of("123456m234p67s55s", "8s")
    assert (result.raw_total, result.fu, result.is_pinfu_shape) == (30, 30, True)
    assert result.note == ""


def test_fu_open_pinfu_shape():
    ron = fu_of("234m55p34s", "5s", melds=["chi 678p", "chi 345m"])
    assert (ron.raw_total, ron.fu) == (20, 30)
    assert "30 符" in ron.note and not ron.is_pinfu_shape
    tsumo = fu_of("234m55p34s", "5s", melds=["chi 678p", "chi 345m"], is_tsumo=True)
    assert ("ツモ", 2) in lines(tsumo)
    assert (tsumo.raw_total, tsumo.fu, tsumo.note) == (22, 30, "")


def test_fu_seven_pairs_and_kokushi():
    ctx, found = readings("1133m5577p2299s1z", "1z")
    chiitoi = calculate_fu(found[0], ctx, DEFAULT_RULES)
    assert lines(chiitoi) == [("七対子", 25)] and chiitoi.fu == 25
    ctx, found = readings("119m19p19s123456z", "7z")
    assert calculate_fu(found[0], ctx, DEFAULT_RULES).fu == 0


@pytest.mark.parametrize(
    ("meld", "label", "fu"),
    [
        ("pon 888m", "明刻（中張牌）", 2),
        ("pon 999m", "明刻（么九牌）", 4),
        ("pon 777z", "明刻（么九牌）", 4),
        ("minkan 8888m", "明槓（中張牌）", 8),
        ("kakan 8888m", "明槓（中張牌）", 8),
        ("minkan 9999m", "明槓（么九牌）", 16),
        ("ankan 8888m", "暗槓（中張牌）", 16),
        ("ankan 9999m", "暗槓（么九牌）", 32),
    ],
)
def test_fu_of_called_sets(meld, label, fu):
    result = fu_of("123p456p23s55p", "4s", melds=[meld])
    assert (label, fu) in lines(result)


def test_fu_of_concealed_triplets():
    simple = fu_of("222m456p789s23s99p", "4s", riichi=True)
    assert ("暗刻（中張牌）", 4) in lines(simple)
    terminal = fu_of("111m456p789s23s99p", "4s", riichi=True)
    assert ("暗刻（么九牌）", 8) in lines(terminal)


def test_fu_of_ron_completed_triplet():
    result = fu_of("123m456p789s22s44z", "2s", riichi=True)
    line = next(line for line in result.lines if line.label == "明刻（中張牌）")
    assert line.fu == 2 and "ロンで完成" in line.detail
    assert ("待ち：双碰", 0) in lines(result)


@pytest.mark.parametrize(
    ("pair", "seat", "round_wind", "fu"),
    [
        ("55z", SOUTH, EAST, 2),   # 白
        ("66z", SOUTH, EAST, 2),   # 發
        ("77z", SOUTH, EAST, 2),   # 中
        ("22z", SOUTH, EAST, 2),   # 自風
        ("11z", SOUTH, EAST, 2),   # 場風
        ("33z", SOUTH, EAST, 0),   # 客風（役牌でない風牌）
        ("11z", EAST, EAST, 4),    # 連風牌
        ("22z", SOUTH, SOUTH, 4),
        ("99p", SOUTH, EAST, 0),
    ],
)
def test_pair_fu(pair, seat, round_wind, fu):
    result = fu_of(f"123m456p789s23s{pair}", "4s", riichi=True, seat_wind=seat, round_wind=round_wind)
    assert next(line for line in result.lines if line.label == "雀頭").fu == fu


def test_double_wind_pair_fu_follows_rule():
    kw = {"riichi": True, "seat_wind": EAST, "round_wind": EAST}
    assert fu_of("111m456p789s23s11z", "4s", **kw).fu == 50                                   # 30 ＋ 8 ＋ 4 ＝ 42
    assert fu_of("111m456p789s23s11z", "4s", Rules(double_wind_pair_fu=2), **kw).fu == 40     # 30 ＋ 8 ＋ 2 ＝ 40


@pytest.mark.parametrize(("raw", "rounded"), [(20, 20), (22, 30), (30, 30), (32, 40), (40, 40), (62, 70), (102, 110)])
def test_fu_rounds_up_to_tens(raw, rounded):
    assert round_up_fu(raw) == rounded


# ---------------------------------------------------------------- 点数


def points(han, fu, *, yakuman_times=0, dealer=False, tsumo=False, honba=0, kyotaku=0, rules=DEFAULT_RULES):
    return calculate_points(han, fu, yakuman_times=yakuman_times, is_dealer=dealer, is_tsumo=tsumo, honba=honba, kyotaku=kyotaku, rules=rules)


def test_formula_in_the_requested_style():
    assert points(3, 30).formula == "30 符 3 翻・子のロン：30 × 2⁵ ＝ 30 × 32 ＝ 960 → × 4 ＝ 3,840 → 切り上げて 3,900 点"
    assert points(2, 20, tsumo=True).formula == (
        "20 符 2 翻・子のツモ：20 × 2⁴ ＝ 20 × 16 ＝ 320 → 親が × 2 ＝ 640 → 切り上げて 700 点、子 2 人が × 1 ＝ 320 → 切り上げて 400 点ずつ"
    )
    assert points(2, 20, tsumo=True, dealer=True).formula == "20 符 2 翻・親のツモ：20 × 2⁴ ＝ 20 × 16 ＝ 320 → 子 3 人が × 2 ＝ 640 → 切り上げて 700 点ずつ"
    assert points(2, 25).formula == "25 符 2 翻・子のロン：25 × 2⁴ ＝ 25 × 16 ＝ 400 → × 4 ＝ 1,600 点"
    assert points(4, 40).formula == "40 符 4 翻・子のロン：40 × 2⁶ ＝ 40 × 64 ＝ 2,560 → 2,000 を超えるので満貫（基本点 2,000） → × 4 ＝ 8,000 点"
    assert points(6, 30, dealer=True).formula == "6 翻・親のロン：跳満（基本点 3,000） → × 6 ＝ 18,000 点"
    assert points(13, 0, yakuman_times=1, tsumo=True).formula == "役満・子のツモ：基本点 8,000 → 親が × 2 ＝ 16,000 点、子 2 人が × 1 ＝ 8,000 点ずつ"
    assert points(4, 30, rules=Rules(kiriage_mangan=True)).formula == "30 符 4 翻・子のロン：30 × 2⁶ ＝ 30 × 64 ＝ 1,920 → 切り上げ満貫（基本点 2,000） → × 4 ＝ 8,000 点"


def test_steps_explain_each_stage():
    result = points(3, 30, honba=2, kyotaku=1)
    assert result.steps == (
        "基本点 ＝ 符 × 2^(翻＋2) ＝ 30 × 2⁵ ＝ 30 × 32 ＝ 960",
        "子のロン：放銃者が 基本点 × 4 を払う。960 × 4 ＝ 3,840 → 切り上げて 3,900 点。",
        "2 本場：放銃者の支払いに 600 点を上乗せ。",
        "供託のリーチ棒 1 本（1,000 点）も和了者が受け取る。",
    )


@pytest.mark.parametrize(
    ("kw", "say"),
    [
        ({"han": 3, "fu": 30}, "3900"),
        ({"han": 3, "fu": 30, "honba": 1}, "3900は4200"),
        ({"han": 3, "fu": 30, "tsumo": True}, "1000・2000"),
        ({"han": 3, "fu": 30, "tsumo": True, "honba": 2}, "1000・2000は1200・2200"),
        ({"han": 3, "fu": 30, "tsumo": True, "dealer": True}, "2000オール"),
        ({"han": 3, "fu": 30, "tsumo": True, "dealer": True, "honba": 1}, "2000は2100オール"),
        ({"han": 5, "fu": 30}, "満貫、8000"),
        ({"han": 5, "fu": 30, "dealer": True}, "満貫、12000"),
        ({"han": 7, "fu": 30, "tsumo": True}, "跳満、3000・6000"),
        ({"han": 8, "fu": 30, "tsumo": True, "dealer": True}, "倍満、8000オール"),
        ({"han": 26, "fu": 0, "yakuman_times": 2}, "ダブル役満、64000"),
        ({"han": 39, "fu": 0, "yakuman_times": 3, "dealer": True}, "トリプル役満、144000"),
    ],
)
def test_declaration(kw, say):
    assert points(**kw).declaration == say


def test_payments_and_total():
    ron = points(3, 30, honba=1, kyotaku=2)
    assert [(p.payer, p.count, p.points, p.honba) for p in ron.payments] == [("放銃者", 1, 4200, 300)]
    assert ron.total == 4200 + 2000
    child_tsumo = points(3, 30, tsumo=True, honba=1)
    assert [(p.payer, p.count, p.points, p.honba) for p in child_tsumo.payments] == [("親", 1, 2100, 100), ("子", 2, 1100, 100)]
    assert child_tsumo.total == 2100 + 2 * 1100
    dealer_tsumo = points(3, 30, tsumo=True, dealer=True, honba=1)
    assert [(p.payer, p.count, p.points, p.honba) for p in dealer_tsumo.payments] == [("子", 3, 2100, 100)]
    assert dealer_tsumo.total == 3 * 2100


@pytest.mark.parametrize(
    ("han", "fu", "child_ron", "dealer_ron", "child_tsumo", "dealer_tsumo"),
    [
        # 点数表の代表的な行（子ロン、親ロン、子ツモ（子・親）、親ツモ）
        (1, 30, 1000, 1500, (300, 500), 500),
        (1, 40, 1300, 2000, (400, 700), 700),
        (1, 50, 1600, 2400, (400, 800), 800),
        (2, 20, 1300, 2000, (400, 700), 700),      # 20 符はツモ（平和）でしか出ないが、式としては同じ
        (2, 25, 1600, 2400, (400, 800), 800),
        (2, 30, 2000, 2900, (500, 1000), 1000),
        (2, 40, 2600, 3900, (700, 1300), 1300),
        (3, 30, 3900, 5800, (1000, 2000), 2000),
        (3, 40, 5200, 7700, (1300, 2600), 2600),
        (3, 50, 6400, 9600, (1600, 3200), 3200),
        (4, 20, 5200, 7700, (1300, 2600), 2600),
        (4, 25, 6400, 9600, (1600, 3200), 3200),
        (4, 30, 7700, 11600, (2000, 3900), 3900),
        (2, 110, 7100, 10600, (1800, 3600), 3600),
        (4, 40, 8000, 12000, (2000, 4000), 4000),
        (5, 30, 8000, 12000, (2000, 4000), 4000),
        (6, 30, 12000, 18000, (3000, 6000), 6000),
        (8, 30, 16000, 24000, (4000, 8000), 8000),
        (11, 30, 24000, 36000, (6000, 12000), 12000),
        (13, 30, 32000, 48000, (8000, 16000), 16000),
    ],
)
def test_score_table_rows(han, fu, child_ron, dealer_ron, child_tsumo, dealer_tsumo):
    assert points(han, fu).main == child_ron
    assert points(han, fu, dealer=True).main == dealer_ron
    result = points(han, fu, tsumo=True)
    assert (result.additional, result.main) == child_tsumo
    result = points(han, fu, tsumo=True, dealer=True)
    assert result.main == result.additional == dealer_tsumo


def test_levels():
    rules = DEFAULT_RULES
    assert level_of(4, 30, 0, rules) is Level.NONE            # 1920
    assert level_of(3, 60, 0, rules) is Level.NONE            # 1920
    assert level_of(3, 70, 0, rules) is Level.MANGAN          # 2240 → 満貫
    assert level_of(4, 40, 0, rules) is Level.MANGAN          # 2560 → 満貫
    assert level_of(4, 30, 0, Rules(kiriage_mangan=True)) is Level.MANGAN
    assert level_of(3, 60, 0, Rules(kiriage_mangan=True)) is Level.MANGAN
    assert level_of(3, 50, 0, Rules(kiriage_mangan=True)) is Level.NONE
    assert [level_of(h, 30, 0, rules) for h in (5, 6, 7, 8, 10, 11, 12, 13, 20)] == [
        Level.MANGAN, Level.HANEMAN, Level.HANEMAN, Level.BAIMAN, Level.BAIMAN,
        Level.SANBAIMAN, Level.SANBAIMAN, Level.KAZOE_YAKUMAN, Level.KAZOE_YAKUMAN,
    ]
    assert level_of(13, 30, 0, Rules(kazoe_yakuman=False)) is Level.SANBAIMAN
    assert level_of(13, 0, 1, rules) is Level.YAKUMAN


def test_ceil100():
    assert [ceil100(v) for v in (0, 1, 100, 101, 3840, 3900)] == [0, 100, 100, 200, 3900, 3900]


# ---------------------------------------------------------------- ドラ


def test_dora_is_the_next_tile():
    assert dora_kind_of(0) == 1 and dora_kind_of(8) == 0             # 1萬 → 2萬、9萬 → 1萬
    assert dora_kind_of(17) == 9 and dora_kind_of(26) == 18          # 9筒 → 1筒、9索 → 1索
    assert [dora_kind_of(k) for k in (EAST, SOUTH, WEST, NORTH)] == [SOUTH, WEST, NORTH, EAST]
    assert [dora_kind_of(k) for k in (HAKU, HATSU, CHUN)] == [HATSU, CHUN, HAKU]
    assert sorted(dora_kind_of(k) for k in range(34)) == list(range(34))   # 34 種類がちょうど 1 回ずつドラになる


def test_dora_lines():
    ctx = make_context("0m345567p234678s", "5m", dora="4m9p", ura="7s", riichi=True, **CHILD)
    result = count_dora(ctx, DEFAULT_RULES)
    assert [(kind_of(line.indicator), line.dora_kind, line.count) for line in result.dora_lines] == [(3, 4, 2), (17, 9, 0)]
    assert [(line.dora_kind, line.count) for line in result.ura_lines] == [(25, 1)]
    assert (result.dora, result.aka, result.ura, result.total) == (2, 1, 1, 4)
    assert result.aka_tiles == (16,)


def test_dora_counts_tiles_in_melds_and_kans():
    # ドラ表示牌が北なら、ドラは東。この手に東は無い
    ctx = make_context("123m456p23s99p", "4s", melds=["ankan 5555z"], dora="4z", riichi=True, **CHILD)
    assert count_dora(ctx, DEFAULT_RULES).dora == 0
    # ドラ表示牌が中なら、ドラは白。暗槓した白の 4 枚すべてがドラになる
    ctx = make_context("123m456p23s99p", "4s", melds=["ankan 5555z"], dora="7z", riichi=True, **CHILD)
    assert count_dora(ctx, DEFAULT_RULES).dora == 4
    assert explain(ctx).consistent


# ---------------------------------------------------------------- 分解図への牌の割り当て


def test_block_tiles_cover_the_hand_exactly():
    for seed in range(80):
        ctx = random_win(seed, "any")
        for candidate in explain(ctx).candidates:
            groups = block_tiles(candidate.interp, ctx)
            if candidate.interp.form is Form.KOKUSHI:
                assert groups == ()
                continue
            flat = [t for group in groups for t in group]
            assert sorted(flat) == sorted(ctx.all_tiles)
            for block, group in zip(candidate.interp.blocks, groups, strict=True):
                assert tuple(sorted(kind_of(t) for t in group)) == tuple(sorted(block.kinds))
            assert ctx.win_tile in groups[candidate.interp.win_index]
            for index, block in enumerate(candidate.interp.blocks):
                meld = meld_of_block(candidate.interp, ctx, index)
                assert (meld is not None) == (block.open or (block.type is BlockType.KANTSU))


# ---------------------------------------------------------------- 副露・状況・ルールの検査


def test_meld_kinds():
    assert chi(parse_tiles("234m")).type is MeldType.CHI and chi(parse_tiles("234m")).is_open
    assert pon(parse_tiles("777z")).is_open and not pon(parse_tiles("777z")).is_kan
    assert not ankan(parse_tiles("1111m")).is_open and ankan(parse_tiles("1111m")).is_kan
    assert minkan(parse_tiles("1111m")).is_open and kakan(parse_tiles("1111m")).is_open
    assert chi(parse_tiles("435m")).first_kind == 2


@pytest.mark.parametrize(
    ("kind", "tiles"),
    [
        (MeldType.CHI, "235m"),
        (MeldType.CHI, "891m"),
        (MeldType.CHI, "123z"),
        (MeldType.CHI, "89m1p"),
        (MeldType.CHI, "2345m"),
        (MeldType.PON, "223m"),
        (MeldType.PON, "2222m"),
        (MeldType.ANKAN, "222m"),
        (MeldType.MINKAN, "2223m"),
    ],
)
def test_invalid_melds_are_rejected(kind, tiles):
    with pytest.raises(MeldError):
        Meld(kind, tuple(parse_tiles(tiles)))


def test_meld_rejects_repeated_tile_id_and_bad_called_tile():
    with pytest.raises(MeldError):
        Meld(MeldType.PON, (0, 0, 1))
    with pytest.raises(MeldError):
        Meld(MeldType.PON, (0, 1, 2), called_tile=5)
    with pytest.raises(MeldError):
        Meld(MeldType.ANKAN, (0, 1, 2, 3), called_tile=0)


def test_parse_meld():
    assert parse_meld("pon 888m").type is MeldType.PON
    assert parse_meld("ankan 1111z").type is MeldType.ANKAN
    for text in ("888m", "pong 888m", "pon"):
        with pytest.raises(TileError):
            parse_meld(text)


def test_notation_rejects_fifth_copy_across_hand_melds_and_dora():
    with pytest.raises(TileError):
        make_context("23488m567p345s", "6s", melds=["pon 888m"])       # 8萬 が 5 枚
    with pytest.raises(TileError):
        make_context("123m456p789s23s11z", "4s", dora="1z1z1z")          # 東が 5 枚
    with pytest.raises(TileError):
        make_context("123m456p789s23s11z", "4s4s")                       # 和了牌は 1 枚


@pytest.mark.parametrize(
    "kw",
    [
        {"riichi": True, "melds": ["pon 888m"]},              # 鳴いた手でリーチ
        {"ippatsu": True},                                    # リーチなしの一発
        {"double_riichi": True},                              # riichi なしのダブル立直
        {"rinshan": True},                                    # ロンで嶺上開花
        {"chankan": True, "is_tsumo": True},                  # ツモで槍槓
        {"haitei": True},                                     # ロンで海底摸月
        {"houtei": True, "is_tsumo": True},                   # ツモで河底撈魚
        {"haitei": True, "rinshan": True, "is_tsumo": True},
        {"houtei": True, "chankan": True},
        {"tenhou": True, "is_tsumo": True, "seat_wind": SOUTH},    # 子の天和
        {"chiihou": True, "is_tsumo": True, "seat_wind": EAST},    # 親の地和
        {"tenhou": True, "seat_wind": EAST},                       # ロンの天和
        {"honba": -1},
        {"kyotaku": -1},
        {"seat_wind": 5},
        {"round_wind": HAKU},
    ],
)
def test_impossible_situations_are_rejected(kw):
    hand = "234m55p34s" if "melds" in kw else "123m456p789s23s44z"
    melds = kw.pop("melds", [])
    if melds:
        melds = [*melds, "chi 678p"]
    with pytest.raises(ContextError):
        make_context(hand, "5s" if melds else "4s", melds=melds, **kw)


def test_context_checks_tile_counts():
    tiles = parse_tiles("123m456p789s234s44z")
    with pytest.raises(ContextError):
        WinContext(closed_tiles=tuple(tiles[:13]), win_tile=tiles[0], is_tsumo=False)         # 13 枚しかない
    with pytest.raises(ContextError):
        WinContext(closed_tiles=tuple(tiles), win_tile=135, is_tsumo=False)                   # 和了牌が手に無い
    with pytest.raises(ContextError):
        WinContext(closed_tiles=(*tiles[:13], tiles[0]), win_tile=tiles[0], is_tsumo=False)   # 同じ牌IDが 2 回


def test_context_properties():
    ctx = make_context("123m456p78s22p", "9s", melds=["ankan 1111z"], riichi=True, seat_wind=WEST)
    assert ctx.is_menzen and not ctx.is_dealer and len(ctx.all_tiles) == 15
    assert make_context("234m55p34s", "5s", melds=["pon 888m", "chi 678p"], seat_wind=EAST).is_dealer
    assert not make_context("234m55p34s", "5s", melds=["pon 888m", "chi 678p"]).is_menzen


def test_rules_round_trip_and_validation():
    rules = Rules(aka_dora=False, kiriage_mangan=True, double_wind_pair_fu=2)
    assert Rules.from_dict(rules.to_dict()) == rules
    assert Rules.from_dict({"kuitan": False, "unknown": 1}) == Rules(kuitan=False)     # 知らない項目は無視
    with pytest.raises(ValueError):
        Rules(double_wind_pair_fu=3)
    assert DEFAULT_RULES == Rules()
    assert (DEFAULT_RULES.aka_dora, DEFAULT_RULES.kuitan, DEFAULT_RULES.kiriage_mangan) == (True, True, False)
    assert (DEFAULT_RULES.double_wind_pair_fu, DEFAULT_RULES.double_yakuman, DEFAULT_RULES.kazoe_yakuman) == (4, True, True)

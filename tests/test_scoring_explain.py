"""和了の解説データ（読み方の候補、役の成立条件、惜しい役、申告の言い方）のテスト"""
from __future__ import annotations

import pytest

from engine.rules import Rules
from engine.scoring.decompose import WaitType
from engine.scoring.explain import Status, explain
from engine.scoring.notation import make_context
from engine.scoring.yaku_eval import MAX_NEAR_MISSES
from engine.tiles import EAST, SOUTH

CHILD = {"seat_wind": SOUTH, "round_wind": EAST}


def run(hand: str, win: str, rules: Rules | None = None, **kw):
    ctx = make_context(hand, win, **{**CHILD, **kw})
    result = explain(ctx, rules) if rules else explain(ctx)
    assert result.consistent, result.mismatches
    return result


def keys(items) -> list[str]:
    return [item.key for item in items]


# ---------------------------------------------------------------- 読み方の候補と高点法


def test_candidates_are_sorted_best_first():
    result = run("111222333m78p99s", "9p", riichi=True)
    assert result.has_alternatives and len(result.candidates) == 2
    best, other = result.candidates
    assert result.best is best
    assert (best.han, best.fu.fu, best.points.main) == (6, 30, 12000)       # 順子で読む: 跳満
    assert (other.han, other.fu.fu, other.points.main) == (3, 50, 6400)     # 刻子で読む: 三暗刻
    assert keys(other.evaluation.yaku) == ["riichi", "sanankou"]


def test_same_han_higher_fu_wins():
    result = run("222333444m67p88s", "5p")
    best, other = result.candidates
    assert (best.han, best.fu.fu, best.points.main) == (3, 50, 6400)
    assert (other.han, other.fu.fu, other.points.main) == (3, 30, 3900)
    assert sorted(keys(other.evaluation.yaku)) == ["iipeikou", "pinfu", "tanyao"]


def test_wait_reading_is_part_of_the_choice():
    result = run("12345m456p789s44z", "3m", riichi=True)
    best, other = result.candidates
    assert best.interp.wait is WaitType.RYANMEN and keys(best.evaluation.yaku) == ["riichi", "pinfu"]
    assert other.interp.wait is WaitType.PENCHAN and keys(other.evaluation.yaku) == ["riichi"]
    assert (best.points.main, other.points.main) == (2000, 1300)


def test_seven_pairs_versus_two_double_runs():
    result = run("223344m556677p8s", "8s")
    best, other = result.candidates
    assert "ryanpeikou" in keys(best.evaluation.yaku) and best.points.main == 8000
    assert keys(other.evaluation.yaku) == ["chiitoitsu", "tanyao"] and (other.han, other.fu.fu, other.points.main) == (3, 25, 3200)


def test_single_reading_has_no_alternatives():
    result = run("123m456p789s13s44z", "2s", riichi=True)
    assert not result.has_alternatives and result.status is Status.WIN


def test_candidates_without_yaku_rank_last():
    # 刻子で読めば対々和・三暗刻。234萬 × 3 と読むと、鳴いているので一盃口が付かず、9筒と北があるので断么九でもなく、役がない
    result = run("222333444m4z", "4z", melds=["pon 999p"])
    assert result.status is Status.WIN
    assert [c.has_yaku for c in result.candidates] == [True, False]
    assert sorted(keys(result.best.evaluation.yaku)) == ["sanankou", "toitoi"]
    assert result.candidates[1].points is None and result.candidates[1].han == 0


# ---------------------------------------------------------------- 役の成立条件


def test_every_counted_yaku_shows_satisfied_conditions():
    result = run("223344m567p67s55p", "8s", riichi=True, is_tsumo=True)
    yaku = result.best.evaluation.yaku
    assert keys(yaku) == ["riichi", "menzen_tsumo", "pinfu", "tanyao", "iipeikou"]
    for item in yaku:
        assert item.ok and item.checks and all(check.ok and check.text for check in item.checks)
        assert item.name and item.reading and item.han >= 1
        if item.key in ("pinfu", "tanyao", "iipeikou"):       # 形で決まる役は、どの牌で満たしたかも示す
            assert all(check.detail for check in item.checks if "門前" not in check.text)
    pinfu = next(item for item in yaku if item.key == "pinfu")
    assert [check.text for check in pinfu.checks] == [
        "門前である（鳴いていない）",
        "4 つの面子がすべて順子",
        "雀頭が役牌でない",
        "待ちが両面待ち",
    ]
    assert "67索 で 5索・8索 を待つ両面待ち" in pinfu.checks[3].detail
    assert result.best.yaku_han == 5 and result.best.evaluation.han == 5


def test_kuisagari_is_noted():
    closed = run("234m234p23s789m44z", "4s")
    sanshoku = next(item for item in closed.best.evaluation.yaku if item.key == "sanshoku")
    assert (sanshoku.han, sanshoku.note) == (2, "")
    opened = run("234m23s789m44z", "4s", melds=["chi 234p"])
    sanshoku = next(item for item in opened.best.evaluation.yaku if item.key == "sanshoku")
    assert sanshoku.han == 1 and "喰い下がり" in sanshoku.note


def test_wind_yaku_names_show_the_wind():
    result = run("123m456p23s99p", "4s", melds=["pon 111z"], seat_wind=EAST)
    names = [item.name for item in result.best.evaluation.yaku]
    assert names == ["自風牌（東）", "場風牌（東）"]
    assert result.spoken_yaku == ("ダブトン",)
    assert run("123m456p23s99p", "4s", melds=["pon 222z"]).spoken_yaku == ("ナン",)
    assert run("123m456p23s99p", "4s", melds=["pon 111z"]).spoken_yaku == ("トン",)


def test_yakuman_sets_other_yaku_aside():
    result = run("222m444p666s77s88m", "7s", is_tsumo=True, riichi=True, dora="1m")
    best = result.best
    assert keys(best.evaluation.yaku) == ["suuankou"] and best.is_yakuman
    assert best.evaluation.yakuman_times == 1 and best.han == 13 and best.dora_han == 0
    assert "riichi" in keys(best.evaluation.ignored)
    assert best.near == ()


def test_stacked_yakuman():
    result = run("11z22z", "1z", melds=["pon 555z", "pon 666z", "pon 777z"])
    assert sorted(keys(result.best.evaluation.yaku)) == ["daisangen", "tsuuiisou"]
    assert (result.best.evaluation.yakuman_times, result.best.points.main) == (2, 64000)
    assert result.best.points.level_name == "ダブル役満"


# ---------------------------------------------------------------- 惜しい役


def near(result) -> dict[str, str]:
    return {item.key: item.hint for item in result.candidates[0].near}


def test_near_miss_pinfu_by_wait():
    hints = near(run("123m456p789s13s44z", "2s", riichi=True))
    assert hints["pinfu"] == "「待ちが両面待ち」を満たしていれば成立"


def test_near_miss_pinfu_by_pair_and_yakuhai_pair():
    hints = near(run("123m456p789s23s55z", "4s", riichi=True))
    assert hints["pinfu"] == "「雀頭が役牌でない」を満たしていれば成立"
    assert hints["yakuhai_haku"] == "雀頭の白があと 1 枚あって刻子なら成立"


def test_near_miss_one_block_away():
    hints = near(run("234m234p789m45s44z", "6s", riichi=True))
    assert hints["sanshoku"] == "234索 の順子があれば成立"
    hints = near(run("123456m23s789p44z", "4s", riichi=True))
    assert hints["ittsu"] == "789萬 の順子があれば成立"
    hints = near(run("222m444p66s77s456m", "6s", riichi=True))
    assert hints["toitoi"] == "456萬 が刻子なら成立"
    assert hints["sanankou"] == "ツモで和了していれば成立"


def test_near_miss_four_concealed_triplets_on_ron():
    result = run("222m444p666s77s88m", "7s", riichi=True)
    assert sorted(keys(result.best.evaluation.yaku)) == ["riichi", "sanankou", "tanyao", "toitoi"]
    assert near(result)["suuankou"] == "ツモで和了していれば成立（役満）"


def test_near_miss_closed_only_yaku_when_open():
    result = run("22334m99p", "4m", melds=["chi 567s", "pon 111p"])
    assert result.status is Status.NO_YAKU
    assert near(result) == {"iipeikou": "門前（鳴いていない手）なら成立"}
    assert len(result.advice) == 2 and "鳴いても成立する役" in result.advice[1]


def test_near_miss_kuitan_rule():
    result = run("234m55p34s", "5s", Rules(kuitan=False), melds=["pon 888m", "chi 678p"])
    assert result.status is Status.NO_YAKU
    assert near(result)["tanyao"] == "喰いタンありのルールなら成立"


def test_near_misses_are_capped_and_never_already_achieved():
    for hand, win, kw in [
        ("123m456p789s13s44z", "2s", {"riichi": True}),
        ("123m789p12s99m111z", "3s", {}),
        ("234m234p23s789m44z", "4s", {}),
    ]:
        result = run(hand, win, **kw)
        for candidate in result.candidates:
            achieved = set(keys(candidate.evaluation.yaku))
            assert len(candidate.near) <= MAX_NEAR_MISSES
            assert not achieved & set(keys(candidate.near))
            assert all(not item.ok and item.hint for item in candidate.near)


# ---------------------------------------------------------------- 申告の言い方と助言


@pytest.mark.parametrize(
    ("hand", "win", "kw", "say"),
    [
        ("123m456p789s23s44z", "4s", {"riichi": True}, "ロン。リーチ・ピンフ。2000。"),
        ("123456m234p67s55s", "8s", {"is_tsumo": True}, "ツモ。ツモ・ピンフ。400・700。"),
        ("123456m234p67s55s", "8s", {"is_tsumo": True, "seat_wind": EAST}, "ツモ。ツモ・ピンフ。700オール。"),
        ("234567m234p67s55s", "8s", {"riichi": True, "honba": 2}, "ロン。リーチ・ピンフ・タンヤオ。3900は4500。"),
        ("0m345567p234678s", "5m", {"riichi": True, "dora": "4m", "ura": "7s"}, "ロン。リーチ・タンヤオ・ドラ 2・赤 1・裏 1。跳満、12000。"),
        ("119m19p19s123456z", "7z", {}, "ロン。コクシムソウ。役満、32000。"),
        # 役が 1 つだけでドラも無い手は「〜のみ」と言う
        ("123m456p789s13s44z", "2s", {"riichi": True}, "ロン。リーチのみ。1300。"),
        ("123m456p789s13s44z", "2s", {"is_tsumo": True}, "ツモ。ツモのみ。300・500。"),
        ("123m456p789s13s44z", "2s", {"riichi": True, "dora": "3z"}, "ロン。リーチ・ドラ 2。5200。"),     # 3 翻 40 符
    ],
)
def test_declaration_sentence(hand, win, kw, say):
    assert run(hand, win, **kw).declaration == say


def test_no_yaku_advice_for_closed_hand():
    result = run("123m456p789s23s11z", "4s")
    assert result.status is Status.NO_YAKU and result.best is None
    assert result.declaration == "" and result.spoken_yaku == ()
    assert "リーチを宣言していれば" in result.advice[0]
    assert "門前清自摸和" in result.advice[1]


def test_no_advice_when_winning_or_not_a_shape():
    assert run("123m456p789s23s44z", "4s", riichi=True).advice == ()
    assert run("123m456p789s23s19p", "4s").advice == ()


# ---------------------------------------------------------------- ルールによって変わるところ


def test_rule_notes_point_out_house_rule_differences():
    assert run("123m456p789s23s44z", "4s", riichi=True).rule_notes == ()

    kuitan = run("234m55p34s", "5s", melds=["pon 888m", "chi 678p"])
    assert len(kuitan.rule_notes) == 1 and "喰いタン）を認めないルールもある" in kuitan.rule_notes[0]
    no_kuitan = run("234m55p34s", "5s", Rules(kuitan=False), melds=["pon 888m", "chi 678p"])
    assert "喰いタンありのルールなら" in no_kuitan.rule_notes[0]

    near_mangan = run("223344m567p67s55p", "8s", riichi=True)
    assert "切り上げ満貫）もある" in near_mangan.rule_notes[0] and "7700 → 8000" in near_mangan.rule_notes[0]
    kiriage = run("223344m567p67s55p", "8s", Rules(kiriage_mangan=True), riichi=True)
    assert "切り上げ満貫あり」のルール" in kiriage.rule_notes[0] and "8000 → 7700" in kiriage.rule_notes[0]

    pair = run("111m456p789s23s11z", "4s", riichi=True, seat_wind=EAST)
    assert "連風牌" in pair.rule_notes[0] and "いまの設定は 4 符" in pair.rule_notes[0]
    assert "いまの設定は 2 符" in run("111m456p789s23s11z", "4s", Rules(double_wind_pair_fu=2), riichi=True, seat_wind=EAST).rule_notes[0]
    assert run("111m456p789s23s11z", "4s", riichi=True, seat_wind=EAST, round_wind=SOUTH).rule_notes == ()   # 自風だけなら流派差なし

    double = run("111m333p555s777s2z", "2z")
    assert "四暗刻単騎をダブル役満にするかどうか" in double.rule_notes[0] and "ダブル役満（役満 2 つぶん）として" in double.rule_notes[0]
    single = run("111m333p555s777s2z", "2z", Rules(double_yakuman=False))
    assert "ふつうの役満（1 つぶん）として" in single.rule_notes[0]

    kazoe = run("1234567892355m", "4m", riichi=True, is_tsumo=True, ippatsu=True, haitei=True)
    assert "いまの設定では数え役満" in kazoe.rule_notes[0]
    assert "いまの設定では三倍満" in run(
        "1234567892355m", "4m", Rules(kazoe_yakuman=False), riichi=True, is_tsumo=True, ippatsu=True, haitei=True
    ).rule_notes[0]

    aka = run("0m345567p234678s", "5m", riichi=True)
    assert any("赤ドラ（赤い 5）を使わないルールもある" in note for note in aka.rule_notes)
    assert run("123m456p789s23s19p", "4s").rule_notes == ()        # 和了の形でなければ何も出さない

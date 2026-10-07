"""牌効率コーチ（engine/coach.py）のテスト"""
from __future__ import annotations

import pytest
from coach_helpers import TENPAI_PLUS_ONE, TWO_SHANTEN, judge, names, position

from engine import practice
from engine.analysis.blocks import PartType
from engine.analysis.ukeire import chance_within, discard_options, remaining_counts
from engine.coach import Grade, Position, analyze, judge_discard
from engine.luck import LuckSettings
from engine.rules import Rules
from engine.scoring.decompose import Form
from engine.scoring.explain import Status
from engine.scoring.texts import kind_text
from engine.tiles import CHUN, EAST, HAKU, HATSU, SOUTH, counts34, is_red, kind_of, parse_tiles

# ---------------------------------------------------------------- 局面


def test_position_checks_its_input():
    pos = position(TWO_SHANTEN, visible="9s9s", dora="4z")
    assert pos.unseen == 136 - 14 - 3
    assert pos.dora_kinds == (EAST,)                       # 表示牌が北 → ドラは東
    assert pos.value_kinds == (HAKU, HATSU, CHUN, SOUTH, EAST)
    with pytest.raises(ValueError, match="14 枚"):
        Position(tiles=tuple(parse_tiles("123m456p789s23s44z")))
    with pytest.raises(ValueError, match="ツモ牌"):
        Position(tiles=tuple(parse_tiles(TWO_SHANTEN)), drawn=135)
    with pytest.raises(ValueError, match="14 枚"):                                  # 鳴いた手（11 枚）は、まだ扱わない
        Position(tiles=parse_tiles("123m456p78s22p3s"))


# ---------------------------------------------------------------- 調べる


def test_analysis_of_a_two_shanten_hand():
    pos = position(TWO_SHANTEN)
    result = analyze(pos)
    assert result.shanten == 2 and not result.can_win and result.info.regular == 2
    assert names(result.best) == ["1萬", "東", "白"]                          # 受け入れが同じ候補は、すべて「同じ速さ」
    assert kind_text(result.pick.kind) == "東" and result.pick.is_pick        # その中では、字牌から先に切る
    assert [c.is_pick for c in result.candidates].count(True) == 1
    assert (result.pick.kinds, result.pick.total, result.pick.shanten) == (4, 16, 2)
    assert all(c.grade is Grade.BEST and c.shanten_loss == 0 and c.tiles_loss == 0 for c in result.best)
    rest = [c for c in result.candidates if not c.is_best]
    assert all(c.grade is Grade.FARTHER and c.shanten == 3 and c.shanten_loss == 1 for c in rest)   # ほかは全部、面子候補をくずす
    assert len(result.candidates) == 13 and result.candidate(counts34(parse_tiles("2p")).index(1)).held == 2
    assert result.candidate(33) is None

    # 次のツモで有効牌を引く確率 ＝ 16 ÷ 122
    assert result.next_chance == pytest.approx(16 / 122)
    assert result.within_chance == pytest.approx(chance_within(16, 122, 10))
    assert result.waits == ()                                                 # 聴牌しない打牌には、待ちは無い

    # 分け方は手牌をちょうど覆い、式の向聴数がライブラリの値と同じ
    assert sorted(t for group in result.layout_tiles for t in group) == sorted(pos.tiles)
    assert result.layout_matches and result.layout.formula == "8 − 2 × 面子 1 組 − 搭子 3 組 − 対子 1 組 ＝ 2"


def test_candidates_follow_the_ranking_of_discard_options():
    pos = position("123m456p789s2s1445z")
    result = analyze(pos)
    options = discard_options(counts34(pos.tiles), remaining_counts(pos.tiles, pos.visible))
    assert [c.option for c in result.candidates] == options
    grades = {kind_text(c.kind): c.grade for c in result.candidates}
    assert grades["東"] is Grade.BEST and grades["白"] is Grade.BEST
    assert grades["2索"] is Grade.NARROWER and result.candidate(19).tiles_loss == 12
    assert grades["北"] is Grade.FARTHER


def test_same_position_is_analyzed_once():
    assert analyze(position(TWO_SHANTEN)) is analyze(position(TWO_SHANTEN))
    assert analyze(position(TWO_SHANTEN, draws_left=3)) is not analyze(position(TWO_SHANTEN))


def test_no_draws_left_means_no_chance():
    result = analyze(position(TWO_SHANTEN, draws_left=0))
    assert result.next_chance == 0 and result.within_chance == 0 and result.pick.total == 16


def test_dora_is_kept_when_choices_are_equal():
    result = analyze(position(TWO_SHANTEN, dora="4z"))        # 東がドラ
    assert kind_text(result.pick.kind) == "白"
    assert result.candidate(EAST).dora == 1 and result.candidate(HAKU).dora == 0
    assert names(result.best) == ["1萬", "東", "白"]            # 速さは同じ


def test_lone_red_five_is_kept_when_choices_are_equal():
    """赤 5 を 1 枚だけ持っているとき、同じ速さの牌がほかにあれば、そちらをおすすめにする"""
    pos = position("0m5p5s11122233344z")                     # 5萬（赤）・5筒・5索 のどれを切っても同じ速さ
    result = analyze(pos)
    assert names(result.best) == ["5萬", "5筒", "5索"] and kind_text(result.pick.kind) == "5筒"
    assert (result.candidate(4).dora, result.pick.dora) == (1, 0)
    assert not judge(pos, "5p").dora_wasted                   # おすすめを切って「ドラを切った」と言われることはない
    careless = judge(pos, "0m")
    assert careless.is_best and careless.dora_wasted
    assert careless.reasons == ("赤5萬はドラ。受け入れの枚数が同じなら、ドラでない 5筒を先に切ると打点を残せる。",)
    # 七対子の聴牌：赤5萬 を切って 7索 を待つより、7索 を切って 5萬 を待つ（どちらも残り 3 枚）
    tenpai = position("44077m056688p557s")
    result = analyze(tenpai)
    assert kind_text(result.pick.kind) == "7索" and [c.total for c in result.best] == [3, 3]
    assert "待ちの枚数が同じなら、ドラでない 7索を先に切ると" in judge(tenpai, "0m").reasons[0]
    # 赤ドラなしのルールでは、ただの 5 なので、種類の順で 5萬 から
    assert kind_text(analyze(position("0m5p5s11122233344z", rules=Rules(aka_dora=False))).pick.kind) == "5萬"


def test_red_five_is_not_the_tile_to_cut():
    pos = position("123m456p789s4056s4z")                    # 456索 ＋ 5索（片方が赤）＋ 北。5索 を切れば北単騎
    result = analyze(pos)
    assert kind_text(result.pick.kind) == "5索" and result.pick.shanten == 0
    assert not is_red(result.pick.tile) and result.pick.dora == 0 and result.pick.held == 2
    # 赤ドラなしのルールでは、どちらを切ってもよい
    plain = analyze(position("123m456p789s4056s4z", rules=Rules(aka_dora=False)))
    assert plain.pick.dora == 0


def test_dead_tenpai_is_not_recommended():
    pos = position("123m456p789s13s44z9m", visible="2222s")
    result = analyze(pos)
    dead = result.candidate(8)                               # 9萬 を切ると、2索 待ち（残り 0 枚）の聴牌
    assert (dead.shanten, dead.total, dead.grade) == (0, 0, Grade.DEAD)
    assert result.pick.shanten == 1 and result.pick.total > 0 and result.shanten == 0
    assert result.stalled                                    # 形の上では聴牌にとれるが、おすすめは 1 向聴にとる切り方
    assert result.waits == ()
    assert not analyze(position(TENPAI_PLUS_ONE)).stalled and not analyze(position(TWO_SHANTEN)).stalled


def test_waits_come_with_scores_when_the_pick_reaches_tenpai():
    result = analyze(position(TENPAI_PLUS_ONE, dora="9p"))
    assert kind_text(result.pick.kind) == "9萬" and result.shanten == 0
    assert [(kind_text(w.kind), w.remaining) for w in result.waits] == [("1索", 4), ("4索", 4)]
    for wait in result.waits:
        assert wait.plain.status is Status.WIN and wait.plain.consistent and wait.riichi.consistent
        assert wait.plain.declaration == "ツモ。ツモ・ピンフ。400・700。"
        assert wait.riichi.declaration == "ツモ。リーチ・ツモ・ピンフ。700・1300。"
    assert result.next_chance == pytest.approx(8 / (136 - 14 - 1))


def test_complete_hand_can_win():
    result = analyze(position("123m456p789s234s44z"))
    assert result.can_win and result.shanten == -1


# ---------------------------------------------------------------- 切った牌の評価


def test_verdict_best():
    pos = position(TWO_SHANTEN)
    verdict = judge(pos, "1z")
    assert verdict.is_best and verdict.grade is Grade.BEST and verdict.reasons == ()
    assert verdict.text == "東切りは、いちばん受け入れが広い（4 種 16 枚）。"
    equal = judge(pos, "1m")
    assert equal.is_best and equal.text == "1萬切りは、おすすめの東切りと同じ受け入れ（4 種 16 枚）。"
    assert (equal.shanten_loss, equal.tiles_loss, equal.gained, equal.lost, equal.broken) == (0, 0, (), (), None)
    # おすすめが数字の牌のときは、前に空白を入れて読みやすくする
    pos = position("123m456p78s05s44z19m")
    assert judge(pos, "9m").text == "9萬切りは、おすすめの 1萬切りと同じ受け入れ（4 種 12 枚）。"


def test_verdict_says_same_acceptance_only_when_the_tiles_are_the_same():
    """枚数は同じでも、有効牌の中身が違うときは「同じ受け入れ」と言わない"""
    pos = position("066667m56p4577s33z", visible="4s", dora="5m")
    result = analyze(pos)
    assert [(kind_text(c.kind), c.kinds, c.total) for c in result.best] == [("4索", 5, 16), ("7索", 4, 16), ("西", 4, 16)]
    assert kind_text(result.pick.kind) == "西"
    assert judge(pos, "4s").text == "4索切りの受け入れは 5 種 16 枚。おすすめの西切り（4 種 16 枚）と、枚数が同じ。"
    assert judge(pos, "7s").text == "7索切りは、おすすめの西切りと同じ受け入れ（4 種 16 枚）。"
    assert judge(pos, "4s").label == judge(pos, "7s").label == "おすすめと同じ速さ"


def test_verdict_narrower_explains_which_tiles_are_lost():
    pos = position("123m456p789s2s1445z")
    verdict = judge(pos, "2s")
    assert verdict.grade is Grade.NARROWER and not verdict.is_best
    assert (verdict.shanten_loss, verdict.tiles_loss) == (0, 12)
    assert verdict.text == "2索切りの受け入れは 3 種 8 枚。東切りなら 6 種 20 枚で、12 枚多い。"
    assert verdict.reasons == (
        "東切りなら、1索（4 枚）・2索（3 枚）・3索（4 枚）・4索（4 枚）も有効牌になる。",
        "2索切りにだけある有効牌は、東（3 枚）。",
    )
    # 差し引き：増える 15 枚 − 減る 3 枚 ＝ 12 枚
    assert sum(n for _, n in verdict.gained) - sum(n for _, n in verdict.lost) == verdict.tiles_loss


def test_verdict_farther_names_the_broken_block():
    pos = position(TWO_SHANTEN)
    verdict = judge(pos, "3s")
    assert verdict.grade is Grade.FARTHER and verdict.shanten_loss == 1 and verdict.tiles_loss == 0
    assert verdict.text == "3索を切ると、2 向聴から 3 向聴に遠ざかる。東切りなら 2 向聴のまま（受け入れ 4 種 16 枚）。"
    assert verdict.broken.type is PartType.RYANMEN
    assert verdict.reasons == ("3索は「34索」（両面）に使っていた牌。切ると、そのまとまりがくずれる。",)
    assert "「345萬」（順子）" in judge(pos, "4m").reasons[0]
    assert "「22筒」（対子）" in judge(pos, "2p").reasons[0]
    # 同じ牌が順子と対子の両方に入っているとき：1 枚切っても順子は残せるので、くずれるのは対子のほう
    pos = position("4m1205567p1567s23z")
    assert judge(pos, "5p").reasons == ("5筒は「55筒」（対子）に使っていた牌。切ると、そのまとまりがくずれる。",)
    assert judge(pos, "6p").reasons == ("6筒は「567筒」（順子）に使っていた牌。切ると、そのまとまりがくずれる。",)


def test_verdict_farther_in_seven_pairs_explains_the_kind_shortage():
    pos = position("4488m1113355p334z")                       # 対子 6 組＋ 1筒 の 3 枚目＋北
    verdict = judge(pos, "4z")
    assert verdict.grade is Grade.FARTHER and verdict.broken is None
    assert verdict.text == "北を切ると、聴牌をくずして 1 向聴に戻る。1筒切りなら聴牌（待ち 1 種 3 枚）。"
    assert verdict.reasons == (
        "七対子には、種類の違う対子が 7 組いる。同じ牌の 3 枚目・4 枚目は対子に数えられないので、北を切ると、対子にできる牌の種類が足りなくなる。",
    )
    assert judge(pos, "1p").is_best


def test_verdict_for_breaking_tenpai():
    pos = position(TENPAI_PLUS_ONE)
    verdict = judge(pos, "2s")
    assert verdict.grade is Grade.FARTHER
    assert verdict.text == "2索を切ると、聴牌をくずして 1 向聴に戻る。9萬切りなら聴牌（待ち 2 種 8 枚）。"
    assert not verdict.missed_riichi


def test_verdict_at_tenpai_with_and_without_riichi():
    pos = position(TENPAI_PLUS_ONE)
    quiet = judge(pos, "9m")
    assert quiet.is_best and quiet.text == "9萬切りで聴牌。待ちは 2 種 8 枚で、いちばん広い。"
    assert quiet.missed_riichi and quiet.reasons == ("この打牌で聴牌。門前なので、リーチを宣言して切ることもできた（リーチは 1 翻の役）。",)
    declared = judge(pos, "9m", riichi=True)
    assert declared.riichi and declared.text == "9萬を切ってリーチ。待ちは 2 種 8 枚で、いちばん広い。"
    assert not declared.missed_riichi and declared.reasons == ()
    # リーチできない状況（最後のツモなど）では、リーチのことは言わない
    last = judge(position(TENPAI_PLUS_ONE, can_riichi=False), "9m")
    assert not last.missed_riichi and last.reasons == ()


def test_verdict_dead():
    pos = position("123m456p789s13s44z9m", visible="2222s")
    verdict = judge(pos, "9m")
    assert verdict.grade is Grade.DEAD and not verdict.is_best
    assert verdict.text == (
        "9萬を切ると聴牌の形だが、有効牌がすべて見えていて残り 0 枚（何を引いても進まない）。"
        "1索切りなら 1 向聴で、受け入れは 8 種 27 枚。"
    )
    assert not verdict.missed_riichi and verdict.reasons == ()        # 残り 0 枚の待ちで、リーチは勧めない
    assert judge(pos, "1s").is_best


def test_verdict_passed_win():
    pos = position("123m456p789s234s44z")
    verdict = judge(pos, "2s")
    assert verdict.grade is Grade.PASSED and not verdict.is_best
    assert verdict.text == "あがりの形だったが、あがらずに 2索を切った。"
    assert verdict.reasons == ("あがるときは、牌を切らずに「ツモ」を押す。",)
    assert judge(pos, "4z").text == "あがりの形だったが、あがらずに北を切った。"


def test_verdict_warns_about_wasting_a_red_five():
    pos = position("123m456p789s4056s4z")
    careless = judge(pos, "0s")
    assert careless.is_best and careless.red_wasted and not careless.dora_wasted
    assert careless.text == "赤5索切りで聴牌。待ちは 1 種 3 枚で、いちばん広い。"
    assert "赤い 5 はドラ（1 枚で 1 翻）。赤でない 5索を切れば、受け入れは同じままドラを残せた。" in careless.reasons
    careful = judge(pos, "5s")
    assert careful.is_best and not careful.red_wasted and careful.text == "5索切りで聴牌。待ちは 1 種 3 枚で、いちばん広い。"
    # 赤しか持っていなければ、切るしかないので注意しない
    assert not judge(position("123m456p789s406s14z"), "0s").red_wasted
    # 赤ドラなしのルールなら、ただの 5
    assert not judge(position("123m456p789s4056s4z", rules=Rules(aka_dora=False)), "0s").red_wasted


def test_verdict_warns_about_cutting_dora_among_equals():
    pos = position(TWO_SHANTEN, dora="4z")                    # 東がドラ。東・白・1萬 は同じ受け入れ
    verdict = judge(pos, "1z")
    assert verdict.is_best and verdict.dora_wasted
    assert verdict.text == "東切りは、おすすめの白切りと同じ受け入れ（4 種 16 枚）。"
    assert verdict.reasons == ("東はドラ。受け入れの枚数が同じなら、ドラでない白を先に切ると打点を残せる。",)
    assert not judge(pos, "5z").dora_wasted and not judge(pos, "1m").dora_wasted


def test_last_discard_only_cares_about_ending_in_tenpai():
    # 聴牌にとれない手：このあとツモが無いので、どれを切っても同じ
    hopeless = position(TWO_SHANTEN, draws_left=0, can_riichi=False)
    result = analyze(hopeless)
    assert result.last_discard and not result.can_end_tenpai
    assert all(c.is_best and c.shanten_loss == 0 and c.tiles_loss == 0 for c in result.candidates)
    verdict = judge(hopeless, "3s")                  # ふだんなら「遠ざかる」打牌
    assert verdict.is_best and verdict.label == "どれを切っても同じ" and verdict.reasons == ()
    assert verdict.text == "最後の打牌。聴牌にとれない手なので、どれを切っても結果は同じ（ノーテンで流局）。"

    # 聴牌にとれる手：聴牌で終われる牌だけが正解
    pos = position(TENPAI_PLUS_ONE, draws_left=0, can_riichi=False)
    result = analyze(pos)
    assert result.can_end_tenpai and kind_text(result.pick.kind) == "9萬" and names(result.best) == ["9萬"]
    keep = judge(pos, "9m")
    assert keep.is_best and keep.label == "聴牌で流局" and keep.text == "最後の打牌。9萬切りで、聴牌したまま流局。"
    assert keep.reasons == ("対局では、流局したときに聴牌していると、聴牌していない人から点をもらえる（ノーテン罰符）。",)
    assert not keep.missed_riichi
    broke = judge(pos, "2s")
    assert broke.grade is Grade.FARTHER and broke.label == "聴牌をくずした" and broke.broken.type is PartType.RYANMEN
    assert broke.text == "最後の打牌。2索を切ると、聴牌をくずして流局になる。9萬切りなら、聴牌したまま終われた。"


def test_last_discard_keeps_even_a_dead_tenpai_and_ignores_dora():
    # 待ち牌がすべて見えていても、流局のときは「聴牌」に数える（形式聴牌）
    dead = position("123m456p789s13s44z9m", visible="2222s", draws_left=0, can_riichi=False)
    result = analyze(dead)
    assert kind_text(result.pick.kind) == "9萬" and result.pick.total == 0 and result.can_end_tenpai
    assert judge(dead, "9m").is_best and not judge(dead, "1s").is_best
    # ふだんは「赤 5 を残す」「ドラを残す」と注意するが、最後の打牌では言わない
    red = position("123m456p789s4056s4z", draws_left=0, can_riichi=False)
    assert not judge(red, "0s").red_wasted and judge(red, "0s").is_best
    dora = position(TWO_SHANTEN, dora="4z", draws_left=0, can_riichi=False)
    assert not judge(dora, "1z").dora_wasted


def test_judging_a_tile_that_is_not_in_the_hand_fails():
    pos = position(TWO_SHANTEN)
    with pytest.raises(ValueError, match="手牌にない牌"):
        judge_discard(analyze(pos), next(t for t in range(136) if t not in pos.tiles))


# ---------------------------------------------------------------- いろいろな局面での一貫性


def test_coach_is_consistent_on_real_hands():
    """実際の局面を数多く調べて、候補の表と評価が食い違わないことを確かめる"""
    checked = 0
    grades_seen: set[Grade] = set()
    for seed in range(5, 14):
        state = practice.start(practice.PracticeConfig(seed=seed, luck=LuckSettings(50, 25)))
        while not state.finished:
            pos = practice.position_of(state)
            result = analyze(pos)
            pick = result.pick
            assert result.candidates[0].is_best and pick.is_best and pick in result.best
            assert result.stalled == (pick.shanten > result.shanten)
            if not result.last_discard:
                # おすすめは、同じ速さの候補の中で、手放すドラがいちばん少ない。だから、おすすめを切って「ドラを切った」と言われることはない
                assert pick.dora == min(c.dora for c in result.best)
                assert not judge_discard(result, pick.tile).dora_wasted
            if not result.can_win:               # あがりの形（−1）からは、何を切っても聴牌（0）になる
                assert result.shanten == min(c.shanten for c in result.candidates)
            assert sorted(t for group in result.layout_tiles for t in group) == sorted(pos.tiles)
            for candidate in result.candidates:
                if result.last_discard:           # 最後の打牌は、聴牌で終われるかどうかだけで比べる
                    assert candidate.is_best == (not result.can_end_tenpai or candidate.shanten <= 0)
                else:
                    same_rank = (candidate.option.reach, candidate.total) == (pick.option.reach, pick.total)
                    assert candidate.is_best == same_rank
                assert candidate.tile in pos.tiles and kind_of(candidate.tile) == candidate.kind
                assert candidate.held == counts34(pos.tiles)[candidate.kind]
            for tile in pos.tiles:
                verdict = judge_discard(result, tile)
                grades_seen.add(verdict.grade)
                assert verdict.chosen.kind == kind_of(tile) and verdict.pick is pick
                assert verdict.text and "None" not in verdict.text and all(verdict.reasons)
                if result.can_win:
                    assert verdict.grade is Grade.PASSED
                    continue
                assert verdict.is_best == verdict.chosen.is_best
                if verdict.grade is Grade.NARROWER:
                    assert verdict.tiles_loss > 0 and verdict.shanten_loss == 0
                    assert sum(n for _, n in verdict.gained) - sum(n for _, n in verdict.lost) == verdict.tiles_loss
                if verdict.grade is Grade.FARTHER:
                    assert verdict.shanten_loss >= 1
                    # 遠ざかるのは、分け方の中で使っていた牌を切ったとき。ただし同じ牌を 4 枚持っている手は例外がある
                    # （例：1111筒 と北で、北を切ると「5 枚目の 1筒 待ち」になってしまい、聴牌ではなくなる）
                    if result.layout_matches and max(counts34(pos.tiles)) < 4:
                        if verdict.broken is None:       # 七対子で、対子にできる種類が足りなくなる場合
                            assert result.layout.form is Form.CHIITOI and "種類が足りなくなる" in verdict.reasons[0]
                        else:
                            assert verdict.chosen.kind in verdict.broken.kinds
                checked += 1
            state = practice.apply(state, practice.discard(state.drawn) if state.turn % 3 else practice.discard(pick.tile))
    assert checked > 1500 and {Grade.BEST, Grade.NARROWER, Grade.FARTHER, Grade.PASSED} <= grades_seen

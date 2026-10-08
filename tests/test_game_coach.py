"""対局中のコーチ（engine/game_coach.py）のテスト"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import game as g
from engine.analysis.shanten import TENPAI
from engine.defense import danger_table, threats
from engine.game import Move, Phase
from engine.game_coach import (
    SafetyGrade,
    Stance,
    coach_action,
    judge_turn,
    position_of,
    riichi_view,
    ron_ahead,
    ron_preview,
    tsumo_preview,
    turn_advice,
)
from engine.tiles import kind_of, parse_tiles
from tests.game_helpers import build_hand, game_of


def k(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def tile_in(hand: g.HandState, seat: int, text: str) -> int:
    return next(t for t in hand.players[seat].tiles if kind_of(t) == k(text))


def test_free_stance_recommends_the_fastest_tile():
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="5z",
    )
    advice = turn_advice(hand, 0)
    assert advice.stance is Stance.FREE and advice.table == ()
    assert kind_of(advice.pick) == k("5z")
    assert advice.riichi is not None and advice.riichi.can_riichi
    assert position_of(hand, 0).can_riichi


def _riichi_threat_hand(mine: str, drawn: str) -> g.HandState:
    return build_hand(
        [mine, "234m567m78p345s66s", "222z444z666z1m2m3m8m", "258p369s147m3z6z7z5z"],
        turn=0, drawn=drawn, rivers=("", "9p", "", ""), riichi=(None, 0, None, None),
        kyotaku=1, scores=(25_000, 24_000, 25_000, 25_000),
    )


def test_fold_when_not_tenpai_against_riichi():
    hand = _riichi_threat_hand("13m479p2589s1357z", "9m")
    advice = turn_advice(hand, 0)
    assert advice.stance is Stance.FOLD and advice.threats and advice.table
    assert kind_of(advice.pick) == k("9p")                    # 現物
    assert advice.level_of[k("9p")] == 0 and advice.safest_level == 0
    assert "ベタオリ" in advice.reason
    assert advice.yaku == ()                                  # オリるときは役の候補を出さない
    decision = judge_turn(advice, g.discard(0, tile_in(hand, 0, "9p")), number=3)
    assert decision.safety is not None and decision.safety.grade is SafetyGrade.SAFE and decision.followed
    risky = judge_turn(advice, g.discard(0, tile_in(hand, 0, "5s")), number=3)
    assert risky.safety.grade is SafetyGrade.RISKY and "もっと安全な牌" in risky.safety.text


def test_push_when_tenpai_against_riichi_picks_the_safest_equal_speed_tile():
    # 9萬 を切ると、3索・6索 待ちの聴牌
    hand = _riichi_threat_hand("234m456p789s11z4s9m", "5s")
    advice = turn_advice(hand, 0)
    assert advice.analysis.pick.shanten == TENPAI
    assert advice.stance is Stance.PUSH
    chosen = advice.analysis.candidate(kind_of(advice.pick))
    assert chosen is not None and chosen.shanten == TENPAI
    best_levels = [advice.level_of[c.kind] for c in advice.analysis.best]
    assert advice.level_of[kind_of(advice.pick)] == min(best_levels)


def test_riichi_view_without_yaku_recommends_riichi():
    hand = build_hand(
        ["234m567p78s111m99p", "147p258s369m3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="5z",
        dealer=1,
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "5z"))
    assert view is not None and not view.dama_yaku_any and view.recommend_riichi
    assert "ロンであがれない" in view.advice
    assert {w.kind for w in view.waits} == {k("6s"), k("9s")}
    assert all(w.dama_ron is None and w.dama_tsumo is not None and w.riichi_ron is not None for w in view.waits)


def test_riichi_view_with_a_mangan_dama_suggests_dama_is_fine():
    # 断么九・平和・三色同順・ドラ 2（5筒の対子）。5索・8索 のどちらでも跳満
    hand = build_hand(
        ["234m234p234s67s55p", "147p258s369m3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="9m",
        dealer=1, dora="4p",
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "9m"))
    assert view is not None and view.dama_yaku_all
    assert all(w.dama_ron is not None and w.dama_ron >= 8000 for w in view.waits)
    assert not view.recommend_riichi and "満貫以上" in view.advice


def test_riichi_view_with_a_cheap_wait_still_recommends_riichi():
    # 23456索 の形：1索 であがると断么九・三色同順が付かず、安くなる
    hand = build_hand(
        ["234m234p234s56s55p", "147p258s369m3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="9m",
        dealer=1, dora="4p",
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "9m"))
    assert {w.kind for w in view.waits} == {k("1s"), k("4s"), k("7s")}
    assert min(w.dama_ron for w in view.waits) < 8000 and view.recommend_riichi


def test_partial_yaku_wait_is_flagged():
    # 東・南の双碰。親で東場なら、東であがると役牌、南では役なし
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="5z",
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "5z"))
    assert view.dama_yaku_any and not view.dama_yaku_all and view.recommend_riichi
    decision = judge_turn(turn_advice(hand, 0), g.discard(0, tile_in(hand, 0, "5z")), number=1)
    assert any("待ちの一部" in note for note in decision.notes)
    declared = judge_turn(turn_advice(hand, 0), g.riichi(0, tile_in(hand, 0, "5z")), number=1)
    assert not any("役がない" in note for note in declared.notes)


def test_furiten_tenpai_is_noted():
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="5z",
        rivers=("1z", "", "", ""), live_drawn=2,
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "5z"))
    assert view.furiten and "フリテン" in view.advice
    decision = judge_turn(turn_advice(hand, 0), g.riichi(0, tile_in(hand, 0, "5z")), number=2)
    assert any("フリテン" in note for note in decision.notes)


def test_ron_and_tsumo_previews():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=1, drawn="9p", rivers=("2z", "3z", "", ""),
    )
    win = tsumo_preview(hand, 1)
    assert win is not None and win.best is not None and win.ctx.is_tsumo
    assert tsumo_preview(hand, 0) is None
    claim = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "555z678m345p78p55s", "11z22z33z44z11199m"],
        turn=0, drawn="9p", honba=2, kyotaku=1, scores=(25_000, 25_000, 25_000, 24_000),
    )
    game = g.apply(game_of(claim), g.discard(0, tile_in(claim, 0, "9p")))
    hand2 = game.current
    assert hand2.phase is Phase.CLAIM
    preview = ron_preview(hand2, 2)
    # あがる前の見込みは、本場・供託・裏ドラを入れない（リーチとダマの比べ方の表と同じ基準）
    assert preview is not None and preview.ctx.honba == 0 and preview.ctx.kyotaku == 0 and preview.ctx.ura_indicators == ()
    game = g.apply(game, g.ron(1))                                  # 下家（順番が先）がロンした
    hand3 = game.current
    assert ron_ahead(hand3, 2) == (1,)
    assert ron_preview(hand3, 2).ctx.honba == 0 and ron_preview(hand3, 2).ctx.kyotaku == 0


def test_previews_do_not_show_the_ura_dora_before_winning():
    """リーチしてロン・ツモできるとき、見込みの点数に裏ドラを入れない（裏ドラは、あがったあとにめくる）"""
    claim = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "555z678m345p78p55s", "11z22z33z44z11199m"],
        turn=0, drawn="9p", riichi=(None, None, None, None), ura="6m6p",
    )
    players = list(claim.players)
    players[1] = replace(players[1], riichi_at=0, riichi_paid=True)
    river = (g.Discard(parse_tiles("9s")[0], riichi=True, order=0),)
    players[1] = replace(players[1], river=river)
    claim = replace(claim, players=tuple(players))
    game = g.apply(game_of(claim), g.discard(0, tile_in(claim, 0, "9p")))
    hand = game.current
    assert hand.phase is Phase.CLAIM and 1 in hand.pending
    preview = ron_preview(hand, 1)
    actual = g.ron_context(hand, 1, hand.last_discard[1].tile)
    assert actual.ura_indicators and preview.ctx.ura_indicators == ()
    assert not any("裏" in name for name in preview.spoken_yaku)


@pytest.mark.parametrize("seed", [3, 9])
def test_coach_action_plays_legal_moves_through_a_hand(seed):
    from engine.cpu import advance

    game = advance(g.start_game(g.GameConfig(seed=seed)))
    steps = 0
    while not game.finished and game.current.result is None and steps < 60:
        action = coach_action(game.current, 0)
        game = advance(g.apply(game, action))
        steps += 1
    assert game.current.result is not None or game.finished


def test_threat_table_matches_defense_module():
    hand = _riichi_threat_hand("13m479p2589s1357z", "9m")
    advice = turn_advice(hand, 0)
    expected = danger_table(hand.players[0].tiles, hand.visible_to(0), threats(hand, 0), dora_indicators=hand.dora_indicators)
    assert advice.table == expected
    assert all(a.move is not Move.NINE for a in [coach_action(hand, 0)])


def test_skipping_a_recommended_riichi_is_marked():
    """リーチをすすめる聴牌で、リーチせずに切ったら「リーチしなかった」（おすすめどおりとは数えない）"""
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3557z"], turn=0, drawn="5z",
        rivers=("9m", "9p", "9s", "8m"),
    )
    advice = turn_advice(hand, 0)
    assert advice.recommend_riichi and kind_of(advice.pick) == k("5z")
    dama = judge_turn(advice, g.discard(0, advice.pick), number=2)
    assert dama.skipped_riichi and not dama.followed
    assert any("リーチ" in note for note in dama.notes)
    declared = judge_turn(advice, g.riichi(0, advice.pick), number=2)
    assert not declared.skipped_riichi and declared.followed


def test_dead_wait_is_not_called_yakuless():
    """待ち牌が 1 枚も残っていない聴牌（空聴）は、リーチをすすめず「あがれない」と言う（役なしとは言わない）"""
    # 東・南のシャンポン待ち。残りの東 2 枚・南 2 枚は、どちらも河に見えている
    hand = build_hand(
        ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"], turn=0, drawn="5z",
        rivers=("9m", "1z2z", "1z2z", "8m"),
    )
    view = riichi_view(hand, 0, tile_in(hand, 0, "5z"))
    assert view is not None and view.dead and not view.recommend_riichi
    assert "空聴" in view.advice and "役がない" not in view.advice

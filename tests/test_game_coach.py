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
from engine.scoring.texts import kind_text
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


def test_safety_after_a_call_ignores_tiles_that_cannot_be_discarded():
    """鳴いた直後、喰い替えで切れない牌（ここでは現物の 5萬）を基準に「もっと安全な牌があった」とは言わない"""
    hand = build_hand(["456m2378p1379s17z", "444p555p666s24s66z", "777888999m88s25z", "111222333m4455z"],
                      turn=3, drawn="5m", rivers=["", "", "", "9p"], riichi=(None, None, None, 0), next_draws="8s8s")
    config = g.GameConfig(seed=1)
    claimed = g.apply_hand(config, hand, g.discard(3, hand.players[3].drawn))
    chi = next(a for a in claimed.call_actions(0) if a.move is Move.CHI)
    called = g.apply_hand(config, claimed, chi)
    advice = turn_advice(called, 0)
    assert kind_of(chi.tiles[0]) + 1 in called.forbidden                          # 手に残った 5萬 は、いまは切れない
    assert any(row.kind in called.forbidden and row.level == 0 for row in advice.table)
    assert all(row.kind not in called.forbidden for row in advice.usable_table)
    decision = judge_turn(advice, g.discard(0, advice.pick), number=2)
    assert decision.safety is not None and decision.safety.grade is SafetyGrade.SAFE
    assert all(kind not in called.forbidden for kind in decision.safety.safest)


def test_chankan_preview_uses_the_added_kan_tile():
    """加槓の牌でロン（槍槓）できるときの「ロンすると…点」は、加槓の牌で数える（槍槓の 1 翻も入る）"""
    hand = build_hand(["34p123456m789s11z", "1112223334p", "666777888m2223z", "444666777s99m33z"],
                      melds=["", "p550p", "", ""], turn=0, drawn="9s", next_draws="5p")
    config = g.GameConfig(seed=1)
    state = g.apply_hand(config, hand, g.discard(0, hand.players[0].drawn))
    state = g.apply_hand(config, state, g.kakan(1, state.kakan_tiles(1)[0]))
    assert state.phase is Phase.CLAIM and state.ron_check(0).ok
    preview = ron_preview(state, 0)
    assert preview is not None and preview.best is not None and preview.best.has_yaku
    assert kind_of(preview.ctx.win_tile) == kind_of(state.claim.tile) and preview.ctx.chankan
    assert "chankan" in {item.key for item in preview.best.evaluation.yaku}
    won = g.apply_hand(config, state, g.ron(0))
    assert won.result.wins[0].judgement.main == preview.judgement.main            # 見込みの点が、実際にロンした点と同じ


# ---------------------------------------------------------------- 鳴いた手


OPEN_HAND = ["67p234s55s88p9p", "147m258p369s1234z", "19m19p19s5z5z6z6z7z7z2s", "258m147p369s6m7m9s1z"]


def test_open_hand_advice_keeps_the_yaku():
    """鳴いた手は、役が無いとあがれない。速さが同じか 1 段遅いまでの中で、役（ここでは断么九）を残す牌をすすめる"""
    hand = build_hand(OPEN_HAND, melds=["c345m", "", "", ""], turn=0, drawn="4z")
    advice = turn_advice(hand, 0)
    assert kind_of(advice.analysis.pick.tile) == k("4z")            # 速さだけなら北（役の無い聴牌）
    assert kind_of(advice.pick) == k("9p") and "断么九" in advice.reason
    assert advice.open_outlooks[k("9p")].path_yaku[0].name == "断么九"


def test_open_hand_advice_keeps_the_yaku_among_equal_speed_tiles():
    """速さが同じ牌（4萬・7索・中）の中から、役（ここでは混全帯么九）を残せる牌を選ぶ。速さだけの牌（fastest）は出さない"""
    hand = build_hand(["4789m2789p7s7z", *OPEN_HAND[1:]], melds=["p444z", "", "", ""], turn=0, drawn="1p")
    advice = turn_advice(hand, 0)
    assert kind_of(advice.analysis.pick.tile) == k("7z")             # 速さだけなら中（同じ速さの中で、使いにくい字牌から）
    assert kind_of(advice.pick) == k("4m") and advice.keeps_yaku and advice.fastest is None
    assert "速さが同じ牌の中で" in advice.reason and "混全帯么九" in advice.reason
    # 役を残すと遅くなるときは、速さだけの牌を覚えておく
    slower = turn_advice(build_hand(OPEN_HAND, melds=["c345m", "", "", ""], turn=0, drawn="4z"), 0)
    assert slower.keeps_yaku and slower.fastest is not None and kind_of(slower.fastest) == k("4z")


def test_open_hand_discard_that_loses_the_yaku_is_flagged():
    hand = build_hand(OPEN_HAND, melds=["c345m", "", "", ""], turn=0, drawn="1s")
    advice = turn_advice(hand, 0)
    assert kind_of(advice.pick) == k("9p")
    lost = judge_turn(advice, g.discard(0, tile_in(hand, 0, "4s")), number=3)
    assert lost.lost_yaku and any("役が見えなくなる" in note for note in lost.notes)
    kept = judge_turn(advice, g.discard(0, tile_in(hand, 0, "9p")), number=3)
    assert not kept.lost_yaku and kept.followed


def test_following_the_coach_in_an_open_hand_is_judged_against_the_coach():
    """鳴いた手で、役を残すためにすすめた牌（速さだけの牌より遅い）を切ったら ✓。評価の文は、速さだけの牌との違いを書く。
    速さだけの牌（役まで遠回りの聴牌）を切ると「役が遠のいた」。ほかの牌は、コーチのおすすめと比べる"""
    hand = build_hand(OPEN_HAND, melds=["c345m", "", "", ""], turn=0, drawn="4z")
    advice = turn_advice(hand, 0)
    kept = judge_turn(advice, g.discard(0, advice.pick), number=3)
    assert kept.followed and kept.verdict.is_best and kept.verdict.label == "役を残す打牌"
    assert kept.verdict.text.endswith("速さだけなら 北切り（聴牌・待ち 1 種 3 枚）だが、役まで遠回りになる。")
    speed = judge_turn(advice, g.discard(0, tile_in(hand, 0, "4z")), number=3)
    assert not speed.followed and speed.yaku_detour and not speed.lost_yaku
    assert any("役まで遠回りになる" in note for note in speed.notes)
    slower = judge_turn(advice, g.discard(0, tile_in(hand, 0, "6p")), number=3)
    assert slower.verdict.pick.kind == k("9p") and "9筒切りなら" in slower.verdict.text        # 比べる相手は、コーチのおすすめ
    # 速さが同じ牌の中から、役を残す牌を選んだとき：○ は、役の見込みも同じ牌だけ（中 を切ると、役まで遠回り）
    same = build_hand(["4789m2789p7s7z", *OPEN_HAND[1:]], melds=["p444z", "", "", ""], turn=0, drawn="1p")
    advice = turn_advice(same, 0)
    assert [kind_of(t) for t in advice.equal_tiles] == [k("7s")]
    followed = judge_turn(advice, g.discard(0, advice.pick), number=3)
    assert followed.followed and followed.verdict.label == "役を残す打牌"
    other = judge_turn(advice, g.discard(0, tile_in(same, 0, "7s")), number=3)
    assert other.verdict.is_best and not other.yaku_detour and "おすすめの 4萬切り" in other.verdict.text
    assert judge_turn(advice, g.discard(0, tile_in(same, 0, "7z")), number=3).yaku_detour


def test_pushing_with_a_winnable_tenpai_is_judged_against_the_coach():
    """リーチを受けて押すとき、待ちの広い聴牌に役が無ければ、役のある聴牌をすすめる。そのとおりに切ったら ✓（待ちが狭い、とは言わない）"""
    hand = build_hand(["234567p1234s", *OPEN_HAND[1:]], melds=["c345m", "", "", ""], turn=0, drawn="6s",
                      rivers=["", "3z", "", ""], riichi=(None, 0, None, None))
    advice = turn_advice(hand, 0)
    assert advice.stance is Stance.PUSH and kind_of(advice.analysis.pick.tile) == k("6s") and kind_of(advice.pick) == k("1s")
    assert "あがれる聴牌の中で" in advice.reason
    pushed = judge_turn(advice, g.discard(0, advice.pick), number=3)
    assert pushed.followed and pushed.verdict.is_best and pushed.verdict.label == "おすすめどおり"
    assert pushed.verdict.text.endswith("速さだけなら 6索切り（聴牌・待ち 2 種 6 枚）だが、その聴牌は役が無く、あがれない。")
    wide = judge_turn(advice, g.discard(0, tile_in(hand, 0, "6s")), number=3)
    assert not wide.followed and wide.yaku_detour


def test_open_hand_does_not_prefer_a_dead_wait():
    """鳴いた手でも、待ち牌が 1 枚も残っていない聴牌（空聴：2索 切りの 白 単騎）を、有効牌の残る聴牌（白 切りの 2索 単騎。
    フリテンでも、ツモならあがれる）より先にすすめない"""
    others = ["147m258p369s1234z", "19m19p19s4z4z7z7z3s3s4s", "258m147p368s6m7m4s1z"]
    hand = build_hand(["567m789p2s", *others], melds=["c789s p666z", "", "", ""], turn=0, drawn="5z", rivers=("2s", "5z", "5z", "5z"))
    advice = turn_advice(hand, 0)
    assert kind_of(advice.pick) == k("5z") and "どれを切っても" not in advice.reason
    decision = judge_turn(advice, g.discard(0, advice.pick), number=2)
    assert decision.followed and decision.verdict.is_best


def test_tenpai_without_yaku_folds_against_riichi():
    """鳴いた手の、役の無い聴牌は、あがれないので押さない（リーチを受けたらオリる）"""
    hand = build_hand(["67p234s55s", "123456789p1122z", "1112223334445m", "6667778889991s"],
                      melds=["p444z c345m", "", "", ""], turn=0, drawn="9m", rivers=["", "3z", "", ""], riichi=(None, 0, None, None))
    advice = turn_advice(hand, 0)
    assert advice.analysis.pick.shanten == TENPAI
    assert all(not view.winnable for view in advice.tenpai_views)
    assert advice.stance is Stance.FOLD and "あがれない形" in advice.reason


def test_call_table_and_the_advice_after_the_call_pick_the_same_tile():
    """鳴きの判断の表の「鳴いたら ○ 切り」と、鳴いたあとの打牌のおすすめは、同じ決め方（リーチを受けていない局面）"""
    from engine.call_coach import call_advice
    from engine.cpu import decide

    checked = 0
    for seed in range(12):
        game = g.start_game(g.GameConfig(seed=seed))
        while not game.finished and game.current.result is None:
            hand = game.current
            seat = g.waiting_for(hand)
            if seat == 0 and hand.phase is Phase.CLAIM and not threats(hand, 0) and not hand.players[hand.claim.seat].in_riichi:
                advice = call_advice(hand, 0)
                for option in advice.calls if advice is not None else ():
                    if option.action.move is Move.KAN or option.outlook.shanten == TENPAI:
                        continue
                    after = g.apply_hand(game.config, hand, option.action)
                    if after.phase is not Phase.DRAW or after.turn != 0:
                        continue                                            # ほかの人の返事待ち・ロン
                    advice_after = turn_advice(after, 0)
                    assert kind_of(advice_after.pick) == kind_of(option.discard)
                    assert kind_text(kind_of(advice_after.pick)) in advice_after.reason     # 理由は、すすめる牌のこと
                    checked += 1
            action = decide(hand, seat, g.CpuLevel.NORMAL)
            if seat == 0 and hand.phase is Phase.CLAIM:
                calls = [a for a in hand.call_actions(0) if a.move in (Move.CHI, Move.PON)]
                action = calls[0] if calls and action.move is Move.PASS else action
            game = g.apply(game, action)
    assert checked >= 10


def test_kan_advice_recommends_a_kan_that_keeps_the_speed_and_not_against_riichi():
    from engine.game_coach import kan_advice

    free = build_hand(["1111m23p456s789s5z", "123456789p1122z", "1112223334445s", "6667778889993m"], turn=0, drawn="9p")
    advice = kan_advice(free, 0)
    assert len(advice) == 1 and not advice[0].added and kind_of(advice[0].tile) == k("1m")
    assert advice[0].recommend and "遅くならない" in advice[0].reason
    assert coach_action(free, 0) == g.ankan(0, advice[0].tile)            # コーチどおりに打つなら、カンする
    threatened = build_hand(["1111m23p456s789s5z", "123456789p1122z", "1112223334445s", "6667778889993m"], turn=0, drawn="9p",
                            rivers=["", "3z", "", ""], riichi=(None, 0, None, None))
    advice = kan_advice(threatened, 0)
    assert not advice[0].recommend and "リーチを受けている" in advice[0].reason


def test_formal_tenpai_is_an_open_tenpai_without_any_yaku():
    """形式聴牌（鳴いた手の、どの待ちでも役が付かない聴牌）。局の終わりの公開で「役なし。形式聴牌」と添える"""
    from engine.game_coach import formal_tenpai

    hand = build_hand(["123456789m1122z", "67p234s55s", "67p234s50s", "1112223334449p"],
                      melds=["", "p444z c345m", "c345m p888s", ""], turn=0, drawn="9p")
    # 席 1：北（南家には役牌でない）のポンとチーで、58筒 待ち（役なし）。席 2：断么九。席 0・3：門前
    assert [formal_tenpai(hand, seat) for seat in range(4)] == [False, True, False, False]

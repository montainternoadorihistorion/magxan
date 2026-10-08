"""鳴き（チー・ポン・カン）と、それにかかわる決まり（喰い替え・カンドラ・槍槓・四槓散了・責任払いなど）"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import game as g
from engine.game import ClaimKind, EndKind, Furiten, GameConfig, GameError, Move, Phase
from engine.melds import MeldType
from engine.rules import Rules
from engine.tiles import kind_of, parse_tiles
from engine.wall import DORA_START, NUM_LIVE
from tests.game_helpers import build_hand, game_of, with_players
from tests.test_game import _random_play, conserved, total_points


def kind(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def tile_of(hand: g.HandState, seat: int, text: str) -> int:
    target = kind(text)
    return next(t for t in hand.players[seat].tiles if kind_of(t) == target)


def kinds_of(tiles) -> list[int]:
    return sorted(kind_of(t) for t in tiles)


def drop(game: g.GameState, seat: int) -> g.GameState:
    """その席がツモ牌を切る"""
    return g.apply(game, g.discard(seat, game.current.players[seat].drawn))


# ---------------------------------------------------------------- 優先順位：ロン ＞ ポン ＞ チー


def _priority_hand(**kwargs) -> g.HandState:
    """親（席 0）が 5萬 を切る。下家はチー（34・46・67）、対面はポン、上家はロン（34萬の両面、白の暗刻）"""
    defaults = dict(
        hands=["147m258p369s1234z", "3467m8m111p888s22z", "55m13p46p79s3344z6z", "34m567p678s555z99p"],
        turn=0,
        drawn="5m",
        next_draws="9m9m9m9m",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_ron_is_asked_first_then_pon_then_chi():
    hand = _priority_hand()
    claim = drop(game_of(hand), 0).current
    assert claim.phase is Phase.CLAIM and claim.pending == (3, 2, 1)
    assert (claim.claim.ron, claim.claim.pon, claim.claim.chi) == ((3,), (2,), (1,))
    assert g.waiting_for(claim) == 3
    assert [a.move for a in claim.call_actions(3)] == [Move.RON]
    assert [a.move for a in claim.call_actions(2)] == [Move.PON]
    assert [kinds_of(a.tiles) for a in claim.call_actions(1)] == [
        [kind("3m"), kind("4m")], [kind("4m"), kind("6m")], [kind("6m"), kind("7m")],
    ]
    assert claim.call_actions(0) == ()


def test_ron_cancels_the_pon_and_the_chi():
    game = g.apply(drop(game_of(_priority_hand()), 0), g.ron(3))
    result = game.current.result
    assert result.kind is EndKind.RON and [w.seat for w in result.wins] == [3]


def test_pon_goes_before_chi_and_the_turn_jumps_to_the_caller():
    hand = _priority_hand()
    game = g.apply(drop(game_of(hand), 0), g.pass_(3))
    assert game.current.pending == (2, 1)
    game = g.apply(game, game.current.call_actions(2)[0])
    after = game.current
    # チーだけの下家には、もう聞かない。ポンした対面の番（ツモらずに切る）
    assert after.phase is Phase.DRAW and after.turn == 2 and after.players[2].drawn is None
    furo = after.players[2].furo
    assert len(furo) == 1 and furo[0].meld.type is MeldType.PON and furo[0].from_seat == 0
    assert kinds_of(furo[0].meld.tiles) == [kind("5m")] * 3 and furo[0].meld.called_tile == hand.players[0].drawn
    assert after.players[0].river[-1].called_by == 2
    assert after.forbidden == (kind("5m"),) and after.interrupted
    assert len(after.players[2].hand) == 11
    # 上家はロンを見送ったので、同巡内フリテン（見逃し）
    assert after.players[3].missed and after.misses[-1].passed
    assert conserved(after) and total_points(after) == 100_000
    # 鳴かれた捨て牌は、見えている牌として 1 回だけ数える
    assert sum(1 for t in after.visible_to(1) if kind_of(t) == kind("5m")) == 3


def test_chi_with_kuikae_forbids_the_called_tile_and_the_suji():
    game = drop(game_of(_priority_hand()), 0)
    game = g.apply(g.apply(game, g.pass_(3)), g.pass_(2))
    choice = next(a for a in game.current.call_actions(1) if kinds_of(a.tiles) == [kind("6m"), kind("7m")])
    game = g.apply(game, choice)
    after = game.current
    assert after.turn == 1 and after.forbidden == tuple(sorted((kind("5m"), kind("8m"))))      # 67 で 5 をチー → 5 と 8 が切れない
    with pytest.raises(GameError):
        g.apply(game, g.discard(1, tile_of(after, 1, "8m")))
    with pytest.raises(GameError):
        g.apply(game, g.riichi(1, tile_of(after, 1, "3m")))          # 鳴いた手ではリーチできない
    with pytest.raises(GameError):
        g.apply(game, g.tsumo(1))                                    # 鳴いた直後は、切るだけ
    game = g.apply(game, g.discard(1, tile_of(after, 1, "3m")))
    assert game.current.turn == 2 and game.current.forbidden == ()


def test_kanchan_chi_forbids_only_the_called_tile():
    game = drop(game_of(_priority_hand()), 0)
    game = g.apply(g.apply(game, g.pass_(3)), g.pass_(2))
    choice = next(a for a in game.current.call_actions(1) if kinds_of(a.tiles) == [kind("4m"), kind("6m")])
    assert g.apply(game, choice).current.forbidden == (kind("5m"),)


@pytest.mark.parametrize(
    ("called", "used", "expected"),
    [
        ("3m", "45m", "36m"), ("7m", "56m", "47m"), ("4m", "35m", "4m"), ("3m", "12m", "3m"), ("7m", "89m", "7m"),
        ("1p", "23p", "14p"), ("9s", "78s", "69s"), ("6s", "78s", "69s"),
    ],
)
def test_kuikae_kinds(called, used, expected):
    assert g.kuikae_kinds(Move.CHI, parse_tiles(called)[0], parse_tiles(used)) == frozenset(kind_of(t) for t in parse_tiles(expected))


def test_pon_forbids_the_same_tile():
    assert g.kuikae_kinds(Move.PON, parse_tiles("5z")[0], parse_tiles("5z5z")) == {kind("5z")}


def _kuikae_hand(concealed: str) -> g.HandState:
    """下家は副露 3 組（役なし）。親が 5萬 を切る"""
    return build_hand(
        ["147m258p369s1234z", concealed, "13p46p79s3344z6z11s", "567p678s555z99p68m"],
        melds=("", "p111p p888s p999m", "", ""),
        turn=0, drawn="5m", next_draws="7z7z7z",
    )


def test_no_call_when_only_forbidden_tiles_would_remain():
    # 下家の手は 2234萬。5萬 を 34萬でチーすると、残る 2萬 2枚はどちらも喰い替えで切れない → チーできない
    game = drop(game_of(_kuikae_hand("2234m")), 0)
    assert game.current.phase is Phase.DRAW and game.current.turn == 1
    assert [m.seat for m in game.current.misses] == [1]            # 5萬 は形の上ではあがり牌（役なし）


def test_chi_is_allowed_when_a_legal_discard_remains():
    game = drop(game_of(_kuikae_hand("2349m")), 0)
    assert game.current.phase is Phase.CLAIM and game.current.pending == (1,)
    game = g.apply(game, game.current.call_actions(1)[0])
    assert game.current.forbidden == tuple(sorted((kind("2m"), kind("5m"))))
    game = g.apply(game, g.discard(1, tile_of(game.current, 1, "9m")))
    assert game.current.turn == 2


def test_chi_only_from_the_left_and_pon_from_anyone():
    # 対面（席 2）が切った 5萬 は、上家（席 3）がチーできる。下家（席 1）はチーできない
    hand = build_hand(
        ["147m258p369s1234z", "3467m8m111p888s22z", "55m13p46p79s3344z6z", "46m567p678s555z99p"],
        turn=2, drawn="5m", next_draws="9m9m9m9m",
    )
    claim = drop(game_of(hand), 2).current.claim
    assert claim.chi == (3,) and claim.pon == ()


def test_no_calls_on_the_last_discard():
    hand = _priority_hand(live_drawn=NUM_LIVE, next_draws="")
    assert hand.live_remaining == 0
    game = drop(game_of(hand), 0)
    claim = game.current.claim
    # 河底牌：ロンだけ（下家は役が無い形だが、河底撈魚が付くのでロンできる）。ポン・チーは聞かない
    assert game.current.pending == (1, 3) and claim.ron == (1, 3) and claim.pon == () and claim.chi == ()
    game = g.apply(g.apply(game, g.pass_(1)), g.pass_(3))
    assert game.current.result.kind is EndKind.EXHAUSTED


def test_calls_off_rule_offers_only_ron():
    hand = _priority_hand(rules=Rules(calls=False))
    assert drop(game_of(hand), 0).current.pending == (3,)


def test_illegal_calls_are_refused():
    game = drop(game_of(_priority_hand()), 0)
    with pytest.raises(GameError):
        g.apply(game, g.pon(1, *game.current.call_actions(1)[0].tiles))          # 下家はポンできない
    game = g.apply(g.apply(game, g.pass_(3)), g.pass_(2))
    current = game.current
    three, four, eight = (tile_of(current, 1, "3m"), tile_of(current, 1, "4m"), tile_of(current, 1, "8m"))
    with pytest.raises(GameError):
        g.apply(game, g.chi(1, three, eight))                                     # 順子にならない
    with pytest.raises(GameError):
        g.apply(game, g.chi(1, three, three))
    with pytest.raises(GameError):
        g.apply(game, g.discard(1, three))                                        # 返事の番に、切ることはできない
    assert g.apply(game, g.chi(1, three, four)).current.turn == 1


# ---------------------------------------------------------------- 鳴きと一発・リーチ・ダブル立直・九種九牌


def test_any_call_ends_everyones_ippatsu():
    hand = _priority_hand()
    hand = with_players(hand, p3=replace(hand.players[3], riichi_at=0, riichi_paid=True, ippatsu=True))
    game = g.apply(drop(game_of(hand), 0), g.pass_(3))           # リーチ中に見逃した → この局はずっとフリテン
    game = g.apply(game, game.current.call_actions(2)[0])
    after = game.current
    assert not after.players[3].ippatsu and after.players[3].riichi_missed


def test_riichi_tile_that_is_called_still_establishes_the_riichi():
    # 親が 5萬 を切ってリーチ（99筒・東のシャンポン待ち）。対面がポンしても、リーチは成立する
    hand = _priority_hand(hands=["234m567p678s99p11z", "3467m8m111p999s22z", "55m13p46p79s3344z6z", "34m567p678s555z99p"])
    assert hand.players[0].drawn in hand.riichi_tiles(0)
    game = g.apply(game_of(hand), g.riichi(0, hand.players[0].drawn))
    game = g.apply(game, g.pass_(3))
    game = g.apply(game, game.current.call_actions(2)[0])
    after = game.current
    assert after.players[0].riichi_paid and after.kyotaku == 1 and after.scores[0] == 24_000
    assert not after.players[0].ippatsu


def test_double_riichi_is_not_given_after_a_call():
    hand = build_hand(
        ["147m258p369s1234z", "3467m8m111p888s22z", "55m13p46p79s3344z6z", "234m567p678s99p55z"],
        turn=0, drawn="5m", next_draws="9m1m",
    )
    game = drop(game_of(hand), 0)
    game = g.apply(game, game.current.call_actions(2)[0])                # 対面がポン
    game = g.apply(game, g.discard(2, tile_of(game.current, 2, "6z")))
    current = game.current
    assert current.turn == 3 and current.players[3].river == ()
    assert not current.can_nine(3)
    game = g.apply(game, g.riichi(3, current.riichi_tiles(3)[0]))
    me = game.current.players[3]
    assert me.in_riichi and not me.double_riichi


def test_no_tenhou_or_chiihou_after_a_call():
    hand = build_hand(
        ["147m258p369s1234z", "3467m8m111p888s22z", "55m13p46p79s3344z6z", "234m567p678s99p55z"],
        turn=0, drawn="5m", next_draws="9p",
    )
    game = drop(game_of(hand), 0)
    game = g.apply(game, game.current.call_actions(2)[0])
    game = g.apply(game, g.discard(2, tile_of(game.current, 2, "6z")))
    current = game.current                                                # 上家：最初のツモ（9筒）で、あがりの形
    assert current.players[3].river == () and current.can_tsumo(3)
    ctx = g.tsumo_context(current, 3)
    assert not ctx.chiihou and not ctx.tenhou


# ---------------------------------------------------------------- 大明槓とカンドラ


def _kan_hand(**kwargs) -> g.HandState:
    """親（席 0）が赤 5萬 を切る。対面（席 2）は 5萬 を 3 枚持っていて、大明槓できる"""
    defaults = dict(
        hands=["147m258p369s1234z", "3467m8m111p888s22z", "555m13p49p79s3344z", "234m68p567s555z99p"],
        turn=0,
        drawn="0m",
        next_draws="9m9m9m9m",
        next_rinshan="7p",
        dora="1z6p",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_daiminkan_draws_a_replacement_and_reveals_the_dora_after_the_discard():
    hand = _kan_hand()
    game = drop(game_of(hand), 0)
    options = game.current.call_actions(2)
    assert [a.move for a in options] == [Move.PON, Move.KAN]
    game = g.apply(game, options[1])
    after = game.current
    me = after.players[2]
    assert after.turn == 2 and me.rinshan and kind_of(me.drawn) == kind("7p")
    assert me.furo[0].meld.type is MeldType.MINKAN and len(me.hand) == 10 and after.interrupted
    assert after.rinshan_drawn == 1 and after.live_remaining == hand.live_remaining - 1
    assert after.dora_indicators == (hand.wall_tiles[DORA_START],) and after.dora_pending == 1
    assert conserved(after)
    game = drop(game, 2)
    revealed = game.current
    assert revealed.dora_pending == 0 and len(revealed.dora_indicators) == 2 and len(revealed.ura_indicators) == 2
    assert kind_of(revealed.dora_indicators[1]) == kind("6p")


def test_ron_on_the_discard_after_a_daiminkan_counts_the_new_dora():
    # 対面が大明槓して、嶺上牌の 7筒 を切る。上家（68筒 の嵌張・白の暗刻）が 7筒 でロン。新しいドラ表示牌 6筒 → ドラ 7筒
    game = drop(game_of(_kan_hand()), 0)
    game = g.apply(game, game.current.call_actions(2)[1])
    game = drop(game, 2)
    assert game.current.pending == (3,)
    win = g.apply(game, g.ron(3)).current.result.wins[0]
    assert len(win.ctx.dora_indicators) == 2 and win.judgement.dora == 1


def test_rinshan_win_after_a_daiminkan_does_not_count_the_unrevealed_dora():
    # 対面：555萬 を大明槓、残りの 13筒 456索 789索 66z は 2筒 待ち。嶺上牌の 2筒 でツモ（嶺上開花）
    hand = _kan_hand(hands=["147m258p369s1234z", "3467m8m111p888s22z", "555m13p456s789s66z", "234m68p567s555z99p"],
                     next_rinshan="2p", dora="1z9p")
    game = drop(game_of(hand), 0)
    game = g.apply(game, game.current.call_actions(2)[1])
    after = game.current
    assert after.can_tsumo(2)
    ctx = g.tsumo_context(after, 2)
    assert ctx.rinshan and not ctx.haitei and len(ctx.dora_indicators) == 1
    win = g.apply(game, g.tsumo(2)).current.result.wins[0]
    assert any(y.key == "rinshan" for y in win.judgement.yaku)
    assert win.pao is None


# ---------------------------------------------------------------- 暗槓


def _ankan_hand(**kwargs) -> g.HandState:
    defaults = dict(
        hands=["111m234m567p88p99s", "258m147p369s1234z", "3467m8m111p888s22z", "34m67p67s555z99p6z1s"],
        turn=0, drawn="1m", next_rinshan="5z", dora="3z4z",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_ankan_reveals_the_dora_at_once_and_keeps_the_hand_closed():
    hand = _ankan_hand()
    assert [kind_of(t) for t in hand.ankan_tiles(0)] == [kind("1m")]
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    after = game.current
    me = after.players[0]
    assert me.furo[0].meld.type is MeldType.ANKAN and me.menzen and me.furo[0].from_seat is None
    assert len(after.dora_indicators) == 2 and after.dora_pending == 0
    assert me.rinshan and kind_of(me.drawn) == kind("5z") and after.interrupted
    assert after.riichi_tiles(0)                               # 暗槓のあとでも、門前なのでリーチできる
    assert not after.can_nine(0)
    assert conserved(after)


def test_kan_is_not_allowed_on_the_last_tile():
    hand = _ankan_hand(live_drawn=NUM_LIVE)
    assert hand.live_remaining == 0 and hand.ankan_tiles(0) == ()


def test_rinshan_tile_is_not_haitei_even_when_the_live_wall_becomes_empty():
    # 残り 1 枚で暗槓 → ツモ山の最後の 1 枚が王牌に回り、残り 0 枚。嶺上牌（9索）であがっても、海底摸月ではない
    hand = _ankan_hand(hands=["111m234m567p888p9s", "258m147p369s1234z", "3467m8m111p777s22z", "34m67p67s555z99p6z1s"],
                       next_rinshan="9s", live_drawn=NUM_LIVE - 1)
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    after = game.current
    assert after.live_remaining == 0 and after.can_tsumo(0)
    ctx = g.tsumo_context(after, 0)
    assert ctx.rinshan and not ctx.haitei


def test_riichi_ankan_only_when_the_wait_stays_the_same():
    keeps = _ankan_hand(riichi=(0, None, None, None), rivers=("9m", "", "", ""))
    assert [kind_of(t) for t in keeps.ankan_tiles(0)] == [kind("1m")]
    assert g.auto_action(keeps, 0) is None                         # 暗槓するかどうかは、自分で決める
    changes = _ankan_hand(
        hands=["1112345m567p789s", "258m147p369s1234z", "3467m8m111p888s22z", "34m67p67s555z99p6z1s"],
        riichi=(0, None, None, None), rivers=("9m", "", "", ""),
    )
    assert changes.ankan_tiles(0) == ()                            # 2萬・3萬・5萬・6萬待ち → 2萬・5萬待ちに変わる
    assert g.auto_action(changes, 0) == g.discard(0, changes.players[0].drawn)


def test_riichi_cannot_kan_a_tile_that_was_not_just_drawn():
    # 送り槓：手の中の 4 枚をカンして、ツモ牌を残すことはできない
    hand = _ankan_hand(
        hands=["1111m23m567p88p99s", "258m147p369s1234z", "3467m8m111p888s22z", "34m67p67s555z99p6z1s"],
        drawn="5z", next_rinshan="7z", riichi=(0, None, None, None), rivers=("9m", "", "", ""),
    )
    assert hand.ankan_tiles(0) == ()


def test_only_kokushi_can_rob_a_closed_kan():
    # 親が東を暗槓。下家は国士無双の東待ち（ロンできる）
    hand = build_hand(
        ["111z234m567p88p99s", "19m19p19s234567z9s", "258m147p36s22m3z3z4z", "34m567p678s555z9p9p"],
        turn=0, drawn="1z", next_rinshan="5m",
    )
    assert [kind_of(t) for t in hand.ankan_tiles(0)] == [kind("1z")]
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    claim = game.current
    assert claim.claim.kind is ClaimKind.ANKAN and claim.pending == (1,)
    win = g.apply(game, g.ron(1)).current.result.wins[0]
    assert win.seat == 1 and win.judgement.yakuman_times >= 1 and win.ctx.chankan


def test_a_closed_kan_cannot_be_robbed_by_other_hands():
    # 親が 3萬 を暗槓。対面（24萬の嵌張・白の暗刻）と上家（45萬の両面・發の暗刻）は、形の上では 3萬 待ち。
    # でも暗槓の牌では、国士無双しかロンできない（見逃しにもならない）
    hand = build_hand(
        ["333m234p567p88p99s", "258m147p369s2z3z4z5z", "24m111p222s555z88m", "45m567p678s666z9p9p"],
        turn=0, drawn="3m", next_rinshan="5m",
    )
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    after = game.current
    assert after.phase is Phase.DRAW and after.turn == 0 and after.misses == ()


# ---------------------------------------------------------------- 加槓と槍槓


def _kakan_hand(**kwargs) -> g.HandState:
    """親（席 0）は 5筒 をポンしている。4 枚目（赤 5筒）を引いて加槓できる。下家は 46筒 の嵌張で 5筒 待ち"""
    defaults = dict(
        hands=["123m789m11z23s", "46p234m567s888s99m", "147m258s36p1z2z3z4z9p", "13579m2467s777z1p"],
        melds=("p555p", "", "", ""),
        turn=0, drawn="0p", next_rinshan="9p", dora="1z2z",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_kakan_can_be_robbed_by_chankan():
    hand = _kakan_hand()
    assert [kind_of(t) for t in hand.kakan_tiles(0)] == [kind("5p")]
    game = g.apply(game_of(hand), g.kakan(0, hand.kakan_tiles(0)[0]))
    claim = game.current
    assert claim.phase is Phase.CLAIM and claim.claim.kind is ClaimKind.KAKAN and claim.pending == (1,)
    assert [a.move for a in claim.call_actions(1)] == [Move.RON]
    game = g.apply(game, g.ron(1))
    win = game.current.result.wins[0]
    assert win.ctx.chankan and not win.ctx.houtei
    assert any(y.key == "chankan" for y in win.judgement.yaku)
    assert len(win.ctx.dora_indicators) == 1                          # 加槓のカンドラは、めくられない
    assert game.current.players[0].furo[0].meld.type is MeldType.PON
    assert conserved(game.current)


def test_passing_a_chankan_completes_the_kakan():
    hand = _kakan_hand()
    game = g.apply(game_of(hand), g.kakan(0, hand.kakan_tiles(0)[0]))
    game = g.apply(game, g.pass_(1))
    after = game.current
    me = after.players[0]
    assert me.furo[0].meld.type is MeldType.KAKAN and me.furo[0].added == hand.players[0].drawn
    assert after.dora_pending == 1 and len(after.dora_indicators) == 1
    assert me.rinshan and after.turn == 0 and kind_of(me.drawn) == kind("9p")
    missed = after.misses[-1]
    assert missed.seat == 1 and missed.passed and missed.chankan and after.players[1].missed
    assert conserved(after)
    game = drop(game, 0)
    assert len(game.current.dora_indicators) == 2


# ---------------------------------------------------------------- 四槓散了


def test_four_kans_by_two_players_abort_after_the_next_discard():
    hand = build_hand(
        ["444p567s9m", "369m258p147s1234z", "3467m8m111p888s22z", "34m67p678s99p6z"],
        melds=("a1111m a2222m", "", "", "a5555z"),
        turn=0, drawn="4p", next_rinshan="7z",
    )
    assert hand.rinshan_drawn == 3 and hand.live_remaining == NUM_LIVE - hand.live_drawn - 3
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    after = game.current
    assert after.rinshan_drawn == 4 and after.ankan_tiles(0) == () and len(after.dora_indicators) == 5
    result = drop(game, 0).current.result
    assert result.kind is EndKind.FOUR_KANS and result.renchan and result.kind.is_abortive


def test_four_kans_by_one_player_continue_without_more_kans():
    hand = build_hand(
        ["444p9m", "369m258p147s1234z", "3467m8m111p888s22z", "34m67p678s99p6z5z5z5z"],
        melds=("a1111m a2222m a7777z", "", "", ""),
        turn=0, drawn="4p", next_rinshan="6z", next_draws="9p",
    )
    game = g.apply(game_of(hand), g.ankan(0, hand.ankan_tiles(0)[0]))
    after = drop(game, 0).current
    assert after.result is None and after.turn == 1 and not after.can_kan()


# ---------------------------------------------------------------- 責任払い（包）


def _pao_hand(**kwargs) -> g.HandState:
    """下家（席 1）は 白・發 をポンしていて、中の対子（まだ聴牌していない）。親（席 0）の 中 をポンすると大三元が確定（親が責任払い）。
    ポンのあと 8索 を切ると、23萬・99筒 の 1萬・4萬待ち"""
    defaults = dict(
        hands=["258m147p369s1234z", "77z23m99p8s", "147m258p147s258s9m", "369m369p7s7s4z4z1z8p8p"],
        melds=("", "p555z p666z", "", ""),
        turn=0, drawn="7z", next_draws="8m2z3z4m",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def _pon_the_third_dragon(hand: g.HandState, *, discard: str = "8s") -> g.GameState:
    game = drop(game_of(hand), 0)
    assert game.current.pending == (1,)
    game = g.apply(game, game.current.call_actions(1)[0])
    me = game.current.players[1]
    assert (me.pao, me.pao_yaku) == (0, "daisangen")
    return g.apply(game, g.discard(1, tile_of(game.current, 1, discard)))


def test_pao_tsumo_is_paid_by_the_responsible_player_alone():
    game = _pon_the_third_dragon(_pao_hand(honba=1))
    for seat in (2, 3, 0):
        game = drop(game, seat)
    assert game.current.turn == 1 and game.current.can_tsumo(1)
    win = g.apply(game, g.tsumo(1)).current.result.wins[0]
    assert (win.pao, win.pao_yaku) == (0, "daisangen")
    assert win.payments == (-(32_000 + 300), 32_000 + 300, 0, 0)


def test_pao_ron_by_another_player_is_split_and_the_honba_goes_to_the_responsible_player():
    game = _pon_the_third_dragon(_pao_hand(honba=2, next_draws="4m"))
    game = drop(game, 2)
    assert game.current.pending == (1,)
    win = g.apply(game, g.ron(1)).current.result.wins[0]
    assert win.payments == (-(16_000 + 600), 32_000 + 600, -16_000, 0)


def test_pao_player_dealing_in_pays_everything():
    game = _pon_the_third_dragon(_pao_hand(next_draws="8m2z4m"))
    for seat in (2, 3, 0):
        game = drop(game, seat)
    assert game.current.pending == (1,)
    assert g.apply(game, g.ron(1)).current.result.wins[0].payments == (-32_000, 32_000, 0, 0)


def test_pao_covers_only_its_own_yakuman_when_another_one_is_combined():
    # 下家：白・發 ポン、中の対子、東の暗刻、南・西。中をポンして西を切ると、南の単騎。ツモると字一色も付く
    hand = _pao_hand(hands=["258m147p369s1234z", "77z111z2z3z", "147m258p147s258s9m", "369m369p7s7s4z4z9s8p8p"],
                     next_draws="8m3z9p2z")
    game = _pon_the_third_dragon(hand, discard="3z")
    for seat in (2, 3, 0):
        game = drop(game, seat)
    assert game.current.can_tsumo(1)
    win = g.apply(game, g.tsumo(1)).current.result.wins[0]
    assert win.judgement.yakuman_times == 2 and win.pao == 0
    # 大三元の分（32000）は親が全額。字一色の分（役満 1 倍）は、ふつうの子のツモ（親 16000・子 8000 ずつ）
    assert win.payments == (-(32_000 + 16_000), 64_000, -8_000, -8_000)


# ---------------------------------------------------------------- 流し満貫と鳴き


def _nagashi_hand(*, hands0: str = "1234m1234p1234s5z", melds0: str = "") -> g.HandState:
    """海底牌をツモった親の河は么九牌だけ。最後に 9筒 を切ると流局"""
    return build_hand(
        [hands0, "2345m2345p2345s6z", "6789m6789p678s7z7z", "1z1z2z2z3z3z4z4z5z5z7z7z6z"],
        melds=(melds0, "", "", ""),
        turn=0, drawn="9p", rivers=("1m9m1z", "", "", ""), live_drawn=NUM_LIVE,
    )


def test_nagashi_mangan_when_no_discard_was_called():
    result = drop(game_of(_nagashi_hand()), 0).current.result
    assert result.kind is EndKind.EXHAUSTED and result.nagashi == (0,)


def test_no_nagashi_mangan_when_a_discard_was_called():
    hand = _nagashi_hand()
    me = hand.players[0]
    called = replace(me, river=(me.river[0], replace(me.river[1], called_by=2), me.river[2]))
    result = drop(game_of(with_players(hand, p0=called)), 0).current.result
    assert result.kind is EndKind.EXHAUSTED and result.nagashi == ()


def test_nagashi_mangan_is_kept_when_the_player_called_themselves():
    hand = _nagashi_hand(hands0="1234m1234p12s", melds0="p999s")
    assert hand.players[0].furo
    assert drop(game_of(hand), 0).current.result.nagashi == (0,)


# ---------------------------------------------------------------- 同巡内フリテンは、鳴いても次のツモまで


def test_temporary_furiten_survives_own_call_until_the_next_draw():
    # 下家（同巡内フリテン中）が 5萬 をチーして 4z を切る（發の暗刻・99筒・12索 の 3索 待ち）。対面の 3索 ではロンできない
    hand = _priority_hand(
        hands=["147m258p369s1234z", "34m111p666z99p12s4z", "55m13p46p79s3344z6z", "34m567p678s555z99p"],
        next_draws="3s",
    )
    hand = with_players(hand, p1=replace(hand.players[1], missed=True))
    game = g.apply(drop(game_of(hand), 0), g.pass_(3))
    game = g.apply(game, g.pass_(2))
    game = g.apply(game, game.current.call_actions(1)[0])
    game = g.apply(game, g.discard(1, tile_of(game.current, 1, "4z")))
    assert game.current.players[1].missed                       # 鳴いて切っても、まだ解けない（雀魂：自分の次のツモで解ける）
    if game.current.phase is Phase.CLAIM:                       # 対面の 4z ポンを見送る
        game = g.apply(game, g.pass_(2))
    game = drop(game, 2)                                        # 対面が 3索 を切る
    after = game.current
    assert after.turn == 3 and after.phase is Phase.DRAW
    missed = after.misses[-1]
    assert (missed.seat, missed.passed, missed.check.furiten) == (1, False, Furiten.MISSED)


# ---------------------------------------------------------------- 保存の形


@pytest.mark.parametrize(
    ("data", "move", "tiles"),
    [([1, "c", 10, 14], Move.CHI, (10, 14)), ([2, "o", 5, 6], Move.PON, (5, 6)), ([3, "m", 1, 2, 3], Move.KAN, (1, 2, 3))],
)
def test_call_actions_round_trip(data, move, tiles):
    action = g.Action.from_list(data)
    assert action.move is move and action.tiles == tiles and action.to_list() == data


@pytest.mark.parametrize("data", [[0, "a", 3], [0, "e", 7]])
def test_kan_actions_round_trip(data):
    assert g.Action.from_list(data).to_list() == data


@pytest.mark.parametrize(
    "data",
    [[1, "c", 10], [1, "o", 5, 5], [1, "m", 1, 2], [0, "a"], [0, "e", 1, 2], [0, "c", 1, 200], [0, "d", 1, 2], [0, "p", 1], [0, "c", 1, True]],
)
def test_broken_call_actions_raise_value_error(data):
    with pytest.raises(ValueError):
        g.Action.from_list(data)


def test_version_1_saves_replay_without_calls():
    config = GameConfig(seed=7, rules=Rules(calls=False))
    game = g.start_game(config)
    while not game.current.finished:
        hand = game.current
        seat = g.waiting_for(hand)
        action = g.auto_action(hand, seat) or (g.pass_(seat) if hand.phase is Phase.CLAIM else g.discard(seat, hand.players[seat].tiles[-1]))
        game = g.apply(game, action)
    data = g.to_save(game)
    data["v"] = 1
    del data["config"]["rules"]["calls"]
    again = g.from_save(data)
    assert not again.config.rules.calls and again.current == game.current


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_random_games_with_calls_keep_every_tile_and_point(seed):
    game = _random_play(seed, steps=1500)
    again = g.from_save(g.to_save(game))
    assert again.logs == game.logs and again.current == game.current


# ---------------------------------------------------------------- チーの面子の並び（点検で見つかった不具合）


@pytest.mark.parametrize("used, called", [("23m", "1m"), ("13m", "2m"), ("12m", "3m")])
def test_chi_melds_win_whichever_tile_was_called(used, called):
    """チーで鳴いた牌が、順子のいちばん小さい牌・真ん中・いちばん大きい牌のどれでも、あがりと判定する。
    （判定ライブラリは、チーの 3 枚が並んでいることを前提にする。鳴いた牌が先頭でないときに、あがれなくなっていた）"""
    # 自分（席 0）：{used} で上家の {called} をチー → 9萬 を切って、5索 の単騎（白の暗刻で役がある）。下家が 5索 を切る
    hand = build_hand([used + "456p789s555z5s9m", "1112223334446p", "111z222z333z7799p", "444z666z777z888p1p"],
                      turn=3, drawn=called, next_draws="5s")
    game = g.apply(game_of(hand), g.discard(3, hand.players[3].drawn))
    assert g.waiting_for(game.current) == 0
    chi = next(a for a in game.current.call_actions(0) if a.move is Move.CHI and kinds_of(a.tiles) == kinds_of(parse_tiles(used)))
    game = g.apply(game, chi)
    meld = game.current.players[0].furo[-1].meld
    assert list(meld.tiles) == sorted(meld.tiles)                          # 面子の牌は、並べて持つ
    game = g.apply(game, g.discard(0, tile_of(game.current, 0, "9m")))
    assert game.current.phase is Phase.DRAW and game.current.turn == 1
    game = drop(game, 1)                                                    # 下家が、ツモった 5索 を切る
    assert g.waiting_for(game.current) == 0 and game.current.ron_check(0).ok
    game = g.apply(game, g.ron(0))
    win = game.current.result.wins[0]
    assert win.seat == 0 and win.judgement.ok and win.judgement.han >= 1

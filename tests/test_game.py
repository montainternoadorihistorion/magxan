"""4 人の局と試合の進行（engine/game.py）のテスト"""
from __future__ import annotations

import random
from dataclasses import replace

import pytest

from engine import game as g
from engine.game import EndKind, Furiten, GameConfig, GameError, HandStart, Phase
from engine.luck import LuckSettings
from engine.rules import Rules
from engine.tiles import NUM_TILES, kind_of, parse_tiles
from engine.wall import LIVE_START, RINSHAN_START, shuffled_tiles
from tests.game_helpers import build_hand, game_of


def tiles_of(text: str) -> list[int]:
    return parse_tiles(text)


def kind(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def find_tile(hand: g.HandState, seat: int, text: str) -> int:
    """その席の手牌（ツモ牌を含む）から、指定した種類の牌を 1 枚"""
    target = kind(text)
    return next(t for t in hand.players[seat].tiles if kind_of(t) == target)


def total_points(hand: g.HandState) -> int:
    return sum(hand.scores) + g.RIICHI_STICK * hand.kyotaku


def conserved(hand: g.HandState) -> bool:
    """手牌・河・副露・まだツモっていない山・王牌を合わせると、136 枚がちょうど 1 枚ずつ。

    鳴かれた捨て牌は、鳴いた人の副露として数える。引いた嶺上牌は手牌として数える。
    加槓を宣言して返事を待っている牌（と、それを槍槓された牌）は、その牌だけ別に数える。
    """
    seen = [t for p in hand.players for t in (*p.tiles, *(d.tile for d in p.river if d.called_by is None), *p.meld_tiles)]
    rest = list(hand.wall_tiles[LIVE_START + hand.live_drawn:RINSHAN_START]) + list(hand.wall_tiles[RINSHAN_START + hand.rinshan_drawn:])
    claim = hand.claim
    if claim is not None and claim.kind is g.ClaimKind.KAKAN and not any(claim.tile in p.meld_tiles for p in hand.players):
        seen.append(claim.tile)
    return sorted(seen + rest) == list(range(NUM_TILES))


# ---------------------------------------------------------------- 始まり


def test_start_deals_thirteen_each_and_dealer_draws_first():
    game = g.start_game(GameConfig(seed=7))
    hand = game.current
    assert hand.phase is Phase.DRAW and hand.turn == hand.dealer == game.first_dealer
    for seat, player in enumerate(hand.players):
        assert len(player.hand) == 13
        assert (player.drawn is not None) == (seat == hand.dealer)
    assert hand.live_remaining == 69
    assert hand.start.round_wind == 27 and hand.start.round_number == 1
    assert hand.seat_wind(hand.dealer) == 27
    assert conserved(hand) and total_points(hand) == 100_000


def test_luck_zero_keeps_the_plain_shuffle():
    """補正 0 なら、山は素のシャッフルのまま（局ごとのシードで混ぜた並び）"""
    game = g.start_game(GameConfig(seed=11))
    assert list(game.current.wall_tiles) == shuffled_tiles("11:0")
    assert all(not d.applied for d in game.current.deals)


def test_human_luck_changes_only_the_human_deal():
    plain = g.start_game(GameConfig(seed=5))
    lucky = g.start_game(GameConfig(seed=5, luck=LuckSettings(100, 0)))
    order = (g.HUMAN - plain.current.dealer) % 4
    human_positions = set(range(order * 13, order * 13 + 13))
    for position in range(52):
        if position not in human_positions:
            assert plain.current.wall_tiles[position] == lucky.current.wall_tiles[position]
    assert plain.current.wall_tiles[122:] == lucky.current.wall_tiles[122:]      # 王牌には触れない
    assert lucky.current.deals[g.HUMAN].candidates > 1
    assert all(lucky.current.deals[s].candidates == 1 for s in (1, 2, 3))         # CPU の補正は 0


def test_first_dealer_and_seats_rotate():
    game = g.start_game(GameConfig(seed=3))
    start = HandStart(number=1, rotation=1, dealer=(game.first_dealer + 1) % 4, honba=0, kyotaku=0, scores=(25000,) * 4)
    assert start.seat_wind(start.dealer) == 27
    assert start.seat_wind((start.dealer + 1) % 4) == 28
    assert start.round_number == 2
    south = replace(start, rotation=4)
    assert south.round_wind == 28 and south.round_number == 1


def test_draws_left_counts_each_seats_future_draws():
    hand = build_hand(["1112223334445m", "6667778889999m", "1112223334445p", "6667778889999p"], turn=0, drawn="1s", live_drawn=63)
    # ツモ山の残り 7 枚：次の人から順に 1・2・3・0・1・2・3 の席がツモる
    assert hand.live_remaining == 7
    assert [hand.draws_left(s) for s in range(4)] == [1, 2, 2, 2]


# ---------------------------------------------------------------- リーチ


def _riichi_hand(**kwargs) -> g.HandState:
    defaults = dict(
        hands=["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"],
        turn=0,
        drawn="5z",
        next_draws="9m9p9s1m",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_riichi_needs_a_tenpai_discard_and_pays_the_stick_after_it_passes():
    hand = _riichi_hand()
    white = find_tile(hand, 0, "5z")
    assert hand.riichi_tiles(0) == (white,)
    game = game_of(hand)
    with pytest.raises(GameError):
        g.apply(game, g.riichi(0, find_tile(hand, 0, "1m")))       # 切ると聴牌にならない
    game = g.apply(game, g.riichi(0, white))
    after = game.current
    me = after.players[0]
    assert me.riichi_paid and me.riichi_at == 0 and me.double_riichi and me.ippatsu
    assert after.scores[0] == 24_000 and after.kyotaku == 1 and total_points(after) == 100_000
    assert after.turn == 1 and after.phase is Phase.DRAW


def test_riichi_needs_1000_points_and_a_draw_left():
    poor = _riichi_hand(scores=(900, 33_000, 33_000, 33_100))
    assert poor.riichi_tiles(0) == ()
    late = _riichi_hand(live_drawn=67, next_draws="")      # 残り 3 枚：このあと自分のツモ番が無い
    assert late.live_remaining == 3 and late.riichi_tiles(0) == ()
    enough = _riichi_hand(live_drawn=66, next_draws="")
    assert enough.live_remaining == 4 and enough.riichi_tiles(0)
    with pytest.raises(GameError, match="1000"):
        g.apply(game_of(poor), g.riichi(0, find_tile(poor, 0, "5z")))


def test_after_riichi_only_the_drawn_tile_can_be_discarded():
    game = g.apply(game_of(_riichi_hand()), g.riichi(0, find_tile(_riichi_hand(), 0, "5z")))
    # 3 人がツモ切りして、自分の番に戻る
    for seat in (1, 2, 3):
        hand = game.current
        game = g.apply(game, g.discard(seat, hand.players[seat].drawn))
    hand = game.current
    assert hand.turn == 0 and hand.players[0].drawn is not None
    with pytest.raises(GameError, match="ツモった牌"):
        g.apply(game, g.discard(0, hand.players[0].hand[0]))
    assert g.auto_action(hand, 0) == g.discard(0, hand.players[0].drawn)


def test_ippatsu_tsumo_on_the_next_draw():
    hand = _riichi_hand(next_draws="9m9p9s1z")      # 自分の次のツモが 東（あがり牌）
    game = g.apply(game_of(hand), g.riichi(0, find_tile(hand, 0, "5z")))
    for seat in (1, 2, 3):
        game = g.apply(game, g.discard(seat, game.current.players[seat].drawn))
    hand = game.current
    assert g.auto_action(hand, 0) == g.tsumo(0)
    game = g.apply(game, g.tsumo(0))
    win = game.current.result.wins[0]
    assert win.ctx.ippatsu and win.ctx.double_riichi and win.ctx.riichi and win.ctx.is_tsumo
    assert win.ctx.ura_indicators            # リーチしたので裏ドラを見る


def test_ippatsu_ends_after_the_next_own_discard():
    hand = _riichi_hand(next_draws="9m9p9s7z" + "8m8p8s1z")     # 1 巡目は外れ、2 巡目にあがり牌
    game = g.apply(game_of(hand), g.riichi(0, find_tile(hand, 0, "5z")))
    for seat in (1, 2, 3, 0, 1, 2, 3):
        game = g.apply(game, g.auto_action(game.current, seat) or g.discard(seat, game.current.players[seat].drawn))
    assert not game.current.players[0].ippatsu
    game = g.apply(game, g.tsumo(0))
    assert not game.current.result.wins[0].ctx.ippatsu


# ---------------------------------------------------------------- ロンとフリテン


def _ron_hand(**kwargs) -> g.HandState:
    """自分（親）が 9筒 を切る。下家と対面は 69筒 待ち（下家は平和、対面は役牌の白）"""
    defaults = dict(
        hands=[
            "1234m 1234p 1234s 1z",
            "234m567m78p345s66s",
            "555z678m345p78p55s",
            "11z22z33z44z11199m",
        ],
        turn=0,
        drawn="9p",
        next_draws="7z7z7z7z",
    )
    defaults.update(kwargs)
    return build_hand(**defaults)


def test_double_ron_both_win_and_only_the_first_gets_honba_and_sticks():
    hand = _ron_hand(honba=2, kyotaku=1, scores=(25_000, 25_000, 25_000, 24_000))
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    claim = game.current
    assert claim.phase is Phase.CLAIM and claim.pending == (1, 2)
    assert g.waiting_for(claim) == 1
    game = g.apply(game, g.ron(1))
    game = g.apply(game, g.ron(2))
    result = game.current.result
    assert result.kind is EndKind.RON
    first, second = result.wins
    assert (first.seat, second.seat) == (1, 2) and first.from_seat == second.from_seat == 0
    assert (first.ctx.honba, first.ctx.kyotaku) == (2, 1)
    assert (second.ctx.honba, second.ctx.kyotaku) == (0, 0)
    assert first.payments[1] == first.judgement.main + 600 + 1000
    assert second.payments[2] == second.judgement.main
    assert result.settlement[0] == -(first.judgement.main + 600 + second.judgement.main)
    assert result.kyotaku == 0 and sum(result.scores) == 100_000
    assert result.renchan is False


def test_head_bump_rule_lets_only_the_first_win():
    hand = _ron_hand(rules=Rules(multiple_ron=False))
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.ron(1)), g.ron(2))
    result = game.current.result
    assert [w.seat for w in result.wins] == [1] and result.bumped == (2,)


def test_dealer_in_a_double_ron_keeps_the_seat():
    # 親を下家（席 1）にする：席 0 が切って、席 1（親）と席 2 がロン
    hand = _ron_hand(dealer=1)
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.ron(1)), g.ron(2))
    assert game.current.result.renchan
    start = g.next_start(game)
    assert start.dealer == 1 and start.honba == 1 and start.rotation == 0


def test_passing_a_win_makes_temporary_furiten_until_own_draw():
    hand = _ron_hand()
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.pass_(1)), g.pass_(2))
    after = game.current
    assert [(m.seat, m.passed) for m in after.misses] == [(1, True), (2, True)]
    # 下家はすぐにツモったので、同巡内フリテンは解けている（雀魂：自分の次のツモで解ける）。対面は、まだ
    assert after.turn == 1 and not after.players[1].missed
    assert after.players[2].missed and after.furiten(2) is Furiten.MISSED
    game = g.apply(game, g.discard(1, after.players[1].drawn))
    assert not game.current.players[2].missed                                 # 対面がツモると解ける


def test_temporary_furiten_blocks_the_next_ron_until_own_draw():
    # 対面（席 2）が 69筒 待ち（役牌の白）。親の 9筒 を見逃す → 下家の 6筒 ではロンできない → 自分がツモったあとの 6筒 ならロンできる
    hand = build_hand(
        ["1234m1234p1234s1z", "11z22z33z44z66z77z1m", "555z678m345p78p55s", "258p369s147m3z4z6z7z"],
        turn=0, drawn="9p", next_draws="6p8s6p", rules=Rules(calls=False),        # 対面は 6筒 をチーできるので、鳴きなしにして確かめる
    )
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    assert game.current.pending == (2,)
    game = g.apply(game, g.pass_(2))
    assert game.current.players[2].missed
    game = g.apply(game, g.discard(1, game.current.players[1].drawn))          # 下家が 6筒 を切る
    after = game.current
    assert after.phase is Phase.DRAW and after.turn == 2                       # 対面はフリテンなのでロンできない
    missed = after.misses[-1]
    assert (missed.seat, missed.passed, missed.check.furiten) == (2, False, Furiten.MISSED)
    assert not after.players[2].missed                                         # 対面がツモった → 同巡内フリテンが解ける
    game = g.apply(game, g.discard(2, after.players[2].drawn))
    game = g.apply(game, g.discard(3, game.current.players[3].drawn))          # 上家が 6筒 を切る
    assert game.current.phase is Phase.CLAIM and game.current.pending == (2,)


def test_own_discard_furiten_and_no_yaku_block_ron_and_count_as_missed():
    # 下家：67m の両面で 5m・8m 待ちだが、自分で 8m を切っている（フリテン）
    # 対面：69s 待ちの役なし（刻子 2 つ・順子・カンチャンでない形）
    hand = build_hand(
        ["1234m1234p1234s1z", "234p567p678s99s67m", "111m999p78s234m55p", "11z22z33z44z55z66z7z"],
        turn=0, drawn="5m", rivers=("", "8m", "", ""), live_drawn=2, rules=Rules(calls=False),
    )
    assert hand.furiten(1) is Furiten.RIVER
    check = hand.ron_check(1, find_tile(hand, 0, "5m"))
    assert check.shape and check.furiten is Furiten.RIVER and not check.ok
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "5m")))
    assert game.current.phase is Phase.DRAW and game.current.turn == 1      # 誰もロンできない
    assert [(m.seat, m.passed, m.check.furiten) for m in game.current.misses] == [(1, False, Furiten.RIVER)]


def test_no_yaku_wait_cannot_ron():
    hand = build_hand(
        ["1234m1234p1234s6s", "11z22z33z44z55z66z7z", "111m999p78s234m55p", "5z5z6z6z7z7z1p1p8p8p1s1s9s"],
        turn=0, drawn="2m",
    )
    check = hand.ron_check(2, find_tile(hand, 0, "6s"))
    assert check.shape and check.furiten is None and not check.yaku and not check.ok
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "6s")))
    assert game.current.phase is Phase.DRAW and game.current.players[2].missed


def test_riichi_furiten_lasts_the_whole_hand():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=0, drawn="9p", rivers=("", "2z", "", ""), riichi=(None, 0, None, None), live_drawn=2,
        kyotaku=1, scores=(25_000, 24_000, 25_000, 25_000),
    )
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    assert game.current.pending == (1,)
    game = g.apply(game, g.pass_(1))
    player = game.current.players[1]
    assert player.riichi_missed and game.current.furiten(1) is Furiten.RIICHI
    # 下家がツモ切りしても、リーチ後の見逃しは解けない
    game = g.apply(game, g.discard(1, player.drawn))
    assert game.current.players[1].riichi_missed and not game.current.players[1].missed


# ---------------------------------------------------------------- ツモ


def test_non_dealer_tsumo_payments_with_honba():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=1, drawn="9p", rivers=("2z", "3z", "", ""), honba=1,
    )
    assert hand.can_tsumo(1)
    game = g.apply(game_of(hand), g.tsumo(1))
    result = game.current.result
    win = result.wins[0]
    j = win.judgement
    assert win.from_seat is None and win.ctx.is_tsumo
    assert win.payments == (-(j.main + 100), j.main + j.additional * 2 + 300, -(j.additional + 100), -(j.additional + 100))
    assert sum(result.scores) == 100_000 and not result.renchan


def test_dealer_tsumo_everyone_pays_the_same():
    hand = build_hand(
        ["234m567m78p345s66s", "1234m1234p1234s1z", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=0, drawn="9p", dealer=0,
    )
    game = g.apply(game_of(hand), g.tsumo(0))
    win = game.current.result.wins[0]
    assert win.ctx.tenhou                          # 親の配牌（最初のツモ）であがった
    each = win.judgement.main
    assert win.payments == (3 * each, -each, -each, -each)
    assert game.current.result.renchan


def test_haitei_and_houtei_on_the_last_tile():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=1, drawn="9p", rivers=("2z", "3z", "", ""), live_drawn=70,
    )
    assert hand.live_remaining == 0
    win = g.apply(game_of(hand), g.tsumo(1)).current.result.wins[0]
    assert win.ctx.haitei
    # 最後のツモ牌を切って、ロンされる（河底）
    last = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "11z22z33z44z11188m", "5z5z6z6z7z7z1s1s9s9s1p9m3s"],
        turn=0, drawn="9p", rivers=("", "", "", ""), live_drawn=70,
    )
    game = g.apply(game_of(last), g.discard(0, find_tile(last, 0, "9p")))
    game = g.apply(game, g.ron(1))
    assert game.current.result.wins[0].ctx.houtei


# ---------------------------------------------------------------- 流局


def _last_discard(tenpai_hands: list[str], **kwargs) -> g.GameState:
    """席 3 が最後の牌（6筒）をツモったところ。席 3 がツモ切りすると流局（么九牌でないので、流し満貫にはならない）"""
    hand = build_hand(tenpai_hands, turn=3, drawn="6p", live_drawn=70, **kwargs)
    game = game_of(hand)
    return g.apply(game, g.discard(3, find_tile(hand, 3, "6p")))


TENPAI = "123m456p789s1122z"       # 東・南 待ち
NOTEN = "147m258p369s3456z"


@pytest.mark.parametrize(
    ("hands", "expected"),
    [
        ([TENPAI, NOTEN, NOTEN, NOTEN], (3000, -1000, -1000, -1000)),
        ([TENPAI, TENPAI, NOTEN, NOTEN], (1500, 1500, -1500, -1500)),
        ([TENPAI, TENPAI, TENPAI, NOTEN], (1000, 1000, 1000, -3000)),
        ([NOTEN, NOTEN, NOTEN, NOTEN], (0, 0, 0, 0)),
    ],
)
def test_exhausted_draw_noten_payments(hands, expected):
    # 同じ牌を 5 枚使わないように、2 人目以降の手牌は色を変える
    shifted = []
    for seat, text in enumerate(hands):
        if text == TENPAI:
            text = ["123m456p789s1122z", "123p456s789m3344z", "123s456m789p5566z", "789m789p789s7z7z11m"][seat]
        else:
            text = ["147m258p369s3456z", "147p258s369m1z5z6z2p", "147s258m369p2z6z4z3m", "258p369s147m1z2z3z4z"][seat]
        shifted.append(text)
    game = _last_discard(shifted, rivers=("", "", "", ""))
    result = game.current.result
    assert result.kind is EndKind.EXHAUSTED
    assert result.tenpai == tuple(h == TENPAI for h in hands)
    assert result.settlement == expected
    assert result.renchan == (hands[0] == TENPAI)           # 親は席 0


def test_exhausted_draw_keeps_sticks_and_adds_honba():
    game = _last_discard(
        ["147m258p369s3456z", "147p258s369m1z5z6z2p", "147s258m369p2z6z4z3m", "258p369s147m1z2z3z4z"],
        kyotaku=2, honba=1, scores=(24_000, 25_000, 24_000, 25_000),
    )
    result = game.current.result
    assert result.kyotaku == 2 and not result.renchan
    start = g.next_start(game)
    assert start.honba == 2 and start.kyotaku == 2 and start.dealer == 1 and start.rotation == 1


def test_nagashi_mangan_replaces_noten_payments():
    rivers = ("", "", "19m19p19s1z2z3z", "")
    hands = ["123m456p789s1122z", "147p258s369m5z6z7z2p", "234m345p456s5677z", "258p369s147m4z4z3z4z"]
    hand = build_hand(hands, turn=3, drawn="7s", live_drawn=70, rivers=rivers)
    game = g.apply(game_of(hand), g.discard(3, find_tile(hand, 3, "7s")))
    result = game.current.result
    assert result.nagashi == (2,)
    assert result.settlement == (-4000, -2000, 8000, -2000)        # 子の流し満貫：親 4000・子 2000（本場は付けない）
    assert result.renchan                                          # 親（席 0）は聴牌なので連荘
    off = build_hand(hands, turn=3, drawn="7s", live_drawn=70, rivers=rivers, rules=Rules(nagashi_mangan=False))
    result = g.apply(game_of(off), g.discard(3, find_tile(off, 3, "7s"))).current.result
    assert result.nagashi == () and result.settlement[0] > 0       # ノーテン罰符になる


# ---------------------------------------------------------------- 途中流局


def test_nine_terminals_on_the_first_draw():
    hand = build_hand(
        ["19m19p19s1234z567m", "234m567m78p345s66s", "222z678m345p78p55s", "33z44z1188m22467p"],
        turn=0, drawn="5z", next_draws="7z7z7z7z", honba=1,
    )
    assert g.nine_kinds(hand.players[0].tiles) >= 9 and hand.can_nine(0)
    game = g.apply(game_of(hand), g.nine(0))
    result = game.current.result
    assert result.kind is EndKind.NINE_TERMINALS and result.caller == 0 and result.renchan
    assert result.settlement == (0, 0, 0, 0)
    assert g.next_start(game).honba == 2 and g.next_start(game).dealer == 0
    off = replace(hand, rules=Rules(abortive_draws=False))
    assert not off.can_nine(0)
    later = build_hand(
        ["19m19p19s1234z567m", "234m567m78p345s66s", "222z678m345p78p55s", "33z44z1188m22467p"],
        turn=0, drawn="5z", rivers=("8m", "", "", ""),
    )
    assert not later.can_nine(0)          # 最初のツモではない


def test_four_winds_abort():
    hand = build_hand(
        ["123m456p789s2345z", "123p456s789m2345z", "123s456m789p2346z", "22m33p44s55m6z7z7z8m9m"],
        turn=3, drawn="1z", rivers=("1z", "1z", "1z", ""), live_drawn=4,
    )
    game = g.apply(game_of(hand), g.discard(3, hand.players[3].drawn))
    assert game.current.result.kind is EndKind.FOUR_WINDS


def test_four_riichi_abort_after_the_fourth_stick():
    hand = build_hand(
        ["123m456p789s1122z", "123p456s789m3344z", "123s456m789p5566z", "789m789p789s1s2s3s7z"],
        turn=3, drawn="2m", rivers=("4m", "4p", "4s", ""), riichi=(0, 0, 0, None), live_drawn=4,
        kyotaku=3, scores=(24_000, 24_000, 24_000, 25_000),
    )
    seven = find_tile(hand, 3, "2m")
    assert seven in hand.riichi_tiles(3)
    game = g.apply(game_of(hand), g.riichi(3, seven))
    result = game.current.result
    assert result.kind is EndKind.FOUR_RIICHI
    assert result.kyotaku == 4 and result.scores[3] == 24_000 and sum(result.scores) + 4000 == 100_000


# ---------------------------------------------------------------- 試合の終わり


PLAIN_RULES = Rules()


def _draw_game(scores, hands, *, rotation, dealer, first_dealer=0, kyotaku=0, length=g.Length.EAST, rules=PLAIN_RULES):
    """親の 1 つ前の人が、最後の牌（6筒）をツモ切りして流局する局"""
    hand = build_hand(hands, turn=(dealer + 3) % 4, drawn="6p", live_drawn=70, dealer=dealer, rotation=rotation,
                      scores=scores, kyotaku=kyotaku, rules=rules)
    config = GameConfig(seed=1, length=length, rules=rules)
    game = game_of(hand, first_dealer=first_dealer, config=config)
    seat = hand.turn
    return g.apply(game, g.discard(seat, find_tile(hand, seat, "6p")))


ALL_NOTEN = ["147m258p369s3456z", "147p258s369m1z5z6z2p", "147s258m369p2z6z4z3m", "258p369s147m1z2z3z4z"]  # 4 人ともノーテン
DEALER3_TENPAI = ["147m258p369s3456z", "147p258s369m1z5z6z2p", "147s258m369p2z6z4z3m", "123m456p789s1122z"]


def test_all_last_dealer_top_over_30000_ends_the_game():
    game = _draw_game((22_000, 20_000, 26_000, 32_000), DEALER3_TENPAI, rotation=3, dealer=3)
    assert game.finished and game.result.reason == "agariyame"
    assert game.result.ranks[3] == 1


def test_all_last_dealer_tenpai_but_not_top_continues():
    game = _draw_game((35_000, 20_000, 22_000, 23_000), DEALER3_TENPAI, rotation=3, dealer=3)
    assert not game.finished and game.between_hands
    assert g.next_start(game).dealer == 3 and g.next_start(game).rotation == 3


def test_extension_when_nobody_reaches_30000_and_sudden_death():
    game = _draw_game((29_000, 28_000, 22_000, 21_000), ALL_NOTEN, rotation=3, dealer=3)
    assert not game.finished
    start = g.next_start(game)
    assert start.rotation == 4 and start.round_wind == 28 and start.dealer == 0       # 南 1 局
    # 延長戦で 30000 点以上の人が出たら、その局で終わる
    ended = _draw_game((25_000, 22_000, 23_000, 30_000), ALL_NOTEN, rotation=4, dealer=0)
    assert ended.finished and ended.result.reason == "sudden_death"


def test_extension_ends_after_its_fourth_hand():
    game = _draw_game((29_000, 28_000, 22_000, 21_000), ALL_NOTEN, rotation=7, dealer=3)
    assert game.finished and game.result.reason == "extension_end"


def test_planned_end_with_someone_over_30000():
    game = _draw_game((31_000, 28_000, 22_000, 19_000), ALL_NOTEN, rotation=3, dealer=3)
    assert game.finished and game.result.reason == "planned"


def test_hanchan_continues_into_south():
    game = _draw_game((31_000, 28_000, 22_000, 19_000), ALL_NOTEN, rotation=3, dealer=3, length=g.Length.SOUTH)
    assert not game.finished


def test_leftover_sticks_go_to_the_top_and_ties_follow_seat_order():
    game = _draw_game((30_000, 30_000, 19_000, 19_000), ALL_NOTEN, rotation=3, dealer=3, first_dealer=1, kyotaku=2)
    result = game.result
    # 席 0 と席 1 が同点。起家は席 1 なので、席 1 が 1 位
    assert result.ranks[1] == 1 and result.ranks[0] == 2
    assert result.kyotaku_to == 1 and result.scores[1] == 32_000 and sum(result.scores) == 100_000


def test_tobi_ends_the_game():
    hand = build_hand(
        ["1234m1234p1234s1z", "234m567m78p345s66s", "555z678m345p78p55s", "11z22z33z44z11199m"],
        turn=0, drawn="9p", next_draws="7z7z7z7z", scores=(500, 33_000, 33_000, 33_500),
    )
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.ron(1)), g.pass_(2))
    assert game.current.result.scores[0] < 0
    assert game.finished and game.result.reason == "tobi"
    no_tobi = replace(hand, rules=Rules(tobi=False))
    game = g.apply(game_of(no_tobi, config=GameConfig(seed=1, rules=Rules(tobi=False))), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.ron(1)), g.pass_(2))
    assert not game.finished


def test_next_hand_rotates_the_dealer_after_a_child_win():
    hand = _ron_hand(honba=3, kyotaku=1, scores=(25_000, 25_000, 25_000, 24_000))
    game = g.apply(game_of(hand), g.discard(0, find_tile(hand, 0, "9p")))
    game = g.apply(g.apply(game, g.ron(1)), g.pass_(2))
    start = g.next_start(game)
    assert start.dealer == 1 and start.honba == 0 and start.kyotaku == 0 and start.rotation == 1
    following = g.next_hand(game)
    assert len(following.hands) == 2 and following.current.start == start


# ---------------------------------------------------------------- できない行動・再生・保存


def test_illegal_actions_are_refused():
    game = g.start_game(GameConfig(seed=2))
    hand = game.current
    other = (hand.turn + 1) % 4
    with pytest.raises(GameError):
        g.apply(game, g.discard(other, hand.players[other].hand[0]))       # 手番でない
    with pytest.raises(GameError):
        g.apply(game, g.discard(hand.turn, hand.players[other].hand[0]))   # 手牌にない
    with pytest.raises(GameError):
        g.apply(game, g.ron(other))                                         # ロンの返事待ちではない


def _random_play(seed: int, steps: int = 400) -> g.GameState:
    rnd = random.Random(seed)
    game = g.start_game(GameConfig(seed=seed))
    for _ in range(steps):
        if game.finished:
            break
        if game.between_hands:
            game = g.next_hand(game)
            continue
        hand = game.current
        seat = g.waiting_for(hand)
        action = g.auto_action(hand, seat)
        if action is None:
            if hand.phase is Phase.CLAIM:
                options = hand.call_actions(seat)
                rons = [a for a in options if a.move is g.Move.RON]
                calls = [a for a in options if a.move is not g.Move.RON]
                if rons and rnd.random() < 0.7:
                    action = rons[0]
                elif calls and rnd.random() < 0.4:
                    action = rnd.choice(calls)
                else:
                    action = g.pass_(seat)
            elif hand.can_tsumo(seat):
                action = g.tsumo(seat)
            elif hand.riichi_tiles(seat) and rnd.random() < 0.6:
                action = g.riichi(seat, rnd.choice(hand.riichi_tiles(seat)))
            elif (hand.ankan_tiles(seat) or hand.kakan_tiles(seat)) and rnd.random() < 0.5:
                kans = [g.ankan(seat, t) for t in hand.ankan_tiles(seat)] + [g.kakan(seat, t) for t in hand.kakan_tiles(seat)]
                action = rnd.choice(kans)
            else:
                player = hand.players[seat]
                legal = [t for t in player.tiles if kind_of(t) not in hand.forbidden]
                if player.in_riichi:
                    legal = [player.drawn]
                action = g.discard(seat, rnd.choice(legal))
        game = g.apply(game, action)
        assert conserved(game.current) and total_points(game.current) == 100_000
    return game


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_random_play_conserves_tiles_and_points_and_replays(seed):
    game = _random_play(seed)
    again = g.from_save(g.to_save(game))
    assert again.logs == game.logs
    assert again.current == game.current and again.result == game.result


@pytest.mark.parametrize(
    "data",
    [
        None, [], "x", {}, {"v": 2}, {"v": 1, "config": {"seed": 1}, "logs": []},
        {"v": 1, "config": {"seed": 1}, "logs": [[["x"]]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[0, "d"]]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[9, "d", 1]]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[0, "z", 1]]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[0, "d", 999]]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[1, "t"]]]},
        {"v": 1, "config": {"seed": -1}, "logs": [[]]},
        {"v": 1, "config": {"seed": 1, "length": "north"}, "logs": [[]]},
        {"v": 1, "config": {"seed": 1, "cpu_level": 3}, "logs": [[]]},
        {"v": 1, "config": {"seed": 1, "rules": {"tobi": "no"}}, "logs": [[]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[]] * 2},             # 1 局目が終わっていないのに 2 局目
        {"v": 1, "config": {"seed": 1}, "logs": [[None]]},
        {"v": 1, "config": {"seed": 1}, "logs": [[[0, "d", True]]]},
    ],
)
def test_broken_saves_raise_value_error_only(data):
    with pytest.raises(ValueError):
        g.from_save(data)


def test_save_round_trip_keeps_the_config():
    config = GameConfig(seed=42, length=g.Length.SOUTH, luck=LuckSettings(50, 25), cpu_level=g.CpuLevel.WEAK, rules=Rules(tobi=False))
    assert GameConfig.from_dict(config.to_dict()) == config
    game = g.start_game(config)
    assert g.from_save(g.to_save(game)).config == config


# ---------------------------------------------------------------- 点検で確かめた境目（テストで固定する）


def test_ron_on_the_riichi_tile_voids_the_stick():
    """リーチ宣言牌でロンされたら、リーチは成立せず、リーチ棒も出ない。前からの供託は、あがった人がもらう"""
    hand = build_hand(
        ["123m456p789s1122z", "234m567m78p345s66s", "147m258p369s3467z", "369m147p258s3567z"],
        turn=0, drawn="9p", next_draws="9m9p9s1m", kyotaku=1, scores=(25_000, 25_000, 25_000, 24_000),
    )
    game = g.apply(game_of(hand), g.riichi(0, find_tile(hand, 0, "9p")))
    assert game.current.phase is Phase.CLAIM and game.current.pending == (1,)
    game = g.apply(game, g.ron(1))
    result = game.current.result
    assert not game.current.players[0].riichi_paid and result.kyotaku == 0
    assert result.wins[0].ctx.kyotaku == 1 and not result.wins[0].ctx.riichi
    assert sum(result.scores) + 1000 * result.kyotaku == 100_000
    assert result.scores[0] == 25_000 + result.wins[0].payments[0]          # リーチ棒の 1000 点は引かれていない


@pytest.mark.parametrize("multiple", [True, False])
def test_triple_ron_and_head_bump(multiple):
    """3 人が同じ牌でロン：全員のあがり（本場・供託は、捨てた人の下家だけ）。頭ハネなら、下家だけ"""
    rules = Rules(multiple_ron=multiple)
    hand = build_hand(
        ["1234m1234s1z2z3z4z1p", "234m567m78p345s66s", "555z678m345p78p55s", "666z777z123s78p99m"],
        turn=0, drawn="9p", next_draws="9s", honba=2, kyotaku=2, scores=(26_000, 25_000, 25_000, 22_000), rules=rules,
    )
    game = g.apply(game_of(hand, config=GameConfig(seed=1, rules=rules)), g.discard(0, find_tile(hand, 0, "9p")))
    assert game.current.pending == (1, 2, 3)
    while game.current.phase is Phase.CLAIM:
        game = g.apply(game, g.ron(g.waiting_for(game.current)))
    result = game.current.result
    if multiple:
        assert [w.seat for w in result.wins] == [1, 2, 3] and result.bumped == ()
        assert [(w.ctx.honba, w.ctx.kyotaku) for w in result.wins] == [(2, 2), (0, 0), (0, 0)]
    else:
        assert [w.seat for w in result.wins] == [1] and result.bumped == (2, 3)
    assert sum(result.scores) + 1000 * result.kyotaku == 100_000


@pytest.mark.parametrize("second_round", [False, True])
def test_ippatsu_ron_only_before_the_next_own_discard(second_round):
    """一発のロン：リーチのあと、自分が次に切るまでに出たあがり牌でロンすると付く。1 回切ったあとは付かない"""
    draws = "9s9p8s7z1z" if second_round else "1z"
    hand = build_hand(
        ["123m456p789s1122z", "147p258s369m5z6z7z2p", "147s258m369p3z6z4z3m", "258p369s147m3z4z6z8m"],
        turn=0, drawn="5z", next_draws=draws,
    )
    game = g.apply(game_of(hand), g.riichi(0, find_tile(hand, 0, "5z")))
    while game.current.phase is not Phase.CLAIM and game.current.result is None:
        current = game.current
        seat = g.waiting_for(current)
        game = g.apply(game, g.auto_action(current, seat) or g.discard(seat, current.players[seat].drawn))
    assert game.current.phase is Phase.CLAIM and game.current.pending == (0,)
    game = g.apply(game, g.ron(0))
    win = game.current.result.wins[0]
    assert win.seat == 0 and win.ctx.ippatsu is (not second_round)


def test_max_hands_ends_the_game_instead_of_failing(monkeypatch):
    """局の数が上限に達したら、試合を終える（飛びなしで連荘が続くと、終わらないことがあるため）"""
    from engine.cpu import advance, all_cpu

    monkeypatch.setattr(g, "MAX_HANDS", 2)
    game = advance(g.start_game(GameConfig(seed=3, rules=Rules(tobi=False))), cpu_seats=all_cpu())
    while not game.finished:
        game = advance(g.next_hand(game), cpu_seats=all_cpu())
    assert len(game.hands) == 2 and game.result.reason == "max_hands"
    assert "max_hands" in g.END_REASONS
    assert g.from_save(g.to_save(game)).result == game.result

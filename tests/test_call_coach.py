"""鳴きの判断のコーチ：役が残るか・打点・速さを比べて、おすすめを出す"""
from __future__ import annotations

from engine import game as g
from engine.call_coach import CallGrade, YakuStatus, call_advice, call_name, judge_call, outlook_of
from engine.game import Move
from engine.melds import pon
from engine.tiles import kind_of, parse_tiles
from tests.game_helpers import build_hand, game_of


def _claim(hands, tile: str, **kwargs) -> g.HandState:
    """上家（席 3）が tile を切って、自分（席 0）が返事をする番"""
    hand = build_hand(hands, turn=3, drawn=tile, **kwargs)
    game = g.apply(game_of(hand), g.discard(3, hand.players[3].drawn))
    while g.waiting_for(game.current) not in (0, None):
        game = g.apply(game, g.pass_(g.waiting_for(game.current)))
    assert g.waiting_for(game.current) == 0
    return game.current


YAKUHAI = ["55z23m46p678s13s9m1z", "147m258p369s1234z", "258m258p258s6z7z9p9p", "147m147p147s2z3z4z6z"]
NO_YAKU = ["23m456p678s34s99p5z", "147m258p369s1234z", "19m19p19s4z4z6z6z7z7z2s", "258m147p369s6m7m9s1z"]
KUITAN = ["345m67p345s66s2p8s7m", "147m258p369s1234z", "19m19p19s4z4z5z5z6z6z7z", "258m147p369s1z7z9p8m"]
BIG_DROP = ["234m234p23s567s8p5m", "147m258p369s1z2z3z5z", "19m19p19s4z5z6z7z7z8s8s", "258m147p369s1z6z9p8m"]


def test_yakuhai_pon_secures_a_yaku_and_is_recommended():
    hand = _claim(YAKUHAI, "5z")
    advice = call_advice(hand, 0)
    assert advice is not None and [o.action.move for o in advice.calls] == [Move.PON]
    stay, call = advice.stay.outlook, advice.calls[0].outlook
    assert stay.menzen and stay.status is YakuStatus.RIICHI           # 門前：リーチで役が付けられる
    assert call.status is YakuStatus.SECURED and call.secured[0].name == "役牌 白"
    assert advice.calls[0].gains_yakuhai and advice.recommend == advice.calls[0].action
    assert "役牌 白" in advice.reason


def test_chi_that_leaves_no_yaku_is_warned_and_counted():
    hand = _claim(NO_YAKU, "1m")
    advice = call_advice(hand, 0)
    option = advice.calls[0]
    assert option.outlook.status is YakuStatus.NONE and option.outlook.shanten == 0      # 聴牌はするが、役がない
    assert advice.recommend is None and "役が見えなくなる" in advice.reason and advice.short == "鳴くと役が見えなくなる"
    decision = judge_call(advice, option.action, number=3)
    assert decision.grade is CallGrade.BAD and decision.no_yaku and decision.called and not decision.followed
    passed = judge_call(advice, g.pass_(0), number=3)
    assert passed.grade is CallGrade.GOOD and not passed.no_yaku and passed.followed


def test_kuitan_chi_that_speeds_up_is_recommended():
    hand = _claim(KUITAN, "5p")
    advice = call_advice(hand, 0)
    option = advice.calls[0]
    assert option.outlook.status is YakuStatus.ON_PATH and option.outlook.shanten < advice.stay.outlook.shanten
    assert [c.name for c in option.outlook.path_yaku][:1] == ["断么九"]
    assert advice.recommend == option.action
    assert kind_of(option.discard) not in g.kuikae_kinds(Move.CHI, hand.claim.tile, option.action.tiles)
    assert judge_call(advice, option.action, number=2).grade is CallGrade.GOOD
    passed = judge_call(advice, g.pass_(0), number=2)
    assert passed.grade is CallGrade.SOSO and call_name(option.action) in passed.text


def test_no_calls_recommended_when_facing_a_riichi_and_not_tenpai_after_it():
    hand = _claim(KUITAN, "5p", riichi=(None, 0, None, None), rivers=("", "9m", "", ""))
    advice = call_advice(hand, 0)
    assert advice.threatened and advice.recommend is None and "リーチを受けている" in advice.reason


def test_big_value_drop_suggests_staying_closed():
    hand = _claim(BIG_DROP, "4s")
    advice = call_advice(hand, 0)
    stay = advice.stay.outlook
    assert stay.shanten == 1 and stay.han == 3                       # リーチ 1 ＋ 三色同順 2（目安）
    best = advice.best_call
    assert best.outlook.shanten == 0 and best.outlook.han == 1
    assert advice.recommend is None and "大きく下がる" in advice.reason


def test_daiminkan_is_never_recommended():
    hand = _claim(["555z23m46p678s13s9m", "147m258p369s1234z", "258m258p258s6z7z9p9p", "147m147p147s2z3z4z6z"], "5z")
    advice = call_advice(hand, 0)
    assert [o.action.move for o in advice.calls] == [Move.PON, Move.KAN]
    assert advice.recommend is None or advice.recommend.move is not Move.KAN


def test_outlook_secures_a_value_triplet_counts_dora_and_drops_riichi_after_calls():
    hand = _claim(YAKUHAI, "5z", dora="1m")                          # ドラは 2萬
    closed = outlook_of(parse_tiles("555z23m46p678s13s9m"), (), hand=hand, seat=0)
    assert closed.status is YakuStatus.SECURED and closed.secured[0].name == "役牌 白" and closed.can_riichi
    assert closed.dora == 1 and closed.han == 1 + 1 + 1                # 役牌 1 ＋ リーチ 1 ＋ ドラ 1（いまの形で付く役はほかに無い）
    opened = outlook_of(parse_tiles("23m46p678s13s9m"), (pon(parse_tiles("555z")),), hand=hand, seat=0)
    assert opened.status is YakuStatus.SECURED and not opened.menzen and not opened.can_riichi


def test_call_advice_is_none_without_call_options():
    hand = build_hand(YAKUHAI, turn=0, drawn="1p")
    assert call_advice(hand, 0) is None


# ---------------------------------------------------------------- 点検で見つかった局面


def _after_discard(hands, tile: str, **kwargs) -> g.HandState:
    """上家（席 3）がツモった tile をそのまま切ったところ（自分の返事は、まだ）"""
    hand = build_hand(hands, turn=3, drawn=tile, **kwargs)
    return g.apply_hand(g.GameConfig(seed=1), hand, g.discard(3, hand.players[3].drawn))


def test_fourth_tile_of_a_concealed_value_triplet_is_not_called():
    """役牌をもう 3 枚持っていれば、役は付いている。4 枚目をポンしても役は増えず、門前を失う（CPU も鳴かない）"""
    from engine.cpu import decide

    hand = _after_discard(["555z234m678p39s1m1z", "1112223334445m", "6667778889991p", "123456789s1234z"], "5z", next_draws="9m9m9m9m")
    advice = call_advice(hand, 0)
    assert advice.stay.outlook.status is YakuStatus.SECURED
    assert all(not o.gains_yakuhai for o in advice.calls)
    assert advice.recommend is None
    assert judge_call(advice, g.pass_(0), number=1).grade is CallGrade.GOOD
    assert decide(hand, 0, g.CpuLevel.NORMAL).move is Move.PASS


def test_calling_the_riichi_declaration_tile_counts_as_facing_riichi():
    """宣言牌そのものを鳴くときも、鳴けばリーチが成立する。鳴いても聴牌しないなら、コーチも CPU も鳴かない"""
    from engine.cpu import decide

    hand = build_hand(["246m246778p4588s", "3334445556667z", "1117779993336s", "123456789p1122z"], turn=3, drawn="5m",
                      next_draws="1m1m1m1m")
    assert hand.players[3].drawn in hand.riichi_tiles(3)
    declared = g.apply_hand(g.GameConfig(seed=1), hand, g.riichi(3, hand.players[3].drawn))
    assert declared.players[3].in_riichi and not declared.players[3].riichi_paid
    advice = call_advice(declared, 0)
    assert advice.threatened and advice.recommend is None and "リーチを受けている" in advice.reason
    assert all(o.outlook.shanten > 0 for o in advice.calls)
    assert decide(declared, 0, g.CpuLevel.NORMAL).move is Move.PASS


def test_a_call_that_slows_the_hand_says_so():
    hand = _after_discard(["234m678p34s99m555z", "1112223336667p", "1112227778889s", "444555666m1123z"], "5z", next_draws="9p9p")
    advice = call_advice(hand, 0)
    pon = next(o for o in advice.calls if o.action.move is Move.PON)
    assert advice.stay.outlook.shanten == 0 and pon.outlook.shanten == 1
    assert advice.recommend is None and advice.reason.startswith("鳴くと遅くなる（聴牌 → 1 向聴）")


def test_calling_instead_of_a_possible_ron_is_graded_as_a_missed_win():
    """ロンできる牌で鳴いたら「ロンできた」（✗）。ロンも鳴きも見送ったときは、鳴きの評価をしない（ロンの見送りとして知らせる）"""
    from engine.review import judge_action

    hand = _after_discard(["123456m789s55p55z", "1112223336667p", "1112223334449s", "777888999m1236z"], "5z", next_draws="9p9p")
    assert hand.ron_check(0).ok
    pon = next(a for a in hand.call_actions(0) if a.move is Move.PON)
    decision = judge_action(hand, 0, pon)
    assert decision is not None and decision.grade is CallGrade.BAD and decision.ron_missed
    assert decision.label == "ロンできた" and not decision.followed
    assert judge_action(hand, 0, g.pass_(0)) is None


def test_call_decision_headline_does_not_repeat_the_recommendation():
    """答え合わせの案内：評価の言葉がおすすめを言っているとき（見送るのがおすすめだった）は「（おすすめは 見送る）」をくり返さない"""
    from html_helpers import text_of

    from ui.game_view import call_decision_headline_html
    from ui.ruby import Rubifier

    drop = _claim(BIG_DROP, "4s")
    advice = call_advice(drop, 0)
    called = judge_call(advice, advice.best_call.action, number=3)
    assert called.label == "見送るのがおすすめだった"
    text = text_of(call_decision_headline_html(called, Rubifier(), aka=True))
    assert "見送るのがおすすめだった" in text and "おすすめは" not in text
    kuitan = _claim(KUITAN, "5p")
    advice = call_advice(kuitan, 0)
    passed = judge_call(advice, g.pass_(0), number=2)
    text = text_of(call_decision_headline_html(passed, Rubifier(), aka=True))
    assert "鳴くのも有力だった（おすすめは チー" in text

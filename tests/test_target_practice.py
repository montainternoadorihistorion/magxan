"""役指定練習（配牌とツモを狙う役に近づける。その役を狙うコーチ）のテスト。

確かめること
  * 配牌の補正は、まだ誰も見ていない牌の並べ替えだけ。王牌には触れず、牌の枚数も変わらない
  * 補正のあと、配牌は決めた距離まで役に近づいていて、足りない牌はツモ山に残っている
  * 補正 0 では何も変えない
  * ツモの補正が引き寄せるのは、狙う役に近づく牌（無ければ、ふつうの有効牌）
  * コーチのおすすめは、役までの距離がいちばん小さい切り方。切った牌の評価が、距離の変化と合っている
"""
from __future__ import annotations

import pytest

from engine import practice
from engine.analysis import target as tg
from engine.analysis.shanten import shanten_of
from engine.analysis.ukeire import acceptance
from engine.coach import Position
from engine.luck import LuckSettings, aim_deal, target_goal
from engine.practice import TSUMO, PracticeConfig, discard, riichi
from engine.scoring.context import WinContext
from engine.scoring.explain import explain
from engine.scoring.notation import make_context
from engine.target_coach import TargetGrade, judge_target, target_advice, target_result
from engine.tiles import EAST, SOUTH, counts34, kind_of, parse_tiles
from engine.wall import HAND_SIZE, LIVE_END, LIVE_START, Wall, shuffled_tiles

WINDS = {"seat_wind": SOUTH, "round_wind": EAST}
UNUSED = range(HAND_SIZE, LIVE_START)
SAMPLE_KEYS = ("tanyao", "sanshoku", "chiitoitsu", "honitsu", "kokushi", "daisangen", "ryuuiisou", "chuuren")


def _aim(seed: int, key: str, level: int = 75, *, unused=UNUSED, allow_tenpai: bool = False):
    raw = shuffled_tiles(seed)
    wall = Wall(list(raw))
    report = aim_deal(
        wall, 0, LuckSettings(level, level, allow_tenpai), seed, target=key, unused_positions=unused,
        need_tenpai=key in practice.DEAL_TENPAI_TARGETS, **WINDS,
    )
    return raw, wall, report


def _kind(code: str) -> int:
    return kind_of(parse_tiles(code)[0])


# ---------------------------------------------------------------- 配牌


def test_target_goal_by_level():
    assert target_goal(0) is None
    assert [target_goal(level) for level in (5, 25, 30, 50, 55, 75, 80, 100)] == [4, 4, 3, 3, 2, 2, 1, 1]
    assert target_goal(100, allow_tenpai=True) == 0 and target_goal(75, allow_tenpai=True) == 2
    assert target_goal(25, need_tenpai=True) == 0 and target_goal(0, need_tenpai=True) is None


@pytest.mark.parametrize("key", SAMPLE_KEYS)
def test_aimed_deal_only_rearranges_unseen_tiles(key):
    for seed in range(25):
        raw, wall, report = _aim(seed, key)
        wall.check()                                                   # 136 枚が、ちょうど 1 枚ずつ
        assert wall.tiles[LIVE_END:] == raw[LIVE_END:]                 # 王牌（嶺上牌・ドラ表示牌・裏ドラ表示牌）は、そのまま
        assert report.target == key and report.candidates == 1 and report.chosen == 0
        again = _aim(seed, key)[1]
        assert again.tiles == wall.tiles                               # 同じ番号なら、同じ結果
        if report.chosen_distance is None:                             # この山では作れない（必要な牌が王牌にある）
            assert report.swaps == 0 and wall.tiles == raw
            continue
        goal = 2
        assert report.chosen_distance == min(report.original_distance, goal)
        assert report.swaps == max(0, report.original_distance - goal)
        assert report.applied == (report.swaps > 0)
        hand = counts34(wall.dealt_hand(0))
        live = counts34(wall.tiles[LIVE_START:LIVE_END])
        plan = tg.target_plan(hand, key, available=live, **WINDS)
        assert plan.distance == report.chosen_distance                # 足りない牌は、ツモ山に残っている
        assert report.chosen_shanten == shanten_of(hand) <= report.chosen_distance


def test_aimed_deal_without_unused_tiles_keeps_the_other_seats():
    """対局で使うときの形：ほかの席の配牌には触れず、ツモ山とだけ入れ替える"""
    changed = 0
    for seed in range(30):
        raw, wall, report = _aim(seed, "sanshoku", unused=())
        assert wall.tiles[HAND_SIZE:LIVE_START] == raw[HAND_SIZE:LIVE_START] and wall.tiles[LIVE_END:] == raw[LIVE_END:]
        assert report.moved == 0
        changed += report.swaps > 0
    assert changed >= 25


def test_stronger_luck_brings_the_deal_closer():
    for key in ("sanshoku", "kokushi"):
        distances = {}
        for level in (25, 50, 75, 100):
            found = [_aim(seed, key, level)[2].chosen_distance for seed in range(20)]
            distances[level] = [d for d in found if d is not None]
            assert max(distances[level]) <= target_goal(level)
        assert sum(distances[25]) > sum(distances[100])
    assert all(_aim(seed, "sanshoku", 100, allow_tenpai=True)[2].chosen_distance == 0 for seed in range(10))


def test_zero_luck_changes_nothing():
    for key in SAMPLE_KEYS:
        raw, wall, report = _aim(3, key, 0)
        assert wall.tiles == raw and report.swaps == report.moved == 0 and not report.applied
        assert report.original_distance == report.chosen_distance


def test_double_riichi_deal_is_tenpai():
    for seed in range(15):
        _, wall, report = _aim(seed, "double_riichi", 25)
        assert report.chosen_distance == 0 == shanten_of(counts34(wall.dealt_hand(0)))


# ---------------------------------------------------------------- 一人練習への組み込み


def test_config_with_target_roundtrip_and_validation():
    config = PracticeConfig(seed=12, luck=LuckSettings(75, 75), target="sanshoku")
    assert PracticeConfig.from_dict(config.to_dict()) == config
    assert PracticeConfig.from_dict({"seed": 12}).target is None                 # 古い記録には target が無い
    for bad in ("toitoi", "no_such_yaku", 3):
        with pytest.raises(ValueError):
            PracticeConfig(seed=1, target=bad)
    with pytest.raises(ValueError):
        PracticeConfig.from_dict({"seed": 1, "target": "haitei"})


def test_target_hand_is_reproducible_and_replayable():
    config = PracticeConfig(seed=7, luck=LuckSettings(75, 75), target="honitsu")
    first = practice.start(config)
    assert practice.start(config) == first
    assert first.deal.target == "honitsu" and first.deal.chosen_distance == 2
    state = first
    actions = []
    while not state.finished and len(actions) < 8:
        action = discard(target_advice(practice.position_of(state), "honitsu").pick.tile) if not state.can_tsumo else TSUMO
        actions.append(action)
        state = practice.apply(state, action)
    assert practice.replay(config, actions) == state
    assert practice.from_save(practice.to_save(state)) == state
    # 役を変えれば配牌が変わる。補正 0 なら、役を指定しても素の山のまま
    assert practice.start(PracticeConfig(seed=7, luck=LuckSettings(75, 75), target="tanyao")).hand != first.hand
    plain = practice.start(PracticeConfig(seed=7))
    assert practice.start(PracticeConfig(seed=7, target="honitsu")).wall_tiles == plain.wall_tiles


def test_shapeless_targets_use_the_ordinary_deal_luck():
    luck = LuckSettings(75, 75)
    plain = practice.start(PracticeConfig(seed=5, luck=luck))
    for key in ("riichi", "ippatsu", "menzen_tsumo"):
        state = practice.start(PracticeConfig(seed=5, luck=luck, target=key))
        assert state.hand == plain.hand and state.deal.target == ""


def test_target_draw_luck_brings_tiles_that_help_the_yaku():
    """補正で入れ替わったツモは、その時点で「狙う役に近づく牌」か、（それが山に無いときの）ふつうの有効牌"""
    swapped = helpful = 0
    for seed in range(12):
        config = PracticeConfig(seed=seed, luck=LuckSettings(75, 100), target="sanshoku", seat_wind=SOUTH)
        state = practice.start(config)
        while not state.finished:
            before = state
            pick = target_advice(practice.position_of(state), "sanshoku").pick
            if state.can_tsumo or pick is None:
                break
            state = practice.apply(state, discard(pick.tile))
            draw = state.last_draw
            if state.finished or not draw.luck.swapped:
                continue
            swapped += 1
            hand = counts34(state.hand)
            wall = before.wall_tiles[LIVE_START + before.turn:LIVE_END]          # このツモの前に、山に残っていた牌
            closer = tg.target_tiles(hand, "sanshoku", available=counts34(wall), **WINDS)
            ordinary = [kind for kind, _ in acceptance(hand, [4] * 34).tiles]
            assert kind_of(draw.tile) in (closer or ordinary)
            helpful += kind_of(draw.tile) in closer
    assert swapped >= 20 and helpful >= swapped * 0.9


def test_double_riichi_practice_does_not_pull_the_first_draw():
    lucky_first = 0
    for seed in range(40):
        config = PracticeConfig(seed=seed, luck=LuckSettings(100, 100), target="double_riichi")
        state = practice.start(config)
        assert shanten_of(counts34(state.hand)) == 0                # 配牌で聴牌
        assert not state.draws[0].luck.rolled                         # 最初のツモには、補正をかけない
        lucky_first += state.can_tsumo
        if not state.can_tsumo:
            assert state.riichi_discards                              # 最初の打牌で、リーチできる
            after = practice.apply(state, riichi(state.riichi_discards[0]))
            assert after.riichi_index == 0
    assert lucky_first <= 8                                           # 最初のツモであがるのは、たまたまのときだけ


def test_ippatsu_practice_boosts_the_draw_right_after_riichi():
    """一発を狙う練習：リーチのすぐ次のツモだけ、補正の確率が 4 倍になる（強 0.25 → 1.0）"""
    ippatsu = hands = 0
    for seed in range(60):
        config = PracticeConfig(seed=seed, luck=LuckSettings(75, 75), target="ippatsu")
        state = practice.start(config)
        while not state.finished and not state.riichi_discards and not state.can_tsumo:
            state = practice.apply(state, discard(target_advice(practice.position_of(state), "ippatsu").pick.tile))
        if state.finished or state.can_tsumo or state.draws_left < 2:
            continue
        pick = target_advice(practice.position_of(state), "ippatsu").pick
        if pick.tile not in state.riichi_discards or pick.total == 0:
            continue
        after = practice.apply(state, riichi(pick.tile))
        hands += 1
        ippatsu += after.result.win is not None and after.result.win.ippatsu
    assert hands >= 30 and ippatsu >= hands * 0.85


def test_following_the_coach_makes_the_yaku():
    made = 0
    for key in ("sanshoku", "chiitoitsu", "honitsu"):
        for seed in range(4):
            config = PracticeConfig(seed=seed, luck=LuckSettings(100, 100), target=key)
            state = practice.start(config)
            while not state.finished:
                if state.can_tsumo:
                    win = practice.apply(state, TSUMO)
                    if target_result(explain(win.result.win), key).achieved or state.draws_left == 0:
                        state = win
                        continue
                advice = target_advice(practice.position_of(state), key)
                tile = advice.pick.tile if advice.pick is not None else state.drawn
                state = practice.apply(state, discard(tile))
            if state.result.win is not None:
                made += target_result(explain(state.result.win), key).achieved
    assert made >= 10            # 12 局のうち（補正が最大なら、ほとんど成立する）


# ---------------------------------------------------------------- コーチ


def _position(text: str, *, drawn: str | None = None, visible: str = "", draws_left: int = 10) -> Position:
    used: set[int] = set()
    tiles = parse_tiles(text, used=used)
    used.update(tiles)
    seen = parse_tiles(visible, used=used)
    drawn_tile = next(t for t in tiles if kind_of(t) == _kind(drawn)) if drawn else None
    return Position(tiles=tuple(tiles), visible=tuple(seen), draws_left=draws_left, drawn=drawn_tile, can_riichi=True, **WINDS)


def test_advice_prefers_the_yaku_over_speed():
    # 234萬・234筒・245索・789萬 と、雀頭の北。速さなら 2索 を切って 45索 の両面にする（待ち 8 枚）。
    # 三色同順を狙うなら 5索 を切って、24索 で 3索 を待つ（待ちは 4 枚に減るが、三色が付く）
    position = _position("234m234p245s789m44z")
    advice = target_advice(position, "sanshoku")
    assert advice.possible and not advice.won and advice.name == "三色同順" and not advice.shapeless
    assert kind_of(advice.pick.tile) == _kind("5s") and advice.pick.distance == 0 and advice.pick.missing == 1
    assert advice.pick.closer == ((_kind("3s"), 4),)
    assert advice.speed_kind == _kind("2s") and advice.differs_from_speed
    distances = [c.distance for c in advice.candidates]
    assert distances == sorted(distances) and advice.pick is advice.candidates[0]
    assert advice.plan.distance == advice.pick.distance
    best = advice.best
    assert all(c.distance == advice.pick.distance and c.total == advice.pick.total for c in best)
    assert advice.candidate(_kind("3m")).distance > advice.pick.distance          # 234萬 をくずすと遠ざかる
    assert target_advice(position, "sanshoku") is advice                          # 同じ局面は、計算をくり返さない


def test_advice_for_a_finished_or_hopeless_target():
    won = target_advice(_position("234m234p234s789m44z"), "sanshoku")
    assert won.won and won.pick is None and won.distance == -1
    # 国士無双：中が 1 枚も手に無く、残りの 4 枚も見えている → もう作れない
    position = _position("19m19p19s123456z55m", visible="7777z")
    hopeless = target_advice(position, "kokushi")
    assert not hopeless.possible and hopeless.pick is None and hopeless.candidates == ()
    assert judge_target(hopeless, position.tiles[0], position) is None


def test_judging_discards_against_the_target():
    position = _position("234m234p245s789m44z")
    advice = target_advice(position, "sanshoku")
    pick = advice.pick
    best = judge_target(advice, pick.tile, position)
    assert best.grade is TargetGrade.BEST and best.is_best and "三色同順" in best.text and str(pick.missing) in best.text

    tile_3m = next(t for t in position.tiles if kind_of(t) == _kind("3m"))
    farther = judge_target(advice, tile_3m, position)
    assert farther.grade is TargetGrade.FARTHER and farther.label == "三色同順から遠ざかった"
    assert farther.chosen.missing > farther.pick.missing and f"あと {farther.chosen.missing} 枚" in farther.text
    assert farther.reasons and "234萬 の順子" in farther.reasons[0]

    # 近づく牌が少ない切り方：役までの距離は同じでも、近づく牌の枚数が少ない候補
    position = _position("13m123388p2355s22z")
    advice = target_advice(position, "sanshoku")
    narrower = advice.candidate(_kind("8p"))
    assert narrower.distance == advice.pick.distance and narrower.total < advice.pick.total and not narrower.is_best
    verdict = judge_target(advice, narrower.tile, position)
    assert verdict.grade is TargetGrade.NARROWER and verdict.label == f"近づく牌が {advice.pick.total - narrower.total} 枚少ない"
    assert f"{narrower.kinds} 種 {narrower.total} 枚" in verdict.text and f"{advice.pick.kinds} 種 {advice.pick.total} 枚" in verdict.text


def test_discarding_the_last_needed_tile_loses_the_target():
    # 国士無双まであと少し。中は手の 1 枚だけで、残り 3 枚は見えている → 中を切ると、もう作れない
    position = _position("19m19p19s1234567z5m", visible="777z")
    advice = target_advice(position, "kokushi")
    assert advice.possible
    chun = next(t for t in position.tiles if kind_of(t) == _kind("7z"))
    verdict = judge_target(advice, chun, position)
    assert verdict.grade is TargetGrade.LOST and verdict.label == "国士無双が作れなくなった"


def test_target_result_tells_whether_the_yaku_was_made():
    def result(key: str, hand: str, win: str, **flags):
        return target_result(explain(make_context(hand, win, is_tsumo=True, **WINDS, **flags)), key)

    made = result("sanshoku", "234m234p24s789m44z", "3s")
    assert made.made and made.achieved and not made.upgraded and made.check is None and made.name == "三色同順"

    missed = result("sanshoku", "234m234p23s789m44z", "1s")                # 安目：123索 になって、三色が付かない
    assert not missed.made and not missed.achieved
    assert missed.check is not None and not missed.check.ok and any(not c.ok for c in missed.check.checks)

    upgraded = result("iipeikou", "112233m778899p5s", "5s")
    assert not upgraded.made and upgraded.upgraded == "二盃口" and upgraded.achieved
    assert result("riichi", "123m456p789s13s44z", "2s", riichi=True, double_riichi=True).upgraded == "ダブル立直"
    assert result("sanankou", "222m444p999s77s11z", "7s").upgraded == "四暗刻"
    assert result("honitsu", "111345567m7899m", "9m").upgraded == "清一色"

    # 条件は満たしたが、役満があるので数えない：狙った形はできている（付かなかった、とは言わない）
    hidden = result("honroutou", "111m999m111p999s1z", "1z")
    assert not hidden.made and not hidden.upgraded and hidden.superseded == "四暗刻単騎" and hidden.achieved and hidden.check is None
    assert result("sanshoku_doukou", "222m222p222s555m7z", "7z").superseded == "四暗刻単騎"
    assert result("tanyao", "222m444p666s888s3m", "3m").superseded == "四暗刻単騎"
    assert made.superseded == "" and missed.superseded == "" and upgraded.superseded == ""
    seven = result("honroutou", "1199m1199p1199s1z", "1z")                   # 七対子の形なら、混老頭として数える
    assert seven.made and not seven.superseded

    assert result("yakuhai", "555z123m456p23s99s", "4s").made                # まとめて扱うページ（役牌）
    assert result("kokushi", "19m19p19s1234567z", "9s").made                 # 十三面待ちも「国士無双」
    assert result("menzen_tsumo", "123m456p789s13s44z", "2s").made
    assert not result("riichi", "123m456p789s13s44z", "2s").achieved         # リーチしていない
    assert result("yakuhai", "123m456p789s13s44z", "2s").check is None


# ---------------------------------------------------------------- 「聴牌」「あがり」は点数計算で確かめる


def _pos(hand: str, *, drawn: str = "", visible: str = "") -> Position:
    """文字で書いた局面（南家・東場）"""
    used: set[int] = set()

    def take(text: str) -> tuple[int, ...]:
        tiles = parse_tiles(text, used=used)
        used.update(tiles)
        return tuple(tiles)

    tiles = take(hand)
    seen = take(visible)
    drawn_tile = next(t for t in tiles if kind_of(t) == kind_of(parse_tiles(drawn)[0])) if drawn else None
    return Position(tiles=tiles, visible=seen, dora_indicators=(), drawn=drawn_tile, draws_left=10, can_riichi=True, **WINDS)


def _credits(counts13: list[int], kind: int, key: str) -> bool:
    """13 枚 ＋ その牌のツモで、その役が数えられるか（点数計算そのもので確かめる）"""
    tiles = [k * 4 + i for k in range(34) for i in range(counts13[k])]
    win = kind * 4 + counts13[kind]
    result = explain(WinContext(closed_tiles=(*tiles, win), win_tile=win, is_tsumo=True, **WINDS))
    return result.best is not None and any(item.key == key for item in result.best.evaluation.yaku)


def test_pinfu_tenpai_is_only_claimed_with_a_two_sided_wait():
    """嵌張待ちの聴牌は、平和の聴牌と言わない（点検で見つかった例：123m234p234s6679s ＋東）"""
    pos = _pos("123m234p234s6679s1z")
    advice = target_advice(pos, "pinfu")
    assert not advice.won and advice.pick is not None
    assert advice.pick.kind == kind_of(parse_tiles("1z")[0]) and advice.pick.distance == 1     # 東を切っても、あと 2 枚
    counts = counts34(pos.tiles)
    for candidate in advice.candidates:
        if candidate.distance == 0:                       # 「平和の聴牌」と言う切り方は、待ちのどれでも平和が付く
            counts[candidate.kind] -= 1
            assert candidate.closer and all(_credits(counts, kind, "pinfu") for kind, _ in candidate.closer)
            counts[candidate.kind] += 1


def test_every_tenpai_claim_of_the_coach_is_true_for_pinfu():
    """コーチのおすすめどおりに打って、「平和の聴牌」と言った局面は、どれも本当に平和が付く待ち"""
    claims = 0
    for seed in range(8):
        state = practice.start(PracticeConfig(seed=seed, luck=LuckSettings(75, 75), target="pinfu"))
        while not state.finished and not state.can_tsumo:
            advice = target_advice(practice.position_of(state), "pinfu")
            pick = advice.pick
            if pick is not None and pick.distance == 0:
                claims += 1
                counts = counts34(state.tiles)
                counts[pick.kind] -= 1
                assert all(_credits(counts, kind, "pinfu") for kind, _ in pick.closer), (seed, state.tiles)
            state = practice.apply(state, discard(pick.tile if pick else state.drawn))
    assert claims >= 3


def test_a_winning_shape_without_the_yaku_keeps_the_advice():
    """あがりの形でも狙った役が付かないとき（高点法で三暗刻と読む、など）は、あがっていない扱い。狙い続ける切り方を示す"""
    from engine.target_coach import approach_tiles, wins_now

    pos = _pos("66m555666777p678s", drawn="8s")             # 567筒 3 組は、555・666・777 とも読める（三暗刻が高い）
    assert not wins_now(pos, "pinfu")
    advice = target_advice(pos, "pinfu")
    assert not advice.won and advice.pick is not None and advice.pick.closer
    verdict = judge_target(advice, advice.pick.tile, pos)
    assert verdict is not None and verdict.grade is TargetGrade.BEST
    # 8索 を切って戻す 13 枚は、形は平和の聴牌でも、どちらであがっても三暗刻の読み方になる：聴牌とは言わない
    back = counts34(parse_tiles("66m555666777p67s"))
    assert tg.target_distance(back, "pinfu", **WINDS) == 0 and approach_tiles(back, "pinfu", **WINDS) == ()
    assert advice.candidate(kind_of(parse_tiles("8s")[0])).distance == 1


def test_approach_tiles_at_tenpai_are_the_waits_that_give_the_yaku():
    from engine.target_coach import approach_tiles

    def kinds(text: str) -> tuple[int, ...]:
        return tuple(sorted({kind_of(t) for t in parse_tiles(text)}))

    assert approach_tiles(counts34(parse_tiles("123m456p789s23s44z")), "pinfu", **WINDS) == kinds("14s")
    assert approach_tiles(counts34(parse_tiles("234m234p23s789m44z")), "sanshoku", **WINDS) == kinds("4s")    # 1索 は安目
    kanchan = counts34(parse_tiles("123m456p789s13s44z"))
    assert tg.target_distance(kanchan, "pinfu", **WINDS) == 1 and approach_tiles(kanchan, "pinfu", **WINDS)
    # 手の形を問わない役は、点数計算では確かめない（リーチなどの状況で付く役なので）
    assert approach_tiles(counts34(parse_tiles("123m456p789s13s44z")), "riichi", **WINDS) == kinds("2s")

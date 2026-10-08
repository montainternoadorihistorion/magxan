"""役までの距離（engine/analysis/target.py）のテスト。

確かめること
    * 手の形を問わない役（立直など）の距離は、判定ライブラリの向聴数と同じ
    * 距離 −1（その役の形であがっている）と、点数計算が「その役が付く」と言うことが、一致する
    * 平和（聴牌の形で表す役）では、距離 0 が「平和の付くあがり牌がある聴牌」と一致する（嵌張・辺張・単騎は 0 にならない）
    * 1 枚引くと距離はちょうど 1 縮められる（縮む牌が必ずあり、2 以上は縮まない）
    * めざす形（plan）の足りない牌を足し、要らない牌を除くと、本当にその役のあがりになる
"""
from __future__ import annotations

import random
from functools import cache

import pytest

from engine import content
from engine.analysis import target as tg
from engine.analysis.shanten import shanten_of
from engine.scoring.context import WinContext
from engine.scoring.decompose import Form
from engine.scoring.explain import explain
from engine.tiles import EAST, SOUTH, counts34, parse_tiles

SEAT, ROUND = SOUTH, EAST
WINDS = {"seat_wind": SEAT, "round_wind": ROUND}
STRUCTURAL = [key for key in tg.TARGET_KEYS if key not in tg.SHAPELESS_KEYS]
#: 役の形を、あがりの形（14 枚）ではなく、役が付く聴牌の形（13 枚）で表す役
TENPAI_FORM = [key for key in STRUCTURAL if tg.is_tenpai_form(key, **WINDS)]
COMPLETE_FORM = [key for key in STRUCTURAL if key not in TENPAI_FORM]
PAGE_OF = content.page_of_yaku()
#: 距離の計算が「その役の形」に含めている、上位の役
UPGRADES = {
    "iipeikou": {"ryanpeikou"},
    "sanankou": {"suuankou"},
    "chanta": {"junchan"},
    "honitsu": {"chinitsu", "tsuuiisou"},
}
#: 刻子で作る役。刻子 4 つの形（門前のツモでは四暗刻になり、その役を数えない）を、役の形に入れていない
COUNTED_ONLY = frozenset({"sanshoku_doukou", "shousangen", "honroutou"})


def _random_counts(rnd: random.Random, size: int) -> list[int]:
    return counts34(rnd.sample(range(136), size))


def _complete_hand(rnd: random.Random) -> list[int]:
    """適当な 4 面子 1 雀頭の 14 枚（種類ごとの枚数）"""
    while True:
        counts = [0] * 34
        for _ in range(4):
            if rnd.random() < 0.6:
                first = rnd.choice(sorted(tg.SEQUENCE_STARTS))
                kinds = (first, first + 1, first + 2)
            else:
                kinds = (rnd.randrange(34),) * 3
            for kind in kinds:
                counts[kind] += 1
        counts[rnd.randrange(34)] += 2
        if max(counts) <= 4:
            return counts


def _near_hand(rnd: random.Random, size: int) -> list[int]:
    """あがり形から何枚か入れ替えた手（役に近い手も遠い手も混ざるように）"""
    counts = _complete_hand(rnd)
    for _ in range(rnd.randrange(0, 5)):
        counts[rnd.choice([k for k in range(34) if counts[k]])] -= 1
        counts[rnd.choice([k for k in range(34) if counts[k] < 4])] += 1
    if size == 13:
        counts[rnd.choice([k for k in range(34) if counts[k]])] -= 1
    return counts


def _sequence_hand(rnd: random.Random) -> list[int]:
    """順子 4 つと雀頭の 14 枚から 1 枚抜いた手（ときどき、もう 1 枚入れ替える）。待ちの形がいろいろな聴牌になる"""
    while True:
        counts = [0] * 34
        for _ in range(4):
            first = rnd.choice(sorted(tg.SEQUENCE_STARTS))
            for kind in (first, first + 1, first + 2):
                counts[kind] += 1
        counts[rnd.choice([*range(27), 29, 30])] += 2           # 雀頭（数牌か、南家・東場で客風の西・北）
        if max(counts) <= 4:
            break
    counts[rnd.choice([k for k in range(34) if counts[k]])] -= 1
    if rnd.random() < 0.3:
        counts[rnd.choice([k for k in range(34) if counts[k]])] -= 1
        counts[rnd.choice([k for k in range(34) if counts[k] < 4])] += 1
    return counts


def _tiles(counts: list[int]) -> list[int]:
    return [kind * 4 + i for kind in range(34) for i in range(counts[kind])]


@cache
def _pages_of_hand(counts: tuple[int, ...]) -> tuple[frozenset[str], frozenset[str]]:
    """14 枚のあがり形（門前のツモ）に付きうる役（図鑑のページの鍵）。あがり牌と読み方を、すべて試す。

    →（数えられる役, 条件を満たしている役）。あとのほうは、役満があるために数えない役も含む。
    """
    tiles = _tiles(list(counts))
    counted: set[str] = set()
    satisfied: set[str] = set()
    for kind in range(34):
        if not counts[kind]:
            continue
        result = explain(WinContext(closed_tiles=tuple(tiles), win_tile=kind * 4, is_tsumo=True, **WINDS))
        for candidate in result.candidates:
            counted.update(PAGE_OF[item.key] for item in candidate.evaluation.yaku)
            satisfied.update(PAGE_OF[item.key] for item in (*candidate.evaluation.yaku, *candidate.evaluation.ignored))
    return frozenset(counted), frozenset(satisfied)


def _has(counts: list[int], key: str) -> bool:
    counted, satisfied = _pages_of_hand(tuple(counts))
    if key == "honroutou" and "tsuuiisou" in counted:
        return all(n in (0, 2) for n in counts)         # 字牌 7 種の七対子は、混老頭ではなく字一色（役満）として数える
    found = counted if key in COUNTED_ONLY else satisfied
    return bool(found & ({key} | UPGRADES.get(key, set())))


def _distance(counts: list[int], key: str, **kw) -> int:
    return tg.target_distance(counts, key, **WINDS, **kw)


def _wins_with(counts13: list[int], kind: int, key: str) -> bool:
    """13 枚の手が、その牌のツモであがりになり、採用される読み方に、その役が付くか"""
    grown = list(counts13)
    grown[kind] += 1
    if grown[kind] > 4 or shanten_of(grown) != -1:
        return False
    tiles = _tiles(grown)
    result = explain(WinContext(closed_tiles=tuple(tiles), win_tile=kind * 4 + grown[kind] - 1, is_tsumo=True, **WINDS))
    return result.best is not None and key in {PAGE_OF[item.key] for item in result.best.evaluation.yaku}


def _triple_sequence(counts: list[int]) -> bool:
    """同じ順子 3 組（111222333 のように、刻子 3 つとも読める形）を含むか"""
    return any(k % 9 <= 6 and min(counts[k], counts[k + 1], counts[k + 2]) >= 3 for k in range(27))


# ---------------------------------------------------------------- 向聴数との一致


def test_shapeless_targets_equal_ordinary_shanten():
    rnd = random.Random(20261008)
    for index in range(1500):
        size = 13 + index % 2
        counts = _random_counts(rnd, size) if index % 3 else _near_hand(rnd, size)
        for key in ("riichi", "double_riichi"):
            assert _distance(counts, key) == shanten_of(counts), counts


def test_structural_distance_is_never_below_shanten():
    rnd = random.Random(5)
    for _ in range(150):
        counts = _near_hand(rnd, 13)
        base = shanten_of(counts)
        for key in STRUCTURAL:
            assert _distance(counts, key) >= base, (key, counts)


# ---------------------------------------------------------------- 点数計算との一致


def test_keys_are_pages_marked_as_practicable():
    pages = content.yaku_page_map()
    assert set(tg.TARGET_KEYS) == {page.key for page in pages.values() if page.practice}
    assert len(set(tg.TARGET_KEYS)) == len(tg.TARGET_KEYS) == 29
    for key in tg.TARGET_KEYS:
        tg.spec_of(key, SEAT, ROUND)
    with pytest.raises(KeyError):
        tg.spec_of("rinshan")
    # 対々和は、鳴いた手の役の候補には使うが、役指定練習には入れない（門前では四暗刻になる）
    assert "toitoi" not in tg.TARGET_KEYS and tg.spec_of("toitoi").shapes


def test_examples_of_each_page_are_at_distance_minus_one():
    """図鑑の成立例（門前の手）は、その役の形として「あがっている」と数えられる"""
    checked = 0
    for page in content.yaku_pages():
        if page.practice is None:
            continue
        for hand in page.examples:
            ctx = hand.context()
            if ctx.melds:
                continue
            counts = counts34(ctx.closed_tiles)
            winds = {"seat_wind": ctx.seat_wind, "round_wind": ctx.round_wind}
            distance = tg.target_distance(counts, page.key, **winds)
            if tg.is_tenpai_form(page.key, **winds):
                # 聴牌の形で表す役（平和）：あがる前の 13 枚が、その役の聴牌（距離 0）。14 枚でも 0 のまま（−1 にはならない）
                counts[ctx.win_kind] -= 1
                assert distance == 0 and tg.target_distance(counts, page.key, **winds) == 0, (page.key, hand.title)
            else:
                assert distance == -1, (page.key, hand.title)
            checked += 1
    assert checked >= 45


@pytest.mark.parametrize("key", STRUCTURAL)
def test_completed_plan_really_has_the_yaku(key):
    """めざす形どおりに牌を入れ替えると、点数計算でも、その役（か、その上位の役）が付く"""
    rnd = random.Random(f"plan:{key}")
    for index in range(25):
        counts = _near_hand(rnd, 13 + index % 2) if index % 2 else _random_counts(rnd, 13 + index % 2)
        plan = tg.target_plan(counts, key, **WINDS)
        assert plan.possible and plan.form is not None
        assert plan.tenpai_form == (key in TENPAI_FORM)
        size = sum(counts)
        assert plan.distance == plan.missing - 1                     # あがりまでに要る枚数 ＝ 距離 ＋ 1
        assert sum(n for _, n in plan.spare) == size - (13 - plan.distance)
        done = list(counts)
        for kind, n in plan.spare:
            done[kind] -= n
        for kind, n in plan.need:
            done[kind] += n
        goal = 13 if plan.tenpai_form else 14                         # 聴牌の形（平和）は 13 枚、あがりの形は 14 枚
        assert sum(done) == goal and 0 <= min(done) and max(done) <= 4
        assert sum(len(block.tiles) for block in plan.blocks) == goal
        assert sorted(k for block in plan.blocks for k in block.tiles) == sorted(k for k in range(34) for _ in range(done[k]))
        assert sorted(k for block in plan.blocks for k in block.need) == sorted(k for k, n in plan.need for _ in range(n))
        if not plan.tenpai_form:
            assert _distance(done, key) == -1
            assert _has(done, key), (key, done)
            continue
        # 聴牌の形：両面の 2 枚の、どちら側が来ても、その役が付く（同じ順子 3 組を刻子 3 つと読む、高点法の例外を除く）
        assert _distance(done, key) == 0
        ryanmen = [block for block in plan.blocks if block.kind is tg.BlockKind.RYANMEN]
        assert len(ryanmen) == 1
        low, high = ryanmen[0].tiles
        for wait in (low - 1, high + 1):
            if done[wait] < 4:
                assert _wins_with(done, wait, key) or _triple_sequence([n + (k == wait) for k, n in enumerate(done)]), (key, done, wait)


def test_distance_minus_one_matches_the_scoring_engine():
    """いろいろなあがり形について、「距離 −1」と「点数計算でその役が付く」が、どの役でも一致する"""
    rnd = random.Random(99)
    hands: list[list[int]] = [_complete_hand(rnd) for _ in range(60)]
    for key in COMPLETE_FORM:                               # それぞれの役のあがり形も混ぜる（まれな役を試すため）
        for _ in range(4):
            start = _near_hand(rnd, 14)
            plan = tg.target_plan(start, key, **WINDS)
            done = list(start)
            for kind, n in plan.spare:
                done[kind] -= n
            for kind, n in plan.need:
                done[kind] += n
            hands.append(done)
    for counts in hands:
        for key in COMPLETE_FORM:
            assert (_distance(counts, key) == -1) == _has(counts, key), (key, counts)


@pytest.mark.parametrize("key", TENPAI_FORM)
def test_tenpai_form_distance_zero_matches_the_scoring_engine(key):
    """聴牌の形で表す役（平和）：13 枚の手で「距離 0」と「ツモるとその役が付くあがり牌がある」が一致する。

    嵌張・辺張・単騎・双碰の聴牌は、形が 4 面子 1 雀頭に近くても、距離 0 にならない。
    例外は、同じ順子 3 組（111222333）を含む手：高点法で刻子 3 つの読み方（三暗刻）が選ばれ、その役が付かないことがある。
    """
    rnd = random.Random(f"tenpai:{key}")
    zeros = credited_hands = 0
    for index in range(500):
        counts = _near_hand(rnd, 13) if index % 4 == 0 else _sequence_hand(rnd)
        credited = [k for k in range(34) if _wins_with(counts, k, key)]
        distance = _distance(counts, key)
        if credited:
            credited_hands += 1
            assert distance == 0, (counts, credited)
        elif distance == 0:
            assert _triple_sequence(counts), counts
        zeros += distance == 0
    assert zeros >= 20 and credited_hands >= 20
    # 嵌張・辺張・単騎の聴牌は、平和の聴牌ではない（あと 1 枚、両面に変える牌が要る）
    for text in ("123m456p789s13s44z", "123m456p789s12s44z", "123m456p789s234s4z", "123m234p234s66s79s"):
        hand = counts34(parse_tiles(text))
        assert shanten_of(hand) == 0 and _distance(hand, key) == 1, text


# ---------------------------------------------------------------- 距離の性質


@pytest.mark.parametrize("key", tg.TARGET_KEYS)
def test_one_draw_changes_the_distance_by_exactly_one(key):
    rnd = random.Random(f"step:{key}")
    for index in range(12):
        counts = _near_hand(rnd, 13) if index % 2 else _random_counts(rnd, 13)
        base = _distance(counts, key)
        assert 0 <= base < tg.IMPOSSIBLE
        after = []
        for kind in range(34):
            if counts[kind] < 4:
                counts[kind] += 1
                after.append(_distance(counts, key))
                counts[kind] -= 1
        closer = tg.target_tiles(counts, key, **WINDS)
        if base == 0 and key in TENPAI_FORM:
            # 聴牌の形で表す役は、聴牌（距離 0）より先が無い。あがり牌は、点数計算で確かめる（target_coach）
            assert set(after) == {0} and closer == ()
        else:
            assert min(after) == base - 1 and max(after) <= base, (key, counts)
            assert len(closer) == after.count(base - 1) > 0
        # 14 枚から 1 枚切る：いちばん良い切り方をすれば、距離は変わらない
        counts[rnd.choice([k for k in range(34) if counts[k] < 4])] += 1
        full = _distance(counts, key)
        cut = []
        for kind in range(34):
            if counts[kind]:
                counts[kind] -= 1
                cut.append(_distance(counts, key))
                counts[kind] += 1
        assert min(cut) == max(full, 0), (key, counts)


def test_known_distances():
    def distance(text: str, key: str) -> int:
        return _distance(counts34(parse_tiles(text)), key)

    assert distance("234m234p24s789m44z", "sanshoku") == 0          # 3索 で三色同順
    assert distance("234m234p24s789m44z", "tanyao") == 3            # 9萬 と北 2 枚が使えない。あがりまで、3索 を含めて 4 枚
    assert distance("123456789m24s44z", "ittsu") == 0
    assert distance("123456789m24s44z", "chinitsu") == 4            # 使えるのは萬子 9 枚。あがりまで、あと 5 枚
    assert distance("19m19p19s1234567z", "kokushi") == 0            # 十三面待ち
    assert distance("19m19p19s123456z5m", "kokushi") == 1
    assert distance("1112345678999m", "chuuren") == 0
    assert distance("2255m3399p4466s1z", "chiitoitsu") == 0
    assert distance("2255m3399p4466s1z", "suuankou") == 3            # 対子 6 組から四暗刻は遠い（刻子 4 つに、あと 4 枚）
    assert distance("555z666z77z234m56p", "shousangen") == 0
    assert distance("555z666z77z234m56p", "daisangen") == 1
    assert distance("123m456p789s23s44z", "pinfu") == 0
    assert distance("123m456p789s23s55z", "pinfu") == 2             # 雀頭の白は役牌。平和にするには、雀頭を作り直す（2 枚要る）


def test_set_based_targets_avoid_four_concealed_triplets():
    """刻子 4 つを門前でツモると四暗刻（役満）になり、ほかの役を数えない。その形は、役の形に入れない"""
    def distance(text: str, key: str) -> int:
        return _distance(counts34(parse_tiles(text)), key)

    # 三色同刻：4 つめの面子は順子にする
    assert distance("111m111p111s222m5z", "suuankou") == 0
    assert distance("111m111p111s222m5z", "sanshoku_doukou") == 1          # 22萬 を雀頭にして、残りの 2萬 から順子を作る（あと 2 枚）
    assert distance("111m111p111s234m5z", "sanshoku_doukou") == 0
    # 小三元：残りの 2 面子のどちらかは順子
    assert distance("555z666z77z111m99p", "suuankou") == 0
    assert distance("555z666z77z111m99p", "shousangen") == 1               # 9筒 1 枚から順子を作る（あと 2 枚）
    assert distance("555z666z77z111m78p", "shousangen") == 0
    # 混老頭：七対子の形だけ（刻子 4 つの形は入れない）
    assert distance("111m999m111p999p1z", "suuankou") == 0
    assert distance("111m999m111p999p1z", "honroutou") == 4                # 対子は 4 組。あと 3 組と、単騎の 1 枚
    assert distance("1199m1199p1199s1z", "honroutou") == 0
    assert tg.target_plan(counts34(parse_tiles("1199m1199p1199s1z")), "honroutou").form is Form.CHIITOI


def test_plan_shows_what_is_missing():
    counts = counts34(parse_tiles("234m23p24s789m44z5z"))
    plan = tg.target_plan(counts, "sanshoku", **WINDS)
    assert plan.form is Form.REGULAR and plan.distance == 1
    assert dict(plan.need) == {parse_tiles("4p")[0] // 4: 1, parse_tiles("3s")[0] // 4: 1}      # 足りないのは 4筒 と 3索
    fixed = [block for block in plan.blocks if block.fixed]
    assert len(fixed) == 3 and all(block.kind is tg.BlockKind.SEQUENCE for block in fixed)
    assert sum(1 for block in plan.blocks if block.complete) >= 3      # 234萬・789萬・北北 はそろっている
    assert dict(plan.spare) == {31: 1}                                 # 白は、めざす形に入らない

    kokushi = tg.target_plan(counts34(parse_tiles("19m19p19s1234567z")), "kokushi")
    assert kokushi.form is Form.KOKUSHI and len(kokushi.blocks) == 13 and kokushi.missing == 1
    seven = tg.target_plan(counts34(parse_tiles("2255m3399p4466s1z")), "chiitoitsu")
    assert seven.form is Form.CHIITOI and [b.kind for b in seven.blocks] == [tg.BlockKind.PAIR] * 7


def test_availability_makes_a_target_impossible():
    counts = counts34(parse_tiles("19m19p19s123456z55m"))
    free = [4 - n for n in counts]
    assert _distance(counts, "kokushi", available=free) == 1
    free[33] = 0                                                       # 中が 4 枚とも見えている
    assert _distance(counts, "kokushi", available=free) == tg.IMPOSSIBLE
    plan = tg.target_plan(counts, "kokushi", **WINDS, available=free)
    assert not plan.possible and plan.form is None and plan.blocks == ()
    assert tg.target_tiles(counts, "kokushi", **WINDS, available=free) == ()

    # 三色同順：3索 が残っていなければ、234 の三色はあきらめて、別の数字の三色をめざす
    hand = counts34(parse_tiles("234m234p24s789m44z"))
    free = [4 - n for n in hand]
    assert tg.target_tiles(hand, "sanshoku", **WINDS, available=free) == (parse_tiles("3s")[0] // 4,)
    free[parse_tiles("3s")[0] // 4] = 0
    assert _distance(hand, "sanshoku", available=free) > 0
    assert parse_tiles("3s")[0] // 4 not in tg.target_tiles(hand, "sanshoku", **WINDS, available=free)


def test_yakuhai_and_pinfu_depend_on_the_winds():
    counts = counts34(parse_tiles("11z234m567p23s789s"))             # 東の対子と、面子 3 つ、両面
    assert tg.target_distance(counts, "yakuhai", seat_wind=EAST, round_wind=EAST) == 1
    assert tg.target_distance(counts, "yakuhai", seat_wind=SOUTH, round_wind=EAST) == 1          # 東は場風
    assert tg.target_distance(counts, "yakuhai", seat_wind=SOUTH, round_wind=SOUTH) == 2         # 東は、どちらの風でもない
    # 客風の対子は平和の雀頭にできる。役牌の対子はできないので、雀頭を作り直すことになる
    assert tg.target_distance(counts, "pinfu", seat_wind=SOUTH, round_wind=SOUTH) == 0
    assert tg.target_distance(counts, "pinfu", seat_wind=EAST, round_wind=EAST) == 2


def test_speed_is_good_enough_for_the_coach():
    """1 局面ぶん（14 通りの打牌 ＋ 引いて近づく牌 34 通り）を、十分な速さで調べられる"""
    import time

    rnd = random.Random(3)
    hands = [_random_counts(rnd, 14) for _ in range(12)]
    started = time.perf_counter()
    for counts in hands:
        for key in ("sanshoku", "honitsu", "iipeikou"):
            best = min((k for k in range(34) if counts[k]), key=lambda k: _distance([n - (i == k) for i, n in enumerate(counts)], key))
            counts[best] -= 1
            tg.target_tiles(counts, key, **WINDS)
            counts[best] += 1
    assert (time.perf_counter() - started) / 36 < 1.0         # 遅い計算機でも 1 局面 1 秒未満（ふつうは 0.1 秒ほど）


# ---------------------------------------------------------------- 副露のある手（鳴きの判断・CPU の鳴き）


def _open(concealed: str, *melds: str):
    from engine.melds import chi, pon

    used: set[int] = set()

    def take(text: str) -> list[int]:
        tiles = parse_tiles(text, used=used)
        used.update(tiles)
        return tiles

    built = [(chi if text.startswith("c") else pon)(take(text[1:])) for text in melds]
    return counts34(take(concealed)), built


def test_open_hand_distances_respect_the_melds():
    counts, melds = _open("234p567s88s45m9p", "p555z")           # 白をポン：残り 11 枚は 9筒 を切れば聴牌
    assert tg.target_distance(counts, "yakuhai", melds=melds) == 0
    assert tg.target_distance(counts, "tanyao", melds=melds) == tg.IMPOSSIBLE        # 白の刻子は 2〜8 ではない
    counts, melds = _open("234p567s88s45m9p", "c123m")
    assert tg.target_distance(counts, "tanyao", melds=melds) == tg.IMPOSSIBLE        # 123萬 に 1 がある
    assert tg.target_distance(counts, "toitoi", melds=melds) == tg.IMPOSSIBLE        # 順子を鳴いている
    assert tg.target_distance(counts, "pinfu", melds=melds) == tg.IMPOSSIBLE         # 鳴いた手では付かない
    assert tg.target_distance(counts, "chiitoitsu", melds=melds) == tg.IMPOSSIBLE


def test_a_complete_open_hand_is_at_minus_one_and_meld_required_blocks_count():
    counts, melds = _open("234p567s88s345m", "p555z")
    assert tg.target_distance(counts, "yakuhai", melds=melds) == -1
    counts, melds = _open("123p123s88s45m9p", "c123m")
    assert tg.target_distance(counts, "sanshoku", melds=melds) == 0      # 123萬 のチーが、三色同順の 1 つ
    plan = tg.target_plan(counts, "sanshoku", melds=melds)
    assert plan.distance == 0 and all(len(b.tiles) <= 3 for b in plan.blocks)


def test_open_spec_relaxes_the_closed_hand_limits():
    # 鳴いていれば、刻子 4 つの形も対々和として数えられる（三色同刻・小三元・混老頭）
    counts, melds = _open("111p111s99m1z1z", "p111m", "p999p")
    assert tg.target_distance(counts, "sanshoku_doukou", melds=melds) == -1
    assert tg.target_distance(counts, "honroutou", melds=melds) == -1
    assert tg.target_distance(counts, "toitoi", melds=melds) == -1


def test_single_value_kind_spec():
    assert tg.spec_of("yakuhai:31").shapes[0].sets == (31,)
    with pytest.raises(KeyError):
        tg.spec_of("yakuhai:0")                                       # 1萬 は役牌ではない

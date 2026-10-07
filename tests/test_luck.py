"""ツキ補正（engine/luck.py）のテスト。

確かめること
  * 何万局ぶん補正をかけても、山はいつも 136 枚の牌をちょうど 1 枚ずつ含む（同じ牌が 5 枚にならない）
  * 補正が触るのは「自分の配牌」と「これからツモる山」だけ。王牌と、ほかの席の配牌は変わらない
  * 補正 0 では、乱数を使わず、山にも触れない（素のシャッフルと完全に同じ）
  * 補正 0 の配牌の統計が、別の乱数で測ったランダムな配牌の統計と一致する
  * 補正を強くするほど、配牌が良くなる
"""
from __future__ import annotations

import os
from collections import Counter
from statistics import mean

import pytest

from engine import luck
from engine.analysis.shanten import shanten_of
from engine.luck import (
    NO_DRAW_LUCK,
    PRESETS,
    DealReport,
    DrawReport,
    LuckSettings,
    deal_candidates,
    draw_probability,
    hand_prospect,
    improve_deal,
    improve_draw,
)
from engine.rng import Rng
from engine.tiles import EAST, NUM_TILES, SOUTH, counts34, kind_of, parse_tiles
from engine.wall import DORA_START, LIVE_END, LIVE_START, Wall, WallError, shuffled_tiles

#: 「何万局」の規模。ふだんは 2 万局。もっと大きく確かめたいときは環境変数で増やす
STRUCTURE_WALLS = int(os.environ.get("MJDOJO_LUCK_WALLS", "20000"))

#: 補正なしの配牌 13 枚の向聴数の分布。山とは別の乱数（Python 標準の random.sample）で 200 万回測った度数
REFERENCE_SHANTEN = {0: 174, 1: 12491, 2: 187618, 3: 723393, 4: 798002, 5: 261553, 6: 16769}
REFERENCE_TOTAL = sum(REFERENCE_SHANTEN.values())
REFERENCE_MEAN = sum(k * v for k, v in REFERENCE_SHANTEN.items()) / REFERENCE_TOTAL       # 3.579
REFERENCE_SD = 0.884


def own_and_live(tiles: list[int], order: int = 0) -> list[int]:
    start = order * 13
    return [*tiles[start:start + 13], *tiles[LIVE_START:LIVE_END]]


def untouchable(tiles: list[int], order: int = 0) -> list[int]:
    """補正が触ってはいけない場所の牌（ほかの席の配牌と王牌）"""
    start = order * 13
    return [*tiles[:start], *tiles[start + 13:LIVE_START], *tiles[LIVE_END:]]


class StubRng:
    """抽選の結果を決め打ちにした乱数（当たり外れと、選ぶ位置）"""

    def __init__(self, hit: bool, pick_last: bool = False) -> None:
        self.hit = hit
        self.pick_last = pick_last
        self.asked: list[float] = []

    def chance(self, probability: float) -> bool:
        self.asked.append(probability)
        return self.hit

    def choice(self, items):
        return items[-1] if self.pick_last else items[0]


class ForbiddenRng:
    """使われたら失敗にする乱数"""

    def __getattr__(self, name):
        raise AssertionError(f"補正 0 なのに乱数が使われた: {name}")


# ---------------------------------------------------------------- 設定と、スライダーの対応


def test_settings_validation_and_roundtrip():
    settings = LuckSettings(25, 60, allow_tenpai_deal=True)
    assert LuckSettings.from_dict(settings.to_dict()) == settings
    assert LuckSettings.from_dict({}) == LuckSettings() and LuckSettings().is_off
    assert not LuckSettings(0, 1).is_off and not LuckSettings(1, 0).is_off
    for bad in ((-1, 0), (0, 101), (1.5, 0), (True, 0), ("50", 0)):
        with pytest.raises(ValueError):
            LuckSettings(*bad)
    with pytest.raises(ValueError):
        LuckSettings.from_dict({"deal": 500})


def test_presets_cover_the_range():
    assert PRESETS == (("なし", 0), ("弱", 25), ("中", 50), ("強", 75), ("最大", 100))


def test_deal_candidates_curve():
    assert [deal_candidates(level) for level in (0, 25, 50, 75, 100)] == [1, 4, 16, 64, 256]
    values = [deal_candidates(level) for level in range(101)]
    assert values == sorted(values) and values[0] == 1 and values[-1] == 256
    assert deal_candidates(12) == 2          # 256^(0.12) ≒ 1.9 → 2 個（低い値でも、少しは効く）


def test_draw_probability_curve():
    assert [draw_probability(level) for level in (0, 25, 50, 75, 100)] == pytest.approx([0.0, 0.05, 0.12, 0.25, 0.60])
    assert draw_probability(10) == pytest.approx(0.02)                 # 0 と 25 のあいだは直線
    assert draw_probability(60) == pytest.approx(0.12 + 0.13 * 10 / 25)
    values = [draw_probability(level) for level in range(101)]
    assert values == sorted(values) and all(0 <= v <= 0.6 for v in values)


# ---------------------------------------------------------------- 補正 0 は何もしない


def test_zero_luck_deal_touches_nothing_and_uses_no_randomness(monkeypatch):
    monkeypatch.setattr(luck, "Rng", ForbiddenRng)
    for seed in range(300):
        wall = Wall.from_seed(seed)
        report = improve_deal(wall, 0, LuckSettings(0, 0), seed, seat_wind=EAST, round_wind=EAST)
        assert wall.tiles == shuffled_tiles(seed)
        value = shanten_of(counts34(wall.dealt_hand(0)))
        assert report == DealReport(1, 0, value, value) and not report.applied


def test_zero_probability_draw_touches_nothing_and_uses_no_randomness():
    wall = Wall.from_seed(1)
    wall.seal()

    def wanted():
        raise AssertionError("補正 0 なのに、欲しい牌を調べた")

    for _ in range(70):
        assert improve_draw(wall, 0.0, wanted, ForbiddenRng()) is NO_DRAW_LUCK
        wall.draw()
    assert wall.tiles == shuffled_tiles(1)
    assert improve_draw(wall, 1.0, wanted, ForbiddenRng()) is NO_DRAW_LUCK      # 山が尽きていれば何もしない


# ---------------------------------------------------------------- 配牌の補正


@pytest.mark.parametrize(("level", "seeds"), [(25, 300), (50, 150), (75, 40), (100, 20)])
def test_deal_luck_only_rearranges_own_hand_and_live_wall(level, seeds):
    for seed in range(seeds):
        order = seed % 4
        raw = shuffled_tiles(seed)
        wall = Wall.from_seed(seed)
        report = improve_deal(wall, order, LuckSettings(level, 0), seed, seat_wind=EAST + order, round_wind=EAST)
        wall.check()                                                     # 136 枚をちょうど 1 枚ずつ
        assert untouchable(wall.tiles, order) == untouchable(raw, order)  # 王牌と、ほかの席の配牌はそのまま
        assert sorted(own_and_live(wall.tiles, order)) == sorted(own_and_live(raw, order))
        assert max(counts34(wall.tiles)) == 4                            # どの種類も 4 枚

        assert report.candidates == deal_candidates(level)
        assert report.original_shanten == shanten_of(counts34(raw[order * 13:order * 13 + 13]))
        assert report.chosen_shanten == shanten_of(counts34(wall.dealt_hand(order)))
        assert report.applied == (wall.tiles != raw)
        assert report.chosen_shanten >= 1                                # 配牌で聴牌にはしない
        assert report.chosen_shanten <= report.original_shanten or report.original_shanten == 0


def test_stronger_deal_luck_never_gives_a_worse_deal():
    """候補は同じ順に作るので、候補を増やすと「いちばん良い向聴数」は良くなるか、同じ"""
    averages = {}
    for level in (0, 25, 50, 75, 100):
        values = []
        for seed in range(40):
            wall = Wall.from_seed(seed)
            values.append(improve_deal(wall, 0, LuckSettings(level, 0), seed, seat_wind=EAST, round_wind=EAST))
        averages[level] = values
    for weak, strong in ((25, 50), (50, 75), (75, 100)):
        assert all(a.chosen_shanten >= b.chosen_shanten for a, b in zip(averages[weak], averages[strong], strict=True))
    assert all(a.chosen_shanten >= b.chosen_shanten or a.chosen_shanten == 0 for a, b in zip(averages[0], averages[25], strict=True))
    means = [mean(r.chosen_shanten for r in averages[level]) for level in (0, 25, 50, 75, 100)]
    assert means == sorted(means, reverse=True) and means[0] - means[-1] > 1.5      # 補正なし 約 3.6 → 最大 約 1.2


def test_tenpai_deals_are_adopted_only_when_allowed():
    seed = 3          # 256 個の候補の中に、聴牌している配牌がある（探して見つけたシード）
    wall = Wall.from_seed(seed)
    allowed = improve_deal(wall, 0, LuckSettings(100, 0, allow_tenpai_deal=True), seed, seat_wind=EAST, round_wind=EAST)
    assert allowed.chosen_shanten == 0 and shanten_of(counts34(wall.dealt_hand(0))) == 0
    wall = Wall.from_seed(seed)
    default = improve_deal(wall, 0, LuckSettings(100, 0), seed, seat_wind=EAST, round_wind=EAST)
    assert default.chosen_shanten == 1 and shanten_of(counts34(wall.dealt_hand(0))) == 1


def test_deal_luck_is_reproducible_and_independent_of_the_raw_wall():
    first, second = Wall.from_seed(77), Wall.from_seed(77)
    settings = LuckSettings(50, 0)
    assert improve_deal(first, 0, settings, 77, seat_wind=EAST, round_wind=EAST) == improve_deal(second, 0, settings, 77, seat_wind=EAST, round_wind=EAST)
    assert first.tiles == second.tiles
    assert shuffled_tiles(77) == Wall.from_seed(77).tiles       # 補正を変えても、元の山は同じ（乱数の系統が別）


def test_deal_luck_cannot_run_after_dealing():
    wall = Wall.from_seed(5)
    wall.seal()
    with pytest.raises(WallError, match="配り終えたあと"):
        for seed in range(50):          # どこかで並べ替えが必要になる
            improve_deal(wall, 0, LuckSettings(100, 0), seed, seat_wind=EAST, round_wind=EAST)


def test_hand_prospect_counts_what_it_says():
    def score(text: str, dora: str = "", **kw) -> int:
        kw = {"seat_wind": SOUTH, "round_wind": EAST, **kw}
        return hand_prospect(parse_tiles(text), dora_indicators=parse_tiles(dora), **kw)

    assert score("147m258p369s2356m") == 0          # 何も付かない手（么九牌は 1萬・9索 の 2 枚）
    assert score("147m258p36s2356m3z") == 0         # 西 1 枚は役牌ではない
    assert score("147m258p3s235m555z") == 6         # 白の刻子
    assert score("147m258p36s235m55z") == 3         # 白の対子
    assert score("147m258p36s235m22z") == 3         # 自風（南）の対子
    assert score("147m258p36s235m11z") == 3         # 場風（東）の対子
    assert score("147m258p36s235m33z") == 0         # 客風（西）の対子は役にならない
    assert score("147m258p369s2356m", dora="1m") == 2      # ドラ表示牌 1萬 → ドラは 2萬（1 枚）
    assert score("147m258p369s2306m") == 2                 # 赤 5
    assert score("2345678m234p345s") == 2 + 0              # 么九牌なし → 断么九が見える
    assert score("1234567899m234p") == 3                   # 1 色で 10 枚以上 → 混一色・清一色が見える
    assert score("1133m5577p2299s1z") == 1                 # 対子 4 組以上


# ---------------------------------------------------------------- ツモの補正


def ordered_wall(**kwargs) -> Wall:
    """位置 p に牌 p が入っている山（どこに何があるかが分かりやすい）"""
    return Wall(list(range(NUM_TILES)), sealed=True, **kwargs)


def test_draw_luck_swaps_a_wanted_tile_into_the_next_position():
    wall = ordered_wall()
    rng = StubRng(hit=True)
    report = improve_draw(wall, 0.25, lambda: {20}, rng)          # 種類 20（3索）＝ 牌 80〜83
    assert report == DrawReport(rolled=True, swapped=True, original=52)
    assert wall.tiles[52] == 80 and wall.tiles[80] == 52           # 2 か所が入れ替わっただけ
    assert [t for p, t in enumerate(wall.tiles) if p not in (52, 80)] == [p for p in range(NUM_TILES) if p not in (52, 80)]
    assert rng.asked == [0.25]
    assert kind_of(wall.draw()) == 20


def test_draw_luck_does_nothing_when_not_needed_or_not_possible():
    def never():
        raise AssertionError("抽選に外れたのに、欲しい牌を調べた")

    wall = ordered_wall()
    assert improve_draw(wall, 0.25, never, StubRng(hit=False)) == NO_DRAW_LUCK           # 抽選に外れた
    assert improve_draw(wall, 0.25, lambda: {13}, StubRng(hit=True)) == DrawReport(rolled=True)   # 次の牌がもう欲しい牌
    assert improve_draw(wall, 0.25, lambda: set(), StubRng(hit=True)) == DrawReport(rolled=True)  # 欲しい牌が無い
    assert improve_draw(wall, 0.25, lambda: {0, 5}, StubRng(hit=True)) == DrawReport(rolled=True)  # 欲しい牌は配牌の中だけ
    assert improve_draw(wall, 0.25, lambda: {31, 32, 33}, StubRng(hit=True)) == DrawReport(rolled=True)  # 欲しい牌は王牌の中だけ
    assert wall.tiles == list(range(NUM_TILES))


def test_draw_luck_never_reaches_back_or_into_the_dead_wall():
    wall = ordered_wall(live_drawn=5)                    # 位置 52〜56 はツモ済み。次は 57
    assert improve_draw(wall, 1.0, lambda: {13}, StubRng(hit=True)) == DrawReport(rolled=True)   # 牌 52〜55 はもう無い
    assert wall.tiles == list(range(NUM_TILES))

    # 種類 30（北）は牌 120〜123。120・121 はツモ山、122・123 は嶺上牌
    wall = ordered_wall()
    report = improve_draw(wall, 1.0, lambda: {30}, StubRng(hit=True, pick_last=True))
    assert report.swapped and wall.tiles[52] == 121
    # カンが 1 回あると、位置 121 は王牌に回るので、使えるのは 120 だけ
    wall = ordered_wall(rinshan_drawn=1)
    report = improve_draw(wall, 1.0, lambda: {30}, StubRng(hit=True, pick_last=True))
    assert report.swapped and wall.tiles[52] == 120 and wall.tiles[121] == 121


def test_tens_of_thousands_of_walls_keep_every_tile_exactly_once():
    """何万局ぶん、配牌の並べ替えとツモの入れ替えをくり返しても、牌の枚数はいつも正しい。

    欲しい牌は乱数で適当に決める（ここで見たいのは山の整合性で、評価の中身ではないため）。
    """
    reference = list(range(NUM_TILES))
    swaps = 0
    draws_per_wall = 12
    for seed in range(STRUCTURE_WALLS):
        raw = shuffled_tiles(seed)
        wall = Wall(list(raw))
        rng = Rng(seed, "test:luck")
        order = seed % 4
        if seed % 2:                                       # 配牌の補正にあたる並べ替え
            positions = [*wall.deal_positions(order), *range(LIVE_START, LIVE_END)]
            pool = [wall.tiles[p] for p in positions]
            rng.shuffle(pool)
            wall.permute(positions, pool)
        wall.seal()
        hand = wall.dealt_hand(order)
        after_deal = list(wall.tiles)
        drawn = []
        for _ in range(draws_per_wall):
            wanted = {rng.below(34) for _ in range(4)}
            before = wall.tiles[wall.next_live_position]
            report = improve_draw(wall, 0.6, lambda wanted=wanted: wanted, rng)
            tile = wall.draw()
            if report.swapped:
                swaps += 1
                assert kind_of(tile) in wanted and report.original == before != tile
            else:
                assert tile == before
            drawn.append(tile)

        assert sorted(wall.tiles) == reference                               # 136 枚をちょうど 1 枚ずつ
        assert untouchable(wall.tiles, order) == untouchable(raw, order)       # 王牌と、ほかの席の配牌はそのまま
        assert wall.tiles[:LIVE_START] == after_deal[:LIVE_START]              # 配ったあとの配牌は変わらない
        assert wall.tiles[LIVE_START:LIVE_START + draws_per_wall] == drawn     # ツモった牌は、あとから変わらない
        assert len(set(hand + drawn)) == 13 + draws_per_wall                   # 手に来た牌に重複がない
        assert wall.tiles[DORA_START] == raw[DORA_START]
    assert swaps > STRUCTURE_WALLS                                             # 入れ替えが実際にたくさん起きている


# ---------------------------------------------------------------- 補正 0 の統計


def chi_square(observed: Counter, expected_share: dict[int, float], total: int) -> float:
    return sum((observed.get(key, 0) - share * total) ** 2 / (share * total) for key, share in expected_share.items())


def test_zero_luck_deals_match_the_statistics_of_random_deals():
    """補正 0 の配牌の向聴数の分布が、別の乱数で測ったランダムな配牌の分布と一致する（カイ二乗検定）"""
    deals = 5000
    observed: Counter[int] = Counter()
    total_shanten = 0
    for seed in range(deals):
        wall = Wall.from_seed(seed)
        order = seed % 4
        report = improve_deal(wall, order, LuckSettings(0, 0), seed, seat_wind=EAST, round_wind=EAST)
        value = report.chosen_shanten
        total_shanten += value
        observed[max(value, 1)] += 1                 # 聴牌（0）はごくまれなので、1 向聴と合わせて数える

    share = {key: count / REFERENCE_TOTAL for key, count in REFERENCE_SHANTEN.items() if key >= 2}
    share[1] = (REFERENCE_SHANTEN[0] + REFERENCE_SHANTEN[1]) / REFERENCE_TOTAL
    assert sum(observed.values()) == deals and set(observed) <= set(share)
    assert chi_square(observed, share, deals) < 20.5                # 自由度 5 の上側 0.1% 点（20.52）
    # 平均向聴数は約 3.58。5000 局の平均の標準誤差は 0.884 ÷ √5000 ≒ 0.0125
    assert abs(total_shanten / deals - REFERENCE_MEAN) < 4 * REFERENCE_SD / deals ** 0.5


def test_luck_shifts_the_statistics_away_from_random():
    """検定に検出力があることの確認：弱い補正（候補 4 個）でも、同じ検定ではっきり外れる"""
    deals = 400
    observed: Counter[int] = Counter()
    for seed in range(deals):
        wall = Wall.from_seed(seed)
        report = improve_deal(wall, 0, LuckSettings(25, 0), seed, seat_wind=EAST, round_wind=EAST)
        observed[max(report.chosen_shanten, 1)] += 1
    share = {key: count / REFERENCE_TOTAL for key, count in REFERENCE_SHANTEN.items() if key >= 2}
    share[1] = (REFERENCE_SHANTEN[0] + REFERENCE_SHANTEN[1]) / REFERENCE_TOTAL
    assert chi_square(observed, share, deals) > 100

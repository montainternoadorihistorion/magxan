"""山（engine/wall.py）のテスト"""
from collections import Counter
from statistics import mean

import pytest
from mahjong.shanten import Shanten

from engine import wall as W
from engine.tiles import NUM_TILES, counts34


def test_layout_adds_up_to_136():
    assert W.LIVE_START == 52 and W.NUM_LIVE == 70 and W.NUM_DEAD == 14
    assert W.NUM_RINSHAN == 4 and W.NUM_DORA_INDICATORS == 5 and NUM_TILES - W.URA_START == 5
    assert W.NUM_PLAYERS * W.HAND_SIZE + W.NUM_LIVE + W.NUM_DEAD == NUM_TILES


def test_golden_wall():
    """シードから決まる山が変わっていないこと（再現性の見張り）"""
    assert W.shuffled_tiles(1)[:12] == [93, 10, 50, 14, 11, 32, 20, 55, 94, 106, 83, 92]
    tiles = W.shuffled_tiles(20261007)
    assert tiles[:12] == [121, 100, 105, 9, 37, 4, 22, 45, 87, 92, 56, 84]
    assert tiles[-4:] == [106, 54, 114, 71]


def test_every_wall_has_each_tile_exactly_once():
    """何万局ぶん作っても、山は必ず 136 枚の牌をちょうど 1 枚ずつ含む"""
    reference = list(range(NUM_TILES))
    for seed in range(20000):
        assert sorted(W.shuffled_tiles(seed)) == reference


def test_deal_and_draw_never_overlap():
    for seed in range(300):
        wall = W.Wall.from_seed(seed)
        hands = [wall.dealt_hand(order) for order in range(4)]
        drawn = [wall.draw() for _ in range(W.NUM_LIVE)]
        dead = wall.tiles[W.LIVE_END:]
        everything = [t for hand in hands for t in hand] + drawn + dead
        assert all(len(hand) == 13 for hand in hands)
        assert len(dead) == 14 and sorted(everything) == list(range(NUM_TILES))
        assert wall.live_remaining == 0
        with pytest.raises(W.WallError):
            wall.draw()


def test_dora_indicators_are_in_the_dead_wall():
    wall = W.Wall.from_seed(5)
    indicators = [wall.dora_indicator(i) for i in range(5)]
    assert indicators == wall.tiles[126:131]
    with pytest.raises(W.WallError):
        wall.dora_indicator(5)


def test_broken_walls_are_rejected():
    tiles = W.shuffled_tiles(1)
    with pytest.raises(W.WallError):
        W.Wall(tiles[:-1])
    duplicated = tiles[:]
    duplicated[0] = duplicated[1]   # 同じ牌が 2 回＝ある牌が 5 枚目になる状況
    with pytest.raises(W.WallError):
        W.Wall(duplicated)
    with pytest.raises(W.WallError):
        W.Wall.from_seed(1).dealt_hand(4)


def test_first_and_last_positions_are_uniform():
    """山の先頭と末尾に来る牌が偏っていないこと（カイ二乗検定。シード固定なので結果は毎回同じ）"""
    seeds = range(13600)
    for position in (0, NUM_TILES - 1):
        counts = Counter(W.shuffled_tiles(seed)[position] for seed in seeds)
        expected = len(seeds) / NUM_TILES
        chi2 = sum((counts[t] - expected) ** 2 / expected for t in range(NUM_TILES))
        assert chi2 < 190.0  # 自由度 135 の上側 0.1% 点（約 190）


def test_random_deal_has_the_expected_average_shanten():
    """補正なしの配牌の平均向聴数が、理論どおり約 3.6 になること（別の乱数での実測は 3.57〜3.58）"""
    for order in (0, 3):
        values = [Shanten.calculate_shanten(counts34(W.Wall.from_seed(seed).dealt_hand(order))) for seed in range(3000)]
        assert 3.50 < mean(values) < 3.66

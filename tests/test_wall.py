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


# ---------------------------------------------------------------- カン（嶺上牌・カンドラ）


def test_kan_takes_a_rinshan_tile_and_shortens_the_live_wall():
    wall = W.Wall.from_seed(11)
    tiles = list(wall.tiles)
    assert (wall.live_remaining, wall.live_end) == (70, 122)
    assert wall.dora_indicators == tiles[126:127] and wall.ura_indicators == tiles[131:132]

    first = wall.draw()
    assert first == tiles[52]
    for n in range(1, 5):
        assert wall.draw_rinshan() == tiles[122 + n - 1]      # 嶺上牌は 122 から順に引く
        assert wall.reveal_dora() == tiles[126 + n]           # カンドラは、最初のドラ表示牌の次から順にめくる
        assert wall.live_end == 122 - n                       # ツモ山の最後の 1 枚が王牌に回る
        assert wall.live_remaining == 70 - 1 - n
        assert wall.dora_indicators == tiles[126:127 + n] and wall.ura_indicators == tiles[131:132 + n]
    with pytest.raises(W.WallError):
        wall.draw_rinshan()                                    # カンは 1 局に 4 回まで
    with pytest.raises(W.WallError):
        wall.reveal_dora()                                     # ドラ表示牌は 5 枚まで

    drawn = [first] + [wall.draw() for _ in range(wall.live_remaining)]
    assert drawn == tiles[52:118]                              # 4 回カンすると、ツモれるのは 66 枚（位置 118〜121 は誰もツモらない）
    with pytest.raises(W.WallError):
        wall.draw()


def test_kan_is_impossible_when_the_live_wall_is_empty():
    wall = W.Wall.from_seed(3)
    for _ in range(70):
        wall.draw()
    with pytest.raises(W.WallError):
        wall.draw_rinshan()


def test_every_tile_is_used_at_most_once_with_kans():
    """配牌・ツモ・嶺上牌・表示牌をどう取っても、同じ牌が 2 回出ることはない"""
    for seed in range(200):
        wall = W.Wall.from_seed(seed)
        seen = [t for order in range(4) for t in wall.dealt_hand(order)]
        kans = seed % 5
        for step in range(70):
            if wall.live_remaining <= 0:
                break
            seen.append(wall.draw())
            if step < kans:
                seen.append(wall.draw_rinshan())
                wall.reveal_dora()
        seen += wall.dora_indicators + wall.ura_indicators
        assert len(seen) == len(set(seen))
        assert len(seen) == 52 + (70 - kans) + kans + 2 * (1 + kans)


def test_counters_are_validated():
    tiles = W.shuffled_tiles(1)
    for kwargs in ({"live_drawn": 71}, {"live_drawn": -1}, {"rinshan_drawn": 5}, {"dora_revealed": 0}, {"dora_revealed": 6}, {"live_drawn": 70, "rinshan_drawn": 1}):
        with pytest.raises(W.WallError):
            W.Wall(list(tiles), **kwargs)
    assert W.Wall(list(tiles), live_drawn=69, rinshan_drawn=1).live_remaining == 0


def test_copy_is_independent():
    wall = W.Wall.from_seed(8)
    other = wall.copy()
    other.draw()
    other.tiles[0], other.tiles[1] = other.tiles[1], other.tiles[0]
    assert wall.live_drawn == 0 and wall.tiles == W.shuffled_tiles(8) and not wall.sealed and other.sealed


# ---------------------------------------------------------------- ツキ補正のための並べ替え


def test_permute_rearranges_only_the_given_positions():
    wall = W.Wall.from_seed(5)
    before = list(wall.tiles)
    positions = [*wall.deal_positions(0), *range(W.LIVE_START, W.LIVE_END)]
    rearranged = [before[p] for p in reversed(positions)]
    wall.permute(positions, rearranged)
    wall.check()
    assert [wall.tiles[p] for p in positions] == rearranged
    untouched = [p for p in range(NUM_TILES) if p not in positions]
    assert all(wall.tiles[p] == before[p] for p in untouched)      # ほかの席の配牌と王牌はそのまま


def test_permute_refuses_anything_that_is_not_a_rearrangement():
    wall = W.Wall.from_seed(5)
    before = list(wall.tiles)
    with pytest.raises(W.WallError):                # 牌の集まりが変わる（別の牌を入れようとする）
        wall.permute([0, 1], [before[0], before[2]])
    with pytest.raises(W.WallError):                # 同じ牌を 2 か所に入れる
        wall.permute([0, 1], [before[0], before[0]])
    with pytest.raises(W.WallError):                # 同じ位置を 2 回指定する
        wall.permute([0, 0], [before[0], before[0]])
    with pytest.raises(W.WallError):                # 数が合わない
        wall.permute([0, 1], [before[1]])
    for dead in (W.RINSHAN_START, W.DORA_START, W.URA_START, NUM_TILES - 1):
        with pytest.raises(W.WallError):            # 王牌には触れない
            wall.permute([0, dead], [before[dead], before[0]])
    assert wall.tiles == before                      # 断られた操作は、山を変えない


def test_permute_is_only_allowed_before_dealing():
    wall = W.Wall.from_seed(5)
    wall.seal()
    with pytest.raises(W.WallError):
        wall.permute([0, 1], [wall.tiles[1], wall.tiles[0]])
    drawn_first = W.Wall.from_seed(5)
    drawn_first.draw()                               # ツモった時点で、配り終えたものとして扱う
    with pytest.raises(W.WallError):
        drawn_first.permute([0, 1], [drawn_first.tiles[1], drawn_first.tiles[0]])


def test_swap_live_only_touches_tiles_nobody_has_seen():
    wall = W.Wall.from_seed(9)
    before = list(wall.tiles)
    for _ in range(3):
        wall.draw()                                  # 位置 52〜54 はツモ済み
    wall.swap_live(55, 121)
    assert (wall.tiles[55], wall.tiles[121]) == (before[121], before[55])
    wall.check()
    for a, b in ((54, 60), (60, 54), (51, 60), (60, 122), (60, 126), (0, 60), (60, 135)):
        with pytest.raises(W.WallError):             # ツモ済みの牌、配牌、王牌は入れ替えられない
            wall.swap_live(a, b)

    wall.draw_rinshan()                              # カンすると、位置 121 は王牌に回る
    with pytest.raises(W.WallError):
        wall.swap_live(60, 121)
    wall.swap_live(60, 120)
    wall.check()

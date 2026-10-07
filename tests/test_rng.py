"""再現できる乱数（engine/rng.py）のテスト"""
import itertools
from collections import Counter

from engine.rng import Rng


def test_golden_values():
    """同じシードなら、どの Python のバージョンでも同じ列になること（値を固定して見張る）"""
    rng = Rng(1, "wall")
    assert [rng.random() for _ in range(3)] == [0.04991036812449601, 0.844790448778226, 0.5464219392881388]
    rng = Rng(1, "wall")
    assert [rng.below(136) for _ in range(8)] == [6, 114, 74, 68, 72, 122, 48, 54]
    rng = Rng("abc", "luck")
    assert [rng.below(10) for _ in range(8)] == [0, 3, 3, 2, 5, 1, 9, 0]


def test_same_seed_same_sequence_and_streams_are_independent():
    a = [Rng(42, "wall").below(1000) for _ in range(3)]
    assert a[0] == a[1] == a[2]
    wall = Rng(42, "wall")
    luck = Rng(42, "luck")
    assert [wall.below(1000) for _ in range(20)] != [luck.below(1000) for _ in range(20)]


def test_below_stays_in_range():
    rng = Rng(3)
    for n in (1, 2, 3, 136, 1000):
        values = [rng.below(n) for _ in range(2000)]
        assert min(values) >= 0 and max(values) < n
    assert all(Rng(i).below(1) == 0 for i in range(10))


def test_shuffle_is_a_permutation():
    rng = Rng(5)
    items = list(range(136))
    rng.shuffle(items)
    assert sorted(items) == list(range(136)) and items != list(range(136))


def test_shuffle_is_uniform():
    """4 個の並べ替え 24 通りが、ほぼ同じ回数ずつ出ること（カイ二乗検定。シード固定なので結果は毎回同じ）"""
    rng = Rng(7, "test")
    counts: Counter[tuple[int, ...]] = Counter()
    trials = 24000
    for _ in range(trials):
        items = [0, 1, 2, 3]
        rng.shuffle(items)
        counts[tuple(items)] += 1
    expected = trials / 24
    chi2 = sum((counts[p] - expected) ** 2 / expected for p in itertools.permutations(range(4)))
    assert len(counts) == 24
    assert chi2 < 49.7  # 自由度 23 の上側 0.1% 点


def test_choice_and_chance():
    rng = Rng(9)
    picks = Counter(rng.choice("abc") for _ in range(3000))
    assert set(picks) == {"a", "b", "c"} and min(picks.values()) > 850
    rng = Rng(11)
    rate = sum(rng.chance(0.25) for _ in range(20000)) / 20000
    assert 0.235 < rate < 0.265

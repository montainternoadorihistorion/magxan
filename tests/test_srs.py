"""間隔反復（間違えた問題を、間隔をあけてもう一度出す）のテスト"""
import json

from engine.srs import (
    DAY,
    FIRST_RIGHT_BOX,
    INTERVALS,
    MAX_BOX,
    MAX_CARDS,
    Card,
    Deck,
    deck_from_data,
    dump_deck,
    load_deck,
    merge_decks,
)

NOW = 1_800_000_000


def test_intervals_grow_and_first_right_box_is_valid():
    assert list(INTERVALS) == sorted(INTERVALS)
    assert INTERVALS[0] == 10 * 60          # 間違えた問題は、同じ回のうちにもう一度
    assert INTERVALS[1] == DAY
    assert 0 < FIRST_RIGHT_BOX < MAX_BOX


def test_first_time_right_starts_in_a_middle_box():
    deck = Deck().review("a", True, NOW)
    card = deck.cards["a"]
    assert card.box == FIRST_RIGHT_BOX
    assert card.due == NOW + INTERVALS[FIRST_RIGHT_BOX]
    assert (card.seen, card.right, card.last) == (1, 1, NOW)
    assert (deck.answered, deck.right) == (1, 1)
    assert deck.accuracy == 1.0


def test_wrong_answer_comes_back_soon():
    deck = Deck().review("a", False, NOW)
    card = deck.cards["a"]
    assert card.box == 0
    assert card.due == NOW + 10 * 60
    assert deck.due(NOW) == []                      # すぐには出ない
    assert deck.due(NOW + 10 * 60) == ["a"]
    assert deck.accuracy == 0.0


def test_box_climbs_one_step_per_right_answer_and_stops_at_the_top():
    deck = Deck().review("a", False, NOW)
    time = NOW
    for expected in (1, 2, 3, 4, 5, 5, 5):
        time = deck.cards["a"].due
        deck = deck.review("a", True, time)
        assert deck.cards["a"].box == expected
        assert deck.cards["a"].due == time + INTERVALS[expected]
    assert deck.cards["a"].box == MAX_BOX


def test_wrong_answer_resets_to_box_zero_from_anywhere():
    deck = Deck()
    for _ in range(4):
        deck = deck.review("a", True, NOW)
    assert deck.cards["a"].box > FIRST_RIGHT_BOX
    deck = deck.review("a", False, NOW + 5)
    assert deck.cards["a"].box == 0
    assert deck.cards["a"].seen == 5 and deck.cards["a"].right == 4


def test_due_lists_recent_mistakes_first_then_longest_waiting():
    deck = Deck(
        {
            "old": Card(3, NOW - 500, 4, 3, NOW - 9999),
            "older": Card(3, NOW - 900, 4, 3, NOW - 9999),
            "miss": Card(0, NOW - 10, 2, 0, NOW - 700),
            "later": Card(1, NOW + 60, 1, 1, NOW - 10),
        }
    )
    assert deck.due(NOW) == ["miss", "older", "old"]
    assert deck.due(NOW, skip={"miss"}) == ["older", "old"]
    assert deck.due(NOW + 60) == ["miss", "later", "older", "old"]


def test_waiting_counts_cards_not_yet_due_except_mastered_ones():
    deck = Deck(
        {
            "a": Card(0, NOW + 60, 1, 0, NOW),
            "b": Card(2, NOW + 999, 1, 1, NOW),
            "c": Card(MAX_BOX, NOW + 99999, 9, 9, NOW),
            "d": Card(1, NOW - 1, 3, 2, NOW - 5),
        }
    )
    assert deck.waiting(NOW) == 2


def test_generated_kinds_only_remember_mistakes():
    """その場で作る問題（keep=False）：正解した問題は覚えない。間違えた問題は、2 回続けて正解するまで出す"""
    deck = Deck().review("seed1", True, NOW, keep=False)
    assert deck.cards == {}
    assert (deck.answered, deck.right) == (1, 1)

    deck = deck.review("seed2", False, NOW, keep=False)
    assert deck.cards["seed2"].box == 0
    deck = deck.review("seed2", True, NOW + 600, keep=False)
    assert deck.cards["seed2"].box == 1                 # まだ覚えておく（翌日にもう一度）
    deck = deck.review("seed2", True, NOW + 600 + DAY, keep=False)
    assert "seed2" not in deck.cards                    # 2 回続けて正解したので、忘れる
    assert (deck.answered, deck.right) == (4, 3)


def test_card_limit_forgets_the_best_known_first_and_never_the_current_one():
    cards = {f"k{i}": Card(MAX_BOX, NOW + 1000 + i, 5, 5, NOW) for i in range(MAX_CARDS - 1)}
    cards["weak"] = Card(0, NOW + 5, 3, 0, NOW)
    deck = Deck(cards).review("new", True, NOW)        # 401 枚目
    assert len(deck.cards) == MAX_CARDS
    assert "new" in deck.cards and "weak" in deck.cards
    assert f"k{MAX_CARDS - 2}" not in deck.cards         # 次に出すのがいちばん先の 1 枚を忘れた

    full = {f"w{i}": Card(0, NOW + i, 1, 0, NOW) for i in range(MAX_CARDS)}
    deck = Deck(full).review("fresh", False, NOW + 10_000)
    assert "fresh" in deck.cards and len(deck.cards) == MAX_CARDS


def test_round_trip_through_json():
    deck = Deck().review("a", True, NOW).review("b", False, NOW + 1).review("a", True, NOW + 2)
    again = load_deck(dump_deck(deck))
    assert again == deck
    assert json.loads(dump_deck(deck))["v"] == 1


def test_broken_data_is_skipped_not_fatal():
    assert load_deck(None) == Deck()
    assert load_deck("") == Deck()
    assert load_deck("{not json") == Deck()
    assert load_deck("[" * 100000) == Deck()            # 入れ子が深すぎる
    assert load_deck('{"v": 99, "cards": {}}') == Deck()
    assert deck_from_data([1, 2, 3]) == Deck()
    data = {
        "v": 1, "n": 7, "right": 99,
        "cards": {
            "good": [2, NOW, 3, 2, NOW - 5],
            "short": [1, 2, 3],
            "bool": [True, NOW, 1, 1, NOW],
            "box": [9, NOW, 1, 1, NOW],
            "right": [1, NOW, 1, 2, NOW],
            "text": "x",
            "k" * 81: [1, NOW, 1, 1, NOW],
        },
    }
    deck = deck_from_data(data)
    assert list(deck.cards) == ["good"]
    assert (deck.answered, deck.right) == (7, 7)        # 正解の数は、答えた数を超えない
    assert deck_from_data({"v": 1, "n": -3, "right": True, "cards": None}) == Deck()


def test_card_from_list_rejects_bad_shapes():
    import pytest

    for bad in (None, [1, 2, 3, 4], [0, 1, 0, 0, 1], [0, -1, 1, 0, 1], [0, 1, 1, 0, 1.5], ["0", 1, 1, 0, 1]):
        with pytest.raises(ValueError):
            Card.from_list(bad)


def test_merge_takes_the_later_answer_and_never_adds_counts():
    mine = Deck({"a": Card(3, NOW + 9, 4, 3, NOW), "b": Card(0, NOW + 5, 1, 0, NOW - 50)}, answered=10, right=6)
    theirs = Deck({"a": Card(0, NOW + 1, 5, 3, NOW + 100), "c": Card(2, NOW, 1, 1, NOW - 9)}, answered=8, right=7)
    merged = merge_decks(mine, theirs)
    assert merged.cards["a"].box == 0                   # あとで答えたほう
    assert merged.cards["b"] == mine.cards["b"]
    assert merged.cards["c"] == theirs.cards["c"]
    assert (merged.answered, merged.right) == (10, 7)
    assert merge_decks(mine, mine) == mine              # 同じものを 2 回読み込んでも変わらない
    assert merge_decks(Deck(), theirs) == theirs

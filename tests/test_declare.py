"""あがったときの点数の申告（engine/declare.py・ui/declare_state.py）と、直近の正誤の記録（engine/srs.py）のテスト"""
from __future__ import annotations

import pytest

from engine.declare import declare_item, declare_quiz, plain_points
from engine.scoring.examples import EXAMPLES
from engine.scoring.explain import explain
from engine.scoring.notation import make_context
from engine.srs import RECENT_SIZE, Deck, deck_from_data, merge_decks
from engine.tiles import EAST, SOUTH
from ui.declare_state import clean_declared, declared_state, record_declaration
from ui.progress_store import DECLARE, read_deck


class FakeStore(dict):
    def get(self, name):
        return super().get(name)

    def set(self, name, value):
        self[name] = value

    def remove(self, name):
        self.pop(name, None)


def win(hand: str, tile: str, **kw):
    return explain(make_context(hand=hand, win=tile, **kw))


CHILD = {"seat_wind": SOUTH, "round_wind": EAST}
DEALER = {"seat_wind": EAST, "round_wind": EAST}


def test_quiz_for_a_child_ron():
    # 立直・平和・断么九 30 符 3 翻、子のロン ＝ 3,900 点
    explanation = win("234m567m234p55s67s", "8s", riichi=True, **CHILD)
    quiz = declare_quiz(explanation, "t:1")
    assert quiz is not None and quiz.answer == "3,900 点" and quiz.item == "c-r-30-3"
    assert len(quiz.choices) == 4 and quiz.answer in quiz.choices and len(set(quiz.choices)) == 4
    assert quiz.why == "立直・平和・断么九 で 30 符 3 翻。子のロンなので、3,900 点。"
    assert quiz.correct("3,900 点") and not quiz.correct(next(c for c in quiz.choices if c != quiz.answer))
    assert declare_quiz(explanation, "t:1") == quiz                   # 同じ鍵なら、同じ選択肢


def test_honba_and_kyotaku_are_left_out():
    explanation = win("234m567m234p55s67s", "8s", riichi=True, honba=2, kyotaku=1, **CHILD)
    assert explanation.best.points.total == 3900 + 600 + 1000
    assert plain_points(explanation).total == 3900
    quiz = declare_quiz(explanation, "t:2")
    assert quiz.answer == "3,900 点" and "本場と供託は除いて" in quiz.note


def test_tsumo_and_dealer_labels():
    child = declare_quiz(win("234m567m234p55s67s", "8s", is_tsumo=True, **CHILD), "t:3")
    assert child.answer == "700・1,300 点" and "子が払う点・親が払う点" in child.note       # 平和・ツモ・断么九 20 符 3 翻
    dealer = declare_quiz(win("234m567m234p55s67s", "8s", is_tsumo=True, **DEALER), "t:4")
    assert dealer.answer == "1,300 点オール" and dealer.item == "p-t-20-3"


def test_limit_hands_use_the_level_in_the_key():
    found = next(e for e in EXAMPLES if e.key == "G-8")                # 国士無双
    quiz = declare_quiz(explain(found.context(), found.rules), "t:5")
    assert quiz.item == "c-r-yakuman" and quiz.answer == "32,000 点" and quiz.why.startswith("国士無双 で 役満。")


def test_no_quiz_for_a_hand_without_yaku():
    found = next(e for e in EXAMPLES if e.key == "I-1")
    assert declare_quiz(explain(found.context(), found.rules), "t:6") is None


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.key)
def test_every_example_quiz_has_four_different_choices(example):
    explanation = explain(example.context(), example.rules)
    quiz = declare_quiz(explanation, example.key)
    if explanation.best is None or explanation.best.points is None:
        assert quiz is None
        return
    assert len(set(quiz.choices)) == 4 and quiz.answer in quiz.choices
    assert quiz.item == declare_item(plain_points(explanation), dealer=explanation.ctx.is_dealer, tsumo=explanation.ctx.is_tsumo)


def test_record_and_state():
    store = FakeStore()
    quiz = declare_quiz(win("234m567m234p55s67s", "8s", riichi=True, **CHILD), "t:7")
    assert record_declaration(store, quiz, quiz.answer, now=1000) is True
    assert record_declaration(store, quiz, quiz.choices[0] if quiz.choices[0] != quiz.answer else quiz.choices[1], now=2000) is False
    deck = read_deck(store, DECLARE)
    assert (deck.answered, deck.right, deck.recent) == (2, 1, "10") and deck.recent_accuracy(20) == (1, 2)
    state = declared_state(3, quiz, quiz.answer)
    assert clean_declared(state) == state and clean_declared({**state, "hand": -1}) is None
    assert clean_declared({**state, "picked": 5}) is None and clean_declared("x") is None
    old_shape = {"hand": None, "picked": None, "answer": "", "why": ""}                    # recorded の無い控え（前の版）
    assert clean_declared(old_shape) == {**old_shape, "recorded": True}
    unrecorded = declared_state(3, quiz, quiz.answer, recorded=False)
    assert clean_declared(unrecorded)["recorded"] is False and clean_declared({**unrecorded, "recorded": "no"})["recorded"] is True


def test_recent_answers_in_decks():
    deck = Deck()
    for index in range(RECENT_SIZE + 5):
        deck = deck.review(f"q{index % 3}", index % 4 != 0, 1000 + index)
    assert len(deck.recent) == RECENT_SIZE and deck.recent[-1] == "1"
    right, answered = deck.recent_accuracy(20)
    assert answered == 20 and right == deck.recent[-20:].count("1")
    again = deck_from_data(deck.to_data())
    assert again.recent == deck.recent
    old = deck.to_data()
    del old["recent"]                                                   # Phase 5 より前の記録
    assert deck_from_data(old).recent == "" and deck_from_data({**deck.to_data(), "recent": "102"}).recent == ""
    assert merge_decks(Deck(), deck).recent == deck.recent and merge_decks(deck, Deck()).recent == deck.recent

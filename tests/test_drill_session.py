"""ドリルの画面の状態（ui/drill_session.py）のテスト。画面なしで、出題と採点の流れ、記録の保存を確かめる"""
from __future__ import annotations

import json

import pytest

from engine import drills
from engine.drills import DONE, KINDS, NEW, REVIEW, items_of, question
from engine.srs import DAY, Card, Deck, dump_deck, load_deck
from ui.drill_session import EARLY, MODE_KIND, MODE_REVIEW, DrillSession
from ui.progress_store import DRILL_PREFIX

NOW = 1_800_000_000


class FakeStore:
    """ブラウザ内保存の代わり（ただの辞書）"""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def remove(self, name: str) -> None:
        self.values.pop(name, None)

    def append(self, name: str, item: str, *, limit: int) -> None:
        raise AssertionError("ドリルは append を使わない")


class Clock:
    def __init__(self, time: int = NOW) -> None:
        self.time = time

    def __call__(self) -> float:
        return float(self.time)


def new_session(store: FakeStore | None = None, *, picks=None):
    store = store or FakeStore()
    clock = Clock()
    numbers = iter(picks if picks is not None else range(1000, 100000, 7))
    session = DrillSession({}, store, now=clock, pick=lambda: next(numbers))
    return session, store, clock


def deck_of(store: FakeStore, kind: str) -> Deck:
    return load_deck(store.values.get(DRILL_PREFIX + kind))


def right_keys(session: DrillSession) -> list[str]:
    return sorted(session.question.correct)


def wrong_keys(session: DrillSession) -> list[str]:
    q = session.question
    return [next(c.key for c in q.choices if c.key not in q.correct)]


# ---------------------------------------------------------------- 始める・答える


def test_nothing_is_shown_before_a_kind_is_chosen():
    session, store, _ = new_session()
    assert session.kind is None and session.question is None and not session.answered
    assert (session.count, session.right, session.rev) == (0, 0, 0)
    assert not session.answer(["x"]) and not session.answer_discard(0)
    assert store.values == {}


def test_start_shows_a_new_question():
    session, _, _ = new_session()
    session.start("table")
    q = session.question
    assert session.kind == "table" and session.mode == MODE_KIND and session.reason == NEW
    assert q is not None and q.kind == "table" and q.item in items_of("table")
    assert session.rev == 1 and not session.answered and session.result is None
    with pytest.raises(ValueError):
        session.start("nope")


def test_right_answer_is_recorded_and_scheduled():
    session, store, _ = new_session()
    session.start("table")
    item = session.item
    assert session.answer(right_keys(session))
    assert session.result == {"picked": right_keys(session), "correct": True}
    assert (session.count, session.right) == (1, 1)
    card = deck_of(store, "table").cards[item]
    assert card.box == 2 and card.due == NOW + 3 * DAY           # はじめて正解した問題は、3 日後から
    assert session.card == card and session.answered_at == NOW
    assert json.loads(store.values[DRILL_PREFIX + "table"])["n"] == 1


def test_wrong_answer_comes_back_in_ten_minutes():
    session, store, clock = new_session()
    session.start("han")
    first = session.item
    assert session.answer(wrong_keys(session))
    assert session.result["correct"] is False and (session.count, session.right) == (1, 0)
    assert deck_of(store, "han").cards[first].box == 0

    session.next()
    assert session.item != first and session.reason == NEW      # まだ 10 分たっていない
    session.answer(right_keys(session))
    clock.time += 601
    session.next()
    assert session.reason == NEW                                # 直前に出した問題は、続けて出さない（まだ覚えているので）
    for _ in range(4):
        session.answer(right_keys(session))
        session.next()
        if session.item == first:
            break
    assert session.item == first and session.reason == REVIEW


def test_an_answer_is_accepted_only_once_and_only_from_the_choices():
    session, store, _ = new_session()
    session.start("reading")
    assert not session.answer(["そんな読みは無い"])
    assert not session.answer([])
    assert not session.answer_discard(0)                         # 何切るの問題ではない
    assert not session.answered and store.values == {}
    assert session.answer(right_keys(session))
    assert not session.answer(wrong_keys(session))               # 二重に届いた答えは、数えない
    assert (session.count, session.right) == (1, 1)
    assert deck_of(store, "reading").answered == 1


def test_next_moves_on_and_bumps_the_revision():
    session, _, _ = new_session()
    session.start("valid")
    seen = [session.item]
    for _ in range(6):
        rev = session.rev
        session.answer(right_keys(session))
        assert session.rev == rev                                # 答えただけでは、問題の番号は変わらない
        session.next()
        assert session.rev == rev + 1 and not session.answered and session.card is None
        assert session.item not in seen
        seen.append(session.item)


def test_multi_answers_must_match_exactly():
    session, _, _ = new_session(picks=[3])
    session.start("yaku")
    q = session.question
    assert q.multi
    keys = sorted(q.correct)
    extra = next(c.key for c in q.choices if c.key not in q.correct)
    assert session.answer([*keys, extra])
    assert session.result["correct"] is False


def test_generated_kinds_remember_only_mistakes():
    session, store, clock = new_session(picks=range(11, 40))
    session.start("score")
    assert session.item == "11"
    session.answer(right_keys(session))
    assert session.card is None and deck_of(store, "score").cards == {}
    assert deck_of(store, "score").answered == 1

    session.next()
    assert session.item == "12"
    session.answer(wrong_keys(session))
    assert session.card.box == 0 and list(deck_of(store, "score").cards) == ["12"]
    clock.time += 3600
    shown = []
    for _ in range(5):                                           # 直前に出した問題は、続けて出さない。少しあいだを置いて、もう一度出る
        session.next()
        shown.append((session.item, session.reason))
        if session.reason == REVIEW:
            break
        session.answer(right_keys(session))
    assert shown[0][1] == NEW and shown[-1] == ("12", REVIEW) and len(shown) >= 3

    session.answer(right_keys(session))
    assert deck_of(store, "score").cards["12"].box == 1          # もう 1 回正解するまで、覚えておく


def test_discard_drill_is_answered_with_a_tile():
    session, store, _ = new_session(picks=[5])
    session.start("discard")
    q = session.question
    assert q.position is not None
    assert not session.answer(["1"])                             # 選択肢では答えられない
    assert not session.answer_discard(-1)
    best = next(t for t in q.position.tiles if str(t // 4) in q.correct)
    assert session.answer_discard(best)
    assert session.result == {"tile": best, "correct": True}
    assert not session.answer_discard(best)
    assert deck_of(store, "discard").answered == 1


# ---------------------------------------------------------------- 出し終えたとき・先取り・復習


def test_finite_kind_runs_out_then_offers_early_review():
    session, store, clock = new_session()
    items = items_of("han")
    deck = Deck()
    for item in items:
        deck = deck.review(item, True, NOW)
    store.set(DRILL_PREFIX + "han", dump_deck(deck))
    session.start("han")
    assert session.question is None and session.item is None and session.reason == DONE
    assert session.kind == "han"

    session.early()
    assert session.reason == EARLY and session.item in items
    session.answer(right_keys(session))
    assert deck_of(store, "han").cards[session.item].box == 3    # 先取りでも、正解すれば間隔が延びる

    clock.time += 3 * DAY
    session.next()
    assert session.reason == REVIEW


def test_early_review_with_nothing_to_review():
    session, _, _ = new_session()
    session._s["dr_kind"] = "han"
    session.early()
    assert session.item is None and session.reason == DONE


def test_review_mode_walks_through_due_items_of_every_kind():
    store = FakeStore()
    due = {"table": "cr:30:1", "han": "h:riichi", "score": "77"}
    for kind, item in due.items():
        store.set(DRILL_PREFIX + kind, dump_deck(Deck({item: Card(0, NOW - 5, 1, 0, NOW - 700)}, 1, 0)))
    session, _, _ = new_session(store)
    session.start_review()
    assert session.mode == MODE_REVIEW
    order = []
    while session.kind is not None:
        assert session.reason == REVIEW
        order.append((session.kind, session.item))
        session.answer(right_keys(session))
        session.next()
    assert order == [("han", "h:riichi"), ("table", "cr:30:1"), ("score", "77")]      # 種類の一覧と同じ順
    assert session.take_review_done() and not session.take_review_done()
    assert session.count == 3 and session.right == 3


def test_review_mode_with_nothing_due_goes_back_to_the_menu():
    session, _, _ = new_session()
    session.start_review()
    assert session.kind is None and session.take_review_done()


def test_leave_returns_to_the_menu():
    session, _, _ = new_session()
    session.start("table")
    rev = session.rev
    session.leave()
    assert session.kind is None and session.question is None and session.rev == rev + 1


def test_items_that_no_longer_exist_are_skipped():
    """内容を入れ替えたあと、セッションに古い問題の鍵が残っていても、次の問題に進む"""
    session, _, _ = new_session()
    session.start("valid")
    session._s["dr_item"] = "gone:t9"
    q = session.question
    assert q is not None and q.item in items_of("valid") and session.item == q.item


def test_every_kind_can_be_started_and_answered():
    for kind in KINDS:
        session, store, _ = new_session(picks=[21, 22, 23])
        session.start(kind)
        q = session.question
        assert q is not None and q.kind == kind, kind
        assert question(kind, session.item) is q
        if kind == "discard":
            assert session.answer_discard(q.position.tiles[0])
        else:
            assert session.answer(right_keys(session)) and session.result["correct"]
        assert deck_of(store, kind).answered == 1
        assert drills.progress_of(kind, deck_of(store, kind), NOW).answered == 1

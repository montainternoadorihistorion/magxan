"""ドリルのページを、画面なしで動かして確かめる。

答えの選択肢と手牌は、ブラウザの中の部品が描く（ここでは押せない）。答えたあとの状態は、ページが覚えている値
（セッション）を直接入れて作る。問題を進める仕組みそのものは test_drill_session.py、実際の画面は tools/e2e_phase2_check.py。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from html_helpers import check_tile_images, page_html, page_parts, text_of
from streamlit.testing.v1 import AppTest

from engine.coach import analyze
from engine.drills import GROUPS, KINDS, NEW, REVIEW, items_of, question
from engine.srs import DAY, INTERVALS, Card, Deck, dump_deck
from ui.components.browser_store import initial_state
from ui.progress_store import DRILL_PREFIX
from ui.ruby import missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
#: 種類ごとに、確かめる問題を 1 つ
SAMPLES = {
    "reading": "t:和了", "han": "h:sanshoku", "valid": "tanyao:e0", "yaku": "12345", "win": "12345", "wait": "12345",
    "fu": "777", "table": "cr:30:3", "score": "777", "discard": "777",
}
DETAILED = {"fu", "yaku", "valid", "score", "win"}


def open_drill(known: dict[str, str] | None = None, *, storage: bool = True, **query: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if storage:
        at.session_state[STORE_STATE] = initial_state(known or {})
    for name, value in query.items():
        at.query_params[name] = value
    at.switch_page("views/drill.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def show(at: AppTest, kind: str, item: str, *, reason: str = NEW) -> AppTest:
    """その問題を出した状態にする"""
    state = at.session_state
    state["dr_kind"], state["dr_item"], state["dr_reason"] = kind, item, reason
    state["dr_graded"], state["dr_card"] = None, None
    state["dr_rev"] = state["dr_rev"] + 1 if "dr_rev" in state else 1
    state["dr_mode"] = "kind"
    at.run()
    assert not at.exception, (kind, item, [e.value for e in at.exception])
    return at


def answer(at: AppTest, *, correct: bool) -> AppTest:
    """いまの問題に答えた状態にする（部品から答えが届いたあとと同じ値を入れる）"""
    state = at.session_state
    kind, item = state["dr_kind"], state["dr_item"]
    q = question(kind, item)
    now = int(time.time())
    if q.position is not None:
        best = {c.tile // 4 for c in analyze(q.position).best}
        tile = next(t for t in q.position.tiles if (t // 4 in best) == correct)
        state["dr_graded"] = {"tile": tile, "correct": correct}
    else:
        picked = sorted(q.correct) if correct else [next(c.key for c in q.choices if c.key not in q.correct)]
        state["dr_graded"] = {"picked": picked, "correct": correct}
    keep = KINDS[kind].finite or not correct
    state["dr_card"] = Card(2 if correct else 0, now + INTERVALS[2 if correct else 0], 1, 1 if correct else 0, now).to_list() if keep else None
    state["dr_at"] = now
    state["dr_count"], state["dr_right"] = 1, 1 if correct else 0
    at.run()
    assert not at.exception, (kind, item, [e.value for e in at.exception])
    return at


def buttons(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at: AppTest) -> str:
    return text_of(page_html(at))


def assert_ruby(at: AppTest, where: object = "") -> None:
    check_tile_images(page_html(at))
    missing = missing_ruby(page_parts(at))
    assert missing == [], (where, missing)


def choices_of(at: AppTest) -> dict:
    """選択肢の部品に渡した内容"""
    component = next(c for c in at.get("bidi_component") if c.proto.component_name == "mjdojo_choices")
    return json.loads(component.proto.json)


# ---------------------------------------------------------------- 開く・種類の一覧


def test_page_waits_for_browser_storage_then_starts_without_it():
    at = open_drill(storage=False)
    assert at.title[0].value == "ドリル" and any("確認しています" in i.value for i in at.info)
    assert not [b for b in buttons(at) if b in {info.name for info in KINDS.values()}]
    click(at, "保存を使わずに始める")
    assert KINDS["reading"].name in buttons(at)
    assert any("保存を使っていません" in c.value for c in at.caption)


def test_menu_lists_every_kind_in_groups():
    at = open_drill()
    found = buttons(at)
    assert [label for label in found if label in {info.name for info in KINDS.values()}] == [info.name for info in KINDS.values()]
    assert not any(label.startswith("復習する") for label in found)
    text = page_text(at)
    assert all(title in text for title in GROUPS.values()) and text.count("まだ答えていない") == len(KINDS)
    assert "復習の時刻になった問題は、いまは無い。" in text
    assert [e.label for e in at.expander] == ["点数の早見表", "ドリルのしくみ"]
    assert_ruby(at)


def test_menu_offers_review_when_something_is_due():
    now = int(time.time())
    deck = Deck({"cr:30:3": Card(0, now - 60, 1, 0, now - 700), "cr:30:1": Card(2, now + DAY, 1, 1, now)}, 2, 1)
    at = open_drill({DRILL_PREFIX + "table": dump_deck(deck)})
    assert "復習する（1 問）" in buttons(at)
    assert "2 回答えて、正答率 50%" in page_text(at) and "復習 1 問" in page_text(at)
    click(at, "復習する（1 問）")
    assert (at.session_state["dr_kind"], at.session_state["dr_item"], at.session_state["dr_reason"]) == ("table", "cr:30:3", REVIEW)
    assert "復習" in page_text(at) and question("table", "cr:30:3").prompt in page_text(at)


def test_menu_tells_when_the_next_review_comes():
    now = int(time.time())
    deck = Deck({"cr:30:1": Card(2, now + 3 * DAY, 1, 1, now)}, 1, 1)
    at = open_drill({DRILL_PREFIX + "table": dump_deck(deck)})
    assert "次の復習は、3 日後。" in page_text(at) and "復習待ち 1 問" in page_text(at)


def test_kind_button_and_url_start_a_drill():
    at = click(open_drill(), KINDS["table"].name)
    assert at.session_state["dr_kind"] == "table" and at.session_state["dr_item"] in items_of("table")
    shown = question("table", at.session_state["dr_item"])
    assert "やめて、種類の一覧へ" in buttons(at) and len(choices_of(at)["options"]) == len(shown.choices) >= 4

    linked = open_drill(k="han")
    assert linked.session_state["dr_kind"] == "han" and "k" not in linked.query_params
    unknown = open_drill(k="no_such_kind")              # 知らない種類は無視して、一覧を出す
    assert "dr_kind" not in unknown.session_state and KINDS["han"].name in buttons(unknown) and "k" not in unknown.query_params


# ---------------------------------------------------------------- 問題と答え


@pytest.mark.parametrize("kind", list(KINDS))
def test_question_page_before_and_after_answering(kind):
    item = SAMPLES[kind]
    q = question(kind, item)
    at = show(open_drill(), kind, item)
    text = page_text(at)
    assert q.prompt in text and KINDS[kind].name in text and "新しい問題" in text
    assert "やめて、種類の一覧へ" in buttons(at) and "次の問題" not in buttons(at)
    assert_ruby(at, (kind, "before"))
    if q.position is None:
        data = choices_of(at)
        assert [option["key"] for option in data["options"]] == [choice.key for choice in q.choices] and data["multi"] == q.multi
    else:
        assert any(c.proto.component_name == "mjdojo_tile_hand" for c in at.get("bidi_component"))

    for correct in (True, False):
        at = answer(show(at, kind, item), correct=correct)
        text = page_text(at)
        assert ("○ 正解" in text) == correct and ("✗ ちがう" in text) != correct, (kind, correct)
        assert all(line in text for line in q.answer)
        assert {"次の問題", "種類の一覧へ"} <= set(buttons(at)) and "やめて、種類の一覧へ" not in buttons(at)
        assert "この回 1 問・正解" in text
        assert_ruby(at, (kind, correct))
        labels = [e.label for e in at.expander]
        assert ("くわしい解説（計算の内訳）" in labels) == (kind in DETAILED), (kind, labels)
        assert ("受け入れ表（切る牌と、手が進む牌）" in labels) == (kind == "discard")
        if not correct:
            assert "もう一度出す" in text


def test_reading_drill_hides_readings_until_answered():
    at = show(open_drill(), "reading", "t:和了")
    assert "<ruby>" not in page_html(at) and "mj-asked" in page_html(at)
    assert all(reading == "" for option in choices_of(at)["options"] for _, reading in option["parts"])
    at = answer(at, correct=True)
    assert "<ruby>和了<rt>ホーラ</rt></ruby>" in page_html(at) and "mj-asked" not in page_html(at)
    links = [(e.proto.label, e.proto.page, e.proto.query_string) for e in at.get("page_link")]
    assert ("用語辞典で「和了」を見る", "terms", "t=" + quote("和了")) in links


def test_yaku_questions_link_to_the_yaku_page():
    at = answer(show(open_drill(), "han", "h:sanshoku"), correct=True)
    links = [(e.proto.label, e.proto.page, e.proto.query_string) for e in at.get("page_link")]
    assert ("役図鑑で「三色同順」を見る", "yaku", "y=sanshoku") in links


def test_wait_choices_carry_tile_images():
    at = show(open_drill(), "wait", "12345")
    options = choices_of(at)["options"]
    assert all(option["img"] and option["img"].endswith(".png") and option["alt"] for option in options)
    assert choices_of(at)["multi"] is True


def test_next_question_and_leaving():
    at = answer(show(open_drill(), "table", "cr:30:3"), correct=True)
    rev = at.session_state["dr_rev"]
    click(at, "次の問題")
    assert at.session_state["dr_rev"] == rev + 1 and at.session_state["dr_graded"] is None
    assert at.session_state["dr_kind"] == "table" and "やめて、種類の一覧へ" in buttons(at)
    click(at, "やめて、種類の一覧へ")
    assert at.session_state["dr_kind"] is None and KINDS["table"].name in buttons(at)


def test_all_questions_done_offers_early_review():
    now = int(time.time())
    cards = {item: Card(2, now + 3 * DAY, 1, 1, now) for item in items_of("han")}
    at = open_drill({DRILL_PREFIX + "han": dump_deck(Deck(cards, len(cards), len(cards)))})
    click(at, KINDS["han"].name)
    text = page_text(at)
    assert f"ひととおり出し終えた（{len(cards)} 問）" in text and "次の復習は、3 日後。" in text
    assert {"先取りで復習する", "種類の一覧へ"} <= set(buttons(at))
    assert_ruby(at)
    click(at, "先取りで復習する")
    assert at.session_state["dr_item"] in cards and at.session_state["dr_reason"] == "early"
    assert "先取りの復習" in page_text(at)


def test_items_that_no_longer_exist_are_skipped():
    """内容を入れ替えたあとに、古い問題の番号が残っていても、落ちずに次の問題へ進む"""
    at = show(open_drill(), "han", "h:no_such_yaku")
    assert at.session_state["dr_item"] in items_of("han") and "何翻？" in page_text(at)

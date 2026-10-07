"""ドリルの表示（ui/drill_view.py）のテスト。HTML の文字列として確かめる"""
from __future__ import annotations

import pytest
from html_helpers import check_html, check_tile_images, ruby_parts, ruby_terms, text_of

from engine.coach import analyze
from engine.drills import DONE, KINDS, NEW, REVIEW, DrillProgress, grade, grade_discard, items_of, progress_of, question
from engine.scoring.explain import Status, explain
from engine.srs import DAY, INTERVALS, MAX_BOX, Card, Deck
from ui.drill_session import EARLY
from ui.drill_view import (
    answer_lines_html,
    choices_review_html,
    done_html,
    header_html,
    kind_card_html,
    position_status_html,
    progress_text,
    prompt_html,
    river_html,
    srs_note_html,
    verdict_banner_html,
)
from ui.practice_view import candidates_html, shanten_html
from ui.ruby import Rubifier, missing_ruby
from ui.win_view import DETAIL_NORMAL, chips_html, detail_sections, hand_html, situation_chips, tiles_fit_html

NOW = 1_760_000_000
#: くわしい解説に出す部分（views/drill.py と同じ）
DETAIL_KEYS = {"fu": ("reading", "fu"), "yaku": ("reading", "yaku", "dora"), "valid": ("reading", "yaku"), "score": None, "win": None}


def rb() -> Rubifier:
    return Rubifier()


def items(kind: str, count: int = 40) -> list[str]:
    """確かめる問題。決まった数の問題がある種類は、全体からまんべんなく。その場で作る種類は、番号で"""
    if not KINDS[kind].finite:
        return [str(seed) for seed in range(count)]
    every = list(items_of(kind))
    return every[:: max(1, len(every) // count)]


def wrong_answer(q) -> list[str]:
    """はずれの答え（選択肢で答える問題）"""
    wrong = [choice.key for choice in q.choices if choice.key not in q.correct]
    return wrong[:1]


def page_pieces(kind: str, item: str, *, answered: bool, correct: bool = True) -> list[tuple[str, int]]:
    """ページ（views/drill.py）と同じ順・同じ分け方で、画面の部品を作る。返すのは（HTML, 範囲）の列。

    範囲 0 は、いつも見えている部分。折りたたみの中身は、別の番号（Rubifier.fork() に通す）。
    選択肢のボタンと手牌は、ブラウザの中の部品が描く（ここには入らない）。
    """
    q = question(kind, item)
    hidden = kind == "reading" and not answered
    ruby = Rubifier(enabled=False) if hidden else rb()
    pieces = [(header_html(kind, NEW, 3, 2, ruby) + prompt_html(q, ruby, asked=hidden), 0)]
    explanation = None
    if q.ctx is not None:
        explanation = explain(q.ctx, q.rules)
        html = chips_html(situation_chips(explanation), ruby) + hand_html(explanation, ruby)
        if q.river is not None:
            html += river_html(q.river, ruby, caption="自分の河（捨て牌）", aka=q.rules.aka_dora)
        pieces.append((html, 0))
    if q.hand:
        pieces.append((f'<div class="mj-hand">{tiles_fit_html(q.hand, aka=True)}</div>', 0))
    analysis = None
    if q.position is not None:
        analysis = analyze(q.position)
        pieces.append((position_status_html(q.position, ruby), 0))
        if answered:
            pieces.append((f'<div class="mj-sub">{ruby.html("◎ いちばん速い打牌　○ 同じ速さの打牌")}</div>', 0))
        pieces.append((river_html(q.river or (), ruby, caption="河（切った牌）", aka=q.position.rules.aka_dora), 0))
        if answered:
            best = [c.tile for c in analysis.best]
            tile = best[0] if correct else next(t for t in q.position.tiles if t // 4 not in {b // 4 for b in best})
            right, verdict, _ = grade_discard(q, tile)
            assert right == correct
            reasons = "".join(f"<li>{ruby.html(reason)}</li>" for reason in verdict.reasons)
            pieces.append((verdict_banner_html(right, ruby, text=verdict.label), 0))
            pieces.append((f'<div class="mj-review"><div>{ruby.html(verdict.text)}</div><ul>{reasons}</ul></div>', 0))
            pieces.append((answer_lines_html(q, ruby), 0))
    elif answered:
        graded = grade(q, q.correct if correct else wrong_answer(q))
        assert graded.correct == correct
        pieces.append((verdict_banner_html(graded.correct, ruby) + choices_review_html(q, graded, ruby) + answer_lines_html(q, ruby), 0))
    if answered:
        card = Card(0, NOW + INTERVALS[0], 1, 0, NOW) if not correct else Card(2, NOW + INTERVALS[2], 1, 1, NOW)
        note = srs_note_html(kind, card, correct, NOW, ruby)
        if note:
            pieces.append((note, 0))
        if analysis is not None:
            inner = ruby.fork()
            pieces.append((shanten_html(analysis, inner) + candidates_html(analysis, inner), 1))
        if kind in DETAIL_KEYS and explanation is not None and explanation.status is not Status.NOT_WINNING:
            sections = detail_sections(explanation, ruby.fork(), detail=DETAIL_NORMAL, keys=DETAIL_KEYS[kind])
            pieces.append(("".join(section.heading_html + section.html for section in sections), 2))
    return pieces


def scoped_parts(pieces) -> list[tuple[str, bool, int]]:
    return [(text, has, scope) for html, scope in pieces for text, has in ruby_parts(html)]


# ---------------------------------------------------------------- どの問題でも壊れない


@pytest.mark.parametrize("kind", list(KINDS))
def test_question_pages_render_and_give_ruby_on_first_appearance(kind):
    pages = 0
    for item in items(kind):
        for answered, correct in ((False, True), (True, True), (True, False)):
            q = question(kind, item)
            if answered and not correct and q.position is None and not wrong_answer(q):
                continue
            pieces = page_pieces(kind, item, answered=answered, correct=correct)
            for html, _ in pieces:
                check_tile_images(html)
                assert "None" not in html and "nan" not in text_of(html), (kind, item)
            assert missing_ruby(scoped_parts(pieces)) == [], (kind, item, answered, correct, missing_ruby(scoped_parts(pieces)))
            shown = [term for html, scope in pieces if scope == 0 for term in ruby_terms(html)]
            assert len(shown) == len(set(shown)), (kind, item, [t for t in shown if shown.count(t) > 1])
            pages += 1
    assert pages >= 60


def test_reading_drill_hides_every_reading_until_answered():
    for item in items("reading"):
        before = "".join(html for html, _ in page_pieces("reading", item, answered=False))
        assert "<ruby>" not in before and 'class="mj-prompt mj-asked"' in before, item
        after = "".join(html for html, _ in page_pieces("reading", item, answered=True))
        assert "mj-asked" not in after and "<ruby>" in after, item


# ---------------------------------------------------------------- 部品ごと


def test_header_shows_kind_reason_and_count():
    text = text_of(header_html("table", REVIEW, 5, 4, rb()))
    assert KINDS["table"].name in text and "復習" in text and "この回 5 問・正解 4" in text
    first = text_of(header_html("table", NEW, 0, 0, rb()))
    assert "新しい問題" in first and "この回" not in first
    assert "先取りの復習" in text_of(header_html("han", EARLY, 1, 1, rb()))
    done = text_of(header_html("han", DONE, 2, 2, rb()))          # 出す問題が無いとき：理由の札は出さない
    assert "復習" not in done and "新しい問題" not in done and "この回 2 問・正解 2" in done
    for kind in KINDS:
        html = header_html(kind, NEW, 1, 0, rb())
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], kind


def test_prompt_shows_note_and_rule_chips():
    q = question("han", "h:riichi")
    html = prompt_html(q, rb())
    assert q.prompt in text_of(html) and q.note in text_of(html) and 'class="mj-prompt"' in html
    plain = question("reading", "t:和了")
    assert 'class="mj-sub"' not in prompt_html(plain, rb())
    # 初期設定と違うルールで作った問題には、そのルールを札で出す（喰いタンなしの例）
    with_rules = next(q for q in (question("valid", item) for item in items_of("valid")) if q.rule_notes)
    html = prompt_html(with_rules, rb())
    assert text_of(html).count("ルール：") == len(with_rules.rule_notes) and "ルール：喰いタンなし" in text_of(html) and "mj-chip-luck" in html
    assert "ルール：" not in text_of(prompt_html(q, rb()))


def test_river_shows_the_tiles_or_says_it_is_empty():
    q = next(question("win", str(seed)) for seed in range(200) if question("win", str(seed)).river)
    html = river_html(q.river, rb(), caption="自分の河（捨て牌）")
    check_tile_images(html)
    assert html.count("<img") == len(q.river) and f"自分の河（捨て牌） {len(q.river)} 枚" in text_of(html)
    empty = river_html((), rb(), caption="河（切った牌）")
    assert "まだ 1 枚も切っていない" in text_of(empty) and "<img" not in empty
    assert missing_ruby(ruby_parts(empty)) == [] and "<ruby>河" in empty


def test_position_status_shows_round_seat_draws_and_dora():
    q = question("discard", "12345")
    html = position_status_html(q.position, rb())
    text = text_of(html)
    check_tile_images(html)
    assert "場" in text and "家（" in text and f"残りツモ {q.position.draws_left} 回" in text
    assert text.count("ドラ表示牌") == len(q.position.dora_indicators) >= 1
    assert html.count("<img") == 2 * len(q.position.dora_indicators)        # 表示牌と、その次の牌（ドラ）


def test_verdict_banner():
    assert "○ 正解" in text_of(verdict_banner_html(True, rb())) and "good" in verdict_banner_html(True, rb())
    wrong = verdict_banner_html(False, rb(), text="受け入れが狭くなる")
    assert "✗ ちがう" in text_of(wrong) and "受け入れが狭くなる" in text_of(wrong) and "bad" in wrong


def test_choices_review_marks_right_wrong_and_picked():
    q = question("table", "cr:30:3")
    wrong = next(choice.key for choice in q.choices if choice.key not in q.correct)
    html = choices_review_html(q, grade(q, [wrong]), rb())
    check_html(html)
    assert html.count("mj-choice-right") == 1 and html.count("mj-choice-wrong") == 1
    assert html.count("mj-choice-other") == len(q.choices) - 2 and html.count("選んだ答え") == 1
    right_row = html[html.index("mj-choice-right"):].split("</div></div>")[0]
    assert "3,900 点" in text_of(right_row) and "選んだ答え" not in right_row
    perfect = choices_review_html(q, grade(q, q.correct), rb())
    assert "mj-choice-wrong" not in perfect and perfect.count("選んだ答え") == 1


def test_choices_review_puts_the_label_before_its_explanation():
    """選択肢の名前 → その説明、の順に作る（ルビは、画面で先に出る名前のほうに付く）"""
    seen = 0
    for seed in range(120):
        q = question("yaku", str(seed))
        html = choices_review_html(q, grade(q, q.correct), rb())
        assert missing_ruby(ruby_parts(html)) == [], seed
        seen += sum(1 for choice in q.choices if choice.why)
    assert seen > 50


def test_choices_review_shows_tiles_for_wait_questions():
    q = question("wait", "12345")
    html = choices_review_html(q, grade(q, q.correct), rb())
    check_tile_images(html)
    assert html.count("<img") == len(q.choices) and html.count("mj-choice-right") == len(q.correct)


def test_answer_lines():
    q = question("table", "cr:30:3")
    html = answer_lines_html(q, rb())
    assert all(line in text_of(html) for line in q.answer) and html.count("<br>") == len(q.answer) - 1


def test_srs_note_tells_when_the_question_comes_back():
    wrong = Card(0, NOW + INTERVALS[0], 1, 0, NOW)
    assert "10 分ほどあとに、もう一度出す" in text_of(srs_note_html("table", wrong, False, NOW, rb()))
    fresh = Card(2, NOW + INTERVALS[2], 1, 1, NOW)
    assert text_of(srs_note_html("table", fresh, True, NOW, rb())) == "次は、3 日後にもう一度出す。"
    best = Card(MAX_BOX, NOW + INTERVALS[MAX_BOX], 6, 6, NOW)
    assert text_of(srs_note_html("table", best, True, NOW, rb())) == "よく覚えている問題。次は、35 日後。"
    again = Card(1, NOW + INTERVALS[1], 2, 1, NOW)
    assert "前に間違えた問題。次に正解すれば、復習は終わり（次は 1 日後）" in text_of(srs_note_html("fu", again, True, NOW, rb()))
    # その場で作った問題に正解したときは、覚えておかないので、何も出さない
    assert srs_note_html("fu", None, True, NOW, rb()) == ""


def test_done_card_and_kind_card():
    deck = Deck().review("h:riichi", True, NOW).review("h:ippatsu", False, NOW)
    progress = progress_of("han", deck, NOW)
    html = done_html("han", progress, NOW, rb())
    text = text_of(html)
    assert f"「{KINDS['han'].name}」の問題は、ひととおり出し終えた（{progress.total} 問）。" in text
    assert "次の復習は、10 分後。" in text and "先取りで復習することもできる" in text
    assert "次の復習は" not in text_of(done_html("han", progress_of("han", Deck(), NOW), NOW, rb()))
    for kind in KINDS:
        card = kind_card_html(kind, progress_of(kind, Deck(), NOW), rb())
        check_html(card)
        assert missing_ruby(ruby_parts(card)) == [], kind
        assert KINDS[kind].short in text_of(card) and "まだ答えていない" in text_of(card) and "mj-badge" not in card
    due = kind_card_html("han", progress_of("han", deck, NOW + DAY), rb())
    assert '<span class="mj-badge">復習 1</span>' in due


def test_progress_text():
    assert progress_text("han", DrillProgress(0, 0, 0, 0, 38)) == "まだ答えていない"
    finite = DrillProgress(answered=10, right=8, due=2, waiting=3, total=38, seen=9, learned=4)
    assert progress_text("han", finite) == "10 回答えて、正答率 80%・定着 4 / 38 問・復習 2 問"
    waiting = DrillProgress(answered=10, right=8, due=0, waiting=3, total=38, seen=9, learned=4)
    assert progress_text("han", waiting) == "10 回答えて、正答率 80%・定着 4 / 38 問・復習待ち 3 問"
    generated = DrillProgress(answered=3, right=3, due=0, waiting=0, total=None)
    assert progress_text("fu", generated) == "3 回答えて、正答率 100%"

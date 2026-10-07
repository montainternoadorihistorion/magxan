"""「学ぶ」のページ（役図鑑・用語辞典・卓で打つとき・ルールの違い）を、画面なしで動かして確かめる。

ブラウザの中で動く部品（分類を選ぶボタン・ブラウザ内保存）は、ここでは動かせない。部品から値が届いたあとの
ページの動きを確かめる（実際の画面は tools/e2e_phase2_check.py）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from html_helpers import check_tile_images, page_html, page_parts, text_of
from streamlit.testing.v1 import AppTest

from engine.content import GROUPS, glossary, rule_book, table_guide, yaku_pages
from engine.progress import Stamp, dump_stamps
from ui.components.browser_store import initial_state
from ui.learn_view import YAKU_CATEGORY, list_label, next_label
from ui.progress_store import STAMPS_NAME
from ui.ruby import missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
PAGES = yaku_pages()


def open_page(path: str, known: dict[str, str] | None = None, *, storage: bool = True, **query: str) -> AppTest:
    """ページを開く。known はブラウザに残っていた保存内容。storage が偽なら、保存の返事がまだ届いていない状態"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if storage:
        at.session_state[STORE_STATE] = initial_state(known or {})
    for name, value in query.items():
        at.query_params[name] = value
    at.switch_page(path).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def links(at: AppTest) -> list[tuple[str, str, str]]:
    """ページへのリンク（文字, 行き先, URL に付ける値）"""
    return [(e.proto.label, e.proto.page, e.proto.query_string) for e in at.get("page_link")]


def page_text(at: AppTest) -> str:
    return text_of(page_html(at))


def assert_ruby(at: AppTest, where: str = "") -> None:
    """画面に出る順に読んで、初出の用語に読みが付いている（ボタンやリンクの名前も含めて）。牌の画像も実在する"""
    check_tile_images(page_html(at))
    missing = missing_ruby(page_parts(at))
    assert missing == [], (where, missing)


# ---------------------------------------------------------------- 役図鑑：一覧


def test_yaku_list_links_to_every_page_in_groups():
    at = open_page("views/yaku_book.py")
    assert at.title[0].value == "役図鑑"
    found = [link for link in links(at) if link[1] == "yaku"]
    assert [query for _, _, query in found] == [f"y={page.key}" for page in PAGES]
    assert [label for label, _, _ in found] == [list_label(page, None) for page in PAGES]
    text = page_text(at)
    assert all(title in text for group, title in GROUPS.items() if any(page.group == group for page in PAGES))
    assert "「門前」は、鳴くと付かない役。" in text and "まずは、よく出る役" in text
    assert [e.label for e in at.expander] == ["出やすさの目安と、由来の確かさについて"]
    assert_ruby(at)


def test_yaku_list_shows_stamps_from_the_browser_records():
    stamps = {"riichi": Stamp(3, 1_760_000_000, 1_760_100_000, 1), "pinfu": Stamp(1, 1_760_000_000, 1_760_000_000, 0)}
    at = open_page("views/yaku_book.py", {STAMPS_NAME: dump_stamps(stamps)})
    labels = {query: label for label, page, query in links(at) if page == "yaku"}
    assert "✓3" in labels["y=riichi"] and "✓1" in labels["y=pinfu"] and "✓" not in labels["y=tanyao"]
    assert f"{len(PAGES)} の役のうち" in page_text(at)
    progress = at.get("progress")
    assert len(progress) == 1 and f"スタンプ 2 / {len(PAGES)}" in progress[0].proto.text


def test_yaku_list_renders_before_the_browser_records_arrive():
    """開いた直後で、保存の返事がまだ届いていなくても、一覧は出す（スタンプなしで）"""
    at = open_page("views/yaku_book.py", storage=False)
    assert len([link for link in links(at) if link[1] == "yaku"]) == len(PAGES)
    assert not at.get("progress") and "スタンプが押される" not in page_text(at)


def test_unknown_yaku_key_falls_back_to_the_list():
    at = open_page("views/yaku_book.py", y="no_such_yaku")
    assert at.title[0].value == "役図鑑" and len([link for link in links(at) if link[1] == "yaku"]) == len(PAGES)


# ---------------------------------------------------------------- 役図鑑：役のページ


def test_every_yaku_page_opens_with_readings_and_navigation():
    at = open_page("views/yaku_book.py", y=PAGES[0].key)
    for index, page in enumerate(PAGES):
        at.query_params["y"] = page.key
        at.run()
        assert not at.exception, (page.key, [e.value for e in at.exception])
        assert_ruby(at, page.key)
        text = page_text(at)
        assert f"{page.name} {page.reading}" in text and "成立する条件" in text and "読み方と、名前の由来" in text, page.key
        assert ("成立する例" in text) == bool(page.examples) and ("ひっかけ：付きそうで、付かない例" in text) == bool(page.traps)
        found = links(at)
        # 上の行：一覧・前の役・次の役（リンクにはルビを振れないので、役の名前は書かない）
        expected = [("一覧へ", "yaku", "")]
        if index > 0:
            expected.append(("前の役", "yaku", f"y={PAGES[index - 1].key}"))
        if index < len(PAGES) - 1:
            expected.append(("次の役", "yaku", f"y={PAGES[index + 1].key}"))
        assert found[: len(expected)] == expected, page.key
        # 下の行：次の役は、名前と読みを並べて出す
        tail = found[len(expected):]
        if index < len(PAGES) - 1:
            assert tail[0] == (next_label(PAGES[index + 1]), "yaku", f"y={PAGES[index + 1].key}")
        assert [label for label, _, _ in tail][-2:] == ["役の一覧へ", "用語辞典で言葉を調べる"]
        buttons = [b.label for b in at.button]
        assert ("この役を実戦で練習する" in buttons) == (page.practice is not None), page.key
        if page.practice_note:
            assert page.practice_note in text


def test_yaku_page_shows_the_stamp_and_target_practice_record():
    stamps = {"sanshoku": Stamp(2, 1_760_000_000, 1_760_100_000, 0)}
    at = open_page("views/yaku_book.py", {STAMPS_NAME: dump_stamps(stamps)}, y="sanshoku")
    assert "スタンプ：2 回 成立させた" in page_text(at)
    fresh = open_page("views/yaku_book.py", y="sanshoku")
    assert "スタンプ：まだ成立させていない" in page_text(fresh)
    waiting = open_page("views/yaku_book.py", storage=False, y="sanshoku")
    assert "スタンプ：" not in page_text(waiting)          # 記録がまだ届いていないあいだは、スタンプの欄を出さない


def test_practice_button_starts_a_target_hand():
    at = open_page("views/yaku_book.py", y="sanshoku")
    next(b for b in at.button if b.label == "この役を実戦で練習する").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "一人練習"
    assert at.session_state["pr_state"].config.target == "sanshoku"
    assert "役指定：三色同順" in page_text(at) and "target" not in at.query_params


# ---------------------------------------------------------------- 用語辞典


def test_glossary_opens_on_the_first_category():
    book = glossary()
    at = open_page("views/glossary.py")
    assert at.title[0].value == "用語辞典"
    first = next(iter(book.categories))
    text = page_text(at)
    assert all(term.term in text and term.reading in text for term in book.of(first))
    assert at.session_state["gl_category"] == first
    assert_ruby(at)


@pytest.mark.parametrize("category", [*glossary().categories, YAKU_CATEGORY])
def test_glossary_category_pages(category):
    at = open_page("views/glossary.py")
    at.session_state["gl_category"] = category          # 分類のボタンは、ブラウザの中の部品（押すと、この値が変わる）
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert_ruby(at, category)
    text = page_text(at)
    if category == YAKU_CATEGORY:
        assert all(page.name in text and page.reading in text for page in PAGES)
        assert ("役図鑑（定義・成立例・コツ）を開く", "yaku", "") in links(at)
    else:
        assert all(term.term in text and term.meaning in text for term in glossary().of(category))


def test_glossary_search_finds_terms_and_yaku_names():
    at = open_page("views/glossary.py")
    at.text_input(key="gl_w_query").set_value("てんぱい").run()
    assert not at.exception
    text = page_text(at)
    assert "聴牌 テンパイ" in text and "形式聴牌" in text
    assert any(re.fullmatch(r"「てんぱい」で \d+ 件", c.value) for c in at.caption)
    assert_ruby(at, "てんぱい")

    at.text_input(key="gl_w_query").set_value("リーチ").run()
    assert "立直 リーチ" in page_text(at) and "ダブル立直" in page_text(at)
    assert_ruby(at, "リーチ")

    at.text_input(key="gl_w_query").set_value("zzzz").run()
    assert "見つからなかった" in page_text(at) and any(c.value == "「zzzz」で 0 件" for c in at.caption)

    at.text_input(key="gl_w_query").set_value("").run()         # 空に戻すと、分類の一覧に戻る
    assert glossary().of(at.session_state["gl_category"])[0].term in page_text(at)


def test_glossary_deep_link_shows_the_term_first_and_opens_its_category():
    book = glossary()
    term = book.find("聴牌")
    at = open_page("views/glossary.py", t="聴牌")
    html = page_html(at)
    assert "さがした用語" in text_of(html) and at.session_state["gl_category"] == term.category
    assert html.index("さがした用語") < html.index("分類を選ぶ")
    assert_ruby(at)
    # そのあとで分類を変えても、URL の用語に引き戻さない
    other = next(key for key in book.categories if key != term.category)
    at.session_state["gl_category"] = other
    at.run()
    assert at.session_state["gl_category"] == other and book.of(other)[0].term in page_text(at)
    assert "さがした用語" not in page_text(open_page("views/glossary.py", t="そんな言葉は無い"))


# ---------------------------------------------------------------- 卓で打つとき・ルールの違い


def test_table_guide_shows_every_step_with_a_fold_for_details():
    guide = table_guide()
    at = open_page("views/table_guide.py")
    assert at.title[0].value == "卓で打つとき"
    labels = [e.label for e in at.expander]
    # 折りたたみの名前にはルビを振れないので、用語の入った題名は、見出し（HTML）のほうに出す
    assert labels == [*(f"{number}. くわしい手順" for number in range(1, len(guide.sections) + 1)), "調べた資料"]
    text = page_text(at)
    for section in guide.sections:
        assert section.title in text and section.summary in text and all(step in text for step in section.steps)
    assert "30 符 4 翻" in text and ("ドリルで点数を覚える", "drill", "k=table") in links(at)
    assert_ruby(at)


def test_rules_page_lists_the_checklist_and_every_item():
    book = rule_book()
    at = open_page("views/rules.py")
    assert at.title[0].value == "ルールの違い"
    labels = [e.label for e in at.expander]
    assert labels == [*(f"{title}（{len(book.of(group))}）" for group, title in book.groups.items() if book.of(group)), "調べた資料と、注意"]
    text = page_text(at)
    assert "★ 卓に着く前に確かめること" in text and "アリアリですか？" in text
    assert all(item.title in text and item.ask in text for item in book.items)
    assert all(caveat in text for caveat in book.caveats)
    assert ("点数計算ラボで、ルールを変えて計算してみる", "lab", "") in links(at)
    assert_ruby(at)

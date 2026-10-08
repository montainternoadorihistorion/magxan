"""「学ぶ」のページの表示（ui/learn_view.py）のテスト。HTML の文字列として確かめる"""
from __future__ import annotations

import dataclasses
import re

import pytest
from html_helpers import check_html, check_tile_images, ruby_parts, ruby_terms, text_of

from engine.analysis.target import TARGET_KEYS
from engine.content import (
    CERTAINTY_MEANINGS,
    GROUPS,
    TRAP_RESULTS,
    Origin,
    Source,
    glossary,
    rule_book,
    table_guide,
    yaku_page_map,
    yaku_pages,
    yaku_stats,
)
from engine.progress import Stamp, completion
from engine.records import TargetStat
from engine.scoring.explain import Status, explain
from ui.learn_view import (
    YAKU_CATEGORY,
    book_intro_html,
    certainty_html,
    certainty_legend_html,
    checklist_html,
    combos_html,
    completion_text,
    definition_html,
    example_html,
    frequency_html,
    guide_detail_html,
    guide_head_html,
    han_text,
    head_html,
    list_label,
    list_tag,
    next_label,
    origin_html,
    result_line_html,
    river_html,
    rule_item_html,
    rule_names_html,
    score_table_html,
    search_results,
    search_terms,
    sources_html,
    stamp_html,
    subhead,
    term_html,
    tips_html,
    trap_html,
    yaku_term_html,
)
from ui.ruby import Rubifier, missing_ruby
from ui.win_view import payment_text

PAGES = yaku_pages()
BY_KEY = yaku_page_map()
STAMP = Stamp(count=3, first=1_760_000_000, last=1_760_100_000, plain=1)


def rb() -> Rubifier:
    return Rubifier()


def assert_clean(html: str, name: str = "") -> None:
    """タグが対応していて、牌の画像が実在し、初出の用語にルビが付いていて、同じ用語に 2 回ルビを振っていない"""
    check_tile_images(html)
    assert "None" not in html and "nan" not in text_of(html), name
    assert missing_ruby(ruby_parts(html)) == [], (name, missing_ruby(ruby_parts(html)))
    terms = ruby_terms(html)
    assert len(terms) == len(set(terms)), (name, [t for t in terms if terms.count(t) > 1])


def yaku_page_makers(page) -> list:
    """役のページ（views/yaku_book.py）に出す部品を作る関数を、画面に出る順に並べる"""
    stats = yaku_stats()
    makers = [
        lambda r: head_html(page, r, stat=stats.pages.get(page.key)),
        lambda r: stamp_html(page, STAMP, TargetStat(tries=5, wins=3, made=2), r),
    ]
    if page.practice_note:
        makers.append(lambda r: f'<div class="mj-sub">{r.html(page.practice_note)}</div>')
    makers.append(lambda r: definition_html(page, r))
    if page.examples:
        makers.append(lambda r: subhead("成立する例", r) + "".join(example_html(page, hand, r) for hand in page.examples))
    if page.traps:
        makers.append(lambda r: subhead("ひっかけ：付きそうで、付かない例", r) + "".join(trap_html(page, trap, r) for trap in page.traps))
    if page.rivers:
        makers.append(lambda r: subhead("河（捨て牌）の例", r) + "".join(river_html(v.title, v.tiles, v.ok, v.note, r) for v in page.rivers))
    if page.good or page.never or page.combo_note:
        makers.append(lambda r: combos_html(page, r))
    makers.append(lambda r: tips_html(page, r) + subhead("出やすさの目安", r) + frequency_html(page, stats, r))
    makers.append(lambda r: subhead("読み方と、名前の由来", r) + origin_html(page, r))
    return makers


# ---------------------------------------------------------------- 役図鑑：どのページも壊れない


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.key)
def test_every_yaku_page_renders_with_ruby_on_first_appearance(page):
    makers = yaku_page_makers(page)
    ruby = rb()
    html = "".join(make(ruby) for make in makers)       # 画面 1 枚ぶん
    assert_clean(html, page.key)
    # どの部品も、それだけで出したとき、初出の用語にルビが付く（部品の中で、作る順と出る順が合っている）
    for index, make in enumerate(makers):
        alone = make(rb())
        check_html(alone)
        assert missing_ruby(ruby_parts(alone)) == [], (page.key, index, missing_ruby(ruby_parts(alone)))
    text = text_of(html)
    assert page.name in text and page.reading in text and page.short in text
    for line in (*page.definition, *page.tips):
        assert line in text


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.key)
def test_examples_and_traps_are_built_in_screen_order(page):
    """例の札は、題名 → 場面の札 → 手牌 → 結果 → 説明 の順に作る（ルビは、画面で先に出るほうに付く）"""
    for hand in page.examples:
        html = example_html(page, hand, rb())
        assert missing_ruby(ruby_parts(html)) == [], (page.key, hand.title)
        assert html.index("mj-ex-title") < html.index("mj-chips") < html.index("mj-hand") < html.index("mj-result")
    for trap in page.traps:
        html = trap_html(page, trap, rb())
        assert missing_ruby(ruby_parts(html)) == [], (page.key, trap.hand.title)
        assert html.index("mj-ex-title") < html.index("mj-chips") < html.index("mj-hand") < html.index("mj-note")


# ---------------------------------------------------------------- 役図鑑：見出し・一覧


def test_head_shows_name_reading_han_group_and_frequency():
    page = BY_KEY["riichi"]
    html = head_html(page, rb(), stat=yaku_stats().pages["riichi"])
    text = text_of(html)
    assert "立直 リーチ" in text and "1 翻（門前限定）" in text and "出やすさ：よく出る" in text and page.short in text
    assert '<span class="mj-big mj-term">立直</span>' in html and "<ruby>立直" not in html      # 読みを横に並べるので、名前にルビは振らない
    assert "mj-freq-good" in html
    # 卓での呼び方は、読みと違うときだけ出す
    assert "卓での呼び方" not in text
    spoken = next(p for p in PAGES if p.spoken and p.spoken != p.reading)
    assert f"卓での呼び方：{spoken.spoken}" in text_of(head_html(spoken, rb(), stat=None))
    assert "出やすさ" not in text_of(head_html(page, rb(), stat=None))


def test_head_marks_the_name_as_seen_so_later_text_gets_no_second_reading():
    page = BY_KEY["pinfu"]
    ruby = rb()
    head_html(page, ruby, stat=None)
    assert "<ruby>平和" not in definition_html(page, ruby)


def test_han_text_and_list_tags():
    assert han_text(BY_KEY["riichi"]) == "1 翻（門前限定）"
    assert han_text(BY_KEY["sanshoku"]) == "2 翻（鳴くと 1 翻）"
    assert han_text(BY_KEY["toitoi"]) == "2 翻（鳴いても同じ）"
    assert han_text(BY_KEY["kokushi"]).startswith("役満")
    assert han_text(BY_KEY["nagashi_mangan"]) == BY_KEY["nagashi_mangan"].han_text != ""
    assert list_tag(BY_KEY["riichi"]) == "門前" and list_tag(BY_KEY["sanshoku"]) == "鳴↓"
    assert list_tag(BY_KEY["toitoi"]) == "" and list_tag(BY_KEY["nagashi_mangan"]) == ""


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.key)
def test_link_labels_carry_the_reading_next_to_the_name(page):
    """リンクの文字にはルビを振れないので、読みを横に並べて書く"""
    label = list_label(page, None)
    assert label.startswith(f"**{page.name}**　{page.reading}") and "✓" not in label
    assert f"✓{STAMP.count}" in list_label(page, STAMP)
    assert next_label(page) == f"次の役：{page.name}　{page.reading}"
    seen = Rubifier()
    seen.note("門前")                 # 「門前」は、一覧の上の説明でルビを振ってある
    for text in (label, next_label(page)):
        missing = [term for term in missing_ruby([(text, False)]) if term not in seen.seen]
        assert missing == [], (page.key, text)


def test_completion_text_and_intro():
    done = completion({"riichi": STAMP, "pinfu": STAMP})
    assert completion_text(done) == f"スタンプ 2 / {done.total}（{round(200 / done.total)}%）"
    assert completion_text(completion({})) == f"スタンプ 0 / {done.total}（0%）"
    intro = book_intro_html(done, rb())
    assert_clean(intro)
    assert f"{done.total} の役のうち、{done.total - done.reachable} は一人練習では成立しない" in text_of(intro)
    assert "スタンプ" not in text_of(book_intro_html(None, rb()))        # 記録がまだ届いていないとき


def test_stamp_card_variants():
    page = BY_KEY["riichi"]
    got = text_of(stamp_html(page, STAMP, None, rb()))
    assert "スタンプ：3 回 成立させた" in got and "そのうちツキ補正なしで 1 回" in got and "2025/" in got
    assert "ツキ補正なし" not in text_of(stamp_html(page, Stamp(2, 1_760_000_000, 1_760_000_000, 0), None, rb()))
    assert "まだ成立させていない" in text_of(stamp_html(page, None, None, rb()))
    assert "一人練習では成立しない" in text_of(stamp_html(BY_KEY["chankan"], None, None, rb()))
    aimed = text_of(stamp_html(page, None, TargetStat(tries=4, wins=3, made=3), rb()))
    assert "役指定練習：4 局のうち、3 局で、この役の形ができた（上位の役になった局も含む）。" in aimed
    assert "役指定練習" not in text_of(stamp_html(page, None, TargetStat(), rb()))
    for html in (stamp_html(page, STAMP, TargetStat(tries=4, wins=3, made=3), rb()), stamp_html(BY_KEY["chankan"], None, None, rb())):
        assert_clean(html)


# ---------------------------------------------------------------- 役図鑑：例・ひっかけ


def test_result_line_shows_what_the_scoring_engine_computed():
    for page in PAGES:
        for hand in page.examples:
            result = explain(hand.context(), hand.rules)
            line = text_of(result_line_html(result, rb()))
            best = result.best
            assert best is not None and best.points is not None, (page.key, hand.title)
            assert payment_text(best.points, result.ctx) in line
            for item in best.evaluation.yaku:
                assert item.name in line
            if best.is_yakuman:
                assert best.points.level_name in line and " 翻" not in line
            elif best.points.level_name:
                assert f"{best.han} 翻（{best.points.level_name}）" in line
            else:
                assert f"{best.han} 翻 {best.fu.fu} 符" in line
            if best.dora_han:
                words = result.dora_words
                assert words and sum(int(word.split()[-1]) for word in words) == best.dora_han
                assert all(word in line for word in words)


def test_result_line_examples():
    riichi = BY_KEY["riichi"]
    first, second = (text_of(example_html(riichi, hand, rb())) for hand in riichi.examples[:2])
    assert "立直1 翻 40 符　1,300 点" in first
    # 裏ドラは「ドラ」とまとめず、裏ドラと書く（本文で「裏ドラは、リーチしてあがった人だけ」と区別を教えているので）
    assert "立直・門前清自摸和・平和・裏ドラ 25 翻（満貫）　2,000・4,000 点" in second


def test_example_card_shows_the_checks_of_the_page_yaku():
    page = BY_KEY["riichi"]
    html = example_html(page, page.examples[0], rb())
    assert "mj-ex-ok" in html and '<span class="mj-ex-mark good">○</span>' in html
    assert "mj-checks" in html and "mj-ng" not in html      # 成立例では、条件はすべて満たしている
    assert page.examples[0].note in text_of(html)


def test_trap_card_explains_why_the_yaku_is_not_made():
    for page in PAGES:
        for trap in page.traps:
            html = trap_html(page, trap, rb())
            text = text_of(html)
            assert "mj-ex-ng" in html and '<span class="mj-ex-mark bad">✗</span>' in html and trap.why in text, page.key
            result = explain(trap.hand.context(), trap.hand.rules)
            if trap.expect == "no_call":
                # 手の形ではなく、場面の決まりであがれない：点数計算にかけた結果は出さない
                assert TRAP_RESULTS["no_call"] in text and "mj-result-num" not in html
            elif trap.expect == "win":
                assert result.status is Status.WIN and payment_text(result.best.points, result.ctx) in text
                assert all(item.name in text for item in result.best.evaluation.yaku)
            elif trap.expect == "no_yaku":
                assert result.status is Status.NO_YAKU and "役がないので、あがれない" in text
            else:
                assert result.status is Status.NOT_WINNING and "あがりの形になっていない" in text


def test_trap_card_shows_the_failed_check():
    page = BY_KEY["riichi"]
    html = trap_html(page, page.traps[0], rb())
    assert 'class="mj-ng"' in html and "リーチを宣言していない" in text_of(html)


def test_river_examples_for_nagashi_mangan():
    page = BY_KEY["nagashi_mangan"]
    assert page.rivers
    for river in page.rivers:
        html = river_html(river.title, river.tiles, river.ok, river.note, rb())
        assert_clean(html)
        assert ("mj-ex-ok" in html) == river.ok and html.count("<img") == len(re.findall(r"\d", river.tiles)) > 0
    assert "<img" not in river_html("こわれた例", "xyz", False, "", rb())       # 読めない牌の書き方でも、落ちない


# ---------------------------------------------------------------- 役図鑑：複合・出やすさ・由来


def test_combos_name_the_other_yaku_with_reasons():
    page = BY_KEY["riichi"]
    html = combos_html(page, rb())
    text = text_of(html)
    assert "複合しやすい役（同時に付く）" in text and "複合しない役（同時には付かない）" in text
    for combo in (*page.good, *page.never):
        assert BY_KEY[combo.key].name in text and combo.why in text
    assert_clean(html)
    assert combos_html(dataclasses.replace(page, good=(), never=(), combo_note=""), rb()) == ""
    noted = next(p for p in PAGES if p.combo_note)
    assert noted.combo_note in text_of(combos_html(noted, rb()))


def test_frequency_shows_the_numbers_and_their_source():
    stats = yaku_stats()
    html = frequency_html(BY_KEY["riichi"], stats, rb())
    text = text_of(html)
    stat = stats.pages["riichi"]
    assert f"和了 {stat.total:,} 回のうち {stat.count:,} 回（41%。約 2 回に 1 回）" in text and "よく出る" in text
    assert stats.source.title in text and stats.source.site in text and f'href="{stats.source.url}"' in html
    assert "目安として見る" in text
    rare = text_of(frequency_html(BY_KEY["nagashi_mangan"], stats, rb()))
    assert "まれ" in rare and "0.02%" in rare and "局 " in rare
    for page in PAGES:
        assert_clean(frequency_html(page, stats, rb()), page.key)
        if page.key in stats.pages:
            assert stats.pages[page.key].level in text_of(frequency_html(page, stats, rb()))


def test_frequency_of_a_combined_count_does_not_claim_it_for_one_yaku():
    """出典が小四喜と大四喜をまとめて数えている。その回数を、片方の役だけの回数のようには書かない"""
    stats = yaku_stats()
    for key in ("shousuushii", "daisuushii"):
        stat = stats.pages[key]
        assert stat.combined and stat.note
        text = text_of(frequency_html(BY_KEY[key], stats, rb()))
        assert f"{stat.combined}として、和了 {stat.total:,} 回のうち {stat.count:,} 回" in text, text
        assert "この役だけの回数は分からない" in text and stat.note in text
        assert text.count("この役だけの回数") == 1 and "1 回）。" in text           # 同じことを 2 回言わない。文の終わりに「。」
    alone = text_of(frequency_html(BY_KEY["kokushi"], stats, rb()))
    assert "として、" not in alone and "分からない" not in alone


def test_frequency_never_writes_a_small_rate_as_zero_percent():
    stats = yaku_stats()
    for page in PAGES:
        stat = stats.pages.get(page.key)
        if stat is None or not stat.count:
            continue
        text = text_of(frequency_html(page, stats, rb()))
        percent = re.search(r"（([\d.]+)%。", text).group(1)
        assert float(percent) > 0, (page.key, text)
        assert f"約 {stat.one_in:,} 回に 1 回" in text


def test_origin_shows_reading_kanji_origin_and_certainty():
    for page in PAGES:
        html = origin_html(page, rb())
        text = text_of(html)
        assert page.reading in text and page.kanji in text and page.origin.text in text and page.origin.certainty in text
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], page.key


def test_certainty_badges_and_legend():
    for name in CERTAINTY_MEANINGS:
        assert name in certainty_html(Origin("", name))
    assert "mj-cert-mixed" in certainty_html(Origin("", "諸説あり")) and "mj-cert-sure" in certainty_html(Origin("", "確実"))
    legend = certainty_legend_html(rb())
    assert_clean(legend)
    for name, meaning in CERTAINTY_MEANINGS.items():
        assert name in text_of(legend) and meaning in text_of(legend)


def test_practice_targets_point_at_real_targets():
    for page in PAGES:
        assert page.practice is None or page.practice in TARGET_KEYS, page.key


# ---------------------------------------------------------------- 用語辞典


def test_every_term_card_renders():
    book = glossary()
    for term in book.terms:
        html = term_html(term, rb(), category=book.categories[term.category])
        assert_clean(html, term.term)
        text = text_of(html)
        assert term.term in text and term.reading in text and term.meaning in text and book.categories[term.category] in text
        assert f'<b class="mj-term mj-term-word">{term.term}</b>' in html
        if term.origin is not None:
            assert term.origin.text in text and term.origin.certainty in text
        if term.see:
            assert "関連：" + "・".join(term.see) in text
        if term.example:
            assert "<img" in html


def test_term_category_pages_give_ruby_on_first_appearance():
    """分類ごとの一覧（ページと同じ作り方）。先に出てくる札の「関連」の用語にも、ルビが付く"""
    book = glossary()
    for category in book.categories:
        ruby = rb()
        html = "".join(term_html(term, ruby) for term in book.of(category))
        assert_clean(html, category)
    ruby = rb()
    assert_clean("".join(yaku_term_html(page, ruby) for page in PAGES), YAKU_CATEGORY)


def test_related_terms_get_ruby():
    book = glossary()
    html = term_html(book.find("聴牌"), rb())
    assert "関連：" in text_of(html) and "<ruby>向聴<rt>シャンテン</rt></ruby>" in html


def test_yaku_term_cards():
    for page in PAGES:
        html = yaku_term_html(page, rb())
        text = text_of(html)
        assert page.name in text and page.reading in text and page.short in text and page.origin.certainty in text
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], page.key


def test_search_ignores_kana_type_and_width():
    book = glossary()
    terms, pages = search_terms(book, PAGES, "てんぱい")
    assert [t.term for t in terms][:1] == ["聴牌"] and "形式聴牌" in [t.term for t in terms]
    assert search_terms(book, PAGES, "テンパイ")[0] == terms == search_terms(book, PAGES, "ﾃﾝﾊﾟｲ")[0]
    terms, pages = search_terms(book, PAGES, "リーチ")
    assert {"立直", "一発", "ダブル立直"} <= {p.name for p in pages}
    assert search_terms(book, PAGES, "りーち")[1] == pages


def test_search_puts_headword_hits_first_and_needs_every_word():
    book = glossary()
    terms, _ = search_terms(book, PAGES, "待ち")
    hits = [("待ち" in t.term or "まち" in t.reading or "マチ" in t.reading) for t in terms]
    assert hits and hits == sorted(hits, reverse=True) and hits[0]         # 見出し語か読みに当たったものが先
    both, pages = search_terms(book, PAGES, "リーチ 宣言")
    one, _ = search_terms(book, PAGES, "リーチ")
    assert set(t.term for t in both) < set(t.term for t in one)
    assert search_terms(book, PAGES, "") == ([], []) == search_terms(book, PAGES, "   ")
    assert search_terms(book, PAGES, "zzzz") == ([], [])


def test_search_ranks_exact_then_prefix_then_contains_across_terms_and_yaku():
    """読みがぴったり合うものを先に出す（「りーち」なら立直。分類の順に並べると、説明に「リーチ」を含む用語が先に来てしまう）"""
    book = glossary()

    def first(query: str) -> str:
        item = search_results(book, PAGES, query)[0]
        return getattr(item, "term", None) or item.name

    assert first("りーち") == first("リーチ") == first("立直") == "立直"
    assert first("かん") == "カン" and first("ぽん") == "ポン" and first("ちー") == "チー" and first("てんぱい") == "聴牌"
    names = [getattr(item, "term", None) or item.name for item in search_results(book, PAGES, "ぽん")]
    assert names.index("ポン") < names.index("双碰")
    # 用語と役をまぜても、件数は search_terms と同じ（どちらにも入る当たりを、落としも重ねもしない）
    terms, pages = search_terms(book, PAGES, "りーち")
    assert len(search_results(book, PAGES, "りーち")) == len(terms) + len(pages)
    assert search_results(book, PAGES, "  ") == []


def test_sources_are_links_that_open_in_a_new_tab():
    sources = (Source("Wikipedia「立直」", "https://ja.wikipedia.org/wiki/立直"), Source("A & B", "https://example.org/?a=1&b=2"))
    html = sources_html(sources, rb())
    check_html(html)
    assert html.count('target="_blank" rel="noopener noreferrer"') == 2
    assert 'href="https://example.org/?a=1&amp;b=2"' in html and "A &amp; B" in html
    assert "<ruby>立直<rt>リーチ</rt></ruby>" in html        # 題名に出てくる用語にも、読みを付ける
    for book in (glossary(), table_guide(), rule_book()):
        html = sources_html(book.sources, rb())
        assert_clean(html)
        assert html.count("<li>") == len(book.sources) > 0


# ---------------------------------------------------------------- 卓で打つとき


def guide_pieces() -> list[tuple[str, int]]:
    """ページ（views/table_guide.py）と同じ順・同じ分け方で、部品を作る。返すのは（HTML, 範囲）の列"""
    guide = table_guide()
    ruby = rb()
    pieces = [(f'<div class="mj-note">{ruby.html(guide.intro)}</div>', 0)]
    for number, section in enumerate(guide.sections, start=1):
        pieces.append((guide_head_html(number, section, ruby), 0))
        inner = ruby.fork()
        html = guide_detail_html(section, inner)
        if section.key == "points":
            html += subhead("点数の早見表", inner) + score_table_html(inner)
        pieces.append((html, number))
    pieces.append((sources_html(guide.sources, ruby.fork()), len(guide.sections) + 1))
    return pieces


def scoped_parts(pieces) -> list[tuple[str, bool, int]]:
    return [(text, has, scope) for html, scope in pieces for text, has in ruby_parts(html)]


def test_table_guide_page_gives_ruby_inside_and_outside_the_folds():
    pieces = guide_pieces()
    for html, _ in pieces:
        check_tile_images(html)
    assert missing_ruby(scoped_parts(pieces)) == []
    guide = table_guide()
    heads = "".join(html for html, scope in pieces if scope == 0)
    for number, section in enumerate(guide.sections, start=1):
        assert f'<span class="mj-guide-num">{number}</span>' in heads
        assert section.title in text_of(heads) and section.summary in text_of(heads)


def test_guide_headings_carry_the_readings_that_fold_labels_cannot():
    """折りたたみの名前にはルビを振れない。用語の入った題名は、見出し（HTML）に書いて、そこで読みを付ける"""
    guide = table_guide()
    deal = next(s for s in guide.sections if s.key == "deal")
    assert "<ruby>配牌<rt>ハイパイ</rt></ruby>" in guide_head_html(3, deal, rb())


def test_guide_detail_lists_steps_points_and_differences():
    for section in table_guide().sections:
        html = guide_detail_html(section, rb())
        text = text_of(html)
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], section.key
        assert html.count("<ol") == 1 and all(step in text for step in section.steps)
        assert ("覚えておくこと" in text) == bool(section.points)
        assert ("卓やルールによって違うところ" in text) == bool(section.differ)


def test_score_table_matches_the_well_known_values():
    html = score_table_html(rb())
    assert_clean(html)
    child, dealer = re.findall(r'<table class="mj-table mj-score">(.*?)</table>', html, flags=re.DOTALL)

    def rows(table: str) -> dict[str, tuple[str, str]]:
        found = {}
        for row in re.findall(r"<tr>(.*?)</tr>", table, flags=re.DOTALL):
            cells = [text_of(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.DOTALL)]
            found[cells[0]] = (cells[1], cells[2])
        return found

    assert rows(child) == {
        "30 符 1 翻": ("1,000", "300・500"), "30 符 2 翻": ("2,000", "500・1,000"),
        "30 符 3 翻": ("3,900", "1,000・2,000"), "30 符 4 翻": ("7,700", "2,000・3,900"),
        "40 符 1 翻": ("1,300", "400・700"), "40 符 2 翻": ("2,600", "700・1,300"),
        "40 符 3 翻": ("5,200", "1,300・2,600"), "40 符 4 翻": ("8,000", "2,000・4,000"),
        "満貫": ("8,000", "2,000・4,000"), "跳満": ("12,000", "3,000・6,000"), "倍満": ("16,000", "4,000・8,000"),
        "三倍満": ("24,000", "6,000・12,000"), "役満": ("32,000", "8,000・16,000"),
    }
    assert rows(dealer) == {
        "30 符 1 翻": ("1,500", "500 オール"), "30 符 2 翻": ("2,900", "1,000 オール"),
        "30 符 3 翻": ("5,800", "2,000 オール"), "30 符 4 翻": ("11,600", "3,900 オール"),
        "40 符 1 翻": ("2,000", "700 オール"), "40 符 2 翻": ("3,900", "1,300 オール"),
        "40 符 3 翻": ("7,700", "2,600 オール"), "40 符 4 翻": ("12,000", "4,000 オール"),
        "満貫": ("12,000", "4,000 オール"), "跳満": ("18,000", "6,000 オール"), "倍満": ("24,000", "8,000 オール"),
        "三倍満": ("36,000", "12,000 オール"), "役満": ("48,000", "16,000 オール"),
    }
    assert "ルールによって異なる" in text_of(html)         # 切り上げ満貫


# ---------------------------------------------------------------- ルールの違い


def test_rule_items_render_title_question_and_every_side():
    book = rule_book()
    for item in book.items:
        html = rule_item_html(item, rb())
        text = text_of(html)
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], item.key
        assert item.title in text and item.ask in text and all(side.answer in text and side.who in text for side in item.sides)
        assert ("★" in text) == item.check and ("このアプリ" in text) == bool(item.app)
        # 画面に出る順（題名 → 何が分かれるか → それぞれの答え）
        assert html.index("mj-term-head") < html.index("mj-note") < html.index("mj-sides")


def test_rules_page_gives_ruby_inside_and_outside_the_folds():
    """ページ（views/rules.py）と同じ順・同じ分け方"""
    book = rule_book()
    ruby = rb()
    pieces = [
        (f'<div class="mj-note">{ruby.html(book.intro)}</div>' + rule_names_html(book.names, book.surveyed, ruby), 0),
        (
            subhead("★ 卓に着く前に確かめること", ruby)
            + f'<div class="mj-note"><b>{ruby.html(f"まず聞いておくこと（{len(book.first_checks)} つ）")}</b></div>'
            + f'<div class="mj-sub">{ruby.html("あがれるかどうかや、点数に、すぐ関わるもの。初めての卓では、これだけでも聞いておくと安心。")}</div>'
            + checklist_html(book.first_checks, ruby)
            + f'<div class="mj-sub">{ruby.html("聞き方の例：「アリアリですか？」（喰いタンと後付けが、どちらもありか、という意味）「赤は何枚ですか？」「トビはありますか？」。分からないことは、打つ前に聞けばよい。")}</div>',
            0,
        ),
        (checklist_html(book.more_checks, ruby.fork()), 50),
        (
            subhead("項目ごとの違い", ruby)
            + f'<div class="mj-sub">{ruby.html("点数・あがりと流局・試合の進め方・卓での決まりの、4 つのまとまりに分けた。開くと、6 つのルールでどう分かれるかと、このアプリの扱いが出る。")}</div>',
            0,
        ),
    ]
    for scope, group in enumerate(book.groups, start=1):
        inner = ruby.fork()
        pieces.append(("".join(rule_item_html(item, inner) for item in book.of(group)), scope))
    inner = ruby.fork()
    pieces.append((sources_html(book.sources, inner) + "".join(f"<li>{inner.html(text)}</li>" for text in book.caveats), 99))
    for html, _ in pieces:
        check_html(html)
    assert missing_ruby(scoped_parts(pieces)) == []


def test_checklist_and_rule_names():
    book = rule_book()
    html = checklist_html(book.checklist, rb())
    assert html.count("<li>") == len(book.checklist) > 0
    assert all(item.title in text_of(html) and item.ask in text_of(html) for item in book.checklist)
    # 初めての卓で、まず聞くものは 5 つまで（全部を聞くのは現実的でない）。残りは「余裕があれば」
    first = [item.key for item in book.first_checks]
    assert first == ["aka", "kuitan", "atozuke", "ippatsu_ura", "tobi"]
    assert set(book.first_checks) | set(book.more_checks) == set(book.checklist)
    assert not set(book.first_checks) & set(book.more_checks)
    names = text_of(rule_names_html(book.names, "2026-10-07", rb()))
    assert "2026/10/07 に調べた" in names and all(name in names for name in book.names.values())


def test_groups_are_the_ones_the_book_lists():
    assert {page.group for page in PAGES} <= set(GROUPS)

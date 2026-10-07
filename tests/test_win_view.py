"""和了解説の表示（ui/win_view.py）のテスト。HTML の文字列として確かめる"""
from __future__ import annotations

import dataclasses
import re

import pytest
from html_helpers import ROOT, check_html, headings_of, ruby_parts, ruby_terms, text_of

from engine.scoring.examples import EXAMPLES, EXAMPLES_BY_KEY
from engine.scoring.explain import Status, explain
from engine.scoring.notation import make_context
from engine.scoring.random_hand import random_win
from engine.tiles import EAST, SOUTH
from ui.ruby import Rubifier, missing_ruby
from ui.win_view import (
    DETAIL_BRIEF,
    DETAIL_FULL,
    DETAIL_NORMAL,
    explanation_sections,
    headline,
    situation_chips,
    tiles_fit_html,
)


def sections_of(key: str, detail: int = DETAIL_FULL):
    example = EXAMPLES_BY_KEY[key]
    return explanation_sections(explain(example.context(), example.rules), detail=detail)


def page_of(key: str, detail: int = DETAIL_FULL) -> str:
    return "".join(section.html for section in sections_of(key, detail))


def text_page(key: str, detail: int = DETAIL_FULL) -> str:
    return text_of(page_of(key, detail))


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.key)
@pytest.mark.parametrize("detail", [DETAIL_BRIEF, DETAIL_NORMAL, DETAIL_FULL])
def test_every_example_renders_valid_html(example, detail):
    result = explain(example.context(), example.rules)
    sections = explanation_sections(result, detail=detail)
    assert sections[0].key == "summary" and sections[0].title == "" and sections[0].heading_html == ""
    assert all(section.title and section.heading for section in sections[1:])
    for section in sections:
        for src in check_html(section.heading_html + section.html):
            assert (ROOT / "static" / "tiles" / src.rsplit("/", 1)[1]).is_file(), src
        assert "None" not in section.html and "nan" not in section.html
    page = "".join(section.heading_html + section.html for section in sections)      # 画面に出る順（見出し → 本文）
    assert headings_of(page) == [section.title for section in sections[1:]]
    # ルビは、1 つの用語につき画面の中で 1 回だけ。それも、最初に出てきたところに振る（見出しも含めて）
    for term in set(re.findall(r"<ruby>([^<]+)<rt>", page)):
        assert page.count(f"<ruby>{term}<rt>") == 1, term
    assert missing_ruby(ruby_parts(page)) == []


def test_section_order_by_detail():
    assert [s.key for s in sections_of("A-1", DETAIL_FULL)] == ["summary", "reading", "yaku", "dora", "fu", "points", "payment", "say"]
    assert [s.key for s in sections_of("A-1", DETAIL_NORMAL)] == ["summary", "reading", "yaku", "dora", "fu", "points", "payment", "say"]
    assert [s.key for s in sections_of("A-1", DETAIL_BRIEF)] == ["summary", "reading", "yaku", "points", "say"]
    assert [s.title for s in sections_of("A-1")][1:] == ["① 手牌の読み方", "② 役", "③ ドラ", "④ 符", "⑤ 点数", "⑥ 誰がいくら払うか", "⑦ 卓での申告"]


def test_full_explanation_shows_every_step():
    page = text_page("A-1")
    assert "1,300 点" in page
    assert "待ち：13索 で 2索 を待つ" in page
    assert "副底" in page and "32 符 → 10 符単位に切り上げ" in page
    assert "40 符 1 翻・子のロン：40 × 2³ ＝ 40 × 8 ＝ 320 → × 4 ＝ 1,280 → 切り上げて 1,300 点" in page
    assert "「ロン。リーチのみ。1300。」" in page
    assert "惜しかった役" in page and "を満たしていれば成立" in page


def test_brief_explanation_hides_details():
    brief = page_of("A-1", DETAIL_BRIEF)
    assert "40 × 2³" in text_of(brief) and "「ロン。リーチのみ。1300。」" in text_of(brief)
    assert "惜しかった役" not in brief and "mj-checks" not in brief and "mj-steps" not in brief
    normal = page_of("A-1", DETAIL_NORMAL)
    assert "mj-steps" in normal and "mj-checks" not in normal and "惜しかった役" not in normal


def test_alternative_readings_are_listed_with_results():
    page = page_of("F-1")
    text = text_of(page)
    assert "この 14 枚の読み方は 2 通り。点数が最も高くなる読み方を採用する" in text
    assert page.count('class="mj-alt"') == 2 and "採用" in text
    assert "6 翻 30 符 → 跳満 12,000 点" in text and "3 翻 50 符 → 6,400 点" in text
    assert "mj-alt" not in page_of("A-1")
    assert "mj-alt" not in page_of("F-1", DETAIL_BRIEF)       # 要点だけのときは、読み方が複数あることだけを知らせる
    assert "この 14 枚の読み方は 2 通り" in text_page("F-1", DETAIL_BRIEF)


def test_alternative_readings_show_the_payment_in_the_usual_form():
    """読み方の一覧の点数は、まとめと同じ書き方（ツモは「子・親」、親のツモは「オール」）"""
    tsumo = explain(make_context("4566m123p789s111z", "6m", seat_wind=SOUTH, is_tsumo=True))
    text = text_of("".join(s.html for s in explanation_sections(tsumo)))
    assert f"→ {headline(tsumo)}" in text and "オール 点" not in text
    dealer = explain(make_context("4566m123p789s222z", "6m", seat_wind=EAST, is_tsumo=True))
    text = text_of("".join(s.html for s in explanation_sections(dealer)))
    assert f"→ {headline(dealer)}" in text and headline(dealer).endswith("点オール") and "オール 点" not in text


def test_tied_readings_are_explained_as_equal():
    result = explain(make_context("4566m123p789s111z", "6m", seat_wind=SOUTH))
    page = text_of("".join(s.html for s in explanation_sections(result)))
    assert "点数は同じなので、どの読み方で数えてもよい" in page


def test_meld_captions_and_concealed_kan():
    text = text_page("B-1")
    assert "明刻（ポン）" in text and "順子（チー）" in text
    assert text.count("ポン") >= 2 and text.count("チー") >= 2      # 卓で見える形（副露）と、分解図の両方に出る
    kan = page_of("C-3")
    assert kan.count("back.png") == 2           # 卓で見える形では、暗槓の両端は裏向き
    assert "暗槓（么九牌）" in text_of(kan) and "32 符" in kan


def test_seven_pairs_kokushi_and_yakuman():
    chiitoi = text_page("E-1")
    assert "7 組の対子でできた七対子の形" in chiitoi and "25 符で固定" in chiitoi
    kokushi = text_page("G-8")
    assert "国士無双の形" in kokushi and "符は数えない" in kokushi and "役満・子のロン：基本点 8,000" in kokushi
    double = text_page("G-9")
    assert "役満 × 2" in double and "役満 2 つぶん" in double and "ダブル役満" in double
    assert "ほかの役（対々和）とドラは数えない" in double
    assert "符は数えなくてよい" in double


def test_rule_notes_section():
    keys = [s.key for s in sections_of("G-2")]
    assert keys[-1] == "rules" and "切り上げ満貫" in text_page("G-2")
    assert "rules" not in [s.key for s in sections_of("G-2", DETAIL_BRIEF)]
    assert "rules" not in [s.key for s in sections_of("A-1")]


def test_dora_section():
    page = text_page("H-3")
    assert "ドラ表示牌" in page and "裏ドラ表示牌" in page and "赤ドラ" in page
    assert "5萬 が手牌に 2 枚" in page and "8索 が手牌に 1 枚" in page
    assert "役 2 翻 ＋ ドラ 4 翻 ＝ 6 翻" in page
    assert "ドラは 0 翻" in text_page("A-1")


def test_no_yaku_and_not_winning():
    example = EXAMPLES_BY_KEY["I-1"]
    result = explain(example.context(), example.rules)
    sections = explanation_sections(result)
    assert [s.key for s in sections] == ["summary", "reading", "yaku"]
    page = text_of("".join(s.html for s in sections))
    assert "あがれない（役なし）" in page and "成立している役が無い" in page and "リーチを宣言していれば" in page
    assert "惜しかった役" in page

    with_dora = EXAMPLES_BY_KEY["I-2"]
    sections = explanation_sections(explain(with_dora.context(), with_dora.rules))
    assert [s.key for s in sections] == ["summary", "reading", "yaku", "dora"]
    assert "ドラは役ではない" in text_of(sections[-1].html)

    result = explain(make_context("123m456p789s23s19p", "4s", seat_wind=SOUTH))
    sections = explanation_sections(result)
    assert [s.key for s in sections] == ["summary"]
    assert "和了の形になっていない" in text_of(sections[0].html)


def test_inconsistent_result_shows_only_library_values():
    example = EXAMPLES_BY_KEY["A-2"]
    result = dataclasses.replace(explain(example.context(), example.rules), consistent=False, mismatches=("符",))
    sections = explanation_sections(result)
    assert [s.key for s in sections] == ["summary", "library"]
    library = text_of(sections[1].html)
    assert "一致しなかった" in library and "2 翻 30 符" in library and "2,000 点" in library


@pytest.mark.parametrize(
    ("key", "kw", "text"),
    [
        ("A-2", {}, "2,000 点"),
        ("A-3", {}, "400・700 点"),
        ("A-4", {}, "700 点オール"),
        ("H-1", {}, "4,500 点"),               # 本場ぶんを含めた、実際に払われる点
        ("H-2", {}, "1,400・2,700 点"),
    ],
)
def test_headline(key, kw, text):
    example = EXAMPLES_BY_KEY[key]
    assert headline(explain(example.context(), example.rules)) == text


def test_situation_chips():
    ctx = make_context("123m456p789s23s44z", "4s", riichi=True, double_riichi=True, ippatsu=True, honba=2, kyotaku=1, seat_wind=EAST, round_wind=SOUTH)
    assert situation_chips(explain(ctx)) == ["南場", "東家（親）", "ロン", "門前", "ダブル立直", "一発", "2 本場", "供託 1 本"]
    ctx = make_context("234m55p34s", "5s", melds=["pon 888m", "chi 678p"], is_tsumo=True, seat_wind=SOUTH)
    assert situation_chips(explain(ctx)) == ["東場", "南家（子）", "ツモ", "鳴きあり"]


def test_tiles_fit_html():
    ctx = make_context("123m456p789s23s44z", "4s", seat_wind=SOUTH)
    html = tiles_fit_html(ctx.closed_tiles, aka=True, win_tile=ctx.win_tile, gap_before_last=True)
    assert html.count("<img ") == 14 and html.count("mj-win") == 1
    assert html.count("minmax(0,34px)") == 14 and "8px" in html
    assert tiles_fit_html([], aka=True) == ""


def test_headings_get_ruby_when_the_term_first_appears_there():
    """見出しに出てくる用語が初出なら、見出しにルビを振る（本文のほうに回さない）"""
    page = "".join(s.heading_html + s.html for s in sections_of("A-1"))
    assert '<h3 class="mj-h3">① <ruby>手牌<rt>テハイ</rt></ruby>の読み方</h3>' in page
    assert page.count("<ruby>手牌<rt>") == 1 and "手牌を倒す" in text_of(page)          # あとの本文では、もう振らない
    assert '<h3 class="mj-h3">④ 符</h3>' in page                                      # 符は、上のまとめ（1 翻 40 符）で出ている
    # 役満の手は、まとめに符が出てこない。だから「④ 符」の見出しが初出になる
    yakuman = "".join(s.heading_html + s.html for s in sections_of("G-9"))
    assert '<h3 class="mj-h3">④ <ruby>符<rt>フ</rt></ruby></h3>' in yakuman
    assert ruby_terms(yakuman).count("符") == 1


def test_level_badge_keeps_its_ruby_outside_the_coloured_label():
    """満貫などのバッジは色つき。ルビを中に入れると、読みがバッジの文字色のまま外に出て、暗い画面で読めなくなる"""
    summary = sections_of("F-1")[0].html
    assert '<ruby><span class="mj-level">跳満</span><rt>ハネマン</rt></ruby>' in summary
    rb = Rubifier()
    rb.html("跳満")                                                                    # 先に出てきていれば、バッジだけ
    example = EXAMPLES_BY_KEY["F-1"]
    again = explanation_sections(explain(example.context(), example.rules), rb=rb)[0].html
    assert '<span class="mj-level">跳満</span>' in again and "<rt>ハネマン</rt>" not in again


def test_shared_rubifier_continues_across_page():
    """ページの上のほうで振ったルビは、解説の中ではもう振らない"""
    rb = Rubifier()
    rb.html("副底と符と門前")
    example = EXAMPLES_BY_KEY["A-1"]
    page = "".join(s.html for s in explanation_sections(explain(example.context()), rb=rb))
    assert "<ruby>副底<rt>" not in page and "<ruby>門前<rt>" not in page
    assert "<ruby>雀頭<rt>ジャントウ</rt></ruby>" in page


def test_random_hands_render():
    for seed in range(60):
        for kind in ("any", "open", "big"):
            result = explain(random_win(seed, kind))
            assert result.status is Status.WIN
            for section in explanation_sections(result):
                check_html(section.html)

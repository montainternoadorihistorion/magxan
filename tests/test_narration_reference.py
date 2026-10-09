"""AI に渡す参考（用語辞典・役図鑑・卓での手順・質問に出てきた点数）のテスト（narration/reference.py）"""
from __future__ import annotations

from dataclasses import replace

from engine.content import glossary
from engine.rules import DEFAULT_RULES
from engine.scoring.examples import EXAMPLES
from engine.scoring.explain import explain
from narration.facts import win_facts
from narration.reference import (
    MAX_PAGES,
    MAX_TERMS,
    guides_in,
    reference_sections,
    reference_text,
    scores_in,
    terms_in,
    yaku_pages_in,
)


def facts_of(key: str):
    found = next(e for e in EXAMPLES if e.key == key)
    return win_facts(explain(found.context(), found.rules))


def names(indexes: list[int]) -> list[str]:
    terms = glossary().terms
    return [terms[i].term for i in indexes]


def test_scores_for_han_and_fu_in_the_question():
    assert scores_in("30符4翻は何点？") == [
        "30 符 4 翻：子のロン 7,700 点・子のツモ 2,000・3,900 点・親のロン 11,600 点・親のツモ 3,900 点オール。"
    ]
    assert scores_in("2翻40符") == scores_in("４０符２翻") == [
        "40 符 2 翻：子のロン 2,600 点・子のツモ 700・1,300 点・親のロン 3,900 点・親のツモ 1,300 点オール。"
    ]
    assert scores_in("20符2翻") == [
        "20 符 2 翻：子のロンは、この組み合わせが無い・子のツモ 400・700 点・親のロンは、この組み合わせが無い・親のツモ 700 点オール。"
    ]
    assert scores_in("35符3翻")[0].startswith("35 符のあがりは無い")
    assert scores_in("6翻") == ["6 翻（5 翻以上は、符に関係なく点数が決まる）：子のロン 12,000 点・子のツモ 3,000・6,000 点・親のロン 18,000 点・親のツモ 6,000 点オール。"]
    assert scores_in("こんにちは") == []


def test_level_names_are_not_double_counted():
    lines = scores_in("三倍満と数え役満の違いは？")
    assert [line.split("：")[0] for line in lines] == ["数え役満", "三倍満"]        # 「倍満」「役満」は数えない
    assert scores_in("親の満貫") == ["満貫：子のロン 8,000 点・子のツモ 2,000・4,000 点・親のロン 12,000 点・親のツモ 4,000 点オール。"]


def test_scores_follow_the_rules():
    no_kazoe = replace(DEFAULT_RULES, kazoe_yakuman=False)
    assert scores_in("数え役満", no_kazoe)[0].startswith("数え役満（このルールでは三倍満）：子のロン 24,000 点")
    kiriage = replace(DEFAULT_RULES, kiriage_mangan=True)
    assert "子のロン 8,000 点" in scores_in("30符4翻", kiriage)[0]


def test_terms_in_questions_and_facts():
    assert names(terms_in("スジとテンパイって何？", question=True)) == ["筋", "聴牌"]      # 読みでも見つける
    assert names(terms_in("符って？", question=True)) == ["符"]
    assert "符" not in names(terms_in("合計 30 符", question=False))                      # 事実の文では 1 文字の語を探さない
    assert names(terms_in("ツモ切りしたあと", question=True)) == ["ツモ切り"]             # 長い語を先に


def test_yaku_pages():
    assert yaku_pages_in("ピンフとタンヤオ、リーチ", question=True) == ["pinfu", "tanyao", "riichi"]
    assert yaku_pages_in("リーチして", question=False) == []                             # 事実の文では、打ち方のことばを役と見ない
    assert yaku_pages_in("役牌の白", question=True) == ["yakuhai"]


def test_manner_guides_only_for_manner_questions():
    assert guides_in("鳴くときの発声は？") == ["call"]
    assert guides_in("マナーを教えて") == ["manner"]
    assert guides_in("ポンの条件は？") == []


def test_sections_put_the_question_first_and_are_capped():
    facts = facts_of("G-1")
    sections = dict(reference_sections(facts, "30符4翻と、三色の条件は？"))
    assert list(sections)[0].startswith("質問に出てきた点数")
    pages = sections["役の説明（このアプリの役図鑑より）"]
    assert pages[0].startswith("三色同順（サンショクドウジュン）・2 翻（鳴くと 1 翻）：")
    heads = [line for line in pages if "（" in line.split("：")[0] and "・" in line.split("：")[0]]
    assert len(heads) <= MAX_PAGES
    assert len(sections["用語の意味（このアプリの用語辞典より）"]) <= MAX_TERMS
    text = reference_text(facts, "30符4翻")
    assert text.startswith("【参考：質問に出てきた点数")

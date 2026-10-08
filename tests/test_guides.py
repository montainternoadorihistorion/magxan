"""「卓で打つとき」（data/table.yaml）と「ルールの違い」（data/rules.yaml）のデータのテスト"""
from __future__ import annotations

import pytest

from engine import content
from engine.content import ContentError
from engine.rules import DEFAULT_RULES, PRACTICE_SWITCHES

GUIDE = content.table_guide()
RULES = content.rule_book()


# ---------------------------------------------------------------- 卓で打つとき


def test_table_guide_covers_one_hand_from_start_to_end():
    keys = [section.key for section in GUIDE.sections]
    assert keys == ["seat", "wall", "deal", "dora", "turn", "call", "riichi", "win", "points", "draw", "foul", "manner"]
    assert GUIDE.intro.endswith("。")
    for section in GUIDE.sections:
        assert section.title and section.summary.endswith("。"), section.key
        assert len(section.steps) >= 3, section.key
        assert section.differ, section.key                      # 卓によって違うところを、必ず書いてある
        for line in (*section.steps, *section.points, *section.differ):
            assert line.endswith("。"), (section.key, line)
    assert len(GUIDE.sources) >= 8 and all(source.url.startswith("https://") for source in GUIDE.sources)


def test_table_guide_mentions_the_calls_and_the_order_of_actions():
    """卒業条件にある発声（ポン・チー・カン・ロン・ツモ・リーチ）が、手順の中に出てくる"""
    text = " ".join(line for section in GUIDE.sections for line in (*section.steps, *section.points))
    for word in ("「チー」「ポン」「カン」", "「リーチ」", "「ロン」または「ツモ」", "1000 点棒", "ドラ表示牌", "6 枚"):
        assert word in text, word


# ---------------------------------------------------------------- ルールの違い


def test_rule_book_structure():
    assert list(RULES.groups) == ["score", "win", "game", "table"]
    assert list(RULES.names.values()) == ["雀魂", "天鳳", "Mリーグ", "連盟", "最高位戦", "協会"]
    assert RULES.surveyed == "2026-10-08" and RULES.intro.endswith("。")
    assert len(RULES.items) >= 20 and len(RULES.checklist) >= 15
    for group in RULES.groups:
        assert RULES.of(group), group
    for item in RULES.items:
        assert item.ask.endswith("。") and item.sides, item.key
        assert not item.note or item.note.endswith("。"), item.key
        assert not item.app or item.app.endswith("。"), item.key
        assert all(side.answer and side.who for side in item.sides), item.key
    assert all(line.endswith("。") for line in RULES.caveats) and len(RULES.caveats) >= 2
    assert all(source.url.startswith("https://") for source in RULES.sources)


def test_rule_settings_match_the_app_defaults():
    """ルール設定に関わる項目は、書いてある初期値が実際の初期値と同じ。設定項目は、すべて説明されている"""
    # 練習のための切り替え（鳴きなし）は、流派によるルールの違いではないので、ルールの違いのページには載せない
    defaults = {k: v for k, v in DEFAULT_RULES.to_dict().items() if k not in PRACTICE_SWITCHES}
    described = {}
    for item in RULES.items:
        if item.setting is not None:
            assert item.app, item.key
            assert defaults[item.setting] == item.default and type(defaults[item.setting]) is type(item.default), item.key
            described[item.setting] = item
    assert set(described) == set(defaults)
    # 初期値は雀魂に合わせてあるので、その項目では雀魂が「アプリと同じ側」に入っている
    assert "雀魂" in described["kiriage_mangan"].sides[1].who and "切り上げない" in described["kiriage_mangan"].app
    assert "雀魂" in described["double_wind_pair_fu"].sides[0].who and described["double_wind_pair_fu"].app.startswith("4 符")
    assert "雀魂" in described["double_yakuman"].sides[0].who and "雀魂" in described["kazoe_yakuman"].sides[0].who


def test_every_surveyed_rule_set_appears_in_split_items():
    """6 つのルールで分かれる項目では、6 つすべてが、どちらかの側に出てくる"""
    for key in ("aka", "kiriage", "renfon", "kazoe", "double_yakuman", "pao", "double_ron", "tochuu", "nagashi",
                "kokushi_ankan", "mochiten", "agariyame", "kyotaku_end"):
        item = next(i for i in RULES.items if i.key == key)
        text = " ".join(side.who for side in item.sides)
        for name in RULES.names.values():
            assert name in text, (key, name)


def test_rule_loader_rejects_mistakes(monkeypatch):
    base = {
        "intro": "説明。", "surveyed": "2026-10-08", "names": {"a": "A"}, "groups": {"g": "まとまり"},
        "sources": [{"title": "資料", "url": "https://example.com/"}],
    }
    good = {"key": "k", "group": "g", "title": "題", "ask": "問い。", "sides": [{"answer": "あり", "who": "A"}]}

    def load_with(items, **changes):
        monkeypatch.setattr(content, "_load", lambda name: {**base, "items": items, **changes})
        content.rule_book.cache_clear()
        try:
            return content.rule_book()
        finally:
            content.rule_book.cache_clear()

    assert load_with([good]).items[0].key == "k"
    assert load_with([{**good, "setting": "kuitan", "default": True}]).items[0].setting == "kuitan"
    for bad in (
        {**good, "group": "x"},                              # 無いまとまり
        {**good, "setting": "no_such_rule", "default": True},
        {**good, "setting": "kuitan"},                       # 初期値が書かれていない
        {**good, "sides": []},
        {**good, "sides": [{"answer": "あり"}]},
        {**good, "unknown": 1},
    ):
        with pytest.raises(ContentError):
            load_with([bad])
    with pytest.raises(ContentError):
        load_with([good, good])
    with pytest.raises(ContentError):
        load_with([good], sources=[{"title": "資料", "url": "http://example.com/"}])


def test_table_loader_rejects_mistakes(monkeypatch):
    section = {"key": "a", "title": "題", "summary": "まとめ。", "steps": ["1。", "2。", "3。"]}

    def load_with(sections):
        data = {"intro": "説明。", "sections": sections, "sources": [{"title": "資料", "url": "https://example.com/"}]}
        monkeypatch.setattr(content, "_load", lambda name: data)
        content.table_guide.cache_clear()
        try:
            return content.table_guide()
        finally:
            content.table_guide.cache_clear()

    assert load_with([section]).sections[0].steps == ("1。", "2。", "3。")
    for bad in ([section, section], [{**section, "steps": ["1。", ""]}], [{**section, "extra": 1}], [{"key": "a"}]):
        with pytest.raises(ContentError):
            load_with(bad)

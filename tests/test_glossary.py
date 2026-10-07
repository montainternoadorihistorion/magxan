"""用語辞典のデータ（data/terms.yaml）と、ルビに使う読みの表のテスト"""
from __future__ import annotations

import pytest

from engine import content
from engine.analysis.shanten import shanten_of
from engine.analysis.waits import wait_kinds
from engine.content import ContentError
from engine.terms import READINGS
from engine.tiles import counts34, parse_tiles
from engine.yaku_table import YAKU

GLOSSARY = content.glossary()
TERMS = {term.term: term for term in GLOSSARY.terms}

#: 依頼の中で名指しされていた用語（立直は役図鑑のページがある）
REQUIRED = ("自摸", "栄和", "聴牌", "向聴", "面子", "雀頭", "順子", "刻子", "槓子", "両面", "嵌張", "辺張", "単騎", "双碰",
            "么九牌", "中張牌", "振聴", "河", "王牌", "嶺上牌")

#: Phase 1 までに画面でルビを振っていた用語と読み（辞典に移したあとも、同じ読みで残っていること）
OLD_READINGS = {
    "和了": "ホーラ", "聴牌": "テンパイ", "向聴": "シャンテン", "門前": "メンゼン", "副露": "フーロ", "放銃": "ホウジュウ",
    "流局": "リュウキョク", "罰符": "バップ", "空聴": "カラテン", "東場": "トンバ", "南場": "ナンバ", "西場": "シャーバ",
    "北場": "ペーバ", "東家": "トンチャ", "南家": "ナンチャ", "西家": "シャーチャ", "北家": "ペーチャ", "配牌": "ハイパイ",
    "手牌": "テハイ", "打牌": "ダハイ", "河": "ホー", "巡目": "ジュンメ", "有効牌": "ユウコウハイ", "牌効率": "ハイコウリツ",
    "面子": "メンツ", "雀頭": "ジャントウ", "順子": "シュンツ", "刻子": "コーツ", "槓子": "カンツ", "対子": "トイツ",
    "搭子": "ターツ", "孤立牌": "コリツハイ", "暗刻": "アンコー", "明刻": "ミンコー", "暗槓": "アンカン", "明槓": "ミンカン",
    "大明槓": "ダイミンカン", "加槓": "カカン", "嶺上牌": "リンシャンパイ", "両面": "リャンメン", "嵌張": "カンチャン",
    "辺張": "ペンチャン", "単騎": "タンキ", "双碰": "シャンポン", "萬子": "マンズ", "筒子": "ピンズ", "索子": "ソーズ",
    "数牌": "シューパイ", "字牌": "ジハイ", "風牌": "カゼハイ", "三元牌": "サンゲンパイ", "么九牌": "ヤオチューハイ",
    "中張牌": "チュンチャンパイ", "老頭牌": "ロートーパイ", "役牌": "ヤクハイ", "場風": "バカゼ", "自風": "ジカゼ",
    "連風牌": "レンフォンパイ", "客風": "オタカゼ", "翻": "ハン", "符": "フ", "副底": "フーテイ", "本場": "ホンバ",
    "供託": "キョウタク", "満貫": "マンガン", "跳満": "ハネマン", "倍満": "バイマン", "三倍満": "サンバイマン",
    "役満": "ヤクマン", "数え役満": "カゾエヤクマン", "高点法": "コウテンホウ", "喰い下がり": "クイサガリ", "喰いタン": "クイタン",
}


def _is_katakana(text: str, extra: str = "") -> bool:
    return bool(text) and all("ァ" <= ch <= "ヿ" or ch in extra for ch in text)


def test_glossary_loads_with_every_category_used():
    assert len(GLOSSARY.terms) >= 120
    assert list(GLOSSARY.categories) == ["agari", "mentsu", "machi", "hai", "naki", "ba", "ten", "mamori", "sahou"]
    for key in GLOSSARY.categories:
        assert len(GLOSSARY.of(key)) >= 5, key
    assert GLOSSARY.find("聴牌").reading == "テンパイ" and GLOSSARY.find("無い言葉") is None


def test_every_term_has_reading_and_meaning():
    for term in GLOSSARY.terms:
        assert _is_katakana(term.reading, "・ "), (term.term, term.reading)       # 読みはカタカナ（区切りの・と空白はよい）
        assert term.meaning.endswith("。"), term.term
        assert not term.alt or term.alt.endswith("。"), term.term
        assert not term.kanji or term.kanji.endswith("。"), term.term
        assert not term.example_note or (term.example and term.example_note.endswith("。")), term.term
        if term.origin is not None:
            assert term.origin.text.endswith("。") and term.origin.certainty in content.CERTAINTIES, term.term
        assert term.term not in term.see


def test_requested_terms_have_reading_meaning_and_origin():
    for name in REQUIRED:
        term = TERMS[name]
        assert term.reading and term.meaning and term.origin is not None, name
    assert "立直" in {page.name for page in content.yaku_pages()}


def test_unclear_origins_are_labelled():
    """由来がはっきりしないものは、断定せずにそう書いてある"""
    assert TERMS["向聴"].origin.certainty == "不明"
    for name in ("三元牌", "ドラ", "王牌", "カン", "ポン", "跳満", "裏ドラ", "河"):
        assert TERMS[name].origin.certainty == "諸説あり", name


def test_examples_are_real_tiles():
    for term in GLOSSARY.terms:
        if not term.example:
            continue
        tiles = parse_tiles(term.example)
        assert 1 <= len(tiles) <= 14 and max(counts34(tiles)) <= 4, term.term


def test_examples_say_what_the_engine_says():
    """例の説明に書いた「待ち」や「向聴数」が、計算と合っている"""
    def waits(name: str) -> set[int]:
        return set(wait_kinds(parse_tiles(TERMS[name].example)))

    def kinds(text: str) -> set[int]:
        return {t // 4 for t in parse_tiles(text)}

    assert waits("聴牌") == waits("振聴") == waits("高目") == kinds("14s")
    assert waits("片あがり") == waits("延べ単騎") == kinds("14m")
    assert waits("単騎") == kinds("5z") and waits("双碰") == kinds("2s5z") and waits("多面張") == kinds("147m")
    one_away = counts34(parse_tiles(TERMS["一向聴"].example))
    assert shanten_of(one_away) == 1
    assert shanten_of(counts34(parse_tiles(TERMS["4 面子 1 雀頭"].example))) == -1
    assert shanten_of(counts34(parse_tiles(TERMS["高点法"].example))) == -1


def test_readings_table_keeps_everything_it_had():
    for term, reading in OLD_READINGS.items():
        assert READINGS[term] == reading, term
    assert READINGS["自摸"] == "ツモ" and READINGS["栄和"] == "ロンホー" and READINGS["振聴"] == "フリテン"
    assert READINGS["王牌"] == "ワンパイ" and READINGS["一向聴"] == "イーシャンテン"


def test_ruby_terms_are_plain_katakana():
    for term in GLOSSARY.terms:
        if term.ruby:
            assert _is_katakana(term.reading), (term.term, term.reading)
            assert READINGS[term.term] == term.reading
    for info in YAKU.values():
        if " " not in info.name:
            assert READINGS[info.name] == info.reading.replace(" ", "")


def test_hard_to_read_terms_get_ruby_wherever_they_appear():
    """読みが難しい用語（読みのドリルで問う語）は、アプリの文章に出てきたとき、初出に読みを付ける。

    辞典の見出しでは読みを横に並べるが、ほかのページ（卓での手順・ルールの違い・役図鑑）の文章にも、同じ語が出てくる。
    """
    from engine import drills

    asked = {word for key, (word, _, _, _) in drills._reading_items().items() if key.startswith("t:")}
    for term in GLOSSARY.terms:
        if term.term in asked:
            assert term.ruby and READINGS[term.term] == term.reading, term.term
    for must in ("起家", "連荘", "上家", "下家", "対面", "半荘", "洗牌", "理牌", "多牌", "少牌", "不聴", "槓ドラ", "喰い替え"):
        assert must in READINGS, must
    # ふだんの言葉と同じ読みの語には、振らない（文章がルビだらけにならないように）
    for plain in ("親", "子", "山", "局", "待ち", "鳴き", "高目", "点棒", "発声"):
        assert plain not in READINGS, plain


def test_glossary_loader_rejects_mistakes(monkeypatch):
    def load_with(data):
        monkeypatch.setattr(content, "_load", lambda name: data)
        content.glossary.cache_clear()
        try:
            return content.glossary()
        finally:
            content.glossary.cache_clear()

    good = {"term": "山", "reading": "ヤマ", "category": "a", "meaning": "積んだ牌。"}
    assert load_with({"categories": {"a": "分類"}, "terms": [good]}).terms[0].term == "山"
    for bad in (
        {**good, "category": "b"},                                   # 無い分類
        {**good, "unknown": 1},                                      # 知らない項目
        {**good, "see": ["無い言葉"]},                               # 辞典に無い関連語
        {**good, "origin": {"text": "由来。", "certainty": "たぶん"}},
        {"term": "山", "reading": "ヤマ", "category": "a"},          # 意味が無い
    ):
        with pytest.raises(ContentError):
            load_with({"categories": {"a": "分類"}, "terms": [bad]})
    with pytest.raises(ContentError):
        load_with({"categories": {"a": "分類"}, "terms": [good, good]})     # 同じ見出し語が 2 つ

"""用語の読みと、ルビを振る部品のテスト"""
from __future__ import annotations

from engine.terms import READINGS
from engine.yaku_table import YAKU
from ui.ruby import Rubifier


def test_readings_are_katakana_and_cover_yaku_names():
    for term, reading in READINGS.items():
        assert term and reading
        assert all("ァ" <= ch <= "ヿ" for ch in reading), (term, reading)     # 読みはカタカナ
    for info in YAKU.values():
        if " " not in info.name:
            assert READINGS[info.name] == info.reading.replace(" ", "")
    assert READINGS["副底"] == "フーテイ" and READINGS["門前"] == "メンゼン" and READINGS["嵌張"] == "カンチャン"


def test_ruby_only_on_first_occurrence():
    rb = Rubifier()
    first = rb.html("副底 20 符に、門前ロンの 10 符を足す")
    assert first == (
        "<ruby>副底<rt>フーテイ</rt></ruby> 20 <ruby>符<rt>フ</rt></ruby>に、"
        "<ruby>門前<rt>メンゼン</rt></ruby>ロンの 10 符を足す"
    )
    assert rb.html("副底と門前") == "副底と門前"            # 2 回目からは振らない
    assert rb.seen == {"副底", "符", "門前"}


def test_longest_term_wins():
    rb = Rubifier()
    html = rb.html("三暗刻と暗刻、門前清自摸和と門前、数え役満と役満、三倍満と倍満")
    for term, reading in [
        ("三暗刻", "サンアンコー"), ("暗刻", "アンコー"), ("門前清自摸和", "メンゼンチンツモホー"), ("門前", "メンゼン"),
        ("数え役満", "カゾエヤクマン"), ("役満", "ヤクマン"), ("三倍満", "サンバイマン"), ("倍満", "バイマン"),
    ]:
        assert html.count(f"<ruby>{term}<rt>{reading}</rt></ruby>") == 1


def test_text_is_escaped():
    rb = Rubifier()
    assert rb.html('<b>&"和了') == "&lt;b&gt;&amp;&quot;<ruby>和了<rt>ホーラ</rt></ruby>"


def test_disabled_rubifier_only_escapes():
    rb = Rubifier(enabled=False)
    assert rb.html("副底 <20> 符") == "副底 &lt;20&gt; 符"
    assert rb.seen == set()


def test_custom_readings():
    rb = Rubifier({"山": "ヤマ", "山越し": "ヤマゴシ"})
    assert rb.html("山越しと山") == "<ruby>山越し<rt>ヤマゴシ</rt></ruby>と<ruby>山<rt>ヤマ</rt></ruby>"

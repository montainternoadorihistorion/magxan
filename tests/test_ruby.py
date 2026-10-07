"""用語の読みと、ルビを振る部品のテスト"""
from __future__ import annotations

from engine.terms import READINGS
from engine.yaku_table import YAKU
from ui.ruby import Rubifier, missing_ruby


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


def test_wrap_puts_the_ruby_outside_the_decoration():
    rb = Rubifier()
    assert rb.wrap("満貫", "<b>", "</b>") == "<ruby><b>満貫</b><rt>マンガン</rt></ruby>"
    assert rb.wrap("満貫", "<b>", "</b>") == "<b>満貫</b>"                 # 2 回目は、飾りだけ
    assert rb.wrap("役満 2 つぶん", "<b>", "</b>") == "<b><ruby>役満<rt>ヤクマン</rt></ruby> 2 つぶん</b>"   # 用語 1 つでなければ、中に振る
    assert rb.wrap("<点>", "<b>", "</b>") == "<b>&lt;点&gt;</b>"
    assert Rubifier(enabled=False).wrap("満貫", "<b>", "</b>") == "<b>満貫</b>"


def test_fork_inherits_what_was_seen_but_does_not_report_back():
    """折りたたみの中身は fork() に通す。中で振ったルビは、外やほかの折りたたみでは「まだ出てきていない」扱い"""
    rb = Rubifier()
    rb.html("配牌")
    inner = rb.fork()
    assert inner.html("配牌と有効牌") == "配牌と<ruby>有効牌<rt>ユウコウハイ</rt></ruby>"
    assert inner.html("有効牌") == "有効牌"
    assert rb.fork().html("有効牌") == "<ruby>有効牌<rt>ユウコウハイ</rt></ruby>"       # ほかの折りたたみでは、もう一度振る
    assert rb.html("有効牌") == "<ruby>有効牌<rt>ユウコウハイ</rt></ruby>" and rb.seen == {"配牌", "有効牌"}
    assert Rubifier(enabled=False).fork().html("配牌") == "配牌"


def test_missing_ruby_finds_first_appearances_without_ruby():
    assert missing_ruby([("聴牌", True), ("にとれる。聴牌した。", False)]) == []
    assert missing_ruby([("聴牌にとれる。", False), ("聴牌", True)]) == ["聴牌"]            # 最初に出てきたところに、ルビが無い
    assert missing_ruby([("三暗刻と暗刻", False)]) == ["三暗刻", "暗刻"]                    # 長い用語を先に見る
    # 折りたたみ（範囲 1・2）の中で振ったルビは、その折りたたみの中でだけ数える
    parts = [("配牌", True), ("有効牌", True, 1), ("有効牌と配牌", False, 1), ("有効牌", False, 2), ("有効牌", False)]
    assert missing_ruby(parts) == ["有効牌", "有効牌"]
    assert missing_ruby([("山", False)], {"山": "ヤマ"}) == ["山"]

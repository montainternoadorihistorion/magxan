"""AI の文と事実の照らし合わせ（narration/check.py）のテスト"""
from __future__ import annotations

import pytest

from narration.check import MASK, allowed_from, claims, describe, kanji_number, mask, supported, violations, yaku_names


def values(text: str, kind: str | None = None) -> list[str]:
    return [c.value for c in claims(text) if kind is None or c.kind == kind]


@pytest.mark.parametrize(("text", "number"), [
    ("三千九百", 3900), ("二十", 20), ("十", 10), ("百", 100), ("一万二千", 12000), ("八千", 8000), ("三", 3),
    ("二〇", None), ("三三", None),
])
def test_kanji_numbers(text, number):
    assert kanji_number(text) == number


def test_numbers_with_units_are_read_the_same_way_however_written():
    assert values("3,900 点", "number") == ["3900点"]
    assert values("３９００点", "number") == ["3900点"]            # 全角
    assert values("1万2000点", "number") == ["12000点"]
    assert values("三千九百点", "number") == ["3900点"]
    assert values("30符 3翻", "number") == ["30符", "3翻"]
    assert values("1 シャンテン・2 種類・5 巡目・30 フ・2 ハン", "number") == ["1向聴", "2種", "5巡", "30符", "2翻"]
    assert values("42%・42％", "number") == ["42%", "42%"]
    assert values("2.5 枚", "number") == ["2.5枚"]


def test_tiles_in_many_spellings():
    assert values("5萬と赤5筒、7索", "tile") == ["5萬", "5筒", "7索"]
    assert values("234萬", "tile") == ["2萬", "3萬", "4萬"]                # まとめた書き方は 1 枚ずつ
    assert values("五萬・三索", "tile") == ["5萬", "3索"]
    assert values("5m 3p 7s", "tile") == ["5萬", "3筒", "7索"]
    assert values("5マン", "tile") == ["5萬"]
    assert values("1万点", "tile") == [] and values("1万点", "number") == ["10000点"]     # 数の「万」は牌ではない
    assert values("東と白", "tile") == []                                  # 字牌は見ない


def test_yaku_names_except_plain_words():
    assert values("断么九とタンヤオと三色と一通", "yaku") == ["tanyao", "tanyao", "sanshoku", "ittsu"]
    assert values("リーチして、ツモって、役牌を鳴く", "yaku") == []          # 打ち方のことばと区別できない役は見ない
    assert values("ダブル立直", "yaku") == ["double_riichi"]
    every = dict(yaku_names(every=True))
    assert every["リーチ"] == "riichi" and every["役牌"] == "yakuhai_haku"


def test_bare_numbers():
    assert values("12 回と 3 つ", "bare") == ["12", "3"]
    assert values("2⁵ ＝ 32", "bare") == ["2", "32"]                       # 肩の数字は数えない


def test_question_numbers_are_not_allowed_but_tiles_and_yaku_are():
    allowed = allowed_from(["立直 1 翻。30 符。待ちは 5索。"], extra_texts=["5200 点ですか？ 8萬は？ 平和は？"])
    assert "5200点" not in allowed.numbers
    assert {"5索", "8萬"} <= allowed.tiles and "pinfu" in allowed.yaku


def test_violations_find_numbers_tiles_and_yaku_not_in_the_facts():
    allowed = allowed_from(["30 符 3 翻・子のロン：30 × 2⁵ ＝ 30 × 32 ＝ 960 → × 4 ＝ 3,840 → 切り上げて 3,900 点。待ち 5索・8索。断么九 1 翻"])
    assert violations("3900 点。5索 か 8索 を待つ断么九。", allowed) == []
    bad = violations("5200 点。3萬 を待つ平和。", allowed)
    assert [c.text for c in bad] == ["5200 点", "3萬", "平和"]
    assert violations("2 つの面子と 4 枚", allowed) == [c for c in claims("2 つの面子と 4 枚") if c.kind == "number"]    # 単位つきは厳しく
    assert violations("2 つの面子", allowed) == []                         # 小さい数（10 まで）は、単位が無ければ許す
    assert [c.text for c in violations("15 回", allowed)] == ["15"]


def test_points_in_the_middle_of_formulas_are_allowed():
    formula = "基本点 ＝ 30 × 32 ＝ 960 → × 4 ＝ 3,840 → 切り上げて 3,900 点。残り 3 枚"
    allowed = allowed_from([formula], point_texts=[formula])
    assert violations("基本点は 960 点で、3840 点を切り上げる", allowed) == []
    assert [c.text for c in violations("30 点", allowed)] == ["30 点"]      # 100 より小さい数は「点」にしない（符と取り違えやすい）
    claim = claims("960 符")[0]
    assert not supported(claim, allowed)
    # 一般的な決まり（その局面の計算ではない文）に単位なしで出てくる数は、「点」として認めない
    general = allowed_from([formula, "2,000 を超えたら満貫（基本点 2,000）。136 枚"], point_texts=[formula])
    assert [c.text for c in violations("2000 点です。136 点です。", general)] == ["2000 点", "136 点"]


def g1_allowed():
    """点数計算ラボの例題 G-1（立直・平和・断么九。30 符 3 翻・子のロン 3,900 点）の事実"""
    from engine.scoring.examples import EXAMPLES_BY_KEY
    from engine.scoring.explain import explain
    from narration.facts import win_facts

    example = EXAMPLES_BY_KEY["G-1"]
    facts = win_facts(explain(example.context(), example.rules), who="自分")
    return allowed_from([facts.text], point_texts=[facts.point_text])


@pytest.mark.parametrize("text", [
    "この手は子のロンで 4000 点です。", "2000 点", "3000 点", "6,000 点", "136 点",       # 一般的な決まりの数（単位なし）
    "向聴数は2です", "シャンテン数は 3 です", "翻数は4です", "4飜", "2 飜",              # 単位のことばが先・飜
    "ドラ3なので", "ドラが 2 枚", "赤ドラ 2",                                          # ドラの数
    "1ソウ", "9M", "キューピン", "イーソー",                                           # 牌のいろいろな書き方（どれも事実に無い牌）
    "跳満になります", "満貫です", "倍満の手",                                           # この手の点数の段階
    "純チャン", "イーペーコー",                                                       # 役の略し方
    "2万5千点",
])
def test_g1_rejects_wrong_claims(text):
    assert violations(text, g1_allowed()), text


@pytest.mark.parametrize("text", [
    "子のロンで 3,900 点。基本点は 960 点で、× 4 の 3,840 点を切り上げる。",
    "30 符 3 翻。翻数は 3、符は 30 符。", "向聴数が 1 つ進む", "ドラはない",
    "跳満は 6 翻から、倍満は 8 翻から。11 翻で三倍満。",                               # 事実の「6〜7 翻」のような範囲
    "2 フーロ", "一巡のあいだ", "1万を超える点", "満貫は 8,000 点",
    "5索 と 8索 を待つ両面待ち", "リーチ・ピンフ・タンヤオで 3900",
])
def test_g1_accepts_right_claims(text):
    assert violations(text, g1_allowed()) == [], [c.text for c in violations(text, g1_allowed())]


def test_new_spellings_are_read():
    assert values("5ソウ・6M・ウーピン・リャンソー・7ｐ", "tile") == ["5索", "6萬", "5筒", "2索", "7筒"]
    assert values("向聴数は2、翻数が 4、符数：30", "number") == ["2向聴", "4翻", "30符"]
    assert values("2 フーロ・ハンデ", "number") == []                      # カタカナが続くときは、単位ではない
    assert values("一巡のあいだ・一巡目", "number") == ["1巡"]
    assert values("2万5千点・1万2000点・3万点", "number") == ["25000点", "12000点", "30000点"]
    assert [(c.kind, c.value) for c in claims("ドラ 3・赤ドラが 1 枚・裏ドラ 2 つ・ドラ表示牌 3筒・ドラは 5筒")] == [
        ("dora", "ドラ3"), ("dora", "赤ドラ1"), ("dora", "裏ドラ2"), ("tile", "3筒"), ("tile", "5筒"),
    ]
    assert [(c.kind, c.value) for c in claims("跳満になります。満貫で打ち止め。流し満貫です")] == [("level", "跳満"), ("yaku", "nagashi")]


def test_levels_come_from_the_hand_and_ranges_are_opened():
    hand = "合計 5 翻（満貫）"
    allowed = allowed_from([hand, "6〜7 翻は跳満"], point_texts=[hand])
    assert violations("満貫です", allowed) == [] and [c.value for c in violations("跳満です", allowed)] == ["跳満"]
    assert {"6翻", "7翻"} <= allowed.numbers


def test_describe_and_mask():
    text = "5200 点で、3萬 待ち。"
    bad = claims(text)
    assert describe(bad) == "「5200 点」・「3萬」"
    assert mask(text, bad) == f"{MASK}で、{MASK} 待ち。"
    overlapping = claims("234萬")                                          # 3 つの主張が同じ場所 → 1 つの〔?〕
    assert mask("234萬", overlapping) == MASK

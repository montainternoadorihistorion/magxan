"""点数計算ラボのページを、画面なしで動かして確かめる"""
from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine.scoring.examples import EXAMPLES
from engine.scoring.random_hand import KINDS

ROOT = Path(__file__).resolve().parent.parent
ALL_STEPS = ["① 手牌の読み方", "② 役", "③ ドラ", "④ 符", "⑤ 点数", "⑥ 誰がいくら払うか", "⑦ 卓での申告"]
RULES_STEP = "ルールによって変わるところ"


def open_lab(**query: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    for name, value in query.items():
        at.query_params[name] = value
    at.run()
    at.switch_page("views/score_lab.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at: AppTest) -> str:
    """st.html で出した内容を、読める文字だけにしてつなげる"""
    html = "".join(element.proto.body for element in at.get("html"))
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", html))


def param(at: AppTest, name: str) -> str:
    """URL の ?name=… の値（テストの道具は、版によって文字列かリストで返す）"""
    value = at.query_params[name]
    return value[0] if isinstance(value, list) else value


def steps(at: AppTest) -> list[str]:
    """解説の見出し（「ルールによって変わるところ」は、出る手と出ない手があるので除く）"""
    return [s.value for s in at.subheader if s.value != RULES_STEP]


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_opens_with_first_example_and_all_steps():
    at = open_lab()
    assert at.title[0].value == "点数計算ラボ"
    assert at.selectbox(key="lab_example").value == "A-1"
    assert steps(at) == ALL_STEPS
    text = page_text(at)
    assert "A-1 リーチのみ（嵌張待ち）" in text and "1,300 点" in text and "「ロン。リーチ。1300。」" in text
    assert param(at, "ex") == "A-1"


def test_example_from_url():
    at = open_lab(ex="F-1")
    assert at.selectbox(key="lab_example").value == "F-1"
    assert "12,000 点" in page_text(at) and "この 14 枚の読み方は 2 通り" in page_text(at)
    assert open_lab(ex="存在しない").selectbox(key="lab_example").value == "A-1"


def test_every_example_opens_without_error():
    at = open_lab()
    for example in EXAMPLES:
        if at.selectbox(key="lab_group").value != example.key[0]:
            at.selectbox(key="lab_group").set_value(example.key[0]).run()      # 章を変えると、その章の最初の例題になる
            assert at.selectbox(key="lab_example").value == example.key
        else:
            at.selectbox(key="lab_example").set_value(example.key).run()
        assert not at.exception, (example.key, [e.value for e in at.exception])
        assert len(at.selectbox(key="lab_example").options) <= 10 and len(at.selectbox(key="lab_group").options) <= 10
        text = page_text(at)
        assert f"{example.key} {example.title}" in text
        if example.han is None:
            assert "あがれない（役なし）" in text and steps(at) == ALL_STEPS[:2] + (["③ ドラ"] if "ドラ表示牌" in text else [])
        else:
            assert steps(at) == ALL_STEPS and f"「{'ツモ' if example.spec.get('is_tsumo') else 'ロン'}。" in text


def test_next_and_previous_example():
    at = open_lab()
    click(at, "次の例題 ▶")
    assert at.selectbox(key="lab_example").value == "A-2" and "A-2 平和のロン" in page_text(at)
    click(at, "◀ 前の例題")
    click(at, "◀ 前の例題")
    assert at.selectbox(key="lab_example").value == EXAMPLES[-1].key      # 先頭から戻ると末尾へ
    assert at.selectbox(key="lab_group").value == EXAMPLES[-1].key[0]     # 章の表示も付いてくる
    click(at, "次の例題 ▶")
    assert (at.selectbox(key="lab_group").value, at.selectbox(key="lab_example").value) == ("A", "A-1")


def test_changing_the_situation_recalculates_and_can_be_undone():
    at = open_lab(ex="A-2")                       # リーチ・平和のロン 2000
    assert "2,000 点" in page_text(at)
    at.button_group(key="lab_how").set_value("ツモ").run()
    assert not at.exception
    text = page_text(at)
    assert "700・1,300 点" in text                # リーチ・ツモ・平和 ＝ 3 翻 20 符
    assert "A-2 平和のロン" not in text           # 例題の説明は、条件を変えたら出さない
    assert any("条件を変えています" in c.value for c in at.caption)

    at.button_group(key="lab_seat").set_value("東（親）").run()
    assert "1,300 点オール" in page_text(at)

    click(at, "例題の条件に戻す")
    assert "2,000 点" in page_text(at) and "A-2 平和のロン" in page_text(at)
    assert at.button_group(key="lab_how").value == "ロン"


def test_rule_switches_change_the_result():
    at = open_lab(ex="G-2")                       # 4 翻 30 符 ＝ 7700
    assert "7,700 点" in page_text(at)
    at.toggle(key="lab_rule_kiriage").set_value(True).run()
    assert "8,000 点" in page_text(at) and "切り上げ満貫" in page_text(at)

    at = open_lab(ex="G-3")                       # 例題そのものが切り上げ満貫のルール
    assert at.toggle(key="lab_rule_kiriage").value is True and "8,000 点" in page_text(at)

    at = open_lab(ex="B-1")                       # 喰いタン
    at.toggle(key="lab_rule_kuitan").set_value(False).run()
    assert "あがれない（役なし）" in page_text(at) and "喰いタンありのルールなら成立" in page_text(at)

    at = open_lab(ex="E-3")                       # 連風牌の雀頭
    assert "2,400 点" in page_text(at)
    at.button_group(key="lab_rule_pair").set_value("2 符").run()
    assert "2,000 点" in page_text(at)


def test_brief_detail_shows_fewer_steps():
    at = open_lab()
    at.selectbox(key="lab_detail").set_value("要点だけ").run()
    assert steps(at) == ["① 手牌の読み方", "② 役", "⑤ 点数", "⑦ 卓での申告"]
    at.selectbox(key="lab_detail").set_value("ふつう").run()
    assert steps(at) == ALL_STEPS


def test_quiz_mode_hides_the_answer_until_revealed():
    at = open_lab(ex="G-1")
    at.toggle(key="lab_quiz").set_value(True).run()
    assert not at.exception
    assert steps(at) == [] and "この手は何点？" in page_text(at) and "3,900" not in page_text(at)
    click(at, "答えと解説を見る")
    assert steps(at) == ALL_STEPS and "3,900 点" in page_text(at)
    # 次の例題に進むと、また隠れる
    click(at, "次の例題 ▶")
    assert steps(at) == [] and "この手は何点？" in page_text(at)


def test_random_mode():
    at = open_lab()
    at.button_group(key="lab_mode").set_value("ランダムに出す").run()
    assert not at.exception
    first_seed = at.session_state["lab_seed"]
    assert steps(at) == ALL_STEPS and param(at, "n") == str(first_seed)
    click(at, "次の手を出す")
    assert steps(at) == ALL_STEPS
    for kind in KINDS:
        at.selectbox(key="lab_kind").set_value(kind).run()
        assert not at.exception, kind
        assert steps(at) == ALL_STEPS and param(at, "kind") == kind


def test_random_hand_from_url_is_reproducible():
    first = open_lab(kind="fu", n="12345")
    second = open_lab(kind="fu", n="12345")
    assert first.session_state["lab_mode"] == "ランダムに出す" and first.session_state["lab_seed"] == 12345
    assert first.text_input(key="lab_hand").value == second.text_input(key="lab_hand").value
    assert page_text(first) == page_text(second)


def test_custom_input_reports_mistakes_in_plain_words():
    at = open_lab()
    at.button_group(key="lab_mode").set_value("自分で入力").run()
    assert not at.exception and steps(at) == ALL_STEPS            # 直前の手がそのまま入っている

    at.text_input(key="lab_hand").set_value("123m456p789s23s").run()
    assert "13 枚のはずですが、11 枚あります" in at.error[0].value and steps(at) == []

    at.text_input(key="lab_hand").set_value("123m456p789s23s44x").run()
    assert "読めない文字" in at.error[0].value

    at.text_input(key="lab_hand").set_value("123m456p789s23s44z").run()
    at.text_input(key="lab_win").set_value("4s").run()
    assert not at.error and steps(at) == ALL_STEPS

    at.text_input(key="lab_melds").set_value("ポン 555z").run()
    assert "10 枚のはずですが、13 枚あります（副露が 1 組なので 13 − 3 × 1 ＝ 10 枚）" in at.error[0].value
    at.text_input(key="lab_melds").set_value("").run()

    at.button_group(key="lab_flags").set_value(["一発"]).run()      # リーチなしの一発
    assert "一発は立直しているときだけ" in at.error[0].value
    at.button_group(key="lab_flags").set_value(["リーチ", "一発"]).run()
    assert not at.error and "イッパツ" in page_text(at)

    # 入力に誤りがあるあいだも、ほかの入力欄の値は消えない
    at.text_input(key="lab_win").set_value("").run()
    assert at.error and at.selectbox(key="lab_detail").value == "くわしく" and at.toggle(key="lab_quiz").value is False


def test_custom_input_accepts_melds_and_dora():
    at = open_lab()
    at.button_group(key="lab_mode").set_value("自分で入力").run()
    at.text_input(key="lab_hand").set_value("234m55p34s").run()
    at.text_input(key="lab_win").set_value("5s").run()
    at.text_input(key="lab_melds").set_value("ポン 888m、チー 678p").run()
    at.text_input(key="lab_dora").set_value("4p").run()
    at.button_group(key="lab_flags").set_value([]).run()
    assert not at.exception and not at.error
    text = page_text(at)
    assert "明刻（ポン）" in text and "5筒 が手牌に 2 枚" in text and "「ロン。タンヤオ・ドラ 2。" in text

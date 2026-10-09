"""「なぜ？」の折りたたみ（ui/why_view.py・ui/ai_access.py）を、画面なしで動かして確かめる。

本物の AI は呼ばない。キーが無いとき（テンプレートの答え）と、偽物の AI を入れたとき（AI の答え・自分で書く質問・
回数の上限）、合言葉で守ったときを見る。対局・一人練習・点数計算ラボのどこにも出ることも確かめる。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from component_helpers import choose, component_data
from html_helpers import page_html, page_parts
from streamlit.testing.v1 import AppTest
from test_game_page import find, first_turn, open_game, saved

from narration.client import AiError, Reply
from ui.ai_access import MAX_FAILURES, REMEMBER_SECONDS, TEST_CLIENT, UNLOCK_NAME, token_valid, unlock_token
from ui.components.browser_store import initial_state
from ui.game_session import GAME_NAME
from ui.ruby import missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"


@dataclass
class FakeAi:
    """決まった答えを順に返す AI（呼ばれた回数を数える）"""

    replies: list
    calls: list = field(default_factory=list)

    def complete(self, settings, system, messages) -> Reply:
        self.calls.append((settings.model, [m.text for m in messages]))
        reply = self.replies.pop(0) if self.replies else "よくある質問の説明です。"
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply, settings.model, 900, 120)


def open_practice(client: FakeAi | None = None, *, secrets: dict | None = None, known: dict | None = None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    for name, value in (secrets or {}).items():
        at.secrets[name] = value
    at.run()
    at.session_state[STORE_STATE] = initial_state(known or {})
    if client is not None:
        at.session_state[TEST_CLIENT] = client
    at.switch_page("views/practice.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at: AppTest) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", page_html(at)))


def why_labels(at: AppTest) -> list[str]:
    return [e.label for e in at.expander if e.label.startswith("なぜ？")]


def submit(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------- キーが無いとき


def test_without_a_key_suggestions_answer_from_the_engine():
    at = open_practice()
    assert why_labels(at) == ["なぜ？（この局面について質問する）"]
    data = component_data(at, "mjdojo_choices", "pr_why_choices")
    keys = [o["key"] for o in data["options"]]
    assert keys[0] == "why" and "compare" in keys and data["selected"] == []
    body = text(at)
    assert "自分で書いた質問に答えるには、AI のキーが要ります" in body
    choose(at, ["why"], key="pr_why_choices")
    body = text(at)
    assert "アプリの計算より" in body and "おすすめは、速さだけで決めている。速さは、まず切ったあとの向聴数で比べる" in body
    assert component_data(at, "mjdojo_choices", "pr_why_choices")["selected"] == ["why"]
    assert missing_ruby(page_parts(at)) == []


def test_choice_is_forgotten_when_the_position_changes():
    at = open_practice()
    choose(at, ["why"], key="pr_why_choices")
    hand = component_data(at, "mjdojo_tile_hand")
    from component_helpers import pick_tile
    pick_tile(at, hand["tiles"][0]["id"])
    assert component_data(at, "mjdojo_choices", "pr_why_choices")["selected"] == []
    assert "アプリの計算より" not in text(at)


# ---------------------------------------------------------------- 偽物の AI


def test_ai_rephrases_and_answers_free_questions():
    ai = FakeAi(["いちばん受け入れが広い牌を切ると、手が早く進みます。", "切る牌ごとに、手の進み方を比べました。", "白は、どの面子にも使いにくい牌です。"])
    at = open_practice(ai)
    body = text(at)
    assert "AI が言い直します" in body and "AI は、この接続であと 30 回使えます" in body
    choose(at, ["why"], key="pr_why_choices")
    body = text(at)
    assert "AI の説明（数・牌・役は、アプリの計算と照らし合わせ済み）" in body and "手が早く進みます" in body
    assert len(ai.calls) == 1 and ai.calls[0][0] == "claude-haiku-5-5"
    # 同じ質問を選び直しても、AI は呼ばない（前の答えを使う）
    choose(at, ["compare"], key="pr_why_choices")
    choose(at, ["why"], key="pr_why_choices")
    assert len(ai.calls) == 2
    # 自分で書く質問
    at.text_input(key="pr_why_text").input("白を切る理由は？")
    submit(at, "AI に聞く")
    body = text(at)
    assert "質問：白を切る理由は？" in body and "白は、どの面子にも使いにくい牌です。" in body
    assert ai.calls[-1][0] == "claude-sonnet-5-5" and "AI は、この接続であと 27 回使えます" in body
    assert missing_ruby(page_parts(at)) == []


def test_ai_failure_falls_back_to_the_template_and_can_be_retried():
    ai = FakeAi([AiError("network"), "もう一度考えると、受け入れの広さで決まります。"])
    at = open_practice(ai)
    choose(at, ["why"], key="pr_why_choices")
    body = text(at)
    assert "AI につながりませんでした" in body and "アプリの計算より" in body
    at.run()                                                 # 画面を描き直しただけでは、AI を呼び直さない
    assert len(ai.calls) == 1
    submit(at, "もう一度 AI に聞く")
    assert "受け入れの広さで決まります" in text(at) and len(ai.calls) == 2
    assert not any(b.label == "もう一度 AI に聞く" for b in at.button)


def test_made_up_numbers_are_masked_in_free_answers():
    ai = FakeAi(["5200 点になります。", "やはり 5200 点です。"])
    at = open_practice(ai)
    at.text_input(key="pr_why_text").input("あがったら何点？")
    submit(at, "AI に聞く")
    body = text(at)
    assert "やはり 〔?〕です。" in body and "計算と照らし合わせられなかった部分は〔?〕にしました" in body
    assert "5200" not in body                                             # 伏せた数を、注にも書かない


# ---------------------------------------------------------------- 合言葉


def test_passphrase_guards_the_ai():
    at = open_practice(secrets={"ANTHROPIC_API_KEY": "sk-ant-test-not-real", "AI_PASSPHRASE": "ひらけごま"})
    assert "AI を使うのに合言葉が要ります" in text(at)
    assert not any(t.key == "pr_why_text" for t in at.text_input)
    at.text_input(key="pr_why_phrase").input("ちがう")
    submit(at, "AI を使う")
    assert any("合言葉が違います" in e.value for e in at.error)
    at.text_input(key="pr_why_phrase").input("ひらけごま")
    at.checkbox(key="pr_why_remember").check()
    submit(at, "AI を使う")
    assert any(t.key == "pr_why_text" for t in at.text_input)              # 自分で質問を書けるようになった
    assert "合言葉を入れて" not in text(at) and "AI を使うのに合言葉が要ります" not in text(at)
    stored = at.session_state[STORE_STATE]["known"].get(UNLOCK_NAME)
    assert "ひらけごま" not in stored and token_valid(stored, "ひらけごま", KEY, int(time.time()))     # 合言葉そのものは置かない
    # 覚えた合言葉は、ボタンで消せる
    submit(at, "この端末で覚えた合言葉を消す")
    assert at.session_state[STORE_STATE]["known"].get(UNLOCK_NAME) is None and "AI を使うのに合言葉が要ります" in text(at)


KEY = "sk-ant-test-not-real"


def test_remembered_passphrase_opens_the_ai_on_this_device():
    now = int(time.time())
    known = {UNLOCK_NAME: unlock_token("ひらけごま", KEY, now + 3600)}
    at = open_practice(secrets={"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "ひらけごま"}, known=known)
    assert any(t.key == "pr_why_text" for t in at.text_input)
    wrong = open_practice(secrets={"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "べつの合言葉"}, known=known)
    assert not any(t.key == "pr_why_text" for t in wrong.text_input)       # 合言葉を変えたら、覚えた値は使えない
    other_key = open_practice(secrets={"ANTHROPIC_API_KEY": "sk-ant-other", "AI_PASSPHRASE": "ひらけごま"}, known=known)
    assert not any(t.key == "pr_why_text" for t in other_key.text_input)   # キーを変えても使えない


def test_remembered_value_is_checked_without_errors():
    now = 1_800_000_000
    good = unlock_token("ひらけごま", KEY, now + 60)
    assert token_valid(good, "ひらけごま", KEY, now)
    assert not token_valid(good, "ひらけごま", KEY, now + 61)                              # 期限切れ
    assert not token_valid(unlock_token("ひらけごま", KEY, now + REMEMBER_SECONDS + 10), "ひらけごま", KEY, now)   # 期限が長すぎる
    for broken in ("合言葉", "ａｂｃ", "", "123", good.upper(), good + "0", None, 5, ["x"]):
        assert not token_valid(broken, "ひらけごま", KEY, now)                            # 形の違う値でも、例外を出さない
    at = open_practice(secrets={"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "ひらけごま"}, known={UNLOCK_NAME: "合言葉"})
    assert "AI を使うのに合言葉が要ります" in text(at)                                   # 壊れた値でも、ページは落ちない


def test_too_many_wrong_passphrases_lock_the_form():
    at = open_practice(secrets={"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "ひらけごま"})
    for _ in range(MAX_FAILURES):
        at.text_input(key="pr_why_phrase").input("ちがう")
        submit(at, "AI を使う")
    assert "何度も間違えた" in text(at) and not any(t.key == "pr_why_phrase" for t in at.text_input)


# ---------------------------------------------------------------- ほかのページ


def test_game_turn_and_hand_end_have_why_boxes():
    at = open_game({GAME_NAME: saved(first_turn())})
    assert why_labels(at) == ["なぜ？（この局面について質問する）"]
    choose(at, ["why"], key="gm_why_choices")
    assert "アプリの計算より" in text(at)
    assert missing_ruby(page_parts(at)) == []
    end = open_game({GAME_NAME: saved(find("hand_end_win"))})
    assert why_labels(end) == []                                   # 点数を申告するまでは、出さない
    submit(end, "申告しないで結果を見る")
    assert "なぜ？（自分のあがりについて質問する）" in why_labels(end)
    choose(end, ["points"], key="gm_why_win_0_choices")
    assert "あがった人が受け取る点の合計" in text(end)


def test_score_lab_has_a_why_box():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.switch_page("views/score_lab.py").run()
    assert why_labels(at) == ["なぜ？（この手の点数について質問する）"]
    choose(at, ["points"], key="lab_why_choices")
    assert "アプリの計算より" in text(at) and "あがった人が受け取る点の合計" in text(at)
    assert missing_ruby(page_parts(at)) == []


def open_lab(*, secrets: dict, known: dict | None) -> AppTest:
    """点数計算ラボを開く（known が None なら、ブラウザの記録はまだ届いていない）"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    for name, value in secrets.items():
        at.secrets[name] = value
    at.run()
    if known is not None:
        at.session_state[STORE_STATE] = initial_state(known)
    at.switch_page("views/score_lab.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_score_lab_remembers_the_passphrase_like_the_other_pages():
    """点数計算ラボでも、この端末で覚えた合言葉が効き、ラボで入れた合言葉も覚えられる"""
    secrets = {"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "ひらけごま"}
    known = {UNLOCK_NAME: unlock_token("ひらけごま", KEY, int(time.time()) + 3600)}
    remembered = open_lab(secrets=secrets, known=known)
    assert any(t.key == "lab_why_text" for t in remembered.text_input) and "AI を使うのに合言葉が要ります" not in text(remembered)
    fresh = open_lab(secrets=secrets, known={})
    box = next(c for c in fresh.checkbox if c.key == "lab_why_remember")
    assert not box.disabled
    fresh.text_input(key="lab_why_phrase").input("ひらけごま")
    box.check()
    submit(fresh, "AI を使う")
    stored = fresh.session_state[STORE_STATE]["known"].get(UNLOCK_NAME)
    assert token_valid(stored, "ひらけごま", KEY, int(time.time()))


def test_remember_box_explains_when_it_cannot_remember():
    """ブラウザの記録がまだ届いていない（または使えない）ときは、「この端末で覚える」を押せず、理由を添える"""
    at = open_lab(secrets={"ANTHROPIC_API_KEY": KEY, "AI_PASSPHRASE": "ひらけごま"}, known=None)
    box = next(c for c in at.checkbox if c.key == "lab_why_remember")
    assert box.disabled and "覚えられません" in (box.help or "")
    at.text_input(key="lab_why_phrase").input("ひらけごま")
    submit(at, "AI を使う")
    assert any(t.key == "lab_why_text" for t in at.text_input)              # 覚えられなくても、このセッションでは使える


# ---------------------------------------------------------------- 局面が変わったとき・合言葉を入れたあと


def test_choices_reset_when_the_position_changes():
    from component_helpers import pick_tile

    at = open_practice()
    choose(at, ["why"], key="pr_why_choices")
    before = component_data(at, "mjdojo_choices", "pr_why_choices")
    assert before["selected"] == ["why"] and "アプリの計算より" in text(at)
    pick_tile(at, at.session_state["pr_state"].drawn)                       # 1 枚切って、次の局面へ
    assert not at.exception, [e.value for e in at.exception]
    after = component_data(at, "mjdojo_choices", "pr_why_choices")
    assert after["selected"] == [] and after["rev"] != before["rev"]        # 前の局面で選んだ印は消える
    assert "アプリの計算より" not in text(at)


def test_unlocking_after_a_template_answer_asks_the_ai():
    ai = FakeAi(["おすすめの牌は、受け入れが広いから選ばれています。"])
    at = open_practice(ai, secrets={"ANTHROPIC_API_KEY": "sk-ant-test-not-real", "AI_PASSPHRASE": "ひらけごま"})
    choose(at, ["why"], key="pr_why_choices")
    assert "アプリの計算より" in text(at) and not ai.calls                  # 合言葉を入れる前は、アプリの計算
    at.text_input(key="pr_why_phrase").input("ひらけごま")
    submit(at, "AI を使う")
    assert len(ai.calls) == 1 and "受け入れが広いから" in text(at)        # 入れたあとは、同じ質問でも AI に聞く

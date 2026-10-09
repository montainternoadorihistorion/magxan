"""「なぜ？」の答えを作る流れのテスト（narration/service.py）。AI は偽物を使う（本物の API は呼ばない）"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.scoring.examples import EXAMPLES
from engine.scoring.explain import explain
from narration.check import MASK
from narration.client import AiError, Message, Reply
from narration.facts import win_facts
from narration.prompts import SYSTEM
from narration.service import (
    AI,
    ERROR,
    MASKED,
    NOTE_BUDGET,
    NOTE_FALLBACK,
    NOTE_NO_KEY,
    TEMPLATE,
    Budget,
    ask,
    clean_question,
    narrate,
    tidy,
)
from narration.settings import load_settings

SETTINGS = load_settings()


@dataclass
class FakeAi:
    """決まった答えを順に返す AI（例外を入れると、その回は失敗する）"""

    replies: list
    seen: list = field(default_factory=list)

    def complete(self, settings, system: str, messages) -> Reply:
        self.seen.append((settings.model, system, list(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply, settings.model, 1000, 200)


def facts():
    found = next(e for e in EXAMPLES if e.key == "G-1")
    return win_facts(explain(found.context(), found.rules), who="自分")


def points():
    s = facts().suggestion("points")
    assert s is not None
    return s


def test_without_a_key_the_template_answers():
    answer = narrate(facts(), points(), None, SETTINGS, Budget(30))
    assert answer.source == TEMPLATE and answer.text == points().text and answer.calls == 0


def test_ai_answer_that_matches_the_facts_is_used():
    ai = FakeAi(["**3900 点**です。30 符 3 翻で、基本点 960 を 4 倍して切り上げます。"])
    budget = Budget(30)
    answer = narrate(facts(), points(), ai, SETTINGS, budget)
    assert answer.source == AI and answer.by_ai and answer.text.startswith("3900 点です。")      # 太字の記号は取る
    assert (answer.calls, answer.model, answer.input_tokens, budget.used) == (1, "claude-haiku-5-5", 1000, 1)
    model, system, messages = ai.seen[0]
    assert model == SETTINGS.narration.model and system == SYSTEM
    prompt = messages[0].text
    assert "【事実】" in prompt and "【生徒の質問】なぜこの点数になるの？" in prompt and points().text in prompt


def test_ai_is_asked_once_to_fix_numbers_not_in_the_facts():
    ai = FakeAi(["子のロンなので 5200 点です。", "子のロンなので 3900 点です。"])
    answer = narrate(facts(), points(), ai, SETTINGS, Budget(30))
    assert answer.source == AI and answer.text == "子のロンなので 3900 点です。" and answer.calls == 2
    messages = ai.seen[1][2]
    assert [m.role for m in messages] == ["user", "assistant", "user"]
    assert "「5200 点」" in messages[2].text


def test_template_is_used_when_the_ai_keeps_making_up_numbers():
    ai = FakeAi(["5200 点です。", "やはり 5200 点です。"])
    answer = narrate(facts(), points(), ai, SETTINGS, Budget(30))
    assert answer.source == TEMPLATE and answer.text == points().text and answer.note == NOTE_FALLBACK and answer.calls == 2


def test_ai_errors_fall_back_to_the_template_with_a_note():
    answer = narrate(facts(), points(), FakeAi([AiError("rate")]), SETTINGS, Budget(30))
    assert answer.source == TEMPLATE and answer.note.startswith("AI を呼ぶ回数か量が、上限に達しました。")


def test_budget_limits_calls():
    budget = Budget(1)
    answer = narrate(facts(), points(), FakeAi(["5200 点", "3900 点"]), SETTINGS, budget)
    assert answer.source == TEMPLATE and answer.note == NOTE_FALLBACK and budget.left == 0       # 書き直しを頼む回数が残っていない
    again = narrate(facts(), points(), FakeAi(["3900 点"]), SETTINGS, budget)
    assert again.source == TEMPLATE and again.note == NOTE_BUDGET.format(limit=1) and again.calls == 0


def test_free_question_uses_the_question_model_and_masks_unverified_parts():
    ai = FakeAi(["5索 待ちで 5200 点です。", "まだ 5200 点です。"])
    answer = ask(facts(), "なぜ 5200 点じゃないの？", ai, SETTINGS, Budget(30))
    assert ai.seen[0][0] == SETTINGS.question.model
    assert answer.source == MASKED and answer.text == f"まだ {MASK}です。" and answer.unverified == ("「5200 点」",)
    assert "〔?〕" in answer.note


def test_free_question_answer_that_matches():
    ai = FakeAi(["平和は、4 つの面子がすべて順子で、待ちが両面待ちだから付きます。"])
    answer = ask(facts(), "  なぜ\n平和が付くの？ ", ai, SETTINGS, Budget(30))
    assert answer.source == AI
    assert ai.seen[0][2][0].text.endswith("なぜ 平和が付くの？")             # 空白・改行はまとめる


def test_free_question_without_a_key_or_with_bad_text():
    assert ask(facts(), "なぜ？", None, SETTINGS, Budget(30)) == ask(facts(), "なぜ？", None, SETTINGS, Budget(30))
    no_key = ask(facts(), "なぜ？", None, SETTINGS, Budget(30))
    assert no_key.source == ERROR and no_key.note == NOTE_NO_KEY
    assert ask(facts(), "   ", FakeAi([]), SETTINGS, Budget(30)).note == "質問を書いてください。"
    long = ask(facts(), "あ" * 201, FakeAi([]), SETTINGS, Budget(30))
    assert long.source == ERROR and "200 文字まで" in long.note
    failed = ask(facts(), "なぜ？", FakeAi([AiError("auth")]), SETTINGS, Budget(30))
    assert failed.source == ERROR and "ANTHROPIC_API_KEY" in failed.note


def test_question_numbers_are_not_trusted():
    """質問に書いた数を、そのまま答えに使っても、裏付けにはならない"""
    ai = FakeAi(["はい、7700 点です。", "はい、7700 点です。"])
    answer = ask(facts(), "これは 7700 点？", ai, SETTINGS, Budget(30))
    assert answer.source == MASKED


def test_question_about_han_and_fu_gets_engine_points():
    ai = FakeAi(["30 符 4 翻の子のロンは 7,700 点です。"])
    answer = ask(facts(), "30符4翻は何点？", ai, SETTINGS, Budget(30))
    assert answer.source == AI                                              # 参考に、エンジンで計算した点数が入る
    assert "質問に出てきた点数" in ai.seen[0][2][0].text


def test_tidy_and_clean_question():
    assert tidy("## 見出し\n- 1 つ目\n* 2 つ目\n**太字**と__下線__\n\n\n\n終わり") == "見出し\n・1 つ目\n・2 つ目\n太字と下線\n\n終わり"
    assert clean_question(" a \n b ", 10) == "a b"


def test_messages_are_plain_values():
    assert Message("user", "x") == Message("user", "x")

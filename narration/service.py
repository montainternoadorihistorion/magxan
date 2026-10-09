"""「なぜ？」への答えを作る。

    よくある質問（Suggestion）  キーが無ければ、エンジンの答え（テンプレート）をそのまま返す。
                                キーがあれば、AI に分かりやすく言い直してもらい、事実と照らし合わせる。
                                事実に無い数などが混じったら 1 回だけ書き直しを頼み、それでもだめならテンプレートに戻す。
    自分で書いた質問            AI に答えてもらい、事実と照らし合わせる（キーが無ければ答えられない）。
                                事実に無い数などが混じったら 1 回だけ書き直しを頼み、それでもだめなら、その部分を〔?〕で伏せる。

AI を呼ぶ回数は Budget で数える（1 回の接続での上限は data/ai.yaml の calls_per_session）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from narration.check import allowed_from, describe, mask, violations
from narration.client import AiClient, AiError, Message, Reply
from narration.facts import Facts, Suggestion
from narration.prompts import SYSTEM, feedback, narration_prompt, question_prompt
from narration.reference import reference_text
from narration.settings import AiSettings, ModelSettings

#: 答えの出どころ
TEMPLATE = "template"       # エンジンの説明（テンプレート）
AI = "ai"                   # AI の説明（事実と照らし合わせ済み）
MASKED = "masked"           # AI の説明。確かめられない部分を〔?〕で伏せた
ERROR = "error"             # 答えを作れなかった

NOTE_FALLBACK = "AI の説明に、計算と照らし合わせられない数などが入っていたので、アプリの計算をそのまま表示しています。"
NOTE_MASKED = "計算と照らし合わせられなかった部分は〔?〕にしました（確かめられない数などを、そのまま見せないため）。"
NOTE_BUDGET = "この接続で AI を呼べる回数（{limit} 回）を使い切りました。ページを開き直すと、また使えます。"
NOTE_NO_KEY = "自由な質問には AI を使います。AI のキーが設定されていないので、上のよくある質問から選んでください。"


@dataclass
class Budget:
    """AI を呼べる残りの回数（1 回の接続＝セッションごと）"""

    limit: int
    used: int = 0

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class Answer:
    text: str
    source: str                                 # TEMPLATE・AI・MASKED・ERROR
    note: str = ""                              # 画面に添えるひとこと（AI を使えなかった理由など）
    model: str = ""                             # 答えた AI のモデル
    calls: int = 0                              # AI を呼んだ回数
    input_tokens: int = 0
    output_tokens: int = 0
    unverified: tuple[str, ...] = field(default=())   # 伏せた主張の書き方

    @property
    def by_ai(self) -> bool:
        return self.source in (AI, MASKED)


def template_answer(suggestion: Suggestion, note: str = "") -> Answer:
    return Answer(suggestion.text, TEMPLATE, note=note)


_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*]\s+", re.MULTILINE)


def tidy(text: str) -> str:
    """AI の文の、Markdown の飾り（太字・見出し・- の箇条書き）を、ふつうの文にする"""
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("・", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _Session:
    """1 つの質問のための、AI とのやり取り（最初の答え → 必要なら書き直し 1 回）"""

    def __init__(self, client: AiClient, settings: ModelSettings, budget: Budget, prompt: str) -> None:
        self.client = client
        self.settings = settings
        self.budget = budget
        self.messages = [Message("user", prompt)]
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = ""

    def ask(self) -> Reply | None:
        """AI に聞く。回数の上限なら None"""
        if not self.budget.take():
            return None
        self.calls += 1
        reply = self.client.complete(self.settings, SYSTEM, self.messages)
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        self.model = reply.model or self.settings.model
        return reply

    def retry(self, previous: Reply, request: str) -> Reply | None:
        self.messages += [Message("assistant", previous.text), Message("user", request)]
        return self.ask()

    def answer(self, text: str, source: str, note: str = "", unverified: tuple[str, ...] = ()) -> Answer:
        return Answer(text, source, note, self.model, self.calls, self.input_tokens, self.output_tokens, unverified)


def _texts(facts: Facts, question: str) -> tuple[str, str]:
    return facts.text, reference_text(facts, question)


def narrate(facts: Facts, suggestion: Suggestion, client: AiClient | None, settings: AiSettings, budget: Budget) -> Answer:
    """よくある質問に答える（キーが無い・AI が使えないときは、テンプレート）"""
    if client is None:
        return template_answer(suggestion)
    if budget.left <= 0:
        return template_answer(suggestion, NOTE_BUDGET.format(limit=budget.limit))
    facts_text, reference = _texts(facts, suggestion.question)
    allowed = allowed_from([facts_text, reference, suggestion.text], point_texts=[facts.point_text])
    session = _Session(client, settings.narration, budget, narration_prompt(facts_text, reference, suggestion.question, suggestion.text))
    try:
        reply = session.ask()
        if reply is None:
            return template_answer(suggestion, NOTE_BUDGET.format(limit=budget.limit))
        text = tidy(reply.text)
        bad = violations(text, allowed)
        if bad:
            again = session.retry(reply, feedback(bad))
            if again is None:
                return session.answer(suggestion.text, TEMPLATE, NOTE_FALLBACK)
            text = tidy(again.text)
            if violations(text, allowed):
                return session.answer(suggestion.text, TEMPLATE, NOTE_FALLBACK)
    except AiError as error:
        return session.answer(suggestion.text, TEMPLATE, f"{error.message}アプリの計算をそのまま表示しています。")
    return session.answer(text, AI)


def clean_question(question: str, limit: int) -> str:
    """自由な質問の文を整える（前後の空白・改行の連続をまとめる）。長すぎるときは ValueError"""
    text = re.sub(r"\s+", " ", question).strip()
    if not text:
        raise ValueError("質問を書いてください。")
    if len(text) > limit:
        raise ValueError(f"質問は {limit} 文字までにしてください（いま {len(text)} 文字）。")
    return text


def ask(facts: Facts, question: str, client: AiClient | None, settings: AiSettings, budget: Budget) -> Answer:
    """自分で書いた質問に答える（AI が要る。キーが無ければ、答えられないことを返す）"""
    try:
        question = clean_question(question, settings.limits.question_chars)
    except ValueError as error:
        return Answer("", ERROR, str(error))
    if client is None:
        return Answer("", ERROR, NOTE_NO_KEY)
    if budget.left <= 0:
        return Answer("", ERROR, NOTE_BUDGET.format(limit=budget.limit))
    facts_text, reference = _texts(facts, question)
    allowed = allowed_from([facts_text, reference], extra_texts=[question], point_texts=[facts.point_text])
    session = _Session(client, settings.question, budget, question_prompt(facts_text, reference, question))
    try:
        reply = session.ask()
        if reply is None:
            return Answer("", ERROR, NOTE_BUDGET.format(limit=budget.limit))
        text = tidy(reply.text)
        bad = violations(text, allowed)
        if bad:
            again = session.retry(reply, feedback(bad))
            if again is not None:
                text = tidy(again.text)
                bad = violations(text, allowed)
        if bad:
            labels = tuple(dict.fromkeys(describe([claim]) for claim in bad))
            return session.answer(mask(text, bad), MASKED, NOTE_MASKED, labels)
    except AiError as error:
        return session.answer("", ERROR, error.message)
    return session.answer(text, AI)

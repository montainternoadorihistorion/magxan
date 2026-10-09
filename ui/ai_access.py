"""AI（Claude API）を使えるかどうか・呼べる残りの回数・答えの控えを、セッションに持つ。

    API キー    Streamlit の Secrets の ANTHROPIC_API_KEY。無ければ AI を使わず、テンプレートの解説だけで動く。
    合言葉      Secrets の AI_PASSPHRASE（任意）。入れておくと、合言葉を入れた人だけが AI を使える
                （公開したアプリで、ほかの人にキーを使われないように）。「この端末で覚える」を選ぶと、
                ブラウザ内保存に照合用の値（合言葉そのものではない）を置き、90 日のあいだ聞かない。
                照合用の値は、期限と、サーバーだけが知っている API キーを鍵にした HMAC で作る（ブラウザに残った値から、
                合言葉を総当たりで探すことはできない。合言葉か API キーを変えると、覚えた値は使えなくなる）。
                間違いは 1 回の接続で 5 回まで（それ以上は、ページを開き直すまで受け付けない）。
    回数        data/ai.yaml の calls_per_session。1 回の接続で、AI を呼べる回数の上限。
    控え        同じ局面の同じ質問は、もう一度 AI を呼ばずに、前の答えを見せる。

キーと合言葉は、画面に出さず、記録にも残さない。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable, MutableMapping
from typing import Any

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from narration.client import AiClient, AnthropicClient
from narration.service import Answer, Budget
from narration.settings import AiSettings, SettingsError, load_settings

SECRET_KEY = "ANTHROPIC_API_KEY"
SECRET_PASSPHRASE = "AI_PASSPHRASE"
#: ブラウザ内保存に置く、合言葉の照合用の値の名前
UNLOCK_NAME = "ai.unlock"
#: テストで、偽物の AI を入れておく場所（本番では使わない）
TEST_CLIENT = "ai_test_client"
_BUDGET = "ai_budget"
_ANSWERS = "ai_answers"
_UNLOCKED = "ai_unlocked"
_CLIENT = "ai_client"
_FAILURES = "ai_failures"
#: 答えの控えの数の上限（古いものから捨てる）
MAX_ANSWERS = 60
#: 「この端末で覚える」の期限（秒）
REMEMBER_SECONDS = 90 * 24 * 60 * 60
#: 合言葉の間違いを受け付ける回数（1 回の接続で）
MAX_FAILURES = 5
#: 照合用の値の形（期限の UNIX 秒 . HMAC-SHA256 の 16 進）。形が違う値は、比べずに捨てる
_TOKEN = re.compile(r"(\d{9,11})\.([0-9a-f]{64})")


def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except (StreamlitSecretNotFoundError, FileNotFoundError, KeyError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def unlock_token(passphrase: str, secret: str, expires: int) -> str:
    """合言葉の照合用の値（ブラウザに置くのは、合言葉そのものではなく、これ）。secret は、サーバーだけが知っている値（API キー）"""
    digest = hmac.new(f"mjdojo-ai-unlock:{secret}".encode(), f"{expires}:{passphrase}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{digest}"


def token_valid(value: object, passphrase: str, secret: str, now: int) -> bool:
    """ブラウザに残っていた照合用の値が、いまの合言葉と鍵で作ったもので、期限の中か（形がおかしければ False。例外は出さない）"""
    if not isinstance(value, str):
        return False
    match = _TOKEN.fullmatch(value)
    if match is None:
        return False
    expires = int(match.group(1))
    if not now < expires <= now + REMEMBER_SECONDS:
        return False
    return hmac.compare_digest(value.encode(), unlock_token(passphrase, secret, expires).encode())


class AiAccess:
    """AI の窓口（セッションごと。実行のたびに作り直してよい）。store は、ブラウザ内保存（合言葉を覚えるとき）"""

    def __init__(self, session: MutableMapping[str, Any] | None = None, store: Any = None, *, now: Callable[[], float] = time.time) -> None:
        self.session = st.session_state if session is None else session
        self.store = store
        self._now = now
        self.settings: AiSettings | None = None
        self.settings_error = ""
        try:
            self.settings = load_settings()
        except SettingsError as error:
            self.settings_error = str(error)

    # ------------------------------------------------------------ 使えるか

    @property
    def test_client(self) -> AiClient | None:
        return self.session.get(TEST_CLIENT)

    @property
    def has_key(self) -> bool:
        return self.test_client is not None or _secret(SECRET_KEY) is not None

    @property
    def needs_passphrase(self) -> bool:
        return _secret(SECRET_PASSPHRASE) is not None

    @property
    def unlocked(self) -> bool:
        if not self.needs_passphrase or self.session.get(_UNLOCKED):
            return True
        phrase = _secret(SECRET_PASSPHRASE)
        if phrase is not None and token_valid(self._remembered(), phrase, self._signing_secret(), int(self._now())):
            self.session[_UNLOCKED] = True
            return True
        return False

    @property
    def remembered(self) -> bool:
        """この端末で、合言葉を覚えているか"""
        return self._remembered() is not None

    def _remembered(self) -> str | None:
        if self.store is None or not getattr(self.store, "ready", False):
            return None
        value = self.store.get(UNLOCK_NAME)
        return value if isinstance(value, str) else None

    @staticmethod
    def _signing_secret() -> str:
        """照合用の値の鍵（サーバーだけが知っている値。API キー）"""
        return _secret(SECRET_KEY) or ""

    @property
    def locked_out(self) -> bool:
        """合言葉を何度も間違えて、この接続では、もう受け付けないか"""
        return int(self.session.get(_FAILURES, 0)) >= MAX_FAILURES

    @property
    def can_remember(self) -> bool:
        return self.store is not None and getattr(self.store, "ready", False) and getattr(self.store, "available", True)

    def unlock(self, phrase: str, *, remember: bool = False) -> bool:
        """合言葉を確かめる。合っていれば、このセッションで AI を使えるようにする（remember なら、この端末で覚える）。
        間違いが MAX_FAILURES 回になったら、この接続では、合っていても受け付けない"""
        expected = _secret(SECRET_PASSPHRASE)
        if expected is None or self.locked_out:
            return False
        if not hmac.compare_digest(phrase.strip().encode(), expected.encode()):
            self.session[_FAILURES] = int(self.session.get(_FAILURES, 0)) + 1
            return False
        self.session[_UNLOCKED] = True
        self.session.pop(_FAILURES, None)
        if remember and self.can_remember:
            self.store.set(UNLOCK_NAME, unlock_token(expected, self._signing_secret(), int(self._now()) + REMEMBER_SECONDS))
        return True

    def forget(self) -> None:
        """この端末で覚えた合言葉を消し、このセッションでも使えなくする"""
        self.session.pop(_UNLOCKED, None)
        if self.can_remember:
            self.store.remove(UNLOCK_NAME)

    @property
    def available(self) -> bool:
        """いま AI を呼べるか（キーがあり、合言葉が要るなら入れてあり、設定ファイルが読めた）"""
        return self.has_key and self.unlocked and self.settings is not None

    def client(self) -> AiClient | None:
        if not self.available:
            return None
        if self.test_client is not None:
            return self.test_client
        key = _secret(SECRET_KEY)
        assert key is not None and self.settings is not None
        cached = self.session.get(_CLIENT)
        if not isinstance(cached, AnthropicClient):
            cached = AnthropicClient(key, timeout=self.settings.limits.timeout_seconds)
            self.session[_CLIENT] = cached
        return cached

    # ------------------------------------------------------------ 回数と控え

    @property
    def budget(self) -> Budget:
        limit = self.settings.limits.calls_per_session if self.settings is not None else 0
        budget = self.session.get(_BUDGET)
        if budget is None or not hasattr(budget, "take") or budget.limit != limit:
            used = getattr(budget, "used", 0) if budget is not None else 0
            budget = Budget(limit, used)
            self.session[_BUDGET] = budget
        return budget

    def _answers(self) -> dict[str, dict]:
        answers = self.session.get(_ANSWERS)
        if not isinstance(answers, dict):
            answers = {}
            self.session[_ANSWERS] = answers
        return answers

    def recall(self, key: str) -> Answer | None:
        """前に作った答え（無ければ None）"""
        data = self._answers().get(key)
        return Answer(**data) if isinstance(data, dict) else None

    def keep(self, key: str, answer: Answer) -> None:
        """答えを控える（同じ質問で、もう一度 AI を呼ばないように）。答えを作れなかったときは控えない"""
        if answer.source == "error":
            return
        answers = self._answers()
        answers.pop(key, None)
        answers[key] = {
            "text": answer.text, "source": answer.source, "note": answer.note, "model": answer.model, "calls": 0,
            "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens, "unverified": answer.unverified,
        }
        while len(answers) > MAX_ANSWERS:
            answers.pop(next(iter(answers)))

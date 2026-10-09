"""Claude API の呼び方のテスト（narration/client.py）。本物の API は呼ばない（SDK の窓口を偽物にする）"""
from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from narration.client import ERROR_MESSAGES, AiError, AnthropicClient, Message, reply_of, request_params
from narration.settings import ModelSettings

HAIKU = ModelSettings("claude-haiku-5-5", "low", "disabled", 1200)
SONNET = ModelSettings("claude-sonnet-5-5", "low", "adaptive", 3000)
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def message(*blocks, stop="end_turn", model="claude-haiku-5-5"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, model=model,
                           usage=SimpleNamespace(input_tokens=1234, output_tokens=56))


def text(value: str):
    return SimpleNamespace(type="text", text=value)


class FakeSdk:
    """anthropic.Anthropic の代わり：messages.create に渡された引数を覚えて、決まった返事か例外を返す"""

    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **params):
        self.calls.append(params)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_request_params_follow_the_settings():
    messages = [Message("user", "質問"), Message("assistant", "答え"), Message("user", "書き直して")]
    haiku = request_params(HAIKU, "決まり", messages)
    assert haiku == {
        "model": "claude-haiku-5-5", "max_tokens": 1200, "system": "決まり",
        "messages": [{"role": "user", "content": "質問"}, {"role": "assistant", "content": "答え"}, {"role": "user", "content": "書き直して"}],
        "output_config": {"effort": "low"}, "thinking": {"type": "disabled"},
    }
    sonnet = request_params(SONNET, "決まり", messages[:1])
    assert "thinking" not in sonnet and sonnet["output_config"] == {"effort": "low"}       # adaptive は付けない（既定）
    assert "metadata" not in haiku and "metadata" not in sonnet                             # 利用者を見分ける情報は送らない


def test_reply_keeps_only_the_text():
    reply = reply_of(message(SimpleNamespace(type="thinking", thinking="考え中"), text("答え 1。"), text("答え 2。")))
    assert reply.text == "答え 1。答え 2。" and reply.model == "claude-haiku-5-5"
    assert (reply.input_tokens, reply.output_tokens) == (1234, 56)


@pytest.mark.parametrize(("stop", "kind"), [("max_tokens", "truncated"), ("refusal", "refused"), ("end_turn", "empty")])
def test_unusable_replies(stop, kind):
    with pytest.raises(AiError) as caught:
        reply_of(message(text("  ") if stop == "end_turn" else text("途中"), stop=stop))
    assert caught.value.kind == kind and caught.value.message == ERROR_MESSAGES[kind]


def test_client_sends_the_request_and_hides_the_key():
    sdk = FakeSdk(message(text("こたえ")))
    client = AnthropicClient("sk-ant-secret", timeout=30, sdk=sdk)
    reply = client.complete(HAIKU, "決まり", [Message("user", "質問")])
    assert reply.text == "こたえ" and sdk.calls[0]["model"] == "claude-haiku-5-5"
    assert "secret" not in repr(client) and "secret" not in str(sdk.calls)


def status_error(cls, code: int):
    return cls("error", response=httpx2.Response(code, request=REQUEST), body=None)


@pytest.mark.parametrize(("error", "kind"), [
    (status_error(anthropic.AuthenticationError, 401), "auth"),
    (status_error(anthropic.PermissionDeniedError, 403), "permission"),
    (status_error(anthropic.BadRequestError, 400), "settings"),
    (status_error(anthropic.NotFoundError, 404), "settings"),
    (status_error(anthropic.RateLimitError, 429), "rate"),
    (status_error(anthropic.OverloadedError, 529), "busy"),
    (status_error(anthropic.InternalServerError, 500), "busy"),
    (anthropic.APITimeoutError(request=REQUEST), "timeout"),
    (anthropic.APIConnectionError(request=REQUEST), "network"),
    (status_error(anthropic.ConflictError, 409), "other"),
])
def test_errors_become_ai_errors(error, kind):
    client = AnthropicClient("key", timeout=30, sdk=FakeSdk(error))
    with pytest.raises(AiError) as caught:
        client.complete(SONNET, "決まり", [Message("user", "質問")])
    assert caught.value.kind == kind
    assert "key" not in caught.value.detail


def body_error(cls, code: int, error: dict):
    return cls("error", response=httpx2.Response(code, request=REQUEST), body={"type": "error", "error": error, "request_id": "req_x"})


@pytest.mark.parametrize(("error", "kind"), [
    # Claude Console で自分で決めた上限（400。Anthropic の Rate limits の説明「Setting your own spend limit」）
    (body_error(anthropic.BadRequestError, 400, {"type": "invalid_request_error", "message":
                "You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC."}), "spend"),
    (body_error(anthropic.BadRequestError, 400, {"type": "invalid_request_error", "message":
                "You have reached your specified workspace API usage limits. You will regain access on 2026-11-01 at 00:00 UTC."}), "spend"),
    # 利用の段階ごとの月の上限（429。error_code で見分ける）
    (body_error(anthropic.RateLimitError, 429, {"type": "rate_limit_error", "message": "You have reached your API usage limits: …",
                                                "details": {"error_code": "enforced_spend_limit_reached"}}), "spend"),
    # ふつうの 400・429 は、これまでどおり
    (body_error(anthropic.BadRequestError, 400, {"type": "invalid_request_error", "message": "model: claude-x is not a valid model"}), "settings"),
    (body_error(anthropic.RateLimitError, 429, {"type": "rate_limit_error", "message": "Number of request tokens has exceeded your per-minute rate limit"}),
     "rate"),
    (body_error(anthropic.RateLimitError, 429, {"type": "rate_limit_error", "message": "x", "details": "?"}), "rate"),   # 形のおかしい details
])
def test_spend_limits_are_told_apart(error, kind):
    client = AnthropicClient("key", timeout=30, sdk=FakeSdk(error))
    with pytest.raises(AiError) as caught:
        client.complete(HAIKU, "決まり", [Message("user", "質問")])
    assert caught.value.kind == kind
    if kind == "spend":
        assert "Billing" in caught.value.message and "上限" in caught.value.message


def test_spend_limit_reply_over_the_real_sdk():
    """本物の SDK が返事の JSON から作る例外でも、利用額の上限と分かる"""
    def handler(request):
        return httpx2.Response(400, json={"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC."}})

    sdk = anthropic.Anthropic(api_key="sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0)
    with pytest.raises(AiError) as caught:
        AnthropicClient("sk-test", timeout=30, sdk=sdk).complete(HAIKU, "決まり", [Message("user", "質問")])
    assert caught.value.kind == "spend"


def test_unknown_error_kind_is_other():
    assert AiError("strange").kind == "other" and AiError("strange").message == ERROR_MESSAGES["other"]


def test_real_sdk_builds_the_request_over_a_fake_connection():
    """本物の SDK に、通信だけ偽物をつないで、送る中身（JSON）と、返事の読み取りを確かめる"""
    import json

    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content), dict(request.headers)))
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "thinking", "thinking": "…", "signature": "x"}, {"type": "text", "text": "こたえ"}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    sdk = anthropic.Anthropic(api_key="sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0)
    reply = AnthropicClient("sk-test", timeout=30, sdk=sdk).complete(SONNET, "決まり", [Message("user", "質問")])
    assert reply.text == "こたえ" and reply.output_tokens == 5
    url, body, headers = sent[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert body == {"max_tokens": 3000, "messages": [{"role": "user", "content": "質問"}], "model": "claude-sonnet-5-5",
                    "output_config": {"effort": "low"}, "system": "決まり"}
    assert "metadata" not in body and not any("user" in name and name != "user-agent" for name in headers)

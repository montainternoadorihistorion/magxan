"""Claude API を呼ぶ（Anthropic の公式 SDK）。

キーは呼ぶ側（画面）が Secrets から読んで渡す。ここではキーを保存・表示・記録しない。
送るのは、指示（prompts.SYSTEM）と、局面の事実と質問だけ。利用者を見分ける情報（メールアドレスなど）は送らない。
SDK は、AI を初めて呼ぶときに読み込む（キーが無ければ読み込まない。テストでは偽物の AiClient を使う）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from narration.settings import ModelSettings

#: 失敗の種類と、画面に出すひとこと
ERROR_MESSAGES = {
    "auth": "AI のキーが受け付けられませんでした。Secrets の ANTHROPIC_API_KEY を確かめてください。",
    "permission": "このキーでは、設定したモデルを使えないようです（Anthropic のコンソールで、キーの権限を確かめてください）。",
    "settings": "AI の設定（data/ai.yaml のモデル名・effort・thinking）が受け付けられませんでした。",
    "rate": "AI を呼ぶ回数か量が、上限に達しました。しばらくしてから試してください。",
    "spend": "API の利用額が、上限に達しました（Claude Console の Settings → Billing で、上限と、また使えるようになる日を確かめられます）。",
    "busy": "AI が混み合っています。しばらくしてから試してください。",
    "network": "AI につながりませんでした（通信の問題）。",
    "timeout": "AI の返事が、待ち時間のうちに届きませんでした。",
    "truncated": "AI の答えが長くなりすぎて、途中で切れました。",
    "refused": "AI が、この質問には答えませんでした。",
    "empty": "AI から、答えの文が返ってきませんでした。",
    "missing": "AI を呼ぶための部品（anthropic）が入っていません。requirements.txt を確かめてください。",
    "other": "AI を呼ぶときに、問題が起きました。",
}


class AiError(Exception):
    """AI を呼べなかった・答えが使えなかった"""

    def __init__(self, kind: str, detail: str = "") -> None:
        self.kind = kind if kind in ERROR_MESSAGES else "other"
        self.detail = detail
        super().__init__(f"{self.kind}: {detail}" if detail else self.kind)

    @property
    def message(self) -> str:
        return ERROR_MESSAGES[self.kind]


@dataclass(frozen=True)
class Message:
    role: str           # user・assistant
    text: str


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class AiClient(Protocol):
    def complete(self, settings: ModelSettings, system: str, messages: Sequence[Message]) -> Reply:
        """AI に聞いて、答えの文を返す。失敗したら AiError"""
        ...


def request_params(settings: ModelSettings, system: str, messages: Sequence[Message]) -> dict[str, Any]:
    """Messages API に渡す引数（設定ファイルの effort・thinking を、そのまま使う）。

    thinking が adaptive なら、引数を付けない（付けないときの既定が adaptive。古いモデルに替えても通るように）。
    """
    params: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "system": system,
        "messages": [{"role": m.role, "content": m.text} for m in messages],
        "output_config": {"effort": settings.effort},
    }
    if settings.thinking != "adaptive":
        params["thinking"] = {"type": settings.thinking}
    return params


def reply_of(message: Any) -> Reply:
    """SDK の返事から、答えの文（text の部分だけ。考えた過程は捨てる）を取り出す"""
    stop = getattr(message, "stop_reason", None)
    if stop == "max_tokens":
        raise AiError("truncated")
    if stop == "refusal":
        raise AiError("refused")
    text = "".join(getattr(block, "text", "") for block in message.content if getattr(block, "type", "") == "text").strip()
    if not text:
        raise AiError("empty", str(stop))
    usage = getattr(message, "usage", None)
    return Reply(
        text=text,
        model=str(getattr(message, "model", "")),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


class AnthropicClient:
    """本物の Claude API（anthropic の SDK）"""

    def __init__(self, api_key: str, *, timeout: float, max_retries: int = 1, sdk: Any = None) -> None:
        """sdk は、テストで偽物の SDK の窓口（messages.create を持つもの）を渡すときだけ使う"""
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Any = sdk

    def __repr__(self) -> str:            # キーを表示しない
        return "AnthropicClient()"

    def _sdk(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as error:
                raise AiError("missing") from error
            self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries)
        return self._client

    def complete(self, settings: ModelSettings, system: str, messages: Sequence[Message]) -> Reply:
        client = self._sdk()
        import anthropic

        try:
            message = client.messages.create(**request_params(settings, system, messages))
        except anthropic.AuthenticationError as error:
            raise AiError("auth") from error
        except anthropic.PermissionDeniedError as error:
            raise AiError("permission") from error
        except (anthropic.BadRequestError, anthropic.NotFoundError, anthropic.UnprocessableEntityError) as error:
            raise AiError("spend" if spend_limit_reached(error) else "settings", _status_detail(error)) from error
        except anthropic.RateLimitError as error:
            raise AiError("spend" if spend_limit_reached(error) else "rate") from error
        except (anthropic.OverloadedError, anthropic.ServiceUnavailableError, anthropic.InternalServerError) as error:
            raise AiError("busy") from error
        except (anthropic.APITimeoutError, anthropic.DeadlineExceededError) as error:
            raise AiError("timeout") from error
        except anthropic.APIConnectionError as error:
            raise AiError("network") from error
        except anthropic.APIError as error:
            raise AiError("other", _status_detail(error)) from error
        return reply_of(message)


def _status_detail(error: Exception) -> str:
    """エラーの種類と状態コード（キーや送った中身は含めない）"""
    status = getattr(error, "status_code", None)
    return f"{type(error).__name__}" + (f" {status}" if status is not None else "")


def spend_limit_reached(error: Exception) -> bool:
    """API の利用額の上限に達したという返事か。

    Anthropic の説明（Rate limits の「Spend limits」）によると、利用の段階（tier）ごとの月の上限に達したときは 429 で、
    error.details.error_code が enforced_spend_limit_reached。Claude Console で自分で決めた上限に達したときは 400 で、
    メッセージが「You have reached your specified (workspace) API usage limits」で始まる。
    どちらも、そのまま「設定がおかしい」「回数が多すぎる」と伝えると、利用者が見当違いのところを直そうとするので、分けて知らせる。
    """
    body = getattr(error, "body", None)
    info = body.get("error") if isinstance(body, dict) else None
    if not isinstance(info, dict):
        return False
    details = info.get("details")
    if isinstance(details, dict) and details.get("error_code") == "enforced_spend_limit_reached":
        return True
    message = info.get("message")
    return isinstance(message, str) and "API usage limits" in message

"""AI（Claude API）の設定を data/ai.yaml から読む。

モデルの名前・考える量（effort・thinking）・返事の長さの上限・呼べる回数を、プログラムを変えずに変えられるようにする
（仕様の「モデル名は設定ファイルで変更可能にする」）。API キーは、ここでは扱わない（画面の側が Secrets から読む）。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "ai.yaml"
EFFORTS = ("low", "medium", "high")
THINKING = ("adaptive", "disabled", "between_tools")


class SettingsError(ValueError):
    """設定ファイルの書き間違い"""


@dataclass(frozen=True)
class ModelSettings:
    model: str          # Claude API のモデル ID（例: claude-haiku-5-5）
    effort: str         # low・medium・high
    thinking: str       # adaptive・disabled・between_tools
    max_tokens: int     # 返事の長さの上限（考える分を含む）


@dataclass(frozen=True)
class Limits:
    calls_per_session: int      # 1 回の接続で AI を呼べる回数
    question_chars: int         # 自分で書く質問の長さの上限（文字）
    timeout_seconds: int        # 返事を待つ長さ（秒）


@dataclass(frozen=True)
class AiSettings:
    narration: ModelSettings    # よくある質問の答えを、ことばにする
    question: ModelSettings     # 自分で書いた質問に答える
    limits: Limits


def _section(data: Any, name: str, fields: dict[str, type]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SettingsError(f"{name}: 項目の集まり（名前: 値）になっていません")
    unknown = set(data) - set(fields)
    if unknown:
        raise SettingsError(f"{name}: 知らない項目があります {sorted(unknown)}")
    result = {}
    for key, kind in fields.items():
        if key not in data:
            raise SettingsError(f"{name}: 「{key}」がありません")
        value = data[key]
        if type(value) is not kind:
            raise SettingsError(f"{name}: 「{key}」の型が違います（{value!r}）")
        result[key] = value
    return result


def _model(data: Any, name: str) -> ModelSettings:
    values = _section(data, name, {"model": str, "effort": str, "thinking": str, "max_tokens": int})
    if not values["model"].strip():
        raise SettingsError(f"{name}: model が空です")
    if values["effort"] not in EFFORTS:
        raise SettingsError(f"{name}: effort は {EFFORTS} のどれかです（{values['effort']!r}）")
    if values["thinking"] not in THINKING:
        raise SettingsError(f"{name}: thinking は {THINKING} のどれかです（{values['thinking']!r}）")
    if not 200 <= values["max_tokens"] <= 16_000:
        raise SettingsError(f"{name}: max_tokens は 200〜16000 にします（{values['max_tokens']}）")
    return ModelSettings(**values)


def parse_settings(data: Any) -> AiSettings:
    """読み込んだ YAML（辞書）から設定を作る。書き間違いは SettingsError"""
    top = _section(data, "ai.yaml", {"narration": dict, "question": dict, "limits": dict})
    limits = _section(top["limits"], "limits", {"calls_per_session": int, "question_chars": int, "timeout_seconds": int})
    if not 1 <= limits["calls_per_session"] <= 500:
        raise SettingsError("limits: calls_per_session は 1〜500 にします")
    if not 20 <= limits["question_chars"] <= 1000:
        raise SettingsError("limits: question_chars は 20〜1000 にします")
    if not 5 <= limits["timeout_seconds"] <= 300:
        raise SettingsError("limits: timeout_seconds は 5〜300 にします")
    return AiSettings(_model(top["narration"], "narration"), _model(top["question"], "question"), Limits(**limits))


@cache
def load_settings(path: Path = SETTINGS_FILE) -> AiSettings:
    """設定ファイルを読む（同じプロセスでは 1 回だけ。ファイルを書き換えたら、アプリの更新として読み直される）"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SettingsError(f"{path.name} を読めません: {error}") from error
    return parse_settings(data)

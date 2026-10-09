"""AI の設定ファイル（data/ai.yaml）の読み込みのテスト"""
from __future__ import annotations

import copy

import pytest

from narration.settings import SETTINGS_FILE, SettingsError, load_settings, parse_settings

GOOD = {
    "narration": {"model": "claude-haiku-5-5", "effort": "low", "thinking": "disabled", "max_tokens": 1200},
    "question": {"model": "claude-sonnet-5-5", "effort": "low", "thinking": "adaptive", "max_tokens": 3000},
    "limits": {"calls_per_session": 30, "question_chars": 200, "timeout_seconds": 60},
}


def changed(path: tuple[str, ...], value) -> dict:
    data = copy.deepcopy(GOOD)
    node = data
    for key in path[:-1]:
        node = node[key]
    if value is None:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return data


def test_the_shipped_settings_file_is_valid():
    settings = load_settings(SETTINGS_FILE)
    assert settings.narration.model == "claude-haiku-5-5" and settings.narration.thinking == "disabled"
    assert settings.question.model == "claude-sonnet-5-5" and settings.question.thinking == "adaptive"
    assert settings.narration.effort == settings.question.effort == "low"
    assert settings.limits.calls_per_session == 30 and settings.limits.question_chars == 200


def test_parse_good_settings():
    settings = parse_settings(GOOD)
    assert settings.question.max_tokens == 3000 and settings.limits.timeout_seconds == 60


@pytest.mark.parametrize(("path", "value", "message"), [
    (("narration", "effort"), "max", "effort"),
    (("narration", "thinking"), "enabled", "thinking"),
    (("question", "max_tokens"), 100, "max_tokens"),
    (("question", "max_tokens"), "3000", "型"),
    (("question", "model"), " ", "model"),
    (("limits", "calls_per_session"), 0, "calls_per_session"),
    (("limits", "question_chars"), 5000, "question_chars"),
    (("limits", "timeout_seconds"), 1, "timeout_seconds"),
    (("limits", "timeout_seconds"), None, "timeout_seconds"),
    (("narration", "temperature"), 0.5, "知らない項目"),
    (("question",), None, "question"),
])
def test_mistakes_are_reported(path, value, message):
    with pytest.raises(SettingsError, match=message):
        parse_settings(changed(path, value))


def test_unreadable_file(tmp_path):
    path = tmp_path / "ai.yaml"
    path.write_text("narration: [", encoding="utf-8")
    with pytest.raises(SettingsError, match="読めません"):
        load_settings(path)
    with pytest.raises(SettingsError):
        parse_settings(None)

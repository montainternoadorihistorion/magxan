"""文章をクリップボードにコピーするボタン（スマホでも 1 回押すだけでコピーできるようにする）"""
from __future__ import annotations

from pathlib import Path

from ui.components._base import registered

_DIR = Path(__file__).parent


def _component():
    return registered("mjdojo_copy_button", _DIR, html="copy_button.html", css="copy_button.css", js="copy_button.js")


def copy_button(
    text: str,
    *,
    key: str,
    label: str = "コピーする",
    done_text: str = "コピーしました",
    fail_text: str = "コピーできませんでした。下の文章を長押しして選択してください。",
) -> None:
    """text をクリップボードに入れるボタンを置く"""
    _component()(key=key, data={"text": text, "label": label, "doneText": done_text, "failText": fail_text})

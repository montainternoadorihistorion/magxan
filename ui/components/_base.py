"""自作部品の登録をまとめる。

Streamlit の部品（カスタムコンポーネント v2）は、動いている Streamlit 本体に登録してから使う。
モジュールの読み込み時に 1 度だけ登録する書き方だと、本体が作り直される場面（自動テストなど）で
「登録されていない」エラーになる。そこで、置くたびに登録し直す。同じ内容の登録は何も起こさないので害はない。
ファイルの読み込みは 1 度だけ行う。
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

import streamlit as st


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def registered(name: str, folder: Path, *, html: str | None = None, css: str | None = None, js: str | None = None):
    """部品を登録し、画面に置くための関数を返す。html / css / js は folder の中のファイル名"""
    return st.components.v2.component(
        name,
        html=_read(folder / html) if html else None,
        css=_read(folder / css) if css else None,
        js=_read(folder / js) if js else None,
    )

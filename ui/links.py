"""ページへのリンクを、押しやすい枠つきのボタンの形で出す（カリキュラム・卒業判定のページ）。

Streamlit のリンクは、名前が長いと 1 行に収まらず、右が切れてしまう。ここで出すリンクは、名前を折り返し、
指で押しやすい高さ（44px 以上）にする（形は ui/layout.py の st-key-mj_link_…）。
"""
from __future__ import annotations

from collections.abc import Mapping

import streamlit as st


def framed_link(page: str, label: str, icon: str, *, key: str, query_params: Mapping[str, str] | None = None) -> None:
    with st.container(key=f"mj_link_{key}"):
        st.page_link(page, label=label, icon=icon, query_params=dict(query_params) if query_params else None)

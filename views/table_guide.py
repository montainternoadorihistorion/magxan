"""卓で打つとき。

実際の卓（牌と点棒を使う麻雀）で、1 局が始まってから終わるまでの手順と、発声・作法・反則。
"""
from __future__ import annotations

import streamlit as st

from engine.content import table_guide
from ui.learn_view import guide_detail_html, guide_head_html, score_table_html, sources_html, subhead
from ui.ruby import Rubifier

guide = table_guide()
rb = Rubifier()

st.title("卓で打つとき")
st.html(f'<div class="mj-note">{rb.html(guide.intro)}</div>')
st.page_link("views/rules.py", label="ルールの違い（卓に着く前に確かめること）", icon=":material/rule:")

for number, section in enumerate(guide.sections, start=1):
    st.html(guide_head_html(number, section, rb))
    with st.expander(f"{number}. くわしい手順", key=f"tg_x_{section.key}"):
        inner = rb.fork()
        st.html(guide_detail_html(section, inner))
        if section.key == "points":
            st.html(subhead("点数の早見表", inner) + score_table_html(inner))
            st.page_link("views/drill.py", label="ドリルで点数を覚える", icon=":material/quiz:", query_params={"k": "table"})

with st.expander("調べた資料", key="tg_x_sources"):
    st.html(sources_html(guide.sources, rb.fork()))

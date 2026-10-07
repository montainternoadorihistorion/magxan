"""ルールの違い。

麻雀のルールは、打つ場所によって細かく違う。6 つのルールを読みくらべて、分かれるところをまとめたページ。
"""
from __future__ import annotations

import streamlit as st

from engine.content import rule_book
from ui.learn_view import checklist_html, rule_item_html, rule_names_html, sources_html, subhead
from ui.ruby import Rubifier

book = rule_book()
rb = Rubifier()

st.title("ルールの違い")
st.html(f'<div class="mj-note">{rb.html(book.intro)}</div>' + rule_names_html(book.names, book.surveyed, rb))

st.html(subhead("★ 卓に着く前に確かめること", rb) + checklist_html(book, rb))
st.html(f'<div class="mj-sub">{rb.html("聞き方の例：「アリアリですか？」「赤は何枚ですか？」「トビはありますか？」。分からないことは、打つ前に聞けばよい。")}</div>')

for group, title in book.groups.items():
    items = book.of(group)
    if not items:
        continue
    with st.expander(f"{title}（{len(items)}）", key=f"rl_x_{group}"):
        inner = rb.fork()
        st.html("".join(rule_item_html(item, inner) for item in items))

st.page_link("views/score_lab.py", label="点数計算ラボで、ルールを変えて計算してみる", icon=":material/calculate:")
st.page_link("views/table_guide.py", label="卓で打つとき（手順と作法）", icon=":material/table_restaurant:")

with st.expander("調べた資料と、注意", key="rl_x_sources"):
    inner = rb.fork()
    st.html(
        sources_html(book.sources, inner)
        + '<ul class="mj-rules">' + "".join(f"<li>{inner.html(text)}</li>" for text in book.caveats) + "</ul>"
    )

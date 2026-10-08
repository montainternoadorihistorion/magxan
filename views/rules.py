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

st.html(
    subhead("★ 卓に着く前に確かめること", rb)
    + f'<div class="mj-note"><b>{rb.html(f"まず聞いておくこと（{len(book.first_checks)} つ）")}</b></div>'
    + f'<div class="mj-sub">{rb.html("あがれるかどうかや、点数に、すぐ関わるもの。初めての卓では、これだけでも聞いておくと安心。")}</div>'
    + checklist_html(book.first_checks, rb)
    + f'<div class="mj-sub">{rb.html("聞き方の例：「アリアリですか？」（喰いタンと後付けが、どちらもありか、という意味）「赤は何枚ですか？」「トビはありますか？」。分からないことは、打つ前に聞けばよい。")}</div>'
)
with st.expander(f"余裕があれば聞くこと（{len(book.more_checks)}）", key="rl_x_more"):
    st.html(checklist_html(book.more_checks, rb.fork()))

# まとまりの名前（折りたたみの名前）には読みを振れないので、その前に、読みつきで一度出しておく
st.html(
    subhead("項目ごとの違い", rb)
    + f'<div class="mj-sub">{rb.html("点数・あがりと流局・試合の進め方・卓での決まりの、4 つのまとまりに分けた。開くと、6 つのルールでどう分かれるかと、このアプリの扱いが出る。")}</div>'
)
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

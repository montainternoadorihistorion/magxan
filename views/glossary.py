"""用語・読み方辞典。

用語を分類ごとに並べる。言葉でさがすこともできる。役の名前は、役図鑑のページから自動で足す。
URL の t に見出し語を入れると、その用語をいちばん上に出す（例：?t=聴牌）。
"""
from __future__ import annotations

import streamlit as st

from engine.content import glossary, yaku_pages
from ui.components.choices import Option, choice_buttons
from ui.learn_view import (
    YAKU_CATEGORY,
    YAKU_CATEGORY_NAME,
    certainty_legend_html,
    search_terms,
    sources_html,
    subhead,
    term_html,
    yaku_term_html,
)
from ui.ruby import Rubifier

ss = st.session_state
book = glossary()
pages = yaku_pages()
categories = {**book.categories, YAKU_CATEGORY: YAKU_CATEGORY_NAME}
rb = Rubifier()



def _on_category(keys: list[str]) -> None:
    ss["gl_category"] = keys[0]


st.title("用語辞典")
st.html(
    f'<div class="mj-note">{rb.html("麻雀の言葉は、中国語から来た読みが多い。読み・意味・由来を、分類ごとにまとめた。")}</div>'
    f'<div class="mj-sub">{rb.html("由来がはっきりしないものには「諸説あり」と書いてある。調べても分からなかったものは、由来を書いていない。")}</div>'
)

# URL で用語が指定されていたら、その用語を先頭に出す
wanted = st.query_params.get("t")
picked = book.find(wanted) if wanted else None
if picked is not None:
    st.html(subhead("さがした用語", rb) + term_html(picked, rb, category=categories[picked.category]))
    if ss.get("gl_from") != wanted:           # その用語の分類を、下の一覧に出しておく（1 回だけ）
        ss["gl_from"] = wanted
        ss["gl_category"] = picked.category

query = st.text_input("言葉でさがす", key="gl_w_query", placeholder="例：テンパイ、待ち、鳴き", autocomplete="off")
if query.strip():
    terms, found = search_terms(book, pages, query)
    total = len(terms) + len(found)
    st.caption(f"「{query.strip()}」で {total} 件")
    if total == 0:
        st.html(f'<div class="mj-sub">{rb.html("見つからなかった。ひらがな・カタカナ・漢字のどれでもさがせる。短い言葉で試すと、見つかりやすい。")}</div>')
    html = "".join(term_html(term, rb, category=categories[term.category]) for term in terms[:40])
    html += "".join(yaku_term_html(page, rb) for page in found[:20])
    if html:
        st.html(html)
    if len(terms) > 40 or len(found) > 20:
        st.caption("多すぎるので、はじめのほうだけを出している。")
else:
    if ss.get("gl_category") not in categories:
        ss["gl_category"] = next(iter(categories))
    category = ss["gl_category"]
    keys = list(categories)
    st.html(f'<div class="mj-sub">{rb.html("分類を選ぶ")}</div>')
    choice_buttons(
        [Option(key, rb.parts(name)) for key, name in categories.items()], key="gl_c_category", rev=keys.index(category),
        on_pick=_on_category, layout="chips", selected=[category],
    )
    st.html(subhead(categories[category], rb))
    if category == YAKU_CATEGORY:
        st.page_link("views/yaku_book.py", label="役図鑑（定義・成立例・コツ）を開く", icon=":material/menu_book:")
        st.html("".join(yaku_term_html(page, rb) for page in pages))
    else:
        st.html("".join(term_html(term, rb) for term in book.of(category)))

with st.expander("由来の確かさと、調べた資料", key="gl_x_sources"):
    inner = rb.fork()
    st.html(
        certainty_legend_html(inner)
        + subhead("由来を調べるのに使った資料", inner)
        + sources_html(book.sources, inner)
        + f'<div class="mj-sub">{inner.html("役の名前の由来（役図鑑）も、同じ資料によっている。")}</div>'
    )

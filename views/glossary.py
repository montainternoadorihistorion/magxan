"""用語・読み方辞典。

用語を分類ごとに並べる。言葉でさがすこともできる。役の名前は、役図鑑のページから自動で足す。
URL の t に見出し語を入れると、その用語をいちばん上に出す（例：?t=聴牌）。
"""
from __future__ import annotations

import streamlit as st

from engine.content import Term, glossary, yaku_pages
from ui.components.choices import Option, choice_buttons
from ui.learn_view import (
    YAKU_CATEGORY,
    YAKU_CATEGORY_NAME,
    certainty_legend_html,
    search_results,
    sources_html,
    subhead,
    term_html,
    yaku_term_html,
)
from ui.ruby import Rubifier

ss = st.session_state
#: 言葉でさがしたときに出す数の上限（多すぎると、画面がとても長くなる）
MAX_RESULTS = 60
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
    # 見出し語・読みがぴったり合うもの → 先頭が合うもの → … の順。用語と役の名前をまぜて並べる
    results = search_results(book, pages, query)
    st.caption(f"「{query.strip()}」で {len(results)} 件")
    if not results:
        st.html(f'<div class="mj-sub">{rb.html("見つからなかった。ひらがな・カタカナ・漢字のどれでもさがせる。短い言葉で試すと、見つかりやすい。")}</div>')
    html = "".join(
        term_html(item, rb, category=categories[item.category]) if isinstance(item, Term) else yaku_term_html(item, rb)
        for item in results[:MAX_RESULTS]
    )
    if html:
        st.html(html)
    if len(results) > MAX_RESULTS:
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

"""役図鑑。

役の一覧（スタンプつき）と、役ごとのページ（定義・成立例・ひっかけ例・複合・コツ・由来）。
どの役のページを開くかは、URL の y で決める（例：?y=sanshoku）。y が無ければ一覧。
"""
from __future__ import annotations

import streamlit as st

from engine.content import GROUPS, yaku_page_map, yaku_pages, yaku_stats
from engine.progress import completion
from engine.records import target_stats
from ui.components.browser_store import BrowserStore
from ui.components.scroll_top import scroll_top
from ui.learn_view import (
    book_intro_html,
    certainty_legend_html,
    combos_html,
    completion_text,
    definition_html,
    example_html,
    frequency_html,
    head_html,
    list_label,
    next_label,
    origin_html,
    river_html,
    stamp_html,
    subhead,
    tips_html,
    trap_html,
)
from ui.progress_store import read_history, read_stamps
from ui.ruby import Rubifier

PAGE = "views/yaku_book.py"
store = BrowserStore()
pages = yaku_pages()
by_key = yaku_page_map()
# スタンプは、ブラウザに残してある記録から読む。開いた直後で、まだ記録が届いていなければ、スタンプなしで出しておく
# （記録が届くと、もう一度描き直される）
stamps = read_stamps(store) if store.ready else None
rb = Rubifier()

key = st.query_params.get("y")
page = by_key.get(key) if key else None
# 同じページの中でリンクを押したとき、Streamlit はブラウザの URL を書き換えない（ページが変わったときだけ書き換える）。
# 自分で入れ直すと、URL と「戻る」の履歴が、いま見ている役に合う（戻るで一覧や前の役に戻れる。開き直しても同じ役が出る）
if page is not None:
    st.query_params["y"] = page.key
else:
    st.query_params.clear()

if page is None:
    # ---------------------------------------------------------------- 一覧
    st.title("役図鑑")
    done = completion(stamps) if stamps is not None else None
    st.html(book_intro_html(done, rb))
    if done is not None:
        st.progress(done.rate, text=completion_text(done))
    st.html(f'<div class="mj-sub">{rb.html("「門前」は、鳴くと付かない役。「鳴↓」は、鳴くと 1 翻下がる役（喰い下がり）。")}</div>')
    for group, title in GROUPS.items():
        members = [p for p in pages if p.group == group]
        if not members:
            continue
        st.html(subhead(title, rb))
        for member in members:
            stamp = stamps.get(member.key) if stamps else None
            st.page_link(
                PAGE, label=list_label(member, stamp), query_params={"y": member.key},
                icon=":material/verified:" if stamp is not None else ":material/radio_button_unchecked:",
            )
    with st.expander("出やすさの目安と、由来の確かさについて", key="yb_x_about"):
        inner = rb.fork()
        stats = yaku_stats()
        st.html(
            f'<div class="mj-sub">{inner.html("各ページの「出やすさ」は、あがった手のうち、その役が付いていた割合から決めている。よく出る ＝ 10% 以上、ときどき ＝ 1% 以上、まれ ＝ 1% 未満。")}</div>'
            + "".join(f'<div class="mj-sub">{inner.html(note)}</div>' for note in stats.notes)
            + subhead("由来の確かさ", inner)
            + certainty_legend_html(inner)
        )
else:
    # ---------------------------------------------------------------- 役のページ
    index = pages.index(page)
    st.html('<div class="mj-topgap"></div>')        # いちばん上の行が、画面の上の帯（メニュー）に隠れないように
    with st.container(horizontal=True, vertical_alignment="center"):
        st.page_link(PAGE, label="一覧へ", icon=":material/arrow_back:")
        # リンクの文字にはルビを振れないので、ここには役の名前を書かない（名前は、いちばん下のリンクに読みと並べて出す）
        if index > 0:
            st.page_link(PAGE, label="前の役", query_params={"y": pages[index - 1].key})
        if index < len(pages) - 1:
            st.page_link(PAGE, label="次の役", query_params={"y": pages[index + 1].key})

    stats = yaku_stats()
    st.html(head_html(page, rb, stat=stats.pages.get(page.key)))

    stamp = stamps.get(page.key) if stamps else None
    aimed = target_stats(read_history(store)).get(page.key) if store.ready else None
    if stamps is not None:
        st.html(stamp_html(page, stamp, aimed, rb))
    if page.practice and st.button("この役を実戦で練習する", type="primary", width="stretch", key="yb_b_practice"):
        st.switch_page("views/practice.py", query_params={"target": page.practice})
    if page.practice_note:
        st.html(f'<div class="mj-sub">{rb.html(page.practice_note)}</div>')

    st.html(definition_html(page, rb))

    if page.examples:
        st.html(subhead("成立する例", rb) + "".join(example_html(page, hand, rb) for hand in page.examples))
    if page.traps:
        st.html(
            subhead("ひっかけ：付きそうで、付かない例", rb)
            + "".join(trap_html(page, trap, rb) for trap in page.traps)
        )
    if page.rivers:
        st.html(
            subhead("河（捨て牌）の例", rb)
            + "".join(river_html(river.title, river.tiles, river.ok, river.note, rb) for river in page.rivers)
        )

    combos = combos_html(page, rb)
    if combos:
        st.html(combos)
    st.html(tips_html(page, rb) + subhead("出やすさの目安", rb) + frequency_html(page, stats, rb))
    st.html(subhead("読み方と、名前の由来", rb) + origin_html(page, rb))
    with st.expander("由来の確かさについて", key="yb_x_cert"):
        st.html(certainty_legend_html(rb.fork()))

    if index < len(pages) - 1:
        st.page_link(PAGE, label=next_label(pages[index + 1]), icon=":material/arrow_forward:", query_params={"y": pages[index + 1].key})
    st.page_link(PAGE, label="役の一覧へ", icon=":material/arrow_back:")
    st.page_link("views/glossary.py", label="用語辞典で言葉を調べる", icon=":material/dictionary:")

# 一覧 → 役のページ、役 → 次の役 と移ったとき、前の画面のスクロール位置が残らないように、いちばん上へ戻す
scroll_top(pages.index(page) + 1 if page is not None else 0, key="yb_scroll")
store.mount()

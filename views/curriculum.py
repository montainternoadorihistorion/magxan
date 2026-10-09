"""カリキュラム。

ツキ補正を段階的に下げながら、役 → 点数 → 牌効率・守り → 押し引きと高い手 の順に学ぶ（仕様の 8 章）。
段階ごとに、学ぶところ（役図鑑・用語辞典・点数計算ラボ・卓で打つとき・ドリル）と、実戦の練習と、確認テストがある。
確認テストはドリルのページで受ける（ドリルの問題を、決まった数だけ出す）。合格すると、次の段階が開く。
"""
from __future__ import annotations

import secrets

import streamlit as st

from engine.content import glossary, table_guide, yaku_page_map
from engine.curriculum import curriculum, exam_items, step_of
from engine.drills import KINDS
from engine.scoring.examples import EXAMPLES_BY_KEY
from ui.components.browser_store import BrowserStore
from ui.curriculum_view import luck_name, overview_html, status_text, step_body_html, test_result_html
from ui.drill_session import DrillSession
from ui.learn_view import subhead
from ui.links import framed_link
from ui.progress_store import read_curriculum
from ui.ruby import Rubifier

ss = st.session_state
store = BrowserStore()

st.title("カリキュラム")

if not store.ready:
    store.mount()
    st.info("ブラウザに保存された記録を確認しています…")
    st.button("保存を使わずに始める", on_click=store.skip)
    st.stop()

rb = Rubifier()
progress = read_curriculum(store)
drills = DrillSession(ss, store)

st.html(
    f'<div class="mj-note">{rb.html("ツキ補正を段階的に下げながら、4 つの段階で学ぶ。段階ごとに到達目標と確認テストがあり、合格すると次の段階に進める。")}</div>'
    f'<div class="mj-sub">{rb.html("前の段階は、いつでも見直せる。確認テストは、何度でも受けられる。")}</div>'
)
message = ss.pop("cu_message", None)
if isinstance(message, str):
    st.info(message)
running = drills.test
if running is not None:
    # 確認テストの途中（ほかのページを見に来た）。続きをするか、やめるか
    step_now = step_of(running["step"])
    title = step_now.title if step_now is not None else ""
    where = f"{running['index'] + 1} / {len(running['items'])} 問目"
    st.html(f'<div class="mj-note">{rb.html(f"確認テスト「{title}」の途中です（{where}）。")}</div>')
    with st.container(horizontal=True):
        framed_link("views/drill.py", "確認テストの続きをする", ":material/quiz:", key="cu_continue")
        st.button("確認テストをやめる", on_click=drills.leave, key="cu_b_quit")
done = drills.test_done
if done is not None:
    st.html(test_result_html(done, rb))
    st.button("結果を閉じる", on_click=drills.clear_test_done, key="cu_b_close")
st.html(overview_html(progress, rb))

current = progress.current
for number, step in enumerate(curriculum(), start=1):
    label, _ = status_text(step, progress)
    with st.expander(f"{number}. {step.title}（{label}）", expanded=step.key == current.key, key=f"cu_x_{step.key}"):
        inner = rb.fork()
        st.html(step_body_html(step, progress, inner))
        if progress.unlocked(step.key):
            if st.button("確認テストを受ける", type="primary", key=f"cu_b_test_{step.key}", width="stretch"):
                drills.start_test(step.key, exam_items(step, secrets.randbelow(10**9)))
                st.switch_page("views/drill.py")
        else:
            st.html(f'<div class="mj-sub">{inner.html("前の段階の確認テストに合格すると、受けられる。")}</div>')

        st.html(subhead("学ぶところ", inner))
        pages = yaku_page_map()
        link = f"cu_{step.key}"
        for key in step.learn["yaku"]:
            framed_link("views/yaku_book.py", inner.inline(f"役図鑑：{pages[key].name}"), ":material/menu_book:", key=f"{link}_y_{key}",
                        query_params={"y": key})
        for number, term in enumerate(step.learn["term"]):
            entry = glossary().find(term)
            if entry is not None:
                framed_link("views/glossary.py", inner.inline(f"用語辞典：{entry.term}"), ":material/dictionary:", key=f"{link}_t_{number}",
                            query_params={"t": term})
        for key in step.learn["lab"]:
            example = EXAMPLES_BY_KEY[key]
            framed_link("views/score_lab.py", inner.inline(f"点数計算ラボ：{example.key} {example.title}"), ":material/calculate:", key=f"{link}_l_{key}",
                        query_params={"ex": key})
        sections = {s.key: s for s in table_guide().sections}
        for key in step.learn["guide"]:
            framed_link("views/table_guide.py", inner.inline(f"卓で打つとき：{sections[key].title}"), ":material/table_restaurant:", key=f"{link}_g_{key}")
        for kind in step.learn["drill"]:
            framed_link("views/drill.py", inner.inline(f"ドリル：{KINDS[kind].name}"), ":material/quiz:", key=f"{link}_d_{kind}", query_params={"k": kind})

        st.html(subhead("実戦で練習する", inner)
                + f'<div class="mj-sub">{inner.html(f"この段階のツキ補正は「{luck_name(step.luck)}」。一人練習・CPU との対局の設定で選べる（設定の「おまかせ」なら、成績に合わせて自動で上げ下げする）。")}</div>')
        for number, target in enumerate(step.practice):
            if target:
                framed_link("views/practice.py", inner.inline(f"一人練習：{pages[target].name}を狙う（役指定練習）"), ":material/playing_cards:",
                            key=f"{link}_p_{number}", query_params={"target": target})
            else:
                framed_link("views/practice.py", "一人練習", ":material/playing_cards:", key=f"{link}_p_{number}")
        if step.game:
            framed_link("views/game.py", inner.inline(f"CPU と対局：{step.game}"), ":material/groups:", key=f"{link}_game",
                        query_params={"graduation": "1"} if step.graduation else None)

st.html(f'<div class="mj-sub">{rb.html("カリキュラムは学ぶ順番。ゴール（友人と楽しく打てるレベル）に届いたかは、卒業判定のページで、記録から判定する。")}</div>')
framed_link("views/graduation.py", "卒業判定", ":material/emoji_events:", key="cu_graduation")

store.mount()

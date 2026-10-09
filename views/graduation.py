"""卒業判定。

仕様の 9 章「卒業条件（＝友人と楽しく打てるレベル）」の 6 つを、ブラウザに残っている記録（ドリル・点数の申告・CPU 戦の成績）から
まとめて判定する（engine/graduation.py）。条件ごとに、いまの値と目標、練習する場所へのリンクを出す。
カリキュラムの進み具合も、ここに並べる（どこまで学んだか・次に何をするか）。
"""
from __future__ import annotations

import streamlit as st

from engine.curriculum import curriculum
from engine.drills import KINDS
from engine.graduation import WHERE_DRILL, WHERE_GAME, WHERE_PLAY, report
from ui.components.browser_store import BrowserStore
from ui.curriculum_view import luck_name
from ui.graduation_view import condition_html, notes_html, summary_html
from ui.learn_view import subhead
from ui.links import framed_link
from ui.progress_store import read_curriculum, read_decks, read_games
from ui.ruby import Rubifier

store = BrowserStore()

st.title("卒業判定")

if not store.ready:
    store.mount()
    st.info("ブラウザに保存された記録を確認しています…")
    st.button("保存を使わずに開く", on_click=store.skip)
    st.stop()

rb = Rubifier()
result = report(read_decks(store), read_games(store))

st.html(
    f'<div class="mj-note">{rb.html("ゴールは、友人と卓を囲んで、楽しく打てるようになること。そのための 6 つの条件を、これまでの記録から判定する。")}</div>'
    + summary_html(result, rb)
)

for number, condition in enumerate(result.conditions, start=1):
    st.html(condition_html(number, condition, rb))
    links = []
    for check in condition.checks:
        if check.passed:
            continue
        if check.where == WHERE_DRILL and ("drill", check.kind) not in links:
            links.append(("drill", check.kind))
        elif check.where in (WHERE_GAME, WHERE_PLAY) and ("game", "") not in links:
            links.append(("game", ""))
    for where, kind in links:              # リンクは縦に並べる（横に並べると、名前の途中で折り返して読みにくい）
        if where == "drill":
            framed_link("views/drill.py", rb.inline(f"ドリル：{KINDS[kind].name}"), ":material/quiz:", key=f"gr_{condition.key}_{kind}",
                        query_params={"k": kind})
        elif condition.key == "points":
            # 点数の申告は、一人練習でも CPU 戦でも（打つ前のヒントを見ずに打った局だけ数える）
            framed_link("views/practice.py", "一人練習", ":material/playing_cards:", key=f"gr_{condition.key}_practice")
            framed_link("views/game.py", "CPU と対局", ":material/groups:", key=f"gr_{condition.key}_game")
        else:
            framed_link("views/game.py", "CPU と対局（卒業判定に数える設定で）", ":material/groups:", key=f"gr_{condition.key}_game",
                        query_params={"graduation": "1"})

# ---- カリキュラムの進み具合
progress = read_curriculum(store)
steps = curriculum()
passed = sum(1 for step in steps if progress.passed(step.key))
if progress.finished:
    line = f"カリキュラム：{len(steps)} つの段階に、すべて合格。"
else:
    current = progress.current
    done_text = f"{len(steps)} 段階のうち {passed} 段階に合格" if passed else f"{len(steps)} 段階のうち、まだ合格した段階はない"
    line = f"カリキュラム：{done_text}。いまの段階は「{current.title}」（ツキ補正「{luck_name(current.luck)}」）。"
st.html(subhead("学びの進み具合", rb) + f'<div class="mj-note">{rb.html(line)}</div>')
with st.container(horizontal=True):
    framed_link("views/curriculum.py", "カリキュラム", ":material/school:", key="gr_curriculum")
    framed_link("views/records.py", "記録と保存", ":material/save:", key="gr_records")

st.html(subhead("判定のしかた", rb) + notes_html(rb))

store.mount()

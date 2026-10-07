"""ドリル。

短い問題をくり返して、読み・役・待ち・符・点数の数え方を覚えるページ。
間違えた問題は、間隔をあけてもう一度出す（間隔反復）。記録は、種類ごとにブラウザに残す。
URL の k に種類の鍵を入れると、その種類から始める（例：?k=table）。
"""
from __future__ import annotations

import time

import streamlit as st

from engine.coach import analyze
from engine.content import glossary, yaku_page_map
from engine.drills import DONE, GROUPS, KINDS, early_item, grade, grade_discard, progress_of
from engine.scoring.explain import Status, explain
from engine.srs import INTERVALS
from ui.components.browser_store import BrowserStore
from ui.components.choices import Option, choice_buttons
from ui.components.scroll_top import scroll_top
from ui.components.tile_hand import Pick, tile_hand
from ui.drill_session import DrillSession
from ui.drill_view import (
    answer_lines_html,
    choices_review_html,
    done_html,
    header_html,
    kind_card_html,
    position_status_html,
    prompt_html,
    river_html,
    srs_note_html,
    verdict_banner_html,
)
from ui.learn_view import score_table_html, subhead
from ui.practice_view import MARK_EQUAL, MARK_PICK, candidates_html, shanten_html
from ui.progress_store import read_decks
from ui.ruby import Rubifier
from ui.tile_view import tile_image_url, tile_label
from ui.timefmt import span_text
from ui.win_view import DETAIL_NORMAL, chips_html, detail_sections, hand_html, situation_chips, tiles_fit_html

ss = st.session_state
store = BrowserStore()
session = DrillSession(ss, store)
#: くわしい解説に出す部分（種類ごと。None は全部）
DETAIL_KEYS = {"fu": ("reading", "fu"), "yaku": ("reading", "yaku", "dora"), "valid": ("reading", "yaku"), "score": None, "win": None}
#: 選択肢の並べ方（種類ごと。書いていない種類は、縦に並べる）
LAYOUTS = {"valid": "row", "yaku": "chips", "wait": "chips"}


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------- 操作


def _on_choice(keys: list[str]) -> None:
    session.answer(keys)


def _on_discard(pick: Pick) -> None:
    session.answer_discard(pick.tile_id)


# ---------------------------------------------------------------- 画面：種類の一覧


def _menu(rb: Rubifier) -> None:
    now = _now()
    decks = read_decks(store)
    progress = {kind: progress_of(kind, decks[kind], now) for kind in KINDS}
    due = sum(p.due for p in progress.values())
    st.html(
        f'<div class="mj-note">{rb.html("短い問題をくり返して、役・待ち・符・翻・点数の数え方と見分け方を覚える。間違えた問題は、間隔をあけてもう一度出す。")}</div>'
    )
    if session.take_review_done():
        st.success("復習は、すべて終わりました。")
    if due:
        st.button(f"復習する（{due} 問）", type="primary", on_click=session.start_review, width="stretch", key="dr_b_review")
        st.html(f'<div class="mj-sub">{rb.html("復習の時刻になった問題を、種類をまたいで出す。")}</div>')
    else:
        waiting = [p.next_due for p in progress.values() if p.next_due is not None]
        text = "復習の時刻になった問題は、いまは無い。"
        if waiting:
            text += f"次の復習は、{span_text(min(waiting) - now)}後。"
        st.html(f'<div class="mj-sub">{rb.html(text)}</div>')
    for group, title in GROUPS.items():
        st.html(subhead(title, rb))
        for kind, info in KINDS.items():
            if info.group != group:
                continue
            st.button(info.name, key=f"dr_b_kind_{kind}", on_click=session.start, args=(kind,), width="stretch")
            st.html(kind_card_html(kind, progress[kind], rb))
    with st.expander("点数の早見表", key="dr_x_table"):
        st.html(score_table_html(rb.fork()))
    with st.expander("ドリルのしくみ", key="dr_x_about"):
        inner = rb.fork()
        steps = " → ".join(span_text(seconds) for seconds in INTERVALS)
        lines = [
            f"間違えた問題は、間隔をあけて、もう一度出す。正解するたびに、次に出すまでの間隔が延びる（{steps}）。間違えると、最初の間隔に戻る。",
            "はじめての問題に正解したら、3 日後から始める（もう知っている問題を、何度も出さないため）。",
            "読み・翻数・成立/不成立・点数早見は、問題の数が決まっている。全部の問題を、覚えるまで追いかける。",
            "役の判定・あがれる？・待ち・符・点数計算・何切るは、その場で問題を作る。間違えた問題だけを覚えておいて、あとでもう一度出す。",
            "正解は、すべて点数計算・向聴数・牌効率の計算で決めている。ルールは、このアプリの初期設定（雀魂の段位戦と同じ）。",
            "危険牌を見分けるドリルは、相手のいる対局（Phase 3）と一緒に入れる予定。",
        ]
        st.html('<ul class="mj-rules">' + "".join(f"<li>{inner.html(line)}</li>" for line in lines) + "</ul>")
    st.page_link("views/records.py", label="記録と保存（ドリルの記録も、ファイルに保存できる）", icon=":material/save:")


# ---------------------------------------------------------------- 画面：問題


def _detail(kind: str, explanation, rb: Rubifier) -> None:
    """くわしい解説（点数計算ラボと同じ内訳）"""
    if kind not in DETAIL_KEYS or explanation is None or explanation.status is Status.NOT_WINNING:
        return
    sections = detail_sections(explanation, rb.fork(), detail=DETAIL_NORMAL, keys=DETAIL_KEYS[kind])
    if not sections:
        return
    with st.expander("くわしい解説（計算の内訳）", key=f"dr_x_detail_{session.rev}"):
        for section in sections:
            st.html(section.heading_html + section.html)


def _options(q, rb: Rubifier) -> list[Option]:
    """選択肢を、部品に渡す形にする（文字にはルビ、待ちの問題には牌の絵）"""
    options = []
    for choice in q.choices:
        image = alt = None
        if choice.tile is not None:
            tile = choice.tile * 4 + 1          # 赤でないほうの牌
            image, alt = tile_image_url(tile), tile_label(tile)
        options.append(Option(choice.key, rb.parts(choice.label), image, alt or ""))
    return options


def _quiz(kind: str, rb: Rubifier) -> None:
    rev = session.rev
    now = _now()
    q = session.question
    kind = session.kind or kind         # いまは無い問題を飛ばしたときに、種類が変わることがある（復習）
    if q is None:           # 決まった数の問題を、すべて出し終えた
        deck = session.deck(kind)
        st.html(header_html(kind, DONE, session.count, session.right, rb) + done_html(kind, progress_of(kind, deck, now), now, rb))
        with st.container(horizontal=True):
            if early_item(kind, deck) is not None:
                st.button("先取りで復習する", type="primary", on_click=session.early, width="stretch")
            st.button("種類の一覧へ", on_click=session.leave, width="stretch")
        return
    state = session.result
    answered = state is not None
    # 読みの問題では、答える前に読みが見えてしまわないように、ルビを振らない
    hidden = kind == "reading" and not answered
    qrb = Rubifier(enabled=False) if hidden else rb

    st.html(header_html(kind, session.reason, session.count, session.right, qrb) + prompt_html(q, qrb, asked=hidden))
    explanation = None
    if q.ctx is not None:
        explanation = explain(q.ctx, q.rules)
        html = chips_html(situation_chips(explanation), qrb) + hand_html(explanation, qrb)
        if q.river is not None:
            html += river_html(q.river, qrb, caption="自分の河（捨て牌）", aka=q.rules.aka_dora)
        st.html(html)
    if q.hand:
        st.html(f'<div class="mj-hand">{tiles_fit_html(q.hand, aka=True)}</div>')

    analysis = None
    if q.position is not None:
        position = q.position
        analysis = analyze(position)
        marks = {}
        if answered:
            marks = {c.tile: (MARK_PICK if c.is_pick else MARK_EQUAL) for c in analysis.best}
        st.html(position_status_html(position, qrb))
        tile_hand(
            list(position.tiles), key="dr_hand",
            rev=rev * 2 + (1 if answered else 0),       # 答えたら番号を進める（手牌の部品は、番号が変わると「応答した」と分かる）
            on_pick=_on_discard, drawn_id=position.drawn, aka=position.rules.aka_dora,
            enabled=not answered, marks=marks, confirm_label="この牌を切る", prompt="切る牌をタップして選ぶ",
        )
        if answered:
            st.html(f'<div class="mj-sub">{qrb.html(f"{MARK_PICK[0]} いちばん速い打牌　{MARK_EQUAL[0]} 同じ速さの打牌")}</div>')
        st.html(river_html(q.river or (), qrb, caption="河（切った牌）", aka=position.rules.aka_dora))
        if answered:
            correct, verdict, _ = grade_discard(q, state["tile"])
            st.html(verdict_banner_html(correct, qrb, text=verdict.label))
            reasons = "".join(f"<li>{qrb.html(reason)}</li>" for reason in verdict.reasons)
            st.html(f'<div class="mj-review {"good" if correct else "bad"}"><div>{qrb.html(verdict.text)}</div>{"<ul>" + reasons + "</ul>" if reasons else ""}</div>')
            st.html(answer_lines_html(q, qrb))
    elif not answered:
        choice_buttons(
            _options(q, qrb), key="dr_choices", rev=rev, on_pick=_on_choice, multi=q.multi, layout=LAYOUTS.get(kind, "list"),
            prompt="あてはまるものを、すべて選ぶ",
        )
    else:
        graded = grade(q, state["picked"])
        st.html(verdict_banner_html(graded.correct, qrb) + choices_review_html(q, graded, qrb) + answer_lines_html(q, qrb))

    if answered:
        note = srs_note_html(kind, session.card, state["correct"], session.answered_at or now, qrb)
        if note:            # その場で作った問題に正解したときは、何も出さない（覚えておかないので）
            st.html(note)
        with st.container(horizontal=True):
            st.button("次の問題", type="primary", on_click=session.next, width="stretch", key=f"dr_b_next_{rev}")
            st.button("種類の一覧へ", on_click=session.leave, width="stretch", key=f"dr_b_leave_{rev}")
        if analysis is not None:
            with st.expander("受け入れ表（切る牌と、手が進む牌）", expanded=not state["correct"], key=f"dr_x_table_{rev}"):
                inner = qrb.fork()
                st.html(shanten_html(analysis, inner) + candidates_html(analysis, inner, chosen_kind=state["tile"] // 4))
        _detail(kind, explanation, qrb)
        if q.page:
            name = yaku_page_map()[q.page].name
            st.page_link("views/yaku_book.py", label=f"役図鑑で「{name}」を見る", icon=":material/menu_book:", query_params={"y": q.page})
        if q.term and glossary().find(q.term) is not None:
            st.page_link("views/glossary.py", label=f"用語辞典で「{q.term}」を見る", icon=":material/dictionary:", query_params={"t": q.term})
    else:
        st.button("やめて、種類の一覧へ", on_click=session.leave, key=f"dr_b_quit_{rev}")


# ---------------------------------------------------------------- 画面

st.title("ドリル")

if not store.ready:
    # 開いた直後: ブラウザに残っている記録が届くのを待つ（ふつうは一瞬）
    store.mount()
    st.info("ブラウザに保存された記録を確認しています…")
    st.button("保存を使わずに始める", on_click=store.skip)
    st.stop()

wanted = st.query_params.get("k")
if wanted is not None:
    del st.query_params["k"]                 # 1 回だけ使う
    if wanted in KINDS:
        session.start(wanted)

rb = Rubifier()
current = session.kind
if current is not None:
    _quiz(current, rb)
else:
    _menu(rb)

if not store.available:
    st.caption("この端末・ブラウザでは保存を使っていません（ページを閉じると、ドリルの記録は残りません）")
scroll_top(session.rev, key="dr_scroll")
store.mount()

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
from engine.curriculum import step_of
from engine.drills import DONE, GROUPS, KINDS, LEARNED_BOX, early_item, grade, grade_danger, grade_discard, progress_of
from engine.scoring.explain import Status, explain
from engine.srs import INTERVALS
from ui.components.browser_store import BrowserStore
from ui.components.choices import Option, choice_buttons
from ui.components.scroll_top import scroll_top
from ui.components.tile_hand import Pick, tile_hand
from ui.curriculum_view import test_result_html
from ui.drill_session import DrillSession
from ui.drill_view import (
    answer_lines_html,
    choices_review_html,
    danger_legend_html,
    danger_setup_html,
    done_html,
    header_html,
    kind_card_html,
    position_status_html,
    prompt_html,
    river_html,
    srs_note_html,
    verdict_banner_html,
)
from ui.game_view import betaori_html, danger_table_html
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
#: 答えたあとのボタンの入れ物の鍵（画面では st-key-… という印になる）
ACTIONS_KEY = "dr_actions"
#: 答えた直後に、見えるところまで画面を動かす部分：正解・不正解の帯と、そのすぐ下の「次の問題」
REVEAL = (".mj-verdict", f".st-key-{ACTIONS_KEY}")


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
    done = session.test_done
    if done is not None:
        st.html(test_result_html(done, rb))
        with st.container(horizontal=True, vertical_alignment="center"):
            st.page_link("views/curriculum.py", label="カリキュラムへ", icon=":material/school:")
            st.button("閉じる", on_click=session.clear_test_done, key="dr_b_test_close")
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
        learned = span_text(INTERVALS[LEARNED_BOX])
        lines = [
            f"間違えた問題は、間隔をあけて、もう一度出す。正解するたびに、次に出すまでの間隔が延びる（{steps}）。間違えると、最初の間隔に戻る。",
            "はじめての問題に正解したら、3 日後から始める（もう知っている問題を、何度も出さないため）。",
            "読み・翻数・成立/不成立・点数早見は、問題の数が決まっている。全部の問題を、覚えるまで追いかける。",
            f"「定着」は、正解を重ねて、次に出すまでの間隔が {learned}以上になった問題の数（問題の数が決まっている種類だけ）。",
            "役の判定・あがれる？・待ち・符・点数計算・何切る・危険牌は、その場で問題を作る。間違えた問題だけを覚えておいて、あとでもう一度出す。",
            "正解は、すべて点数計算・向聴数・牌効率・守備（危険度）の計算で決めている。ルールは、このアプリの初期設定（雀魂の段位戦と同じ）。",
            "危険牌の局面は、CPU 4 人に打たせて、誰かのリーチが成立したところで作る。危険度は、まだ当たりうる待ちの形から決めた目安（確率ではない）。",
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


def _next_label() -> str:
    """「次の問題」のボタンの文字（確認テストの最後の問題では「結果を見る」）"""
    test = session.test
    return "結果を見る" if test is not None and test["index"] + 1 >= len(test["items"]) else "次の問題"


#: 確認テストを途中でやめたときの知らせ（カリキュラムのページに出す）
QUIT_NOTE = "確認テストをやめました（途中までの答えは、合否に数えていません。また、いつでも受けられます）。"


def _quit_test() -> None:
    """確認テストをやめて、カリキュラムのページへ戻る（ページの移動は、コールバックの中ではできないので、印だけ付ける）"""
    session.leave()
    ss["cu_message"] = QUIT_NOTE
    ss["dr_to_curriculum"] = True


def _test_header() -> tuple[int, int, str] | None:
    test = session.test
    if test is None:
        return None
    step = step_of(test["step"])
    return (test["index"] + 1, len(test["items"]), step.title if step is not None else "")


def _actions(rev: int) -> None:
    """答えたあとのボタン。正解・不正解の帯のすぐ下に置く（解説を読まずに次へ進みたいとき、画面を送らなくてよいように）"""
    with st.container(horizontal=True, key=ACTIONS_KEY):
        st.button(_next_label(), type="primary", on_click=session.next, width="stretch", key=f"dr_b_next_{rev}")
        if session.test is None:
            st.button("種類の一覧へ", on_click=session.leave, width="stretch", key=f"dr_b_leave_{rev}")


def _quiz(kind: str, rb: Rubifier) -> bool:
    """問題の画面。答えたあとの画面なら True を返す（正解・不正解の帯が見えるところまで、画面を動かすため）。

    答えたあとは、上から 問題 → 手牌など → 正解・不正解の帯 → 「次の問題」 → 解説 の順に出す。
    解説の下にも「次の問題」を置く（解説を読み終えた位置から、そのまま進めるように）。
    """
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
        return False
    state = session.result
    answered = state is not None
    # 読みの問題では、答える前に読みが見えてしまわないように、ルビを振らない
    hidden = kind == "reading" and not answered
    qrb = Rubifier(enabled=False) if hidden else rb

    head = header_html(kind, session.reason, session.count, session.right, qrb, test=_test_header()) + prompt_html(q, qrb, asked=hidden)
    if q.danger is not None and q.position is not None:
        head += danger_setup_html(q, qrb)        # 河は問題文と同じ塊に入れる（部品のあいだの余白を減らし、手牌を最初の画面に入れる）
    st.html(head)
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
    review = ""             # 答えたあと、ボタンの下に出す解説（画面に出る順に作る。用語のルビを、最初に出てくるところに振るため）
    if q.danger is not None and q.position is not None:
        position = q.position
        best = [r.kind for r in q.danger.table if r.level == q.danger.best_level]
        marks = {t: MARK_PICK for t in position.tiles if t // 4 in best} if answered else {}
        tile_hand(
            list(position.tiles), key="dr_hand",
            rev=rev * 2 + (1 if answered else 0),
            on_pick=_on_discard, drawn_id=position.drawn, aka=position.rules.aka_dora,
            enabled=not answered, marks=marks, confirm_label="この牌を切る", prompt="いちばん安全な牌を選ぶ",
            chosen_id=state["tile"] if answered else None, chosen_label="切った牌",
        )
        if not answered:
            st.html(danger_legend_html(q, qrb))
        else:
            correct, row = grade_danger(q, state["tile"])
            label = "いちばん安全な牌" if correct else f"もっと安全な牌があった（切った牌は{row.name}）"
            legend = f"{MARK_PICK[0]} いちばん安全な牌　青い枠：切った牌"
            st.html(f'<div class="mj-sub">{qrb.html(legend)}</div>' + verdict_banner_html(correct, qrb, text=label))
            _actions(rev)
            review = answer_lines_html(q, qrb) + danger_legend_html(q, qrb)
            review += danger_table_html(
                q.danger.table, position.tiles, qrb, detail=True, pick_kinds=best, chosen_kind=state["tile"] // 4,
                aka=position.rules.aka_dora,
            )
            review += f'<div class="mj-subhead">{qrb.html("ベタオリの手順")}</div>' + betaori_html(qrb)
    elif q.position is not None:
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
            chosen_id=state["tile"] if answered else None, chosen_label="切った牌",
        )
        if not answered:
            st.html(river_html(q.river or (), qrb, caption="河（切った牌）", aka=position.rules.aka_dora))
        else:
            correct, verdict, _ = grade_discard(q, state["tile"])
            legend = f"{MARK_PICK[0]} いちばん速い打牌　{MARK_EQUAL[0]} 同じ速さの打牌　青い枠：切った牌"
            st.html(f'<div class="mj-sub">{qrb.html(legend)}</div>' + verdict_banner_html(correct, qrb, text=verdict.label))
            _actions(rev)
            reasons = "".join(f"<li>{qrb.html(reason)}</li>" for reason in verdict.reasons)
            review = f'<div class="mj-review {"good" if correct else "bad"}"><div>{qrb.html(verdict.text)}</div>{"<ul>" + reasons + "</ul>" if reasons else ""}</div>'
            review += answer_lines_html(q, qrb)
            review += river_html(q.river or (), qrb, caption="河（切った牌）", aka=position.rules.aka_dora)      # 河は、解説の下へ
    elif not answered:
        choice_buttons(
            _options(q, qrb), key="dr_choices", rev=rev, on_pick=_on_choice, multi=q.multi, layout=LAYOUTS.get(kind, "list"),
            prompt="あてはまるものを、すべて選ぶ",
        )
    else:
        graded = grade(q, state["picked"])
        st.html(verdict_banner_html(graded.correct, qrb))
        _actions(rev)
        review = choices_review_html(q, graded, qrb) + answer_lines_html(q, qrb)

    if not answered:
        if session.test is not None:
            st.button("確認テストをやめる", on_click=_quit_test, key=f"dr_b_quit_{rev}")
        else:
            st.button("やめて、種類の一覧へ", on_click=session.leave, key=f"dr_b_quit_{rev}")
        return False
    # その場で作った問題に正解したときは、いつ出すかの説明を出さない（覚えておかないので）
    st.html(review + srs_note_html(kind, session.card, state["correct"], session.answered_at or now, qrb))
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
    st.button(_next_label(), type="primary", on_click=session.next, width="stretch", key=f"dr_b_next_end_{rev}")
    return True


# ---------------------------------------------------------------- 画面

st.title("ドリル")

if not store.ready:
    # 開いた直後: ブラウザに残っている記録が届くのを待つ（ふつうは一瞬）
    store.mount()
    st.info("ブラウザに保存された記録を確認しています…")
    st.button("保存を使わずに始める", on_click=store.skip)
    st.stop()

if ss.pop("dr_to_curriculum", False):
    st.switch_page("views/curriculum.py")

wanted = st.query_params.get("k")
if wanted is not None:
    del st.query_params["k"]                 # 1 回だけ使う
    if wanted in KINDS:
        if session.test is not None:
            # 確認テストの途中で、ほかの種類を選んできた（カリキュラムの「ドリル：…」など）。テストは、黙って消さずに知らせる
            st.toast(QUIT_NOTE, icon=":material/info:", duration="long")
        session.start(wanted)

rb = Rubifier()
current = session.kind
answered = False
if current is not None:
    answered = _quiz(current, rb)
else:
    _menu(rb)

if not store.available:
    st.caption("この端末・ブラウザでは保存を使っていません（ページを閉じると、ドリルの記録は残りません）")
# 新しい問題（と種類の一覧）は、画面のいちばん上から。答えた直後は、正解・不正解の帯と「次の問題」が見えるところまで
scroll_top(session.rev * 2 + (1 if answered else 0), key="dr_scroll", reveal=REVEAL if answered else ())
store.mount()

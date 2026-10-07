"""一人練習。

相手なしで、配牌からツモと打牌をくり返す。牌効率（どれを切ると聴牌に近づくか）に集中するためのページ。
ツキ補正の強さを選べる。あがると、点数計算ラボと同じ解説が出る。

役指定練習：狙う役を 1 つ決めると、配牌とツモがその役に近づき、コーチも「その役に近い切り方」を勧める。
役図鑑の「この役を実戦で練習する」から来たときは、URL の target に役の鍵が入っている。
"""
from __future__ import annotations

import streamlit as st

from engine import practice
from engine.analysis.target import SHAPELESS_KEYS, TARGET_KEYS
from engine.coach import analyze
from engine.content import yaku_page_map
from engine.luck import PRESETS
from engine.practice import Outcome
from engine.records import summarize, target_stats
from engine.scoring.explain import explain
from engine.target_coach import target_result
from ui.components.browser_store import BrowserStore
from ui.components.choices import Option, choice_buttons
from ui.components.tile_hand import Pick, tile_hand
from ui.practice_session import MAX_SEED, PracticeSession, parse_seed, preset_name
from ui.practice_view import (
    HINT_AFTER,
    HINT_BEFORE,
    HINT_LABELS,
    HINT_OFF,
    LEVEL_FULL,
    LEVEL_LABELS,
    LEVEL_MIN,
    LEVEL_NORMAL,
    MARK_EQUAL,
    MARK_PICK,
    SHAPELESS_TIPS,
    advice_headline_html,
    candidates_html,
    chance_html,
    draw_note_html,
    exhausted_html,
    hand_summary_html,
    help_html,
    layout_html,
    luck_guide_html,
    luck_now_html,
    luck_text,
    note_html,
    plain_headline_html,
    plan_html,
    review_list_html,
    riichi_draws_html,
    river_html,
    shanten_html,
    stamps_html,
    stats_html,
    status_html,
    subhead_html,
    target_candidates_html,
    target_guide_html,
    target_headline_html,
    target_name,
    target_result_html,
    target_stats_html,
    target_verdict_headline_html,
    target_verdict_html,
    verdict_headline_html,
    verdict_html,
    waits_html,
)
from ui.ruby import Rubifier
from ui.win_view import DETAIL_BRIEF, DETAIL_FULL, DETAIL_NORMAL, detail_sections, summary_section

ss = st.session_state
store = BrowserStore()
session = PracticeSession(ss, store)

HINTS = {label: value for value, label in HINT_LABELS.items()}
LEVELS = {label: value for value, label in LEVEL_LABELS.items()}
PRESET_LEVELS = dict(PRESETS)
DETAIL_BY_LEVEL = {LEVEL_MIN: DETAIL_BRIEF, LEVEL_NORMAL: DETAIL_NORMAL, LEVEL_FULL: DETAIL_FULL}
SLIDER_STEP = 5
SEED_HINT = f"番号は、0〜{MAX_SEED} の数字で入れてください。"
# 狙う役は、まとまりを選んでから役を選ぶ（選択肢が多いと、スマホで選びにくい）
NO_TARGET = "なし"
PAGES = yaku_page_map()
TARGET_GROUPS: dict[str, list[str]] = {
    "1 翻": [key for key in TARGET_KEYS if PAGES[key].group == "han1"],
    "2 翻": [key for key in TARGET_KEYS if PAGES[key].group == "han2"],
    "3 翻・6 翻": [key for key in TARGET_KEYS if PAGES[key].group in ("han3", "han6")],
    "役満": [key for key in TARGET_KEYS if PAGES[key].group == "yakuman"],
}


def _group_of(target: str | None) -> str:
    return next((name for name, keys in TARGET_GROUPS.items() if target in keys), NO_TARGET)


# ---------------------------------------------------------------- 設定の入力欄
#
# 入力欄（ウィジェット）の値は、そのページを表示していないあいだに消える。そこで、設定は session.settings に
# 持っておき、入力欄の値が無くなっていたら、そこから入れ直す。


def _sync_widgets() -> None:
    """入力欄を描く前に、その値を整える"""
    settings = session.settings
    ss.setdefault("pr_w_deal", round(settings["deal"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("pr_w_draw", round(settings["draw"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("pr_w_tenpai", settings["tenpai_deal"])
    ss.setdefault("pr_w_mark", settings["mark"])
    if ss.get("pr_w_hint") not in HINTS:
        ss["pr_w_hint"] = HINT_LABELS[settings["hint"]]
    if ss.get("pr_w_level") not in LEVELS:
        ss["pr_w_level"] = LEVEL_LABELS[settings["level"]]
    # 段階の選択は、いつも 2 つのスライダーの値から決める（選択中の段階をもう一度押して外しても、表示が消えない）
    ss["pr_w_preset"] = preset_name(ss["pr_w_deal"], ss["pr_w_draw"])
    # 狙う役のまとまり（1 翻・2 翻…）。役が決まっていれば、その役のまとまり
    if settings["target"] is not None or ss.get("pr_tgroup") not in (NO_TARGET, *TARGET_GROUPS):
        ss["pr_tgroup"] = _group_of(settings["target"])


def _read_widgets() -> None:
    """入力欄の値を設定に写す（入力欄を描く前でも、値は session_state から読める）"""
    session.update_settings(
        {
            "deal": ss["pr_w_deal"],
            "draw": ss["pr_w_draw"],
            "tenpai_deal": ss["pr_w_tenpai"],
            "mark": ss["pr_w_mark"],
            "hint": HINTS[ss["pr_w_hint"]],
            "level": LEVELS[ss["pr_w_level"]],
        }
    )


def _on_preset() -> None:
    level = PRESET_LEVELS.get(ss.get("pr_w_preset"))
    if level is not None:
        ss["pr_w_deal"] = ss["pr_w_draw"] = level


def _set_target(target: str | None) -> None:
    """狙う役を変える（次に始める局から使う）"""
    session.update_settings({"target": target})
    ss["pr_tgroup"] = _group_of(target)


def _on_target_group(keys: list[str]) -> None:
    """狙う役のまとまりを選んだ。「なし」なら、役指定をやめる。ほかは、役を選ぶまで、いまの設定のまま"""
    if keys[0] == NO_TARGET:
        _set_target(None)
    else:
        session.update_settings({"target": None})
        ss["pr_tgroup"] = keys[0]


def _on_target(keys: list[str]) -> None:
    _set_target(keys[0])


# ---------------------------------------------------------------- 操作


def _apply_settings() -> None:
    """ボタンを押した時点の入力欄の値を、設定に反映する（コールバックは、画面を描く前に呼ばれる）"""
    if session.started and "pr_w_deal" in ss:
        _sync_widgets()
        _read_widgets()


def _on_pick(pick: Pick) -> None:
    _apply_settings()
    session.pick(pick.tile_id, riichi=pick.riichi)


def _on_tsumo() -> None:
    session.tsumo()


def _next_hand() -> None:
    _apply_settings()
    session.begin()


def _again() -> None:
    session.again()


def _start_numbered() -> None:
    seed = parse_seed(ss.get("pr_w_seed"))
    if seed is None:
        ss["pr_seed_error"] = True      # 次に画面を描くとき、1 回だけ案内を出す
        return
    _apply_settings()
    session.begin(seed)


def _stop_target() -> None:
    _apply_settings()
    _set_target(None)
    session.begin()


def _clear_history() -> None:
    session.clear_history()


# ---------------------------------------------------------------- 画面

generation = ss.get("mj_generation", 0)      # いま動いているコードの世代（app.py が入れる）

st.title("一人練習")

if not session.started:
    if not store.ready:
        # 開いた直後: ブラウザに残っている記録が届くのを待つ（ふつうは一瞬）
        store.mount()
        st.info("ブラウザに保存された記録を確認しています…")
        st.button("保存を使わずに始める", on_click=store.skip)
        st.stop()
    session.start(generation)
    if store.reconnected:
        # ページを開いたまま、通信が長く切れていた（スマホで別のアプリを見ていた、など）。切れる直前の操作は届いていない
        st.toast("通信が切れていたので、続きから再開しました。もう一度操作してください。", icon=":material/sync:", duration="long")
session.sync_code(generation)

# 役図鑑の「この役を実戦で練習する」から来た：その役を狙う局を始める（同じ役を狙う局の途中なら、そのまま続ける）
wanted = st.query_params.get("target")
if wanted is not None:
    del st.query_params["target"]            # 1 回だけ使う（画面を描き直すたびに、局を始め直さない）
    if wanted in TARGET_KEYS:
        _set_target(wanted)
        if session.state.config.target != wanted or session.state.finished:
            session.begin()

_sync_widgets()
_read_widgets()

state = session.state
settings = session.settings
hint, level = settings["hint"], settings["level"]
aka = state.config.rules.aka_dora
target = state.config.target
aiming = target is not None and target not in SHAPELESS_KEYS       # 手の形で決まる役を狙っているか
# 用語のルビは、この画面で最初に出てきたときだけ振る。文章は画面の上から順に作る。
# 折りたたみの中身は rb.fork() に通す（閉じていると読まれないので、そこで振ったルビを「もう出てきた」と数えない）
rb = Rubifier()

st.html(status_html(state, rb))

if not state.finished:
    # ---- 打っている途中
    last = session.last_decision
    analysis = analyze(practice.position_of(state)) if hint == HINT_BEFORE else None
    advice = practice.target_advice_of(state) if analysis is not None and aiming else None

    if analysis is not None:
        session.note_hint_shown()          # 打つ前のヒントを出した局は、成績で「ヒントあり」に分ける
        can_riichi = bool(state.riichi_discards)
        if advice is not None:
            win = None
            if state.can_tsumo:            # いまあがると、狙った役が付くか
                win = target_result(explain(practice.apply(state, practice.TSUMO).result.win, state.config.rules), target)
            st.html(target_headline_html(advice, analysis, rb, can_riichi=can_riichi, win=win))
        else:
            st.html(advice_headline_html(analysis, rb, can_riichi=can_riichi))
    elif hint == HINT_AFTER:
        if last is not None and last.target is not None:
            st.html(target_verdict_headline_html(last, rb, aka=aka))
        elif last is not None:
            st.html(verdict_headline_html(last, rb, aka=aka))
        else:
            st.html(plain_headline_html("自分で考えて切ってください。切ったあとに、答え合わせを表示します。", rb))
    else:
        st.html(plain_headline_html("コーチはオフです。下の「設定」で、ヒントを出すように変えられます。", rb))

    marks = {}
    if advice is not None and advice.pick is not None and not state.can_tsumo:
        marks = {c.tile: (MARK_PICK if c.is_pick else MARK_EQUAL) for c in advice.best}
    elif analysis is not None and not analysis.can_win and (not analysis.last_discard or analysis.can_end_tenpai):
        marks = {c.tile: (MARK_PICK if c.is_pick else MARK_EQUAL) for c in analysis.best}
    draw = state.last_draw
    lucky_draw = settings["mark"] and draw is not None and draw.luck.swapped
    tile_hand(
        [*state.hand, state.drawn],
        key="pr_hand",
        rev=session.rev,
        on_pick=_on_pick,
        drawn_id=state.drawn,
        aka=aka,
        marks=marks,
        riichi_ids=() if state.can_tsumo else state.riichi_discards,     # あがれるときは、リーチを出さない（押し間違いを防ぐ）
        drawn_label="ツモ ★" if lucky_draw else "ツモ",
        two_rows=True,                       # リーチのボタンが出る巡目でも、確定ボタンの位置を変えない
        scroll_top=session.take_scroll(),    # 新しい局は、画面のいちばん上から
    )
    if state.can_tsumo:
        st.button("ツモ（あがる）", type="primary", on_click=_on_tsumo, width="stretch")
    if lucky_draw:
        st.html(draw_note_html(draw, rb, aka=aka))
    st.html(river_html(state, rb))
    if target in SHAPELESS_TIPS and hint != HINT_OFF:
        st.html(note_html(f"{target_name(target)}を狙う局：{SHAPELESS_TIPS[target]}", rb))
    if aiming and state.config.luck.is_off:
        # 補正なしだと、配牌もツモも役に近づかない（ふつうの麻雀と同じ難しさ）。役指定練習のつもりで開いた人が、とまどわないように
        st.html(note_html(f"ツキ補正が「なし」なので、配牌もツモも、ふつうの麻雀と同じです。{target_name(target)}を作りやすくするには、下の「設定」でツキ補正を上げてください。", rb))

    if hint != HINT_OFF and last is not None:
        if last.target is not None:
            st.html(target_verdict_html(last, rb, level=level, aka=aka))
        else:
            st.html(verdict_html(last, rb, level=level, aka=aka))
        if hint == HINT_AFTER and level >= LEVEL_NORMAL:
            # 鍵に表示の量を入れてある：「詳しい」に変えたら開いた状態で、「ふつう」に戻したら閉じた状態で出し直す
            if last.target_advice is not None and last.target_advice.pick is not None:
                with st.expander("さっきの局面の、役に近い切り方（答え合わせ）", expanded=level == LEVEL_FULL, key=f"pr_x_tprevious_{level}"):
                    inner = rb.fork()
                    st.html(target_candidates_html(last.target_advice, inner, aka=aka, chosen_kind=last.target.chosen.kind if last.target else None))
            with st.expander("さっきの局面の受け入れ表（答え合わせ）", expanded=level == LEVEL_FULL and last.target is None, key=f"pr_x_previous_{level}"):
                inner = rb.fork()
                st.html(shanten_html(last.analysis, inner) + candidates_html(last.analysis, inner, chosen_kind=last.verdict.chosen.kind))

    if advice is not None and level >= LEVEL_NORMAL:
        name = advice.name
        with st.expander(f"めざす形（{name}）", expanded=True, key="pr_x_plan"):
            st.html(plan_html(advice.plan, rb.fork()))
        if advice.pick is not None and not state.can_tsumo:
            with st.expander(f"{name}に近い切り方の表", expanded=level == LEVEL_FULL, key=f"pr_x_ttable_{level}"):
                st.html(target_candidates_html(advice, rb.fork(), aka=aka))

    if analysis is not None and not analysis.can_win and level >= LEVEL_NORMAL:
        if analysis.waits and not analysis.last_discard and advice is None:
            with st.expander("聴牌したときの待ちと点数", expanded=True, key="pr_x_waits"):
                st.html(waits_html(analysis, rb.fork()))
        if not analysis.last_discard:        # 最後の打牌では、もうツモが無いので、受け入れは関係ない
            title = "受け入れ表（速さだけで見たとき）" if advice is not None else "受け入れ表（切る牌と、手が進む牌）"
            with st.expander(title, expanded=level == LEVEL_FULL and advice is None, key=f"pr_x_table_{level}"):
                inner = rb.fork()
                st.html(shanten_html(analysis, inner) + candidates_html(analysis, inner) + chance_html(analysis, inner, luck_draw=state.config.luck.draw))
        with st.expander("手の分け方（分解図）", expanded=level == LEVEL_FULL and advice is None, key=f"pr_x_layout_{level}"):
            st.html(layout_html(analysis, rb.fork(), level=level))
else:
    # ---- 局が終わったあと
    result = state.result
    explanation = None
    if result.outcome == Outcome.TSUMO and result.win is not None:
        explanation = explain(result.win, state.config.rules)
        banner = f'<div class="mj-headline mj-headline-short good"><b class="mj-stage">ツモあがり</b>　{result.turn} {rb.html("巡目")}</div>'
        if target is not None:
            banner += target_result_html(target_result(explanation, target), rb)
        # ドラ表示牌は、上の札にもう出ている。手牌の下にもう一度出すのは、裏ドラがあるとき（リーチしてあがった局）だけ。
        # 「次の局へ」を、スマホの最初の画面に収めるため
        st.html(banner + summary_section(explanation, rb, indicators=bool(result.win.ura_indicators)).html)
    else:
        st.html(exhausted_html(state, rb))

    with st.container(horizontal=True):
        st.button("次の局へ", type="primary", on_click=_next_hand, width="stretch")
        st.button("同じ局をもう一度", on_click=_again, width="stretch")
    if target is not None:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.page_link("views/yaku_book.py", label=f"役図鑑で「{target_name(target)}」を見る", icon=":material/menu_book:", query_params={"y": target})
            st.button("役指定をやめる", on_click=_stop_target)

    # はじめて押されたスタンプの案内は、ボタンの下に出す（上に置くと、「次の局へ」が最初の画面から押し出される）
    st.html(stamps_html(session.fresh_stamps, rb) + hand_summary_html(state, session.decisions, rb, counted=session.counted, hinted=session.hinted))
    if state.in_riichi:
        st.html(riichi_draws_html(state, rb, mark=settings["mark"]))
    st.html(river_html(state, rb))
    with st.expander("この局の振り返り（切った牌の評価）", key="pr_x_review"):
        st.html(review_list_html(session.decisions, rb.fork(), aka=aka))

    if explanation is not None:
        for section in detail_sections(explanation, rb, detail=DETAIL_BY_LEVEL[level]):
            st.html(section.heading_html + section.html)
        # 解説を下まで読んだあと、上まで戻らなくても次へ進めるように
        st.button("次の局へ", key="pr_b_next_bottom", type="primary", on_click=_next_hand, width="stretch")

# ---- 設定（どの状態でも必ず描く。描かなかった入力欄の値は消えてしまうため）
with st.expander("設定（ツキ補正・役指定・コーチ）", key="pr_x_settings"):
    srb = rb.fork()
    st.html(subhead_html("ツキ補正", "配牌とツモの「引きの良さ」を上げます。変えた強さは、次の局から使います。", srb))
    st.segmented_control("強さ", list(PRESET_LEVELS), key="pr_w_preset", on_change=_on_preset, label_visibility="collapsed")
    st.slider("配牌の良さ", 0, 100, step=SLIDER_STEP, key="pr_w_deal")
    st.slider("ツモの良さ", 0, 100, step=SLIDER_STEP, key="pr_w_draw")
    st.html(luck_now_html(ss["pr_w_deal"], ss["pr_w_draw"], srb, target=settings["target"], tenpai_deal=ss["pr_w_tenpai"]))
    st.toggle("補正によるツモに印（★）を付ける", key="pr_w_mark")
    st.html(note_html("配牌の候補のうち、最初から聴牌しているものは、ふつう採用しません（あがりに近すぎて、練習にならないため）。", srb))
    st.toggle("聴牌している配牌も採用する", key="pr_w_tenpai")
    if session.luck_changed or session.target_changed:
        now = luck_text(state.config.luck.deal, state.config.luck.draw)
        aimed = f"・役指定：{target_name(target)}" if target else ""
        st.caption(f"いまの局は「{now}{aimed}」のまま。変更は次の局から反映されます。")
        st.button("この設定で新しい局を始める", on_click=_next_hand)
    st.html(subhead_html("強さの目安", "", srb) + luck_guide_html(srb))

    st.html(
        subhead_html(
            "役指定練習",
            "狙う役を 1 つ決めて打ちます。配牌がその役に近くなり、ツモの補正も、その役に近づく牌を引き寄せます（補正が「なし」なら、何も変えません）。"
            "コーチは、その役に近い切り方を勧めます。",
            srb,
        )
    )
    group = ss["pr_tgroup"]
    names = [NO_TARGET, *TARGET_GROUPS]
    # 番号は「いま選んである値」から作る（選ぶたびに変わるので、部品は「応答した」と分かる）
    choice_buttons(
        [Option(name, srb.parts(name)) for name in names], key="pr_c_tgroup", rev=names.index(group), on_pick=_on_target_group,
        layout="chips", selected=[group],
    )
    if group != NO_TARGET:
        keys = TARGET_GROUPS[group]
        chosen = settings["target"] if settings["target"] in keys else None
        choice_buttons(
            [Option(key, srb.parts(target_name(key))) for key in keys], key="pr_c_target",
            rev=names.index(group) * 100 + (keys.index(chosen) + 1 if chosen else 0), on_pick=_on_target,
            layout="chips", selected=[chosen] if chosen else [],
        )
        if chosen is not None:
            st.html(target_guide_html(chosen, srb))
        else:
            st.html(note_html("狙う役を 1 つ選んでください。", srb))
    st.html(note_html("対々和・嶺上開花など、鳴きやカン、相手の牌が要る役は、一人練習では狙えません（役図鑑の各ページに、理由を書いてあります）。", srb))

    st.html(subhead_html("コーチ", "", srb))
    st.segmented_control("ヒントのタイミング", list(HINTS), key="pr_w_hint", required=True)
    st.segmented_control("表示の量", list(LEVELS), key="pr_w_level", required=True)
    st.html(note_html("コーチのおすすめは、速さ（向聴数と受け入れ枚数）だけで決めています。役や打点との兼ね合いは、対局のコーチで扱う予定です。", srb))

    st.html(
        subhead_html(
            "局の番号",
            f"いまの局の番号は {state.config.seed}。同じ番号・同じ補正なら、いつでも同じ配牌から始まります。"
            "ツモの補正が 0 なら、ツモも同じ順に来ます（ツモの補正は手牌に合わせて牌を入れ替えるので、補正があると、切り方によってツモが変わります）。",
            srb,
        )
    )
    with st.form("pr_f_seed", border=False), st.container(horizontal=True, vertical_alignment="bottom"):
        # 数字のキーボードが出るように、電話番号用の入力欄を使う。フォームなので、入力してすぐボタンを押しても 1 回で届く。
        # 入力の確かめは、ボタンを押したあとに自分でする（Streamlit に任せると、案内が英語で、しかも隠れた場所に出る）
        st.text_input(
            "番号を指定して始める", key="pr_w_seed", type="phone", max_chars=len(str(MAX_SEED)), placeholder="例: 123456",
            icon="", autocomplete="off",
        )
        st.form_submit_button("この番号で始める", on_click=_start_numbered)
    if ss.pop("pr_seed_error", False):
        st.caption(f":red[{SEED_HINT}]")
    if not state.finished:
        st.button("この局をやめて、新しい局を始める", on_click=_next_hand)

with st.expander("成績", key="pr_x_stats"):
    inner = rb.fork()
    st.html(stats_html(summarize(session.history), inner) + target_stats_html(target_stats(session.history), inner))
    st.page_link("views/records.py", label="記録と保存（スタンプ・ファイルへの書き出し）", icon=":material/save:")
    if session.history:
        with st.popover("成績を消す"):
            st.caption("このブラウザに残っている成績を、すべて消します。元に戻せません。")
            st.button("消す", on_click=_clear_history)

with st.expander("このページの使い方", key="pr_x_help"):
    st.html(help_html(rb.fork()))

# ---- 下のほうの補足
notes = [f"局の番号 {state.config.seed}"]
if session.resumed:
    notes.append("この局は、ブラウザに残っていた記録から再開したものです")
if not store.available:
    notes.append("この端末・ブラウザでは保存を使っていません（ページを閉じると、局と成績は残りません）")
st.caption(" ／ ".join(notes))

# ブラウザ内保存の読み書きは、ここまでの変更をまとめてここで行う
store.mount()

"""点数計算ラボ。

あがった手の点数が、どういう計算で決まるのかを 1 歩ずつ確かめるページ。
例題・ランダム出題・自分で入力した手のどれでも、同じ解説（読み方 → 役 → ドラ → 符 → 点数 → 支払い → 申告）が出る。
"""
from __future__ import annotations

import re
import secrets

import streamlit as st

from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.examples import EXAMPLES, EXAMPLES_BY_KEY
from engine.scoring.explain import Status, explain
from engine.scoring.notation import MELD_WORDS, make_context, parse_meld, to_notation
from engine.scoring.random_hand import KINDS, random_win
from engine.tiles import EAST, NORTH, SOUTH, WEST, TileError, format_tiles, parse_tiles
from ui.ruby import Rubifier
from ui.win_view import (
    DETAIL_FULL,
    DETAIL_LABELS,
    explanation_sections,
    hand_html,
    situation_chips,
    tiles_fit_html,
)

ss = st.session_state

MODE_EXAMPLE, MODE_RANDOM, MODE_CUSTOM = "例題で学ぶ", "ランダムに出す", "自分で入力"
MODES = [MODE_EXAMPLE, MODE_RANDOM, MODE_CUSTOM]
SEATS = {"東（親）": EAST, "南": SOUTH, "西": WEST, "北": NORTH}
ROUNDS = {"東": EAST, "南": SOUTH, "西": WEST, "北": NORTH}
FLAGS = {
    "リーチ": "riichi",
    "ダブルリーチ": "double_riichi",
    "一発": "ippatsu",
    "嶺上開花": "rinshan",
    "槍槓": "chankan",
    "海底摸月": "haitei",
    "河底撈魚": "houtei",
    "天和": "tenhou",
    "地和": "chiihou",
}
PAIR_FU = {"4 符": 4, "2 符": 2}
DETAILS = {label: level for level, label in DETAIL_LABELS.items()}
EXAMPLE_KEYS = [e.key for e in EXAMPLES]
# 例題は章ごとに選ぶ。選択肢が 10 個以下の一覧は、スマホで開いてもキーボードが出ない
GROUPS = {e.key[0]: e.group for e in EXAMPLES}

# 画面の入力欄（ウィジェット）の名前。ここに値を入れてから描くと、その内容で表示される
HAND_FIELDS = ("lab_hand", "lab_win", "lab_melds", "lab_dora", "lab_ura")
SITUATION_FIELDS = ("lab_how", "lab_seat", "lab_round", "lab_flags", "lab_honba", "lab_kyotaku")
RULE_FIELDS = ("lab_rule_kuitan", "lab_rule_aka", "lab_rule_kiriage", "lab_rule_pair", "lab_rule_double", "lab_rule_kazoe")


# ---------------------------------------------------------------- 入力欄 ⇔ 手の内容


def _label_of(mapping: dict[str, int], value: int) -> str:
    return next(label for label, v in mapping.items() if v == value)


def _load_spec(spec: dict) -> None:
    """手の内容（make_context に渡す形）を、入力欄に流し込む"""
    ss.lab_hand = spec["hand"]
    ss.lab_win = spec["win"]
    melds = [parse_meld(m) for m in spec.get("melds", [])]
    ss.lab_melds = "、".join(f"{MELD_WORDS[m.type]} {format_tiles(m.tiles)}" for m in melds)
    ss.lab_dora = spec.get("dora", "")
    ss.lab_ura = spec.get("ura", "")
    ss.lab_how = "ツモ" if spec.get("is_tsumo") else "ロン"
    ss.lab_seat = _label_of(SEATS, spec.get("seat_wind", EAST))
    ss.lab_round = _label_of(ROUNDS, spec.get("round_wind", EAST))
    flags = [label for label, name in FLAGS.items() if spec.get(name)]
    if "ダブルリーチ" in flags:
        flags.remove("リーチ")
    ss.lab_flags = flags
    ss.lab_honba = int(spec.get("honba", 0))
    ss.lab_kyotaku = int(spec.get("kyotaku", 0))


def _load_rules(rules: Rules) -> None:
    ss.lab_rule_kuitan = rules.kuitan
    ss.lab_rule_aka = rules.aka_dora
    ss.lab_rule_kiriage = rules.kiriage_mangan
    ss.lab_rule_pair = _label_of(PAIR_FU, rules.double_wind_pair_fu)
    ss.lab_rule_double = rules.double_yakuman
    ss.lab_rule_kazoe = rules.kazoe_yakuman


def _rules() -> Rules:
    return Rules(
        aka_dora=ss.lab_rule_aka,
        kuitan=ss.lab_rule_kuitan,
        kiriage_mangan=ss.lab_rule_kiriage,
        double_wind_pair_fu=PAIR_FU[ss.lab_rule_pair or "4 符"],
        double_yakuman=ss.lab_rule_double,
        kazoe_yakuman=ss.lab_rule_kazoe,
    )


def _meld_texts() -> list[str]:
    return [part.strip() for part in re.split(r"[,、，\n]", ss.lab_melds or "") if part.strip()]


def _current_spec() -> dict:
    flags = set(ss.lab_flags or [])
    spec: dict = {
        "hand": ss.lab_hand or "",
        "win": ss.lab_win or "",
        "melds": _meld_texts(),
        "dora": ss.lab_dora or "",
        "ura": ss.lab_ura or "",
        "is_tsumo": ss.lab_how == "ツモ",
        "seat_wind": SEATS[ss.lab_seat or "東（親）"],
        "round_wind": ROUNDS[ss.lab_round or "東"],
        "honba": int(ss.lab_honba or 0),
        "kyotaku": int(ss.lab_kyotaku or 0),
    }
    for label, name in FLAGS.items():
        if label in flags:
            spec[name] = True
    if spec.get("double_riichi"):
        spec["riichi"] = True
    return spec


def _signature() -> tuple:
    """いまの入力内容をひとまとめにしたもの（「読み込んだときから変えたか」を見るため）"""
    values = [ss.get(name) for name in (*HAND_FIELDS, *SITUATION_FIELDS, *RULE_FIELDS)]
    return tuple(tuple(v) if isinstance(v, list) else v for v in values)


def _mark_loaded() -> None:
    ss.lab_loaded = _signature()
    ss.lab_revealed = None


# ---------------------------------------------------------------- 手を選ぶ操作


def _show_example(key: str) -> None:
    example = EXAMPLES_BY_KEY[key]
    ss.lab_example = ss.lab_example_last = key
    ss.lab_group = key[0]
    _load_spec(example.spec)
    _load_rules(example.rules)
    _mark_loaded()
    st.query_params.from_dict({"ex": key})


def _on_example_change() -> None:
    _show_example(ss.lab_example)


def _on_group_change() -> None:
    _show_example(next(key for key in EXAMPLE_KEYS if key[0] == ss.lab_group))


def _step_example(step: int) -> None:
    index = (EXAMPLE_KEYS.index(ss.lab_example) + step) % len(EXAMPLE_KEYS)
    _show_example(EXAMPLE_KEYS[index])


def _show_random(seed: int | None = None) -> None:
    kind = ss.get("lab_kind") or ss.get("lab_kind_last") or "any"
    ss.lab_kind = ss.lab_kind_last = kind
    ss.lab_seed = secrets.randbelow(1_000_000) if seed is None else seed
    rules = _rules() if "lab_rule_aka" in ss else DEFAULT_RULES
    _load_spec(to_notation(random_win(ss.lab_seed, kind, rules)))
    _mark_loaded()
    st.query_params.from_dict({"kind": kind, "n": str(ss.lab_seed)})


def _on_mode_change() -> None:
    mode = ss.lab_mode
    if mode == MODE_EXAMPLE:
        _show_example(ss.get("lab_example_last") or EXAMPLE_KEYS[0])
    elif mode == MODE_RANDOM:
        _show_random()
    else:
        _mark_loaded()
        st.query_params.clear()


def _start() -> None:
    """このページを開いて最初の 1 回。URL に例題や手の番号があれば、それを出す"""
    _load_rules(DEFAULT_RULES)
    ss.lab_detail = DETAIL_LABELS[DETAIL_FULL]
    params = st.query_params
    kind = params.get("kind")
    number = params.get("n", "")
    if kind in KINDS and number.isdigit():
        ss.lab_mode = MODE_RANDOM
        ss.lab_kind = kind
        _show_random(int(number))
        return
    ss.lab_mode = MODE_EXAMPLE
    key = params.get("ex") or ss.get("lab_example_last")      # ほかのページから戻ったときは、前に見ていた例題から
    _show_example(key if key in EXAMPLES_BY_KEY else EXAMPLE_KEYS[0])


if "lab_hand" not in ss:
    _start()


# ---------------------------------------------------------------- 画面

st.title("点数計算ラボ")
rb = Rubifier()     # 用語のルビは、この画面で最初に出てきたときだけ振る

mode = st.segmented_control("手の選び方", MODES, key="lab_mode", on_change=_on_mode_change, label_visibility="collapsed") or MODE_EXAMPLE


def _hand_inputs() -> None:
    st.text_input("手牌（和了牌を除く。鳴いていなければ 13 枚）", key="lab_hand", placeholder="例: 123m456p789s23s44z")
    with st.container(horizontal=True):
        st.text_input("和了牌（1 枚）", key="lab_win", placeholder="例: 4s")
        st.text_input("ドラ表示牌", key="lab_dora", placeholder="例: 3m")
    st.text_input("副露（鳴いた面子と暗槓。「、」で区切る）", key="lab_melds", placeholder="例: ポン 555z、チー 678p")
    st.text_input("裏ドラ表示牌（リーチしたときだけ）", key="lab_ura", placeholder="例: 9s")


def _notation_help() -> None:
    sample = parse_tiles("123m456p789s1234567z0m0p0s")
    st.html(
        '<div class="mj-sub">数字のあとに種類の文字を付けます。<b>m</b> ＝ 萬子、<b>p</b> ＝ 筒子、<b>s</b> ＝ 索子、<b>z</b> ＝ 字牌。'
        "字牌は 1z 東・2z 南・3z 西・4z 北・5z 白・6z 發・7z 中。赤い 5 は 0（0m・0p・0s）と書きます。<br>"
        "例: <code>123m456p789s1234567z0m0p0s</code> は下の並びになります。</div>"
        + tiles_fit_html(sample, aka=True, max_px=26)
    )


if mode == MODE_EXAMPLE:
    st.selectbox(
        "章",
        list(GROUPS),
        format_func=lambda letter: f"{letter}  {GROUPS[letter]}",
        key="lab_group",
        on_change=_on_group_change,
        label_visibility="collapsed",
    )
    st.selectbox(
        "例題",
        [key for key in EXAMPLE_KEYS if key[0] == ss.lab_group],
        format_func=lambda key: EXAMPLES_BY_KEY[key].label,
        key="lab_example",
        on_change=_on_example_change,
        label_visibility="collapsed",
    )
    with st.container(horizontal=True):
        st.button("◀ 前の例題", on_click=_step_example, args=(-1,), width="stretch")
        st.button("次の例題 ▶", on_click=_step_example, args=(1,), type="primary", width="stretch")
elif mode == MODE_RANDOM:
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.selectbox("出題の種類", list(KINDS), format_func=KINDS.get, key="lab_kind", on_change=_show_random)
        st.button("次の手を出す", on_click=_show_random, type="primary")
    st.caption(f"手の番号 {ss.get('lab_seed', '—')}（同じ種類・同じ番号なら、いつでも同じ手が出ます）")
else:
    _hand_inputs()
    with st.expander("牌の書き方"):
        _notation_help()

# ---- 入力を読んで計算する（入力欄を描く前でも、値は session_state から読める）
signature = _signature()
spec = _current_spec()
rules = _rules()
problem = None
result = None
try:
    meld_count = len(spec["melds"])
    expected = 13 - 3 * meld_count
    hand_count = len(parse_tiles(spec["hand"]))
    if hand_count != expected:
        because = f"副露が {meld_count} 組なので 13 − 3 × {meld_count} ＝ {expected} 枚" if meld_count else "鳴いていなければ 13 枚"
        raise TileError(f"手牌（和了牌を除く）は {expected} 枚のはずですが、{hand_count} 枚あります（{because}）。")
    result = explain(make_context(**spec), rules)
except ValueError as error:      # 牌の書き方、枚数、状況の組み合わせの誤り
    problem = str(error)

quiz_hidden = bool(ss.get("lab_quiz")) and ss.get("lab_revealed") != signature
detail = DETAILS.get(ss.get("lab_detail"), DETAIL_FULL)

# ルビは「画面で最初に出てきたとき」に振るので、文章は画面の上から順に作る
example = EXAMPLES_BY_KEY[ss.lab_example] if mode == MODE_EXAMPLE else None
example_changed = signature != ss.get("lab_loaded")
lesson_html = ""
if example is not None and not example_changed and not quiz_hidden:
    lesson_html = f'<div class="mj-lesson"><b>{example.key} {rb.html(example.title)}</b><br>{rb.html(example.lesson)}</div>'
sections = explanation_sections(result, detail=detail, rb=rb) if result is not None and not quiz_hidden else []


def _reveal() -> None:
    ss.lab_revealed = signature


# ---- 例題の要点、まとめ（または問題）
if example is not None and example_changed:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"例題 {example.key} から条件を変えています。")
        st.button("例題の条件に戻す", on_click=_show_example, args=(example.key,))
elif lesson_html:
    st.html(lesson_html)

if problem is not None:
    st.error(problem)
elif quiz_hidden:
    chips = "".join(f'<span class="mj-chip">{rb.html(chip)}</span>' for chip in situation_chips(result))
    st.html(
        f'<div class="mj-card"><div class="mj-chips">{chips}</div><b>この手は何点？</b>'
        '<div class="mj-sub">役 → ドラ → 符 → 点数 の順に数えてから、答えを開いてください。</div></div>' + hand_html(result, rb)
    )
    st.button("答えと解説を見る", type="primary", on_click=_reveal, width="stretch")
else:
    st.html(sections[0].html)

# ---- 条件を変える（入力に誤りがあっても必ず描く。描かなかった入力欄の値は消えてしまうため）
with st.expander("状況を変えてみる（ツモ／ロン、親／子、リーチ など）"):
    st.caption("同じ手でも、状況で点数が変わります。切り替えて、計算がどう変わるかを見てください。")
    st.segmented_control("あがり方", ["ロン", "ツモ"], key="lab_how")
    st.segmented_control("自風（東なら親）", list(SEATS), key="lab_seat")
    st.segmented_control("場風", list(ROUNDS), key="lab_round")
    st.pills("付いた状況", list(FLAGS), selection_mode="multi", key="lab_flags")
    with st.container(horizontal=True):
        st.number_input("本場", min_value=0, max_value=20, step=1, key="lab_honba")
        st.number_input("供託のリーチ棒", min_value=0, max_value=10, step=1, key="lab_kyotaku")
    if mode != MODE_CUSTOM:
        st.divider()
        _hand_inputs()
        _notation_help()

with st.expander("ルール設定（流派で違うところ）"):
    st.caption("初期値は雀魂の段位戦と同じです。友人と打つときは、その場の決まりに合わせてください。")
    st.toggle("喰いタンあり（鳴いた断么九を認める）", key="lab_rule_kuitan")
    st.toggle("赤ドラあり（各色の 5 に 1 枚ずつ）", key="lab_rule_aka")
    st.toggle("切り上げ満貫あり（30 符 4 翻・60 符 3 翻を満貫にする）", key="lab_rule_kiriage")
    st.segmented_control("連風牌（東場の親の東など）を雀頭にしたときの符", list(PAIR_FU), key="lab_rule_pair")
    st.toggle("ダブル役満あり（四暗刻単騎・国士無双十三面待ち・純正九蓮宝燈・大四喜）", key="lab_rule_double")
    st.toggle("数え役満あり（13 翻以上を役満にする）", key="lab_rule_kazoe")

with st.container(horizontal=True, vertical_alignment="center"):
    st.toggle("先に自分で計算する", key="lab_quiz", help="答えと解説を隠します。自分で役・符・点数を数えてから開いてください。")
    st.selectbox("解説の詳しさ", list(DETAILS), key="lab_detail", label_visibility="collapsed")

# ---- 解説の本体
for section in sections[1:]:
    st.subheader(section.title, anchor=False)
    st.html(section.html)

if result is not None and result.status is Status.WIN and not result.consistent:
    st.warning("解説の計算が判定ライブラリと食い違いました。お手数ですが、この画面の手牌と状況を開発者に知らせてください。")

"""CPU との対局。

CPU 3 人と、東風戦（半荘戦も選べる）を打つ。ポン・チー・カンもある（設定で、門前だけにもできる）。
自分が切ると、CPU 3 人の打牌がまとめて進む。鳴ける牌が出たら、そこで止まって返事を聞く。
コーチが、牌効率・守備（危険度と根拠）・リーチ判断・役の候補・鳴きの判断（役が残るか・打点・速さ）を出す。
局が終わると全員の手牌と待ちを公開し、あがった手は点数計算の全過程を見せる。牌譜で、局を 1 手ずつ振り返れる。
"""
from __future__ import annotations

import streamlit as st

from engine.call_coach import call_advice
from engine.cpu import human_turn
from engine.declare import declare_quiz
from engine.game import HUMAN, SEAT_NAMES, GameState, Move, Phase
from engine.game_coach import Stance, kan_advice, ron_ahead, ron_preview, tsumo_preview, turn_advice
from engine.game_records import graduation, summarize
from engine.luck import PRESETS
from engine.scoring.explain import explain
from engine.scoring.texts import kind_text
from engine.tiles import kind_of
from narration.facts import call_facts, call_review_facts, turn_facts, turn_review_facts, win_facts
from ui.ai_access import AiAccess
from ui.auto_state import last_change
from ui.auto_view import GAME, auto_html, news_text
from ui.components.browser_store import BrowserStore
from ui.components.kifu_view import kifu_view
from ui.components.scroll_top import scroll_top
from ui.components.tile_hand import HandButton, Pick, tile_hand
from ui.declare_view import declare_quiz_view, declare_result_html
from ui.game_session import CALL_KEY, GAME_RULES, KAN_KEY, MAX_SEED, MOVES_EACH, MOVES_TOGETHER, GameSession, config_of
from ui.game_view import (
    MARK_RIICHI,
    advice_headline_html,
    betaori_html,
    call_decision_headline_html,
    call_decision_html,
    call_headline_html,
    call_html,
    claim_headline_html,
    config_text,
    danger_html,
    decision_headline_html,
    decision_html,
    final_html,
    furiten_note_html,
    graduation_text,
    hand_title,
    help_html,
    kan_headline_html,
    kan_notes_html,
    meld_label,
    meld_tiles,
    misses_html,
    moves_each_html,
    moves_html,
    pao_text,
    passed_html,
    phase_text,
    plain_headline_html,
    result_banner_html,
    reveal_html,
    review_list_html,
    riichi_html,
    scores_html,
    stats_html,
    status_html,
    table_html,
    yaku_hints_html,
)
from ui.practice_session import parse_seed, preset_name
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
    candidates_html,
    chance_html,
    draw_note_html,
    layout_html,
    luck_now_html,
    note_html,
    shanten_html,
    stamps_html,
    subhead_html,
)
from ui.ruby import Rubifier
from ui.why_view import why_box
from ui.win_view import DETAIL_BRIEF, DETAIL_FULL, DETAIL_NORMAL, detail_sections, summary_section

ss = st.session_state
store = BrowserStore()
session = GameSession(ss, store)

HINTS = {label: value for value, label in HINT_LABELS.items()}
LEVELS = {label: value for value, label in LEVEL_LABELS.items()}
PRESET_LEVELS = dict(PRESETS)
DETAIL_BY_LEVEL = {LEVEL_MIN: DETAIL_BRIEF, LEVEL_NORMAL: DETAIL_NORMAL, LEVEL_FULL: DETAIL_FULL}
LENGTHS = {"東風戦": "east", "半荘戦": "south"}
CPU_LEVELS = {"ふつう": "normal", "弱い": "weak"}
MOVES = {"まとめて": MOVES_TOGETHER, "1 人ずつ": MOVES_EACH}
RULE_LABELS = {
    "calls": "鳴き（チー・ポン・カン）。オフなら、全員が門前だけで打つ",
    "multiple_ron": "2 人以上が同じ牌でロンしたら、全員のあがり（オフなら頭ハネ）",
    "abortive_draws": "途中流局（九種九牌・四風連打・四家立直・四槓散了）",
    "nagashi_mangan": "流し満貫",
    "tobi": "飛び（持ち点が 0 点より少なくなったら終わる）",
}
SLIDER_STEP = 5
SEED_HINT = f"番号は、0〜{MAX_SEED} の数字で入れてください。"


# ---------------------------------------------------------------- 設定の入力欄


def _sync_widgets() -> None:
    settings = session.settings
    ss.setdefault("gm_w_auto", settings["auto"])
    if settings["auto"]:
        # おまかせのあいだは、自分の補正は成績で決まる（スライダーは動かせない）。決まった値を、いつも入力欄に写す
        ss["gm_w_deal"], ss["gm_w_draw"] = settings["deal"], settings["draw"]
    ss.setdefault("gm_w_deal", round(settings["deal"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("gm_w_draw", round(settings["draw"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("gm_w_cpu_deal", round(settings["cpu_deal"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("gm_w_cpu_draw", round(settings["cpu_draw"] / SLIDER_STEP) * SLIDER_STEP)
    ss.setdefault("gm_w_mark", settings["mark"])
    ss.setdefault("gm_w_declare", settings["declare"])
    for name in GAME_RULES:
        ss.setdefault(f"gm_w_rule_{name}", settings["rules"][name])
    if ss.get("gm_w_hint") not in HINTS:
        ss["gm_w_hint"] = HINT_LABELS[settings["hint"]]
    if ss.get("gm_w_level") not in LEVELS:
        ss["gm_w_level"] = LEVEL_LABELS[settings["level"]]
    if ss.get("gm_w_length") not in LENGTHS:
        ss["gm_w_length"] = next(label for label, value in LENGTHS.items() if value == settings["length"])
    if ss.get("gm_w_cpu") not in CPU_LEVELS:
        ss["gm_w_cpu"] = next(label for label, value in CPU_LEVELS.items() if value == settings["cpu_level"])
    if ss.get("gm_w_moves") not in MOVES:
        ss["gm_w_moves"] = next(label for label, value in MOVES.items() if value == settings["moves"])
    ss["gm_w_preset"] = preset_name(ss["gm_w_deal"], ss["gm_w_draw"])


def _read_widgets() -> None:
    session.update_settings(
        {
            "deal": ss["gm_w_deal"],
            "draw": ss["gm_w_draw"],
            "cpu_deal": ss["gm_w_cpu_deal"],
            "cpu_draw": ss["gm_w_cpu_draw"],
            "mark": ss["gm_w_mark"],
            "declare": ss["gm_w_declare"],
            "hint": HINTS[ss["gm_w_hint"]],
            "level": LEVELS[ss["gm_w_level"]],
            "length": LENGTHS[ss["gm_w_length"]],
            "cpu_level": CPU_LEVELS[ss["gm_w_cpu"]],
            "moves": MOVES[ss["gm_w_moves"]],
            "rules": {name: ss[f"gm_w_rule_{name}"] for name in GAME_RULES},
        }
    )


def _on_preset() -> None:
    level = PRESET_LEVELS.get(ss.get("gm_w_preset"))
    if level is not None:
        ss["gm_w_deal"] = ss["gm_w_draw"] = level


def _on_auto() -> None:
    """おまかせを入れた・切った（入れたときは、いまの補正にいちばん近い段階から始める）"""
    session.set_auto(bool(ss.get("gm_w_auto")))


# ---------------------------------------------------------------- 操作


def _apply_settings() -> None:
    if session.started and "gm_w_deal" in ss:
        _sync_widgets()
        _read_widgets()


def _on_pick(pick: Pick) -> None:
    session.pick(pick.tile_id, riichi=pick.riichi)


def _chi_mark(game: GameState) -> tuple[int, int, int]:
    """チーの組み合わせを選んでいる局面の印（対局の番号・局の数・行動の数。別の対局・別の局に残らないように）"""
    return (game.config.seed, len(game.hands), len(game.current.actions))


def _on_action(key: str) -> None:
    if key == "chi":                      # チーの組み合わせを選ぶ画面にする
        ss["gm_chi"] = _chi_mark(session.game)
        session.refresh()
        return
    if key == "back":
        ss.pop("gm_chi", None)
        session.refresh()
        return
    ss.pop("gm_chi", None)
    if key == "tsumogiri":                # リーチのあと、暗槓しないでツモ切り
        drawn = session.game.current.players[HUMAN].drawn
        if drawn is None or not session.pick(drawn):
            session.refresh()
        return
    session.act(key)


def _next_hand(expected: int) -> None:
    session.next_hand(expected)


def _new_game() -> None:
    _apply_settings()
    session.begin()


def _start_numbered() -> None:
    seed = parse_seed(ss.get("gm_w_seed"))
    if seed is None:
        ss["gm_seed_error"] = True
        return
    _apply_settings()
    session.begin(seed)


def _clear_history() -> None:
    session.clear_history()


#: 卒業判定に数える対局の設定（補正 0・CPU ふつう・東風戦・初期のルール・打つ前のヒントなし）
GRADUATION_SETTINGS = {"length": "east", "cpu_level": "normal", "deal": 0, "draw": 0, "cpu_deal": 0, "cpu_draw": 0, "auto": False,
                       "rules": {name: True for name in GAME_RULES}}


def _use_graduation_settings() -> None:
    """設定を、卒業判定に数える条件にそろえる。打つ前のヒントは、答え合わせに変える。いまの対局が終わっていれば、新しい対局を始める"""
    hint = session.settings["hint"]
    session.update_settings({**GRADUATION_SETTINGS, "hint": HINT_AFTER if hint == HINT_BEFORE else hint})
    for key in [k for k in ss if isinstance(k, str) and k.startswith("gm_w_")]:
        del ss[key]                      # 入力欄の値を、新しい設定から入れ直す（入力欄を描く前なので、消してよい）
    if session.game.finished:
        session.begin()
        st.toast("卒業判定に数える設定で、新しい対局を始めました。", icon=":material/emoji_events:", duration="long")
    else:
        ss["gm_graduation_set"] = True


def _open_kifu() -> None:
    ss["gm_kifu_on"] = True


# ---------------------------------------------------------------- 画面


def _html(body: str) -> None:
    """HTML を出す（空なら何も出さない。st.html は空の文字を受け付けない）"""
    if body:
        st.html(body)


generation = ss.get("mj_generation", 0)

st.title("CPU と対局")

if not session.started:
    if not store.ready:
        store.mount()
        st.info("ブラウザに保存された記録を確認しています…")
        st.button("保存を使わずに始める", on_click=store.skip)
        st.stop()
    session.start(generation)
    if store.reconnected:
        st.toast("通信が切れていたので、続きから再開しました。もう一度操作してください。", icon=":material/sync:", duration="long")
session.sync_code(generation)

# 卒業判定のページの「卒業判定に数える設定で対局する」から来た：設定を、数える条件にそろえる（URL の graduation は 1 回だけ使う）
if st.query_params.get("graduation") is not None:
    del st.query_params["graduation"]
    _use_graduation_settings()

_sync_widgets()
_read_widgets()
news = session.take_auto_news()
if news is not None:
    # おまかせが、新しい対局の補正の段階を変えた（理由は、設定のツキ補正のところに出す）
    st.toast(news_text(news), icon=":material/tune:", duration="long")
if ss.pop("gm_graduation_set", False):
    st.info("卒業判定に数える設定にしました（ツキ補正なし・CPU ふつう・東風戦・初期のルール・ヒントは答え合わせ）。いまの対局は、前の設定のままです。")
    st.button("この設定で新しい対局を始める", on_click=_new_game, key="gm_b_graduation_new", type="primary", width="stretch")

game = session.game
hand = game.current
settings = session.settings
hint, level = settings["hint"], settings["level"]
aka = game.config.rules.aka_dora
mark = session.mark
rb = Rubifier()
access = AiAccess(store=store)

# 自分があがった局は、解説の前に点数を申告してもらう（設定で切れる。申告するか、申告しないことにするまで、結果を見せない）
declaring = None
if hand.result is not None and settings.get("declare", True) and session.declared is None:
    mine = next((w for w in hand.result.wins if w.seat == HUMAN), None)
    if mine is not None:
        mine_explanation = explain(mine.ctx, game.config.rules)
        quiz = declare_quiz(mine_explanation, f"{game.config.seed}:{hand.start.number}")
        declaring = (mine_explanation, quiz) if quiz is not None else None
auto_game = session.auto and game.config.luck == config_of(settings, game.config.seed).luck      # おまかせで決まった補正の対局か
st.html(status_html(game, rb, auto=auto_game) + scores_html(game, rb, mark=mark, settled=declaring is None))

my_turn = human_turn(game)
claim = my_turn and hand.phase is Phase.CLAIM
drawing = my_turn and hand.phase is Phase.DRAW
player = hand.players[HUMAN]
claim_actions = hand.call_actions(HUMAN) if claim else ()
can_ron = any(a.move is Move.RON for a in claim_actions)
calls = [a for a in claim_actions if a.move is not Move.RON]
after_call = drawing and player.drawn is None                       # 鳴いた直後（ツモらずに 1 枚切る）
kan_tiles = (*hand.kakan_tiles(HUMAN), *hand.ankan_tiles(HUMAN)) if drawing else ()
riichi_kan = drawing and player.in_riichi and bool(kan_tiles)        # リーチのあとで、暗槓できる
advice = None
if drawing and hint == HINT_BEFORE and not (riichi_kan and not hand.can_tsumo(HUMAN)):     # 答え合わせ・オフでは、打つ前のおすすめを使わない
    advice = turn_advice(hand, HUMAN)
# 鳴きの判断のコーチ（打つ前のヒント）。ロンもできるときは出さない（あがるのがいちばん。鳴きに ◎ を付けて迷わせない）
call_adv = call_advice(hand, HUMAN) if calls and hint == HINT_BEFORE and not can_ron else None
# カンの目安（打つ前のヒントのとき）。リーチのあとは出さない
kan_adv = {a.tile: a for a in kan_advice(hand, HUMAN)} if kan_tiles and hint == HINT_BEFORE else {}
# カンをすすめるとき（あがれるときを除く）は、案内と ◎ をカンに付ける（打牌の ◎ は付けない。カンのあとは、嶺上牌を引いてから切る）
kan_pick = next((a for a in kan_adv.values() if a.recommend), None) if drawing and not hand.can_tsumo(HUMAN) else None
# チーの組み合わせが 2 つ以上のときは、「チー」を押してから組み合わせを選ぶ（ボタンが 1 段に収まるように）
choosing_chi = claim and ss.get("gm_chi") == _chi_mark(game) and sum(a.move is Move.CHI for a in calls) > 1

if hand.result is None and my_turn:
    # ---- 自分の番（打牌か、ロン・鳴きの返事）
    last = session.last_decision
    last_call = session.last_call
    can_tsumo = hand.can_tsumo(HUMAN)
    # リーチのあとにあがり牌を引いたら、ツモを宣言するだけ（ツモ切りは、ほかの巡と同じく自動）
    tsumo_only = drawing and player.in_riichi and can_tsumo
    if claim and can_ron:
        bumped = bool(ron_ahead(hand, HUMAN)) and not hand.rules.multiple_ron
        # 点数の申告の練習中（ヒントを見ていない対局）は、ロンする前に点数を見せない（申告の答えになってしまうため）
        show_points = session.hinted or not settings.get("declare", True)
        st.html(claim_headline_html(hand, ron_preview(hand, HUMAN), rb, bumped=bumped, points=show_points))
    elif claim:
        if call_adv is not None:
            session.note_hint_shown()
        st.html(call_headline_html(hand, call_adv, rb))
    elif tsumo_only and hint != HINT_BEFORE:
        # 手順の案内（コーチの助言ではない）。前の打牌の答え合わせは、リーチのあと何巡も前のものなので出さない
        st.html(plain_headline_html("リーチのあとに、あがり牌を引いた。「ツモ（あがる）」を押して、あがる。", rb))
    elif riichi_kan and not can_tsumo:
        st.html(plain_headline_html("リーチ中：暗槓できる（カンしても待ちは変わらない）。カンするか、ツモ切りするかを選ぶ。", rb))
    elif hint == HINT_BEFORE and advice is not None:
        session.note_hint_shown()
        if kan_pick is not None:
            st.html(kan_headline_html(kan_pick, hand, rb))
        else:
            st.html(advice_headline_html(advice, hand, rb, win=tsumo_preview(hand, HUMAN), can_nine=hand.can_nine(HUMAN)))
    elif hint == HINT_AFTER and last_call is not None:
        st.html(call_decision_headline_html(last_call, rb, aka=aka))
    elif hint == HINT_AFTER:
        if last is not None:
            st.html(decision_headline_html(last, rb, aka=aka))
        else:
            st.html(plain_headline_html("自分で考えて切ってください。切ったあとに、答え合わせを表示します。", rb))
    else:
        st.html(plain_headline_html("コーチはオフです。下の「設定」で、ヒントを出すように変えられます。", rb))

    marks = {}
    if hint == HINT_BEFORE and advice is not None and not can_tsumo and kan_pick is None:
        marks[advice.pick] = MARK_PICK
        # 「○ おすすめと同じ速さ」：おすすめと同じ速さで、鳴いた手なら役の見込みも同じ牌（切っても、評価は ✓ になる）
        for tile in advice.equal_tiles:
            marks.setdefault(tile, MARK_EQUAL)
    buttons = []
    if claim:
        recommended = call_adv.recommend if call_adv is not None else None
        if choosing_chi:
            # チーの組み合わせが 2 つ以上：どの 2 枚でチーするかを選ぶ
            for index, action in enumerate(calls):
                if action.move is Move.CHI:
                    label = ("◎ " if action == recommended else "") + "チー"
                    buttons.append(HandButton(f"{CALL_KEY}{index}", label, "call", tiles=action.tiles))
            buttons.append(HandButton("back", "戻る", "plain"))
        else:
            if can_ron:
                buttons.append(HandButton("ron", "ロン"))
            chis = [a for a in calls if a.move is Move.CHI]
            for index, action in enumerate(calls):
                mark_text = "◎ " if action == recommended or (action.move is Move.CHI and len(chis) > 1 and recommended in chis) else ""
                if action.move is Move.CHI and len(chis) > 1:
                    if action is chis[0]:
                        buttons.append(HandButton("chi", mark_text + "チー", "call"))
                    continue
                word = {Move.CHI: "チー", Move.PON: "ポン", Move.KAN: "カン"}[action.move]
                buttons.append(HandButton(f"{CALL_KEY}{index}", mark_text + word, "call", tiles=action.tiles if action.move is Move.CHI else ()))
            pass_mark = "◎ " if call_adv is not None and recommended is None and not can_ron else ""
            buttons.append(HandButton("pass", pass_mark + "見送る", "plain"))
    else:
        if can_tsumo:
            buttons.append(HandButton("tsumo", "ツモ（あがる）"))
        for tile in kan_tiles:
            mark_text = "◎ " if tile in kan_adv and kan_adv[tile].recommend else ""
            buttons.append(HandButton(f"{KAN_KEY}{tile}", mark_text + "カン", "call", tiles=(tile,)))
        if riichi_kan and player.drawn is not None:
            buttons.append(HandButton("tsumogiri", "ツモ切り", "plain"))
        if hand.can_nine(HUMAN):
            buttons.append(HandButton("nine", "九種九牌", "alert"))
    riichi_ids = () if (claim or can_tsumo) else hand.riichi_tiles(HUMAN)
    locked: tuple[int, ...] = ()
    locked_note = ""
    if after_call and hand.forbidden:
        locked = tuple(t for t in player.tiles if kind_of(t) in hand.forbidden)
        names = "・".join(kind_text(k) for k in hand.forbidden)
        # 部品の中の文字にはルビを振れないので、読みを〈 〉で添える
        locked_note = f"鳴いた直後：{names}は切れない（喰い替え〈クイカエ〉）"
    elif riichi_kan and player.drawn is not None:
        locked = tuple(t for t in player.tiles if t != player.drawn)
    if claim and can_ron:
        # 見送ったらどうなるか（フリテン）を、押す前に見せる
        prompt = "見送ると、この局はもうロンできない" if player.in_riichi else "見送ると、次に自分がツモるまでロンできない"
    elif claim:
        prompt = "チーの組み合わせを選ぶ" if choosing_chi else "鳴くか、見送るかを選ぶ"
    elif tsumo_only:
        prompt = "リーチ中：「ツモ（あがる）」で、あがる"
    elif after_call:
        prompt = "鳴いたので、1 枚切る"
    else:
        prompt = "牌をタップして選ぶ"
    recommend = advice is not None and hint == HINT_BEFORE and advice.recommend_riichi and kan_pick is None
    draw = player.draws[-1] if player.draws else None
    lucky_draw = settings["mark"] and draw is not None and draw.luck.swapped and player.drawn is not None
    tiles = list(player.hand) + ([player.drawn] if player.drawn is not None else [])
    tile_hand(
        tiles,
        key="gm_hand",
        rev=session.rev,
        on_pick=_on_pick,
        drawn_id=player.drawn,
        aka=aka,
        marks=marks,
        riichi_ids=riichi_ids,
        riichi_label=MARK_RIICHI if recommend else "リーチ",
        # カンの補充で引いた牌（嶺上牌）。部品の中の文字にはルビを振れないので、読みのカタカナで出す
        drawn_label="リンシャン" if player.rinshan else ("ツモ ★" if lucky_draw else "ツモ"),
        two_rows=True,
        scroll_top=session.take_scroll(),
        actions=buttons,
        on_action=_on_action,
        discard=not claim and not tsumo_only,
        prompt=prompt,
        melds=[meld_tiles(f, HUMAN) for f in player.furo],
        meld_labels=[meld_label(f) for f in player.furo],
        locked_ids=locked,
        locked_note=locked_note,
    )
    # CPU の打牌（自分が切ったあとの動き）。手牌のすぐ下に、まとめて 1 行で（「1 人ずつ」なら、順番に河と一緒に）
    moves = moves_each_html(hand, mark, rb) if settings["moves"] == MOVES_EACH else moves_html(hand, mark, rb)
    _html(moves + misses_html(hand, mark, rb) + furiten_note_html(hand, rb) + kan_notes_html(hand, session.dora_seen, rb)
          + "".join(f'<div class="mj-sub">{rb.html(a.reason)}</div>' for a in kan_adv.values()))
    if lucky_draw and draw is not None:
        _html(draw_note_html(draw, rb, aka=aka))

    if hint != HINT_OFF and last_call is not None and not claim:
        st.html(call_decision_html(last_call, rb, aka=aka))
    elif hint != HINT_OFF and last is not None and not claim:
        st.html(decision_html(last, rb, detail=level >= LEVEL_NORMAL, aka=aka))

    st.html(table_html(hand, mark, rb))

    # 「なぜ？」：打つ前のヒントのときは、いまの局面。答え合わせのときは、さっきの打牌
    if call_adv is not None:
        why_box(call_facts(hand, HUMAN, call_adv), key="gm_why_call", access=access, rb=rb)
    elif advice is not None and hint == HINT_BEFORE and kan_pick is None:
        win_now = tsumo_preview(hand, HUMAN) if can_tsumo else None
        why_box(turn_facts(hand, HUMAN, advice, last=last, win=win_now), key="gm_why", access=access, rb=rb)
    elif hint == HINT_AFTER and last_call is not None and not claim:
        why_box(call_review_facts(last_call, game.config.rules), key="gm_why_review_call", access=access, rb=rb,
                title="なぜ？（さっきの返事について質問する）")
    elif hint == HINT_AFTER and last is not None and not claim:
        why_box(turn_review_facts(last), key="gm_why_review", access=access, rb=rb, title="なぜ？（さっき切った牌について質問する）")

    if call_adv is not None and level >= LEVEL_NORMAL:
        with st.expander("鳴きの判断（鳴く・鳴かないの比べ方）", expanded=True, key="gm_x_call"):
            st.html(call_html(call_adv, rb.fork(), aka=aka))

    # あがれるときは、あがるのがいちばん（守備やリーチの比べ方は出さない。迷わせないように）
    if advice is not None and hint == HINT_BEFORE and not can_tsumo:
        if advice.table:
            with st.expander("守備：牌ごとの危険度と根拠", expanded=True, key="gm_x_danger"):
                inner = rb.fork()
                st.html(danger_html(advice, inner, detail=level >= LEVEL_FULL))
                st.html(subhead_html("ベタオリの手順", "", inner) + betaori_html(inner))
        if advice.riichi is not None and advice.stance is not Stance.FOLD and level >= LEVEL_NORMAL:
            title = "リーチとダマ（聴牌したときの比べ方）" if player.menzen else "聴牌したときの待ちと点数"
            with st.expander(title, expanded=True, key="gm_x_riichi"):
                st.html(riichi_html(advice.riichi, rb.fork(), aka=aka))
        if advice.stance is Stance.FREE and level >= LEVEL_NORMAL:
            with st.expander("役の候補", expanded=level == LEVEL_FULL, key=f"gm_x_yaku_{level}"):
                st.html(yaku_hints_html(advice.yaku, hand, rb.fork()))
        if level >= LEVEL_NORMAL and not advice.analysis.last_discard:
            with st.expander("受け入れ表（切る牌と、手が進む牌）", expanded=level == LEVEL_FULL, key=f"gm_x_table_{level}"):
                inner = rb.fork()
                st.html(shanten_html(advice.analysis, inner) + candidates_html(advice.analysis, inner) + chance_html(advice.analysis, inner, luck_draw=game.config.luck.draw))
            with st.expander("手の分け方（分解図）", expanded=level == LEVEL_FULL, key=f"gm_x_layout_{level}"):
                st.html(layout_html(advice.analysis, rb.fork(), level=level))
    if hint == HINT_AFTER and last is not None and level >= LEVEL_NORMAL and not claim and last_call is None:
        with st.expander("さっきの局面の受け入れ表と危険度（答え合わせ）", expanded=level == LEVEL_FULL, key=f"gm_x_previous_{level}"):
            inner = rb.fork()
            chosen = last.verdict.chosen.kind
            html = ""
            if last.advice.table:
                html += danger_html(last.advice, inner, detail=False, chosen_kind=chosen)
            html += shanten_html(last.advice.analysis, inner) + candidates_html(last.advice.analysis, inner, chosen_kind=chosen)
            st.html(html)
    if hint == HINT_AFTER and last_call is not None and level >= LEVEL_NORMAL and not claim:
        with st.expander("さっきの鳴きの判断（答え合わせ）", expanded=level == LEVEL_FULL, key=f"gm_x_prevcall_{level}"):
            st.html(call_html(last_call.advice, rb.fork(), aka=aka))

elif hand.result is not None and declaring is not None:
    # ---- 自分があがった：解説の前に、点数を申告してもらう
    declare_quiz_view(
        declaring[0], declaring[1], rb, key="gm_declare", rev=session.rev,
        on_pick=lambda picked: session.declare(declaring[1], picked), on_skip=session.skip_declare,
    )
elif hand.result is not None:
    # ---- 局が終わったあと
    result = hand.result
    if any(w.seat == HUMAN for w in result.wins):
        session.result_shown()          # 申告の問題を出さずに点数を見せたら、この局では、あとから問題を出さない
    if session.declared_rev:
        scroll_top(session.declared_rev, key="gm_declare_scroll")     # 申告した直後は、答え合わせの札が見えるように、上へ
    _html(declare_result_html(session.declared, rb))
    st.html(result_banner_html(game, rb) + passed_html(hand, rb))
    if game.finished:
        st.html(final_html(game, session.tally, rb))
        st.button("新しい対局を始める", type="primary", on_click=_new_game, width="stretch", key="gm_b_new_top")
    else:
        st.button("次の局へ", type="primary", on_click=_next_hand, args=(len(game.hands),), width="stretch", key="gm_b_next_top")
    _html(stamps_html(session.fresh_stamps, rb) + moves_html(hand, mark, rb))
    st.html(f'<div class="mj-subhead">{rb.html("全員の手牌と待ち（この河で、この待ちだった）")}</div>' + reveal_html(hand, rb))
    for win in result.wins:
        explanation = explain(win.ctx, game.config.rules)
        with st.expander(f"あがりの解説（{SEAT_NAMES[win.seat]}）", expanded=win.seat == HUMAN, key=f"gm_x_win_{win.seat}"):
            inner = rb.fork()
            st.html(summary_section(explanation, inner, indicators=bool(win.ctx.ura_indicators)).html)
            for section in detail_sections(explanation, inner, detail=DETAIL_BY_LEVEL[level]):
                st.html(section.heading_html + section.html)
        extra = [] if win.from_seat is None else [f"放銃した人：{SEAT_NAMES[win.from_seat]}。"]
        if win.pao is not None:
            extra.append(pao_text(win))
        why_box(win_facts(explanation, who=SEAT_NAMES[win.seat], extra=extra), key=f"gm_why_win_{win.seat}", access=access, rb=rb,
                title=f"なぜ？（{SEAT_NAMES[win.seat]}のあがりについて質問する）")
    with st.expander("この局の振り返り（自分の判断の評価）", key="gm_x_review"):
        st.html(review_list_html(session.decisions, rb.fork(), aka=aka, calls=session.calls))
    # 牌譜：局を 1 手ずつ振り返る（作るのに少し時間がかかるので、開いたときだけ作る）
    # 折りたたみの名前にはルビを振れないので、読みを（ ）の中に書く
    with st.expander("牌譜（パイフ。局を 1 手ずつ振り返る）", expanded=bool(ss.get("gm_kifu_on")), key="gm_x_kifu"):
        if not ss.get("gm_kifu_on"):
            st.html(note_html("全員の手牌を見ながら、局の最初から 1 手ずつ進められます。自分の判断には、コーチの評価が付きます。", rb.fork()))
            st.button("牌譜を見る", on_click=_open_kifu, key="gm_b_kifu")
        else:
            titles = [hand_title(h) for h in game.hands]
            picked = st.selectbox("局", list(range(len(game.hands))), index=len(game.hands) - 1,
                                  format_func=lambda i: titles[i], key=f"gm_w_kifu_{len(game.hands)}")
            kifu_view(session.kifu(picked), key="gm_kifu", ident=f"{game.config.seed}:{picked}", aka=aka)
    if not game.finished:
        st.button("次の局へ", type="primary", on_click=_next_hand, args=(len(game.hands),), width="stretch", key="gm_b_next_bottom")
else:
    # CPU の番のまま止まっている（起きないはず。念のため、進めるボタンを出す）
    st.html(plain_headline_html("CPU の番です。", rb))
    st.html(table_html(hand, mark, rb))

# ---- 設定（どの状態でも必ず描く）
with st.expander("設定（対局・ツキ補正・コーチ）", key="gm_x_settings"):
    srb = rb.fork()
    st.html(subhead_html("対局", "長さ・CPU の強さ・ルール・ツキ補正の変更は、次の対局から使います。", srb))
    st.html(note_html("東風戦は、東場の 4 局。半荘戦は、東場と南場の 8 局。どちらも、最後に 30000 点以上の人がいなければ延長する（雀魂の決まり）。", srb))
    st.segmented_control("長さ", list(LENGTHS), key="gm_w_length", required=True)
    st.segmented_control("CPU の強さ", list(CPU_LEVELS), key="gm_w_cpu", required=True)
    st.html(note_html("ふつう：牌効率で打ち、聴牌したらリーチ。リーチを受けて聴牌していなければオリる。弱い：受け入れの広さを見ずに切り、オリない。", srb))
    st.html(subhead_html("自分のツキ補正", "配牌とツモの「引きの良さ」を上げます。CPU の補正は別に決めます（初期値 0）。", srb))
    st.html(note_html(
        "補正が強いと、CPU のリーチを受ける前にあがれることが多い。守備（オリ）を練習するなら、弱か、なしにする"
        "（計測では、CPU のリーチを受けた局が、強で 4 局に 1 局ほど、弱で 3 局に 2 局ほど、なしで 5 局に 4 局ほど）。",
        srb,
    ))
    auto = settings["auto"]
    st.toggle("おまかせ（成績に合わせて、補正を自動で上げ下げする）", key="gm_w_auto", on_change=_on_auto)
    if auto:
        st.html(auto_html(session.auto_preview(), last_change(settings), srb, mode=GAME, hint_before=hint == HINT_BEFORE))
    st.segmented_control("強さ", list(PRESET_LEVELS), key="gm_w_preset", on_change=_on_preset, label_visibility="collapsed", disabled=auto)
    st.slider("配牌の良さ", 0, 100, step=SLIDER_STEP, key="gm_w_deal", disabled=auto)
    st.slider("ツモの良さ", 0, 100, step=SLIDER_STEP, key="gm_w_draw", disabled=auto)
    st.html(luck_now_html(ss["gm_w_deal"], ss["gm_w_draw"], srb))
    st.toggle("補正によるツモに印（★）を付ける", key="gm_w_mark")
    st.toggle("あがったら、解説の前に点数を申告する", key="gm_w_declare")
    st.html(subhead_html("CPU のツキ補正", "CPU 3 人に、同じ強さで働きます。", srb))
    st.slider("CPU の配牌の良さ", 0, 100, step=SLIDER_STEP, key="gm_w_cpu_deal")
    st.slider("CPU のツモの良さ", 0, 100, step=SLIDER_STEP, key="gm_w_cpu_draw")
    st.html(
        subhead_html(
            "ルール（雀魂の段位戦が初期値）",
            "ルールによって異なるところ：2 人以上が同じ牌でロンしたとき（全員のあがりか、頭ハネか）、途中流局（九種九牌・四風連打・四家立直・四槓散了）、"
            "流し満貫、飛び。くわしくは「ルールの違い」のページ。鳴き（チー・ポン・カン）をオフにすると、全員が門前（鳴かない手）だけで打つ。"
            "鳴きをオフにした対局は、卒業の目安に数えない。",
            srb,
        )
    )
    for name, label in RULE_LABELS.items():
        st.toggle(label, key=f"gm_w_rule_{name}")
    if session.config_changed and not game.finished:
        st.caption("いまの対局は、前の設定のままです。")
        st.button("この設定で新しい対局を始める", on_click=_new_game)
    st.html(subhead_html("コーチ", "", srb))
    st.segmented_control("ヒントのタイミング", list(HINTS), key="gm_w_hint", required=True)
    st.segmented_control("表示の量", list(LEVELS), key="gm_w_level", required=True)
    st.html(note_html("CPU の打牌は、まとめて（手牌の下に 1 行で並べ、河で印を付ける）か、1 人ずつ（順番に、その人の河と一緒に）見せる。", srb))
    st.segmented_control("CPU の打牌の見せ方", list(MOVES), key="gm_w_moves", required=True)
    st.html(subhead_html("対局の番号", f"いまの対局の番号は {game.config.seed}。同じ番号・同じ設定なら、同じ配牌から始まります（ツモの補正があると、切り方によってツモが変わります）。", srb))
    with st.form("gm_f_seed", border=False), st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("番号を指定して始める", key="gm_w_seed", type="phone", max_chars=len(str(MAX_SEED)), placeholder="例: 123456", icon="", autocomplete="off")
        st.form_submit_button("この番号で始める", on_click=_start_numbered)
    if ss.pop("gm_seed_error", False):
        st.caption(f":red[{SEED_HINT}]")
    if not game.finished:
        st.button("この対局をやめて、新しい対局を始める", on_click=_new_game)

with st.expander("成績", key="gm_x_stats"):
    st.html(stats_html(summarize(session.history), graduation(session.history), rb.fork()))
    st.page_link("views/graduation.py", label="卒業判定（ドリル・点数の申告も合わせた、6 つの条件）", icon=":material/emoji_events:")
    if session.history:
        with st.popover("成績を消す"):
            st.caption("このブラウザに残っている対局の成績を、すべて消します。元に戻せません。")
            st.button("消す", on_click=_clear_history)

with st.expander("このページの使い方", key="gm_x_help"):
    st.html(help_html(rb.fork()))

notes = [f"対局の番号 {game.config.seed}", config_text(game), phase_text(hand)]
if not session.counted:
    notes.append("番号を指定した対局は、成績に入れません")
notes.append(graduation_text(game, hinted=session.hinted, counted=session.counted))
if session.resumed:
    notes.append("この対局は、ブラウザに残っていた記録から再開したものです")
if not store.available:
    notes.append("この端末・ブラウザでは保存を使っていません（ページを閉じると、対局と成績は残りません）")
# 用語（東風戦など）にルビを振れるように、st.caption ではなく HTML で出す
st.html(f'<div class="mj-sub mj-footnote">{rb.html(" ／ ".join(notes))}</div>')

store.mount()

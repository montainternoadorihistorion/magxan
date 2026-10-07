"""実機チェック（Phase 0）。

スマホでの操作感、ブラウザ内保存、通信切れからの復帰、サーバーの速さを確かめ、
結果を 1 つの文章にまとめて送れるようにするページ。
"""
from __future__ import annotations

import json
import platform
import secrets
import statistics
import time
from datetime import datetime, timedelta, timezone
from importlib import metadata

import streamlit as st

from engine import solo
from engine.rng import Rng
from engine.tiles import counts34, format_tiles
from ui.components.browser_store import BrowserStore
from ui.components.copy_button import copy_button
from ui.components.tile_hand import Pick, tile_hand
from ui.tile_view import tile_short_label, tiles_row_html
from ui.version import APP_VERSION

SAVE_NAME = "check.solo"   # いまの局面（シードと切った牌の列）
META_NAME = "check.meta"   # このブラウザで開いた回数・再開できた回数
TARGET_DISCARDS = 10
JST = timezone(timedelta(hours=9))
BENCH_ROUNDS = 3
BENCH_CALLS = 1500         # 1 回の計測で向聴数を計算する回数。これを BENCH_ROUNDS 回くり返し、最も速かった回を採る
BENCH_REFERENCE_US = 40    # 開発環境での実測（向聴数計算 1 回あたり、マイクロ秒）
RATINGS = ["◎", "○", "△", "×"]

ss = st.session_state
store = BrowserStore()


# ---------------------------------------------------------------- 状態の操作


def _save(state: solo.SoloState) -> None:
    store.set(SAVE_NAME, json.dumps({"seed": state.seed, "discards": list(state.discards)}))


def _load_saved() -> solo.SoloState | None:
    """ブラウザに残っている局面を再生する。壊れていたら None"""
    text = store.get(SAVE_NAME)
    if not text:
        return None
    try:
        data = json.loads(text)
        return solo.replay(int(data["seed"]), [int(t) for t in data["discards"]])
    except (ValueError, KeyError, TypeError):
        return None


def _load_meta() -> dict[str, int]:
    try:
        data = json.loads(store.get(META_NAME) or "{}")
        return {"opens": int(data.get("opens", 0)), "restores": int(data.get("restores", 0))}
    except (ValueError, TypeError, AttributeError):
        return {"opens": 0, "restores": 0}


def _start_session() -> None:
    """このセッションで最初に 1 回だけ行う準備（保存があれば続きから）"""
    saved = _load_saved()
    ss.chk_restored = saved is not None
    ss.chk_state = saved or solo.start(secrets.randbelow(1_000_000))
    ss.chk_rev = 0
    ss.chk_latencies = []
    ss.chk_env = {}
    ss.chk_counts = {"tap": 0, "fallback": 0}
    ss.chk_bench_us = None

    meta = _load_meta()
    meta["opens"] += 1
    meta["restores"] += 1 if ss.chk_restored else 0
    ss.chk_meta = meta
    store.set(META_NAME, json.dumps(meta))
    _save(ss.chk_state)


def _apply_discard(tile_id: int, *, via: str) -> None:
    try:
        ss.chk_state = solo.discard(ss.chk_state, tile_id)
        ss.chk_counts[via] += 1
        _save(ss.chk_state)
    except solo.SoloError:
        pass  # 画面が古かった場合など。何もせず描き直す
    ss.chk_rev += 1


def _on_pick(pick: Pick) -> None:
    if pick.prev_response_ms is not None:
        ss.chk_latencies.append(pick.prev_response_ms)
    ss.chk_env = {
        "vw": pick.viewport_width,
        "vh": pick.viewport_height,
        "dpr": pick.device_pixel_ratio,
        "img_ng": pick.image_errors,
    }
    _apply_discard(pick.tile_id, via="tap")


def _on_fallback_pick(tile_id: int | None) -> None:
    if tile_id is not None:
        _apply_discard(tile_id, via="fallback")


def _new_hand() -> None:
    ss.chk_state = solo.start(secrets.randbelow(1_000_000))
    ss.chk_rev += 1
    _save(ss.chk_state)


def _reset_all() -> None:
    store.remove(SAVE_NAME)
    store.remove(META_NAME)
    for name in ("chk_state", "chk_rev", "chk_latencies", "chk_env", "chk_counts", "chk_bench_us", "chk_restored", "chk_meta"):
        ss.pop(name, None)


def _run_benchmark() -> None:
    """向聴数の計算を一定回数まわして、1 回あたりの時間を測る"""
    from mahjong.shanten import Shanten

    rng = Rng(20261007, "bench")
    hands = []
    for _ in range(200):
        tiles = list(range(136))
        rng.shuffle(tiles)
        hands.append(counts34(tiles[:14]))
    best = float("inf")
    for _ in range(BENCH_ROUNDS):   # 他の処理に邪魔された回を除くため、最も速かった回を採る
        started = time.perf_counter()
        for i in range(BENCH_CALLS):
            Shanten.calculate_shanten(hands[i % len(hands)])
        best = min(best, (time.perf_counter() - started) / BENCH_CALLS * 1e6)
    ss.chk_bench_us = best


# ---------------------------------------------------------------- 画面

st.title("実機チェック")

if "chk_state" not in ss:
    if not store.ready:
        # 開いた直後: ブラウザに残っている記録が届くのを待つ（ふつうは一瞬）
        store.mount()
        st.info("ブラウザに保存された記録を確認しています…")
        st.button("保存を使わずに始める", on_click=store.skip)
        st.stop()
    _start_session()

state: solo.SoloState = ss.chk_state

st.caption("上から順に試して、最後の「結果」をコピーして送ってください。3〜5 分で終わります。")

# ---- ① 牌を切る
st.subheader("① 牌を選んで切る")
st.markdown(
    f"**{TARGET_DISCARDS} 回ほど**切ってみてください。牌をタップして選び、"
    "「この牌を切る」を押すか、同じ牌をもう一度タップすると確定します。"
)
use_fallback = st.toggle("予備の操作方法（標準の部品）で試す", key="chk_use_fallback")

if state.finished:
    st.success("この局はここまでです。")
    st.html(tiles_row_html(state.hand, tile_width_px=24))
    st.button("新しい局を始める", type="primary", on_click=_new_hand)
elif use_fallback:
    st.html(tiles_row_html(state.tiles_in_hand, tile_width_px=22))
    choice = st.pills(
        "切る牌",
        list(state.tiles_in_hand),
        format_func=lambda t: tile_short_label(t) + ("（ツモ）" if t == state.drawn else ""),
        key=f"chk_pills_{ss.chk_rev}",
    )
    st.button("この牌を切る", type="primary", disabled=choice is None, on_click=_on_fallback_pick, args=(choice,))
else:
    tile_hand(
        [*state.hand, state.drawn],
        key="chk_hand",
        rev=ss.chk_rev,
        on_pick=_on_pick,
        drawn_id=state.drawn,
    )

done = ss.chk_counts["tap"] + ss.chk_counts["fallback"]
st.markdown("**河（切った牌）**")
st.html(tiles_row_html(state.discards, tile_width_px=26, empty_text="まだ切っていません"))
st.caption(f"切った回数 {done} / 目安 {TARGET_DISCARDS} 回 ・ この局の残りツモ {max(state.draws_left, 0)} 回")

# ---- ② 保存と再開
st.subheader("② 閉じても続きから再開できるか")
meta = ss.chk_meta
if store.available:
    if ss.chk_restored:
        st.success("この画面は、ブラウザに残っていた記録から再開したものです。")
    st.markdown(
        f"""
ブラウザ内保存は**使えています**（このブラウザで開いた回数 {meta["opens"]} 回、うち続きから再開 {meta["restores"]} 回）。

1. 何枚か切ったあと、**ページを再読み込み**してください。同じ手牌と河に戻れば合格です。
2. 余裕があれば、**別のアプリに切り替えて 3 分以上**待ってから戻ってください。続きから打てれば合格です。
"""
    )
else:
    reason = store.error or "ブラウザからの返事を待たずに始めました"
    st.warning(f"この端末・ブラウザでは、ブラウザ内保存を使っていません（{reason}）。")

# ---- ③ サーバーの速さ
st.subheader("③ サーバーの計算の速さ")
st.button("計測する（数秒）", on_click=_run_benchmark)
if ss.chk_bench_us is not None:
    ratio = ss.chk_bench_us / BENCH_REFERENCE_US
    st.markdown(
        f"向聴数の計算 1 回あたり **{ss.chk_bench_us:.0f} マイクロ秒**"
        f"（開発環境の約 {ratio:.1f} 倍の時間）"
    )

# ---- ④ 感想
st.subheader("④ 使ってみた感想")
st.caption("◎ とても良い ／ ○ 問題ない ／ △ 少し気になる ／ × 困る")
rating_tap = st.segmented_control("牌の押しやすさ", RATINGS, key="chk_rating_tap")
rating_look = st.segmented_control("牌の見やすさ", RATINGS, key="chk_rating_look")
rating_speed = st.segmented_control("反応の速さ", RATINGS, key="chk_rating_speed")
comment = st.text_area("気づいたこと（任意）", key="chk_comment", height=80)

# ---- ⑤ 結果
st.subheader("⑤ 結果")
st.caption("下のボタンで全文をコピーして、そのまま送ってください。")


def _latency_line() -> str:
    samples = ss.chk_latencies
    if not samples:
        return "未計測（牌を 2 回以上切ると測れます）"
    median = statistics.median(samples)
    return f"{len(samples)} 回 ／ 中央値 {median / 1000:.2f} 秒 ／ 最大 {max(samples) / 1000:.2f} 秒"


def _env_line() -> str:
    env = ss.chk_env
    if not env:
        return "未取得（牌を 1 回切ると取れます）"
    return f"幅 {env['vw']} × 高さ {env['vh']} px ／ 画素比 {env['dpr']} ／ 読めなかった牌画像 {env['img_ng']} 枚"


def _bench_line() -> str:
    if ss.chk_bench_us is None:
        return "未計測"
    return f"{ss.chk_bench_us:.0f} マイクロ秒/回（開発環境 {BENCH_REFERENCE_US}）"


def _storage_line() -> str:
    if not store.available:
        return f"使えない（{store.error or '待たずに開始'}）"
    return f"使える ／ 開いた回数 {meta['opens']} ／ 続きから再開 {meta['restores']} ／ 今回は{'再開' if ss.chk_restored else '新規'}"


try:
    user_agent = st.context.headers.get("User-Agent", "不明")
except Exception:  # noqa: BLE001 - 取れない環境でも結果は出す
    user_agent = "不明"

report = "\n".join(
    [
        "【ツキ付き麻雀道場 実機チェック結果】",
        f"日時: {datetime.now(JST):%Y-%m-%d %H:%M} (JST)",
        f"版: {APP_VERSION} ／ Python {platform.python_version()} ／ Streamlit {st.__version__} ／ mahjong {metadata.version('mahjong')}",
        f"端末: {user_agent}",
        f"画面: {_env_line()}",
        f"切った回数: 牌タップ {ss.chk_counts['tap']} 回 ／ 予備の方法 {ss.chk_counts['fallback']} 回",
        f"応答時間（牌タップ）: {_latency_line()}",
        f"ブラウザ内保存: {_storage_line()}",
        f"サーバーの速さ: {_bench_line()}",
        f"押しやすさ: {rating_tap or '未回答'} ／ 見やすさ: {rating_look or '未回答'} ／ 反応の速さ: {rating_speed or '未回答'}",
        f"局面: シード {state.seed} ／ 手牌 {format_tiles(state.tiles_in_hand)} ／ 河 {len(state.discards)} 枚",
        f"メモ: {comment.strip() or 'なし'}",
    ]
)
copy_button(report, key="chk_copy", label="結果をコピー")
st.code(report, language=None, wrap_lines=True)

st.divider()
st.button("記録を消して最初からやり直す", on_click=_reset_all)

# ブラウザ内保存の読み書きは、ここまでの変更をまとめてここで行う
store.mount()

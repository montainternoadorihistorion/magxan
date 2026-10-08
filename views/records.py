"""記録と保存。

進み具合（一人練習の成績・スタンプ・ドリルの記録）のまとめと、ファイルへの書き出し・読み込み。
記録の置き場所はブラウザの中なので、端末やブラウザを変えると引き継がれない。ブラウザが消してしまうこともある。
ファイルに保存しておけば、別の端末に移したり、消えたときに戻したりできる。
"""
from __future__ import annotations

import hashlib
import time

import streamlit as st

from engine.drills import KINDS, progress_of
from engine.progress import completion, parse_export
from engine.records import summarize, target_stats
from ui.components.browser_store import BrowserStore
from ui.components.copy_button import copy_button
from ui.components.scroll_top import scroll_top
from ui.drill_view import progress_text
from ui.learn_view import completion_text, subhead
from ui.practice_session import clean_settings
from ui.practice_view import stats_html, target_stats_html
from ui.progress_store import (
    apply_import,
    clear_all,
    export_text,
    read_decks,
    read_history,
    read_stamps,
    store_signature,
    summary_of_export,
    summary_of_store,
)
from ui.ruby import Rubifier
from ui.timefmt import datetime_text, file_stamp
from ui.version import APP_VERSION

ss = st.session_state
store = BrowserStore()
MERGE, REPLACE = "いまの記録と合わせる", "ファイルの中身で置き換える"
#: 読み込めるファイルの大きさの上限（MB）。書き出したファイルは、多くても 1 MB ほど
MAX_FILE_MB = 5


def _forget_pages() -> None:
    """ほかのページがセッションに持っている控えを捨てる（次に開いたとき、ブラウザの記録から読み直させる）"""
    for key in [k for k in ss if isinstance(k, str) and k.startswith(("pr_", "dr_"))]:
        del ss[key]


def _tell(kind: str, text: str) -> None:
    """結果を、ページのいちばん上に出す（押したボタンは下のほうにあるので、上まで戻して見せる）"""
    ss["rc_message"] = (kind, text)
    ss["rc_told"] = ss.get("rc_told", 0) + 1


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _incoming(round_: int) -> tuple[str | None, str]:
    """選んだファイルか、貼り付けた文字 →（中身, 読めなかったときの理由）。どちらも無ければ（None, ""）"""
    uploaded = ss.get(f"rc_w_file_{round_}")
    if uploaded is not None:
        if uploaded.size > MAX_FILE_MB * 1024 * 1024:
            return None, "ファイルが大きすぎます。このアプリが保存したファイルを選んでください。"
        try:
            return uploaded.getvalue().decode("utf-8-sig"), ""
        except UnicodeDecodeError:
            return None, "このファイルは読めませんでした（文字の形式が違います）。このアプリが保存したファイルを選んでください。"
    pasted = ss.get(f"rc_w_paste_{round_}")
    if isinstance(pasted, str) and pasted.strip():
        return pasted, ""
    return None, ""


def _import(round_: int, shown: str) -> None:
    """「読み込む」を押したとき。ボタンを描いたときの値ではなく、押した時点の選択と中身を使う。

    shown は、画面で確かめてもらった中身のしるし。そのあとで中身が変わっていたら、読み込まない（確かめ直してもらう）。
    """
    text, _ = _incoming(round_)
    if text is None or _digest(text) != shown:
        _tell("error", "読み込む中身が、確かめたときから変わりました。表示された内容を確かめてから、もう一度押してください。")
        return
    merge = ss.get(f"rc_w_how_{round_}", MERGE) != REPLACE
    try:
        data = parse_export(text)
    except ValueError as error:
        _tell("error", str(error))
        return
    after = apply_import(store, data, merge=merge, clean_settings=clean_settings)
    _forget_pages()
    how = "いまの記録と合わせた" if merge else "ファイルの中身で置き換えた"
    _tell("success", f"読み込みました（{how}）。成績 {after.hands} 局・スタンプ {after.stamps} 役・ドリル {after.answers} 回。")
    ss["rc_upload"] = ss.get("rc_upload", 0) + 1         # ファイルの欄と貼り付けの欄を、空に戻す


def _clear() -> None:
    clear_all(store)
    _forget_pages()
    _tell("success", "成績・スタンプ・ドリルの記録を消しました。")


st.title("記録と保存")

if not store.ready:
    # 開いた直後: ブラウザに残っている記録が届くのを待つ（ふつうは一瞬）
    store.mount()
    st.info("ブラウザに保存された記録を確認しています…")
    st.button("保存を使わずに開く", on_click=store.skip)
    st.stop()

rb = Rubifier()
now = int(time.time())
message = ss.pop("rc_message", None)
if message is not None:
    (st.success if message[0] == "success" else st.error)(message[1])

if not store.available:
    st.warning("この端末・ブラウザでは、記録をブラウザに残せません。ページを閉じると消えるので、下の「進み具合をファイルに保存する」で残してください（次に開いたときに、読み込めます）。")

st.html(
    f'<div class="mj-note">{rb.html("記録は、このブラウザの中に残している。別の端末やブラウザには引き継がれず、しばらく開かないと、ブラウザが消してしまうこともある。")}</div>'
    f'<div class="mj-sub">{rb.html("ときどきファイルに保存しておくと安心。保存したファイルを読み込めば、別の端末でも続きから使える。")}</div>'
)

# ---------------------------------------------------------------- いまの記録
history = read_history(store)
stamps = read_stamps(store)
decks = read_decks(store)
done = completion(stamps)

st.html(subhead("スタンプ（成立させた役）", rb))
st.progress(done.rate, text=completion_text(done))
st.page_link("views/yaku_book.py", label="役図鑑で、スタンプを見る", icon=":material/menu_book:")

aimed = target_stats(history)
st.html(subhead("一人練習の成績", rb) + stats_html(summarize(history), rb, aimed=sum(stat.tries for stat in aimed.values())) + target_stats_html(aimed, rb))

rows = ['<tr class="mj-dim"><td>ドリル</td><td>進み具合</td></tr>']
for kind, info in KINDS.items():
    rows.append(f"<tr><td style=\"white-space:nowrap\">{rb.html(info.name)}</td><td>{rb.html(progress_text(kind, progress_of(kind, decks[kind], now)))}</td></tr>")
st.html(subhead("ドリル", rb) + f'<table class="mj-table">{"".join(rows)}</table>')

# ---------------------------------------------------------------- ファイルに保存
st.html(subhead("ファイルに保存する", rb))
# 記録が変わらないあいだは、作った文字を使い回す（画面を描き直すたびに、大きな文字を送り直さない）
signature = store_signature(store)
cached = ss.get("rc_export")
if cached is None or cached[0] != signature:
    cached = (signature, export_text(store, time=now, app_version=APP_VERSION), now)
    ss["rc_export"] = cached
_, text, made_at = cached
size = summary_of_store(store)
try:
    st.download_button(
        "進み具合をファイルに保存する", data=text, file_name=f"mjdojo-{file_stamp(made_at)}.json", mime="application/json",
        on_click="ignore", type="primary", width="stretch", key="rc_b_download",
    )
except UnicodeEncodeError:        # 念のため：書き出せない文字が残っていても、下の「読み込む」「消す」は使えるようにする
    st.error("記録の中に、ファイルに書き出せない文字がありました。下の「ファイルから読み込む」で置き換えるか、「すべて消す」で消してください。")
st.html(
    f'<div class="mj-sub">{rb.html(f"入るもの：成績 {size.hands} 局・スタンプ {size.stamps} 役・ドリル {size.answers} 回ぶんの記録と、一人練習の設定。打っている途中の局は入らない。")}</div>'
    # 押しても画面は変わらない（ブラウザがファイルを保存するだけ）。どこに入るかを、ここで言っておく
    f'<div class="mj-sub">{rb.html("iPhone では、確認が出たら「ダウンロード」を押す。ファイルは「ファイル」アプリの「ダウンロード」に入る。")}</div>'
)
with st.expander("ファイルに保存できないとき（文字としてコピーする）", key="rc_x_copy"):
    st.caption("下のボタンで、記録の文字をコピーできます。メモ帳やメールに貼り付けて、残しておいてください。")
    copy_button(
        text, key="rc_copy", label="記録の文字をコピーする",
        fail_text="コピーできませんでした。上の「進み具合をファイルに保存する」で保存してください。",
    )

# ---------------------------------------------------------------- ファイルから読み込む
st.html(subhead("ファイルから読み込む", rb))
round_ = ss.get("rc_upload", 0)
st.file_uploader(
    "保存したファイル（.json）を選ぶ", type=["json", "txt"], key=f"rc_w_file_{round_}", max_upload_size=MAX_FILE_MB,
)
# ファイルを選ぶ部品の文字（ボタンと、大きさの上限）は、英語のまま変えられないので、ここで説明する
st.caption(f"「Upload」（または「Browse files」）を押して、保存したファイル（名前が mjdojo- で始まる .json）を選びます。{MAX_FILE_MB}MB まで。")
with st.expander("ファイルを選べないとき（文字を貼り付ける）", key="rc_x_paste"):
    with st.container(key="rc_paste_box"):            # 英語の案内（Press Ctrl+Enter to apply）を隠すための目印
        st.text_area("コピーしておいた記録の文字", key=f"rc_w_paste_{round_}", height=120, placeholder='{"app": "mjdojo", …')
    st.caption("貼り付けたら、下の「この文字を確かめる」を押してください。中身が下に出ます。")
    st.button("この文字を確かめる", key=f"rc_b_check_{round_}")       # 押すと、貼り付けた文字が届いて、画面が描き直される

incoming, problem = _incoming(round_)
if problem:
    st.error(problem)
pasted = ss.get(f"rc_w_paste_{round_}")
if ss.get(f"rc_w_file_{round_}") is not None and isinstance(pasted, str) and pasted.strip():
    st.info("ファイルと、貼り付けた文字の両方があります。ファイルのほうを読み込みます（貼り付けた文字は使いません）。")

if incoming is not None:
    try:
        data = parse_export(incoming)
    except ValueError as error:
        st.error(str(error))
    else:
        inside = summary_of_export(data)
        when = datetime_text(data.exported) if data.exported else "不明"
        lines = [f"保存した日時：{when}（アプリの版 {data.app_version or '不明'}）", f"入っているもの：成績 {inside.hands} 局・スタンプ {inside.stamps} 役・ドリル {inside.answers} 回"]
        if data.skipped:
            lines.append(f"読めなかった成績が {data.skipped} 件あった（その記録は飛ばす）。")
        st.html('<div class="mj-card">' + "<br>".join(rb.html(line) for line in lines) + "</div>")
        how = st.radio("読み込み方", [MERGE, REPLACE], key=f"rc_w_how_{round_}")
        if how == MERGE:
            st.caption("同じ局は 1 つにまとめます。スタンプとドリルの回数は、多いほうを採ります（足しません）。設定は、いまのままです。")
        else:
            st.caption(f"いまの記録（成績 {size.hands} 局・スタンプ {size.stamps} 役・ドリル {size.answers} 回）は消えて、ファイルの中身になります。設定も置き換えます。")
        st.button("読み込む", type="primary", on_click=_import, args=(round_, _digest(incoming)), key=f"rc_b_import_{round_}")

# ---------------------------------------------------------------- 消す
st.html(subhead("記録を消す", rb))
with st.popover("成績・スタンプ・ドリルの記録を、すべて消す"):
    st.caption("このブラウザに残っている進み具合を、すべて消します。元に戻せません（先にファイルに保存しておけば、読み込んで戻せます）。")
    st.button("すべて消す", on_click=_clear, key="rc_b_clear")

scroll_top(ss.get("rc_told", 0), key="rc_scroll")
store.mount()

"""ホーム"""
import streamlit as st

from ui.ruby import Rubifier
from ui.version import APP_NAME, APP_PHASE, APP_VERSION

rb = Rubifier()      # 用語のルビは、この画面で最初に出てきたときだけ振る。文章は画面の上から順に作る


def _list(items: list[str], ruby: Rubifier) -> str:
    return '<ul class="mj-rules">' + "".join(f"<li>{ruby.rich(item)}</li>" for item in items) + "</ul>"


st.title(APP_NAME)
st.caption(f"版 {APP_VERSION} ／ {APP_PHASE}")

st.html(
    '<div class="mj-note">'
    + rb.rich(
        "**Phase 1** まで入りました。相手なしで打って牌効率を身につける **一人練習** と、"
        "あがったときの点数計算を 1 歩ずつ確かめられる **点数計算ラボ** が使えます。"
    )
    + "</div>"
)

st.page_link("views/practice.py", label="一人練習を始める", icon=":material/playing_cards:")
st.html(
    _list(
        [
            "配牌からツモと打牌をくり返し、**どれを切ると聴牌に近づくか**を練習する",
            "コーチが、向聴数・受け入れ（有効牌の種類と残り枚数）・おすすめの打牌を出す。"
            "ヒントは「打つ前」「打った後に答え合わせ」「オフ」から選べる",
            "**ツキ補正**で、配牌とツモの引きの良さを上げられる（補正の強さはいつも画面に出て、成績も補正ごとに分けて記録）",
            "あがると、点数計算ラボと同じ解説が出る",
        ],
        rb,
    )
)

st.page_link("views/score_lab.py", label="点数計算ラボを開く", icon=":material/calculate:")
st.html(
    _list(
        [
            "**例題で学ぶ**：符の足し算の基本から、鳴いた手、暗刻・槓子、待ち、高点法、満貫以上、本場・供託まで 43 題",
            "**ランダムに出す**／**自分で入力**／**状況を変えてみる**（ツモ／ロン、親／子、リーチあり／なし）",
            "どの手でも、読み方 → 役 → ドラ → 符 → 点数 → 支払い → 申告 の順に、計算の途中をすべて表示",
        ],
        rb,
    )
)

PLAN = (
    ("Phase 2", "役図鑑、用語辞典、ドリル、役指定練習（狙った役が出やすい配牌・ツモ）、進捗の保存"),
    ("Phase 3", "CPU 3 人との対局（門前）、対局中コーチ（役・打点・守備）"),
    ("Phase 4", "ポン・チー・カン、鳴き判断コーチ、局後の振り返り"),
    ("Phase 5", "AI による解説と自由質問、カリキュラム、おまかせ補正、卒業判定"),
)

with st.expander("このあとの予定"):
    inner = rb.fork()      # 折りたたみの中身は、別に数える（閉じていると読まれないので）
    rows = "".join(f'<tr><td style="white-space:nowrap">{name}</td><td>{inner.html(text)}</td></tr>' for name, text in PLAN)
    st.html(f'<table class="mj-table"><tr class="mj-dim"><td>段階</td><td>内容</td></tr>{rows}</table>')

st.caption("Phase 0 の確認用のページも残してあります。")
st.page_link("views/device_check.py", label="実機チェックを始める", icon=":material/smartphone:")

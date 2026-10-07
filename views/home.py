"""ホーム"""
import streamlit as st

from ui.version import APP_NAME, APP_PHASE, APP_VERSION

st.title(APP_NAME)
st.caption(f"版 {APP_VERSION} ／ {APP_PHASE}")

st.markdown(
    """
いまは **Phase 1 の途中**です。最初に、あがったときの点数計算を 1 歩ずつ確かめられる
**点数計算ラボ**ができました。
"""
)

st.page_link("views/score_lab.py", label="点数計算ラボを開く", icon=":material/calculate:")

st.markdown(
    """
**ラボでできること**

- **例題で学ぶ**：符の足し算の基本から、鳴いた手、暗刻・槓子、待ち、高点法、満貫以上、本場・供託まで 43 題
- **ランダムに出す**：役のある手を次々に出して、点数を数える練習をする
- **自分で入力**：気になった手を入れて確かめる
- **状況を変えてみる**：同じ手をツモ／ロン、親／子、リーチあり／なしで比べる

どの手でも、読み方 → 役 → ドラ → 符 → 点数 → 支払い → 申告 の順に、計算の途中をすべて表示します。
"""
)

with st.expander("このあとの予定"):
    st.markdown(
        """
| 段階 | 内容 |
|---|---|
| Phase 1（続き） | 山・ツキ補正・向聴数と受け入れ、一人練習（あがると同じ解説が出る） |
| Phase 2 | 役図鑑、用語辞典、ドリル、役指定練習、進捗の保存 |
| Phase 3 | CPU 3 人との対局（門前）、対局中コーチ、守備 |
| Phase 4 | ポン・チー・カン、鳴き判断コーチ、局後の振り返り |
| Phase 5 | AI による解説と自由質問、カリキュラム、おまかせ補正、卒業判定 |
"""
    )

st.caption("Phase 0 の確認用のページも残してあります。")
st.page_link("views/device_check.py", label="実機チェックを始める", icon=":material/smartphone:")

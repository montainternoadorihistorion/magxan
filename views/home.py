"""ホーム"""
import streamlit as st

from ui.version import APP_NAME, APP_PHASE, APP_VERSION

st.title(APP_NAME)
st.caption(f"版 {APP_VERSION} ／ {APP_PHASE}")

st.markdown(
    """
いまは**土台の確認用の版**です。麻雀の対局や解説はまだ入っていません。

この版で確かめたいのは次の 3 点です。

1. スマホの縦画面で、手牌を押し間違えずに選べるか
2. 画面を閉じたり通信が切れたりしても、続きから再開できるか
3. 無料枠のサーバーで、反応と計算が十分に速いか
"""
)

st.page_link("views/device_check.py", label="実機チェックを始める", icon=":material/smartphone:")

with st.expander("このあとの予定"):
    st.markdown(
        """
| 段階 | 内容 |
|---|---|
| Phase 1 | 山・ツキ補正・向聴数と受け入れ・和了判定・点数計算の解説、一人練習、点数計算ラボ |
| Phase 2 | 役図鑑、用語辞典、ドリル、役指定練習、進捗の保存 |
| Phase 3 | CPU 3 人との対局（門前）、対局中コーチ、守備 |
| Phase 4 | ポン・チー・カン、鳴き判断コーチ、局後の振り返り |
| Phase 5 | AI による解説と自由質問、カリキュラム、おまかせ補正、卒業判定 |
"""
    )

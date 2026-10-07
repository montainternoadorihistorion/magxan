"""ツキ付き麻雀道場（入口）。

起動:  streamlit run app.py
"""
import importlib
import sys
from pathlib import Path

import streamlit as st


@st.cache_resource
def _code_state() -> dict:
    """サーバーが動いているあいだ残る入れ物（前回の表示のときのコードの状態を覚えておく）"""
    return {}


# コードが更新されていたら、古いまま残っている自作モジュールを捨てる（理由は ui/fresh.py）。
# 見張り役のモジュール自身が古いと役に立たないので、これだけは毎回読み直す。
sys.modules.pop("ui.fresh", None)
importlib.import_module("ui.fresh").drop_stale_modules(Path(__file__).resolve().parent, ("engine", "ui"), _code_state())

from ui.layout import apply_base_style  # noqa: E402  （上の処理のあとで読み込む必要がある）
from ui.version import APP_NAME  # noqa: E402

st.set_page_config(page_title=APP_NAME, page_icon="🀄", layout="centered")
apply_base_style()

page = st.navigation(
    [
        st.Page("views/home.py", title="ホーム", icon=":material/home:", default=True),
        st.Page("views/score_lab.py", title="点数計算ラボ", icon=":material/calculate:", url_path="lab"),
        st.Page("views/device_check.py", title="実機チェック", icon=":material/smartphone:", url_path="check"),
    ],
    position="top",
)
page.run()

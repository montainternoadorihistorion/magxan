"""ツキ付き麻雀道場（入口）。

起動:  streamlit run app.py
"""
import streamlit as st

from ui.layout import apply_base_style
from ui.version import APP_NAME

st.set_page_config(page_title=APP_NAME, page_icon="🀄", layout="centered")
apply_base_style()

page = st.navigation(
    [
        st.Page("views/home.py", title="ホーム", icon=":material/home:", default=True),
        st.Page("views/device_check.py", title="実機チェック", icon=":material/smartphone:", url_path="check"),
    ],
    position="top",
)
page.run()

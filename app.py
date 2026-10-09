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
_fresh = importlib.import_module("ui.fresh")
_state = _code_state()
_changed = _fresh.drop_stale_modules(Path(__file__).resolve().parent, ("engine", "narration", "ui"), _state, data_folders=("data",))
# Streamlit も、ページ（views/）などが書き換わると、自作モジュールを捨てて読み直させる。そのときも型が作り直される
_replaced = _fresh.module_replaced(_state, importlib.import_module("engine.tiles"))
if _changed or _replaced:
    _state["generation"] = _state.get("generation", 0) + 1
# いま動いているコードの世代。ページは、これが変わったら、セッションに残っている古い型のオブジェクトを作り直す
st.session_state["mj_generation"] = _state.get("generation", 0)

from ui.layout import apply_base_style  # noqa: E402  （上の処理のあとで読み込む必要がある）
from ui.version import APP_NAME  # noqa: E402

st.set_page_config(page_title=APP_NAME, page_icon="🀄", layout="centered")
apply_base_style()

page = st.navigation(
    {
        "": [st.Page("views/home.py", title="ホーム", icon=":material/home:", default=True)],
        "打つ": [
            st.Page("views/game.py", title="CPU と対局", icon=":material/groups:", url_path="game"),
            st.Page("views/practice.py", title="一人練習", icon=":material/playing_cards:", url_path="practice"),
            st.Page("views/score_lab.py", title="点数計算ラボ", icon=":material/calculate:", url_path="lab"),
        ],
        "学ぶ": [
            st.Page("views/curriculum.py", title="カリキュラム", icon=":material/school:", url_path="curriculum"),
            st.Page("views/yaku_book.py", title="役図鑑", icon=":material/menu_book:", url_path="yaku"),
            st.Page("views/glossary.py", title="用語辞典", icon=":material/dictionary:", url_path="terms"),
            st.Page("views/drill.py", title="ドリル", icon=":material/quiz:", url_path="drill"),
            st.Page("views/table_guide.py", title="卓で打つとき", icon=":material/table_restaurant:", url_path="table"),
            st.Page("views/rules.py", title="ルールの違い", icon=":material/rule:", url_path="rules"),
        ],
        "記録": [
            st.Page("views/graduation.py", title="卒業判定", icon=":material/emoji_events:", url_path="graduation"),
            st.Page("views/records.py", title="記録と保存", icon=":material/save:", url_path="records"),
            st.Page("views/device_check.py", title="実機チェック", icon=":material/smartphone:", url_path="check"),
        ],
    },
    position="top",
)
page.run()

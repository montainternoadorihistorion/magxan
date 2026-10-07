"""全ページ共通の見た目の調整"""
import streamlit as st

# スマホの縦画面では、Streamlit の標準の余白と見出しが大きすぎて手牌が画面の下に押し出される。
# 幅の狭い画面に限って、上の余白と見出しを詰める。
_BASE_STYLE = """
<style>
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] {
    padding-top: 3.25rem;
    padding-bottom: 4rem;
  }
  [data-testid="stMainBlockContainer"] h1 {
    font-size: 1.6rem;
    padding: 0.25rem 0 0.5rem;
  }
  [data-testid="stMainBlockContainer"] h2 {
    font-size: 1.3rem;
    padding: 0.75rem 0 0.25rem;
  }
  [data-testid="stMainBlockContainer"] h3 {
    font-size: 1.15rem;
    padding: 0.75rem 0 0.25rem;
  }
}
</style>
"""


def apply_base_style() -> None:
    """共通のスタイルを入れる。app.py で 1 度呼ぶ"""
    st.html(_BASE_STYLE)

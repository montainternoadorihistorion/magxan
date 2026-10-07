"""全ページ共通の見た目の調整"""
import streamlit as st

# スマホの縦画面では、Streamlit の標準の余白と見出しが大きすぎて手牌が画面の下に押し出される。
# 幅の狭い画面に限って、余白と見出しを詰める（左右の余白を詰めるぶん、牌を大きく表示できる）。
_BASE_STYLE = """
<style>
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] {
    padding-top: 3.25rem;
    padding-bottom: 4rem;
    padding-left: 0.6rem;
    padding-right: 0.6rem;
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

/* ---- ルビ（読みがな） */
ruby { ruby-align: center; }
ruby rt { font-size: 0.55em; opacity: 0.85; user-select: none; }

/* ---- 牌の表示（表示専用。タップできる手牌は ui/components/tile_hand） */
.mj-img {
  width: 100%;
  height: auto;
  aspect-ratio: 3 / 4;
  display: block;
  border-radius: 3px;
  filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.35));
}
.mj-win { outline: 2px solid #e8a400; outline-offset: 1px; }
.mj-fit { display: grid; gap: 2px; align-items: end; }
.mj-hand { margin-top: 0.6rem; }
.mj-right { text-align: right; }
.mj-row { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; }
.mj-rowlabel { font-size: 12px; opacity: 0.8; padding-top: 8px; white-space: nowrap; }
.mj-blocks { display: flex; flex-wrap: wrap; gap: 10px 12px; }
.mj-block { display: flex; flex-direction: column; align-items: center; gap: 3px; }
.mj-block-tiles { display: flex; gap: 1px; }
.mj-block-tiles .mj-img { width: 30px; }
.mj-block.mj-small .mj-block-tiles .mj-img { width: 22px; }
.mj-cap { font-size: 12px; opacity: 0.8; white-space: nowrap; }
.mj-inline { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mj-inline .mj-img { width: 22px; }

/* ---- 解説の部品 */
.mj-card { border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 10px; padding: 10px 12px; }
.mj-chips { margin-bottom: 4px; }
.mj-chip {
  display: inline-block;
  padding: 1px 8px;
  margin: 0 4px 4px 0;
  border-radius: 999px;
  background: rgba(128, 128, 128, 0.18);
  font-size: 12px;
}
.mj-big { font-size: 1.7rem; font-weight: 700; line-height: 1.5; }
.mj-level {
  font-size: 0.9rem;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  background: #e8a400;
  color: #1b1b1b;
  vertical-align: middle;
}
.mj-bad { color: #d9534f; }
.mj-sub { font-size: 12.5px; opacity: 0.85; line-height: 1.7; }
.mj-note { font-size: 14px; line-height: 1.8; margin-top: 6px; }
.mj-subhead { font-size: 14px; font-weight: 700; margin: 14px 0 6px; }
.mj-table { width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.7; }
.mj-table td { padding: 5px 4px; border: none; border-bottom: 1px solid rgba(128, 128, 128, 0.25); vertical-align: top; }
.mj-table td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.mj-table tr.total td { font-weight: 700; border-top: 2px solid rgba(128, 128, 128, 0.5); border-bottom: none; }
.mj-table tr.mj-dim td { opacity: 0.55; }
.mj-reading { font-size: 11.5px; opacity: 0.75; margin-left: 4px; }
.mj-checks { list-style: none; margin: 4px 0 2px; padding: 0; font-size: 12.5px; line-height: 1.7; }
.mj-checks li { display: flex; gap: 5px; }
.mj-checks li > span { flex: 1; }
.mj-ok::before { content: "✓"; color: #2e9d57; font-weight: 700; }
.mj-ng::before { content: "✗"; color: #d9534f; font-weight: 700; }
.mj-why { opacity: 0.75; }
.mj-why::before { content: " … "; }
.mj-near { padding: 6px 4px; border-bottom: 1px solid rgba(128, 128, 128, 0.25); font-size: 14px; line-height: 1.7; }
.mj-near-hint::before { content: "→ "; opacity: 0.7; }
.mj-formula {
  font-size: 15px;
  line-height: 2;
  padding: 8px 10px;
  margin-top: 6px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.12);
  font-variant-numeric: tabular-nums;
}
.mj-steps { font-size: 13.5px; line-height: 1.9; margin: 8px 0 0; padding-left: 1.4em; }
.mj-rules { font-size: 13.5px; line-height: 1.9; margin: 0; padding-left: 1.3em; }
.mj-details { margin-top: 10px; font-size: 13.5px; }
.mj-details summary { cursor: pointer; opacity: 0.85; }
.mj-say {
  font-size: 1.15rem;
  font-weight: 700;
  line-height: 1.8;
  padding: 10px 12px;
  border-left: 4px solid #e8a400;
  border-radius: 4px;
  background: rgba(232, 164, 0, 0.1);
}
.mj-alt { border: 1px dashed rgba(128, 128, 128, 0.45); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.mj-alt-head { font-size: 13px; font-weight: 700; margin-bottom: 6px; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
.mj-alt-result { font-weight: 400; margin-left: auto; }
.mj-adopt { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: #2e9d57; color: #fff; }
.mj-lesson { border-left: 4px solid #4a90d9; background: rgba(74, 144, 217, 0.1); padding: 8px 12px; border-radius: 4px; font-size: 14px; line-height: 1.8; }
</style>
"""


def apply_base_style() -> None:
    """共通のスタイルを入れる。app.py で 1 度呼ぶ"""
    st.html(_BASE_STYLE)

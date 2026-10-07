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
.mj-big > ruby > rt { font-size: 11px; font-weight: 400; }   /* 大きな文字に付けるルビは、文字に合わせて大きくしない */
/* 解説の見出し。Streamlit の見出し（st.subheader）と同じ見た目にしてある。見出しの中の用語にルビを振りたいので、自前で出している。
   すぐ下に本文が続くので、部品どうしの間隔（1rem）のぶんを下に空ける。幅の狭い画面では、上の h3 の決まりで小さくなる */
.mj-h3 { font-size: 1.75rem; font-weight: 600; line-height: 1.2; letter-spacing: -0.005em; padding: 0.75rem 0 1rem; margin: 0 0 1rem; }
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
.mj-subhead-first { margin: 2px 0 2px; }
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

/* ---- 一人練習 */
img.mj-img.mj-s { display: inline-block; width: 18px; vertical-align: middle; }
.mj-statusbar { margin: 0 0 2px; }
.mj-chip-tiles img.mj-img.mj-s { width: 15px; margin: 1px 0 2px; }
.mj-chip-luck { background: rgba(232, 164, 0, 0.3); }
.mj-chip-plain { background: rgba(46, 157, 87, 0.28); }
.mj-chip-target { background: rgba(74, 144, 217, 0.3); }
.mj-missing { opacity: 0.3; outline: 1.5px dashed rgba(128, 128, 128, 0.9); outline-offset: -1px; filter: none; }
.mj-blocks-tight { gap: 6px 5px; }
.mj-headline {
  /* 2 行ぶん（牌の画像やルビが入った行を含む）がちょうど収まる高さに固定する。
     1 行のときも同じ高さにして、巡目によって手牌の位置が上下しないようにする */
  display: flex;
  align-items: center;
  min-height: 72px;
  box-sizing: border-box;
  font-size: 15px;
  line-height: 1.75;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.12);
  border-left: 4px solid rgba(128, 128, 128, 0.5);
}
.mj-headline-in { flex: 1; min-width: 0; }
.mj-headline-short { display: block; min-height: 0; margin-bottom: 8px; }
@media (max-width: 350px) {
  .mj-headline { min-height: 96px; }      /* 幅の狭い画面では 3 行になることが多い */
  .mj-headline-short { min-height: 0; }
}
.mj-headline.good, .mj-review.good { border-left-color: #2e9d57; }
.mj-headline.soso, .mj-review.soso { border-left-color: #e8a400; }
.mj-headline.bad, .mj-review.bad { border-left-color: #d9534f; }
.mj-stage { font-size: 1.05rem; }
.mj-dimtext { opacity: 0.7; font-size: 13.5px; }
.mj-icon { display: inline-block; min-width: 1.3em; text-align: center; font-weight: 700; }
.mj-icon.good { color: #2e9d57; }
.mj-icon.soso { color: #c98a00; }
.mj-icon.bad { color: #d9534f; }
.mj-river { display: grid; grid-template-columns: repeat(6, 27px); gap: 3px 2px; margin-top: 4px; }
.mj-river > span { display: flex; align-items: center; justify-content: center; width: 27px; height: 36px; }
.mj-river img.mj-img { width: 27px; }
.mj-river img.mj-sideways { transform: rotate(90deg) scale(0.8); }
.mj-draws { row-gap: 9px; padding-top: 6px; }
.mj-draws > span { position: relative; }
.mj-star { position: absolute; top: -9px; right: -2px; font-style: normal; font-size: 12px; line-height: 1; color: #c98a00; }
.mj-lucknote { font-size: 13px; line-height: 1.9; }
.mj-review {
  border-left: 4px solid rgba(128, 128, 128, 0.5);
  border-radius: 4px;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.8;
  background: rgba(128, 128, 128, 0.08);
}
.mj-review.good { background: rgba(46, 157, 87, 0.1); }
.mj-review.soso { background: rgba(232, 164, 0, 0.1); }
.mj-review.bad { background: rgba(217, 83, 79, 0.1); }
.mj-review-head { font-size: 12.5px; opacity: 0.85; }
.mj-review ul { margin: 4px 0 0; padding-left: 1.3em; font-size: 13px; }
.mj-cands { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.mj-cand { border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px; padding: 6px 8px; }
.mj-cand-pick { border-color: #e8a400; background: rgba(232, 164, 0, 0.08); }
.mj-cand-you { outline: 2px dashed rgba(74, 144, 217, 0.85); outline-offset: 1px; }
.mj-cand-head { display: flex; align-items: center; gap: 6px; font-size: 14px; }
.mj-cand-mark { width: 1.2em; text-align: center; font-weight: 700; color: #c98a00; }
.mj-cand-name { font-weight: 700; }
.mj-cand-num { margin-left: auto; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mj-cand-tiles { display: flex; flex-wrap: wrap; gap: 4px 9px; margin: 5px 0 0 1.6em; }
.mj-acc { display: inline-flex; align-items: center; gap: 2px; font-size: 12px; font-variant-numeric: tabular-nums; }
.mj-acc-dead { opacity: 0.35; }
.mj-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1.6;
  background: #d9534f;
  color: #fff;
  vertical-align: middle;
}
.mj-badge-you { background: #4a90d9; }
.mj-minus { color: #d9534f; font-size: 12px; margin-left: 4px; }
.mj-farrow { display: flex; flex-wrap: wrap; gap: 5px; }
.mj-far img.mj-img.mj-s { width: 22px; opacity: 0.8; }
.mj-far-you img.mj-img.mj-s { outline: 2px dashed rgba(74, 144, 217, 0.9); outline-offset: 1px; opacity: 1; }
.mj-legend { margin-top: 8px; }
.mj-waits td { vertical-align: middle; border-bottom: none; padding: 3px 4px; }
.mj-wait-head { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; font-size: 13px; margin-bottom: 2px; }
.mj-wait-how { width: 6.5em; font-size: 12.5px; opacity: 0.85; white-space: nowrap; }
.mj-part .mj-block-tiles { padding-bottom: 3px; border-bottom: 4px solid transparent; }
.mj-part .mj-cap { text-align: center; line-height: 1.4; }
.mj-part-done .mj-block-tiles { border-bottom-color: #2e9d57; }
.mj-part-pair .mj-block-tiles { border-bottom-color: #4a90d9; }
.mj-part-wait .mj-block-tiles { border-bottom-color: #e8a400; }
.mj-part-float .mj-block-tiles { border-bottom-color: rgba(128, 128, 128, 0.6); }
.mj-need { font-size: 11px; opacity: 0.85; }
.mj-key { display: inline-block; width: 14px; height: 5px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
.mj-key.mj-part-done { background: #2e9d57; }
.mj-key.mj-part-pair { background: #4a90d9; }
.mj-key.mj-part-wait { background: #e8a400; }
.mj-key.mj-part-float { background: rgba(128, 128, 128, 0.6); }
.mj-reviewlist td { vertical-align: middle; }

/* ---- 役図鑑・用語辞典・ドリル */
.mj-home-head { font-size: 1.05rem; margin-top: 18px; padding-bottom: 2px; border-bottom: 2px solid rgba(128, 128, 128, 0.35); }
.mj-topgap { height: 2px; }
.mj-yaku-head { margin-top: 2px; }
.mj-reading-big { font-size: 14px; }
.mj-chip-han { background: rgba(232, 164, 0, 0.3); font-weight: 700; }
.mj-freq-good { background: rgba(46, 157, 87, 0.3); }
.mj-freq-soso { background: rgba(232, 164, 0, 0.3); }
.mj-freq-rare { background: rgba(128, 128, 128, 0.3); }
.mj-ex { border: 1px solid rgba(128, 128, 128, 0.35); border-left-width: 4px; border-radius: 8px; padding: 8px 10px 10px; margin-top: 10px; }
.mj-ex-ok { border-left-color: #2e9d57; }
.mj-ex-ng { border-left-color: #d9534f; }
.mj-ex-title { font-size: 14px; font-weight: 700; margin-bottom: 6px; line-height: 1.6; }
.mj-ex-mark.good { color: #2e9d57; }
.mj-ex-mark.bad { color: #d9534f; }
.mj-ex .mj-hand { margin-top: 2px; }
.mj-ex .mj-river { margin-top: 2px; }
.mj-result { display: flex; flex-wrap: wrap; gap: 2px 12px; align-items: baseline; margin-top: 8px; padding: 6px 8px; border-radius: 6px; background: rgba(128, 128, 128, 0.12); font-size: 14px; line-height: 1.7; }
.mj-result-num { margin-left: auto; white-space: nowrap; font-variant-numeric: tabular-nums; }
.mj-origin td:first-child { white-space: nowrap; opacity: 0.8; font-size: 12.5px; padding-right: 10px; }
.mj-cert { display: inline-block; padding: 0 7px; border-radius: 999px; font-size: 11px; line-height: 1.7; white-space: nowrap; vertical-align: middle; }
.mj-cert-sure { background: rgba(46, 157, 87, 0.3); }
.mj-cert-likely { background: rgba(74, 144, 217, 0.3); }
.mj-cert-mixed { background: rgba(232, 164, 0, 0.35); }
.mj-cert-unknown { background: rgba(128, 128, 128, 0.3); }
.mj-termcard { border-bottom: 1px solid rgba(128, 128, 128, 0.3); padding: 10px 2px 12px; }
.mj-term-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; }
.mj-term-word { font-size: 1.15rem; }
.mj-term-ex { margin: 6px 0 2px; }
.mj-termcard .mj-table { margin-top: 6px; font-size: 13px; }
.mj-sources { word-break: break-all; }
.mj-star-inline { color: #c98a00; }
.mj-sides td:first-child { width: 46%; }
.mj-score td { padding-top: 3px; padding-bottom: 3px; font-size: 13.5px; }
.mj-score { margin-bottom: 12px; }
.mj-prompt { font-size: 1.2rem; font-weight: 700; line-height: 1.7; margin: 4px 0 2px; }
.mj-choices { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.mj-choice { display: flex; gap: 6px; border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px; padding: 6px 8px; font-size: 14px; line-height: 1.7; }
.mj-choice-mark { width: 1.2em; text-align: center; font-weight: 700; }
.mj-choice-body { flex: 1; min-width: 0; }
.mj-choice-right { border-color: #2e9d57; background: rgba(46, 157, 87, 0.1); }
.mj-choice-right .mj-choice-mark { color: #2e9d57; }
.mj-choice-wrong { border-color: #d9534f; background: rgba(217, 83, 79, 0.1); }
.mj-choice-wrong .mj-choice-mark { color: #d9534f; }
.mj-choice-other { opacity: 0.75; }
.mj-kind-note { margin: -8px 0 6px 2px; }
.mj-river-cap { margin-top: 12px; }
.mj-guide-head { display: flex; align-items: baseline; gap: 8px; margin: 10px 0 4px; font-size: 1.05rem; line-height: 1.7; }
.mj-guide-num { display: inline-block; min-width: 1.7em; padding: 0 5px; border-radius: 999px; background: rgba(74, 144, 217, 0.3); font-size: 13px; font-weight: 700; text-align: center; font-variant-numeric: tabular-nums; }
.mj-stats td { padding-left: 2px; padding-right: 2px; font-size: 13px; }
.mj-stats tr.mj-skill td { background: rgba(46, 157, 87, 0.12); }
</style>
"""


def apply_base_style() -> None:
    """共通のスタイルを入れる。app.py で 1 度呼ぶ"""
    st.html(_BASE_STYLE)

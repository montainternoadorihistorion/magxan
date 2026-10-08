// 画面のスクロールの位置を動かす部品（見えるものは何も出さない）。
//
// 受け取るデータ（Python → ここ）: { rev, reveal }
//   rev が変わるたびに 1 回、画面を動かす。
//   reveal が空なら、いちばん上に戻す（ドリルで次の問題に進んだとき、問題文が見える位置にするため）。
//   reveal に CSS セレクタが入っていれば、それに合う要素（それぞれ最初の 1 つ）が見えるところまでだけ動かす
//   （ドリルで答えた直後に、正解・不正解の帯と「次の問題」が見えるようにするため。もう見えていれば動かさない）。
//
// この部品は Shadow DOM の中にあるので、外側へたどりながら、スクロールできる祖先をすべて先頭に戻す
// （Streamlit の画面は、ページ全体ではなく中の枠がスクロールする）。

function scrollPageToTop(start) {
  let node = start;
  while (node) {
    if (node.nodeType === 1) {
      const overflow = getComputedStyle(node).overflowY;
      if ((overflow === "auto" || overflow === "scroll") && node.scrollTop > 0) node.scrollTop = 0;
    }
    node = node.parentNode || node.host || null;
  }
  window.scrollTo(0, 0);
}

// 要素が見えるところまでだけ動かす。後ろの要素から順に「いちばん近い位置へ」動かし、最後に先頭の要素を動かすので、
// まとめて画面に入らないときは、先頭の要素が見える。上の帯（メニュー）に隠れないぶんの余白は、CSS の scroll-margin で付ける
function reveal(selectors) {
  const found = selectors.map((selector) => document.querySelector(selector)).filter(Boolean);
  for (let i = found.length - 1; i >= 0; i -= 1) found[i].scrollIntoView({ block: "nearest", inline: "nearest" });
  return found.length > 0;
}

export default function (component) {
  const { data, parentElement } = component;
  const state = parentElement.__mjScrollTop || (parentElement.__mjScrollTop = { rev: undefined });
  if (state.rev === data.rev) return;
  state.rev = data.rev;
  const selectors = Array.isArray(data.reveal) ? data.reveal.filter((s) => typeof s === "string" && s) : [];
  if (selectors.length) {
    reveal(selectors);
    // 画面の残りの部分が描き直されたあとで、もう一度（描き直しの途中で位置がずれることがあるため）
    requestAnimationFrame(() => reveal(selectors));
    setTimeout(() => reveal(selectors), 250);
    return;
  }
  scrollPageToTop(parentElement);
  requestAnimationFrame(() => scrollPageToTop(parentElement));
}

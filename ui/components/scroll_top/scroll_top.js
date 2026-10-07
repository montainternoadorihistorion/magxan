// 画面のいちばん上までスクロールを戻す部品（見えるものは何も出さない）。
//
// 受け取るデータ（Python → ここ）: { rev }
//   rev が変わるたびに 1 回、先頭に戻す（ドリルで次の問題に進んだとき、問題文が見える位置にするため）。
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

export default function (component) {
  const { data, parentElement } = component;
  const state = parentElement.__mjScrollTop || (parentElement.__mjScrollTop = { rev: undefined });
  if (state.rev === data.rev) return;
  state.rev = data.rev;
  scrollPageToTop(parentElement);
  // 画面の残りの部分が描き直されたあとで、もう一度（描き直しの途中で位置がずれることがあるため）
  requestAnimationFrame(() => scrollPageToTop(parentElement));
}

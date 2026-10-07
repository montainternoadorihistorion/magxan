// 手牌をタップして切るための部品（Streamlit カスタムコンポーネント v2）。
//
// 受け取るデータ（Python → ここ）:
//   rev          Python 側が行動を 1 つ処理するたびに増える番号。これが変わる＝サーバーが応答した、とみなす
//   tiles        [{ id, src, label, short, mark, markLabel }]  並べる順。id は牌ID。mark は牌の左上に出す印（無ければ空）
//   drawnId      ツモ牌の牌ID（無ければ null）
//   drawnLabel   ツモ牌の下に出す文字（既定「ツモ」）
//   enabled      false なら表示だけ
//   prompt       何も選んでいないときの案内文
//   confirmLabel 確定ボタンの文字
//   riichiIds    リーチを宣言して切れる牌ID の一覧。空ならリーチのボタンを出さない
//   twoRows      true なら、案内文を上の段、ボタンを下の段に、いつも分けて置く（リーチのボタンが出たり消えたり
//                しても、確定ボタンの位置が動かないようにする）
//   scrollTop    true なら、画面のいちばん上までスクロールを戻す（新しい局を始めたとき）。同じ rev では 1 回だけ
//
// 送る値（ここ → Python）: 確定したとき 1 回だけ "pick" を送る
//   { id, rev, riichi, prevMs, vw, vh, dpr, imgNg }
//   riichi は、リーチを宣言して切るとき true
//   prevMs は「ひとつ前の確定」から画面が更新されるまでにかかった時間（ミリ秒）。体感の応答時間の計測に使う
//
// リーチの操作: 「リーチ」を押すと、切れる牌（聴牌を保てる牌）だけが明るく残る。牌を選んで確定するとリーチ。
// もう一度「リーチ」を押すと取り消し。
//
// この関数は、最初に表示されたときと、Python から届くデータが変わったときに呼ばれる。
// 画面の要素は呼び出しをまたいで残るので、状態は要素に持たせ、中身は毎回データから作り直す。

const PENDING_TIMEOUT_MS = 8000;

// 画面のいちばん上までスクロールを戻す。この部品は Shadow DOM の中にあるので、外側へたどりながら、
// スクロールできる祖先をすべて先頭に戻す（Streamlit の画面は、ページ全体ではなく中の枠がスクロールする）。
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
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".mj-hand-root");
  const grid = root.querySelector(".mj-grid");
  const status = root.querySelector(".mj-status");
  const confirm = root.querySelector(".mj-confirm");
  const riichi = root.querySelector(".mj-riichi");
  const note = root.querySelector(".mj-note");

  const state =
    root.__mj || (root.__mj = { picked: null, pending: null, timer: null, lastMs: null, imgNg: 0, riichi: false, rev: null });

  // 直前に送った確定への応答が届いた（rev が進んだ）→ かかった時間を記録して待ち状態を解く
  if (state.pending && state.pending.rev !== data.rev) {
    state.lastMs = Math.round(performance.now() - state.pending.t0);
    clearPending();
    note.textContent = "";
  }
  if (state.rev !== data.rev) state.riichi = false; // 局面が進んだら、リーチの選択は解く
  if (data.scrollTop && state.scrolledRev !== data.rev) {
    state.scrolledRev = data.rev;
    scrollPageToTop(parentElement);
    // 画面の残りの部分が描き直されたあとで、もう一度（描き直しの途中で位置がずれることがあるため）
    requestAnimationFrame(() => scrollPageToTop(parentElement));
  }
  state.rev = data.rev;
  state.picked = null;
  state.imgNg = 0; // 今回の表示で読めなかった画像の数（並べ直すたびに数え直す）

  const tiles = Array.isArray(data.tiles) ? data.tiles : [];
  const byId = new Map(tiles.map((t) => [t.id, t]));
  const riichiIds = new Set(Array.isArray(data.riichiIds) ? data.riichiIds : []);
  if (!riichiIds.size) state.riichi = false;

  function clearPending() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    state.pending = null;
    root.classList.remove("mj-pending");
  }

  function selectable(id) {
    return !state.riichi || riichiIds.has(id);
  }

  function refresh() {
    grid.querySelectorAll(".mj-tile").forEach((el) => {
      const id = Number(el.dataset.id);
      el.setAttribute("aria-pressed", String(id === state.picked));
      el.classList.toggle("mj-dim", !selectable(id));
    });
    const picked = state.picked === null ? null : byId.get(state.picked);
    if (state.pending) {
      status.textContent = "送信中…";
    } else if (picked) {
      status.textContent = "選択中：" + picked.label;
    } else if (!data.enabled) {
      status.textContent = "";
    } else if (state.riichi) {
      status.textContent = "リーチ：明るい牌から選ぶ";
    } else {
      status.textContent = data.prompt || "";
    }
    confirm.textContent = state.riichi ? "リーチして切る" : data.confirmLabel || "この牌を切る";
    confirm.disabled = !data.enabled || !picked || Boolean(state.pending);
    riichi.hidden = !data.enabled || riichiIds.size === 0;
    riichi.disabled = Boolean(state.pending);
    riichi.setAttribute("aria-pressed", String(state.riichi));
    riichi.textContent = state.riichi ? "やめる" : "リーチ";
    root.classList.toggle("mj-riichi-on", state.riichi);
    // リーチのボタンがあるあいだは、案内文を上の段、ボタンを下の段に固定する
    // （牌を選ぶと案内文の長さが変わる。同じ段に置くと、そのたびにボタンの位置が動いてしまう）。
    // twoRows が指定されていれば、いつも 2 段にする（巡目によって確定ボタンの高さが変わらないように）
    root.classList.toggle("mj-two-rows", Boolean(data.twoRows) || !riichi.hidden);
  }

  function send() {
    if (!data.enabled || state.pending || state.picked === null) return;
    state.pending = { rev: data.rev, t0: performance.now() };
    root.classList.add("mj-pending");
    state.timer = setTimeout(() => {
      // 応答が返らないまま時間が過ぎた（通信切れなど）。押し直せるように戻す
      clearPending();
      note.textContent = "応答がありません。通信を確かめて、もう一度押してください。";
      refresh();
    }, PENDING_TIMEOUT_MS);
    refresh();
    setTriggerValue("pick", {
      id: state.picked,
      rev: data.rev,
      riichi: state.riichi && riichiIds.has(state.picked),
      prevMs: state.lastMs,
      vw: window.innerWidth,
      vh: window.innerHeight,
      dpr: window.devicePixelRatio || 1,
      imgNg: state.imgNg,
    });
  }

  // 牌を並べ直す
  grid.replaceChildren();
  for (const t of tiles) {
    const isDrawn = t.id === data.drawnId;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mj-tile" + (isDrawn ? " mj-drawn" : "");
    btn.dataset.id = String(t.id);
    if (isDrawn) btn.dataset.note = data.drawnLabel || "ツモ";
    const extras = (isDrawn ? "（ツモ牌）" : "") + (t.mark && t.markLabel ? "（" + t.markLabel + "）" : "");
    btn.setAttribute("aria-label", t.label + extras);
    btn.setAttribute("aria-pressed", "false");

    const img = document.createElement("img");
    img.alt = "";
    img.decoding = "async";
    img.draggable = false;
    img.onerror = () => {
      // 画像が届かないときは文字で表示する（操作は続けられる）
      state.imgNg += 1;
      btn.classList.add("mj-noimg");
      const text = document.createElement("span");
      text.textContent = t.short || t.label;
      btn.appendChild(text);
    };
    img.src = t.src;
    btn.appendChild(img);

    if (t.mark) {
      const mark = document.createElement("span");
      mark.className = "mj-mark";
      mark.textContent = t.mark;
      mark.setAttribute("aria-hidden", "true");
      btn.appendChild(mark);
    }

    btn.onclick = () => {
      if (!data.enabled || state.pending || !selectable(t.id)) return;
      if (state.picked === t.id) {
        send(); // 選んだ牌をもう一度タップしたら確定
        return;
      }
      state.picked = t.id;
      note.textContent = "";
      refresh();
    };
    grid.appendChild(btn);
  }

  confirm.onclick = send;
  riichi.onclick = () => {
    if (!data.enabled || state.pending || !riichiIds.size) return;
    state.riichi = !state.riichi;
    if (state.picked !== null && !selectable(state.picked)) state.picked = null;
    note.textContent = "";
    refresh();
  };
  root.classList.toggle("mj-off", !data.enabled);
  refresh();

  // 画面から外れるときはタイマーを止める
  return () => {
    if (state.timer) clearTimeout(state.timer);
  };
}

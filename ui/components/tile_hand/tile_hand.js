// 手牌をタップして切るための部品（Streamlit カスタムコンポーネント v2）。
//
// 受け取るデータ（Python → ここ）:
//   rev          Python 側が行動を 1 つ処理するたびに増える番号。これが変わる＝サーバーが応答した、とみなす
//   tiles        [{ id, src, label, short }]  並べる順。id は牌ID
//   drawnId      ツモ牌の牌ID（無ければ null）
//   enabled      false なら表示だけ
//   prompt       何も選んでいないときの案内文
//   confirmLabel 確定ボタンの文字
//
// 送る値（ここ → Python）: 確定したとき 1 回だけ "pick" を送る
//   { id, rev, prevMs, vw, vh, dpr, imgNg }
//   prevMs は「ひとつ前の確定」から画面が更新されるまでにかかった時間（ミリ秒）。体感の応答時間の計測に使う
//
// この関数は、最初に表示されたときと、Python から届くデータが変わったときに呼ばれる。
// 画面の要素は呼び出しをまたいで残るので、状態は要素に持たせ、中身は毎回データから作り直す。

const PENDING_TIMEOUT_MS = 8000;

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".mj-hand-root");
  const grid = root.querySelector(".mj-grid");
  const status = root.querySelector(".mj-status");
  const confirm = root.querySelector(".mj-confirm");
  const note = root.querySelector(".mj-note");

  const state = root.__mj || (root.__mj = { picked: null, pending: null, timer: null, lastMs: null, imgNg: 0 });

  // 直前に送った確定への応答が届いた（rev が進んだ）→ かかった時間を記録して待ち状態を解く
  if (state.pending && state.pending.rev !== data.rev) {
    state.lastMs = Math.round(performance.now() - state.pending.t0);
    clearPending();
    note.textContent = "";
  }
  state.picked = null;
  state.imgNg = 0; // 今回の表示で読めなかった画像の数（並べ直すたびに数え直す）

  const tiles = Array.isArray(data.tiles) ? data.tiles : [];
  const byId = new Map(tiles.map((t) => [t.id, t]));

  function clearPending() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    state.pending = null;
    root.classList.remove("mj-pending");
  }

  function refresh() {
    grid.querySelectorAll(".mj-tile").forEach((el) => {
      el.setAttribute("aria-pressed", String(Number(el.dataset.id) === state.picked));
    });
    const picked = state.picked === null ? null : byId.get(state.picked);
    if (state.pending) {
      status.textContent = "送信中…";
    } else if (picked) {
      status.textContent = "選択中：" + picked.label;
    } else {
      status.textContent = data.enabled ? data.prompt || "" : "";
    }
    confirm.disabled = !data.enabled || !picked || Boolean(state.pending);
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
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mj-tile" + (t.id === data.drawnId ? " mj-drawn" : "");
    btn.dataset.id = String(t.id);
    btn.setAttribute("aria-label", t.label + (t.id === data.drawnId ? "（ツモ牌）" : ""));
    btn.setAttribute("aria-pressed", "false");

    const img = document.createElement("img");
    img.alt = "";
    img.decoding = "async";
    img.draggable = false;
    img.onerror = () => {
      // 画像が届かないときは文字で表示する（操作は続けられる）
      state.imgNg += 1;
      btn.classList.add("mj-noimg");
      btn.textContent = t.short || t.label;
    };
    img.src = t.src;
    btn.appendChild(img);

    btn.onclick = () => {
      if (!data.enabled || state.pending) return;
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

  confirm.textContent = data.confirmLabel || "この牌を切る";
  confirm.onclick = send;
  root.classList.toggle("mj-off", !data.enabled);
  refresh();

  // 画面から外れるときはタイマーを止める
  return () => {
    if (state.timer) clearTimeout(state.timer);
  };
}

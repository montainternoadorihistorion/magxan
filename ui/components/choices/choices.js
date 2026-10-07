// 答えの選択肢を並べる部品（ドリル）。
//
// 受け取るデータ（Python → ここ）:
//   rev          問題ごとに変わる番号。値が変わったら「サーバーが応答した」とみなし、次の入力を受け付ける
//   options      選択肢の一覧。{ key, parts, img, alt }
//                  parts は [文字, 読み] の並び（読みが空でなければ、その文字にルビを振る）
//                  img は、牌の画像の URL（無ければ null）。alt は、その牌の名前
//   multi        true なら、いくつでも選べる（選んでから「確定」を押す）。false なら、押した選択肢がそのまま答えになる
//   layout       "list"（縦に並べる）／"row"（横に 2 つ並べる）／"chips"（折り返しながら並べる）
//   confirmLabel 確定ボタンの文字（multi のときだけ使う）
//   prompt       何も選んでいないときの案内文（multi のときだけ使う）
//   selected     はじめから選んである選択肢の鍵（設定の切り替えに使うとき、いまの値を示す）。
//                multi でないとき、選んである選択肢をもう一度押しても、何も送らない
//
// 送る値（ここ → Python）: 答えたとき 1 回だけ "pick" を送る  { rev, keys }
//
// 選択肢の文字は、HTML としてではなく文字として入れる（部品に渡った文字が、タグとして働くことはない）。
//
// この関数は、最初に表示されたときと、Python から届くデータが変わったときに呼ばれる。
// 画面の要素は呼び出しをまたいで残るので、状態は要素に持たせ、中身は毎回データから作り直す。

const PENDING_TIMEOUT_MS = 12000;

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".mj-choices-root");
  const list = root.querySelector(".mj-opts");
  const status = root.querySelector(".mj-status");
  const confirm = root.querySelector(".mj-confirm");
  const note = root.querySelector(".mj-note");

  const state = root.__mjState || (root.__mjState = { rev: null, picked: new Set(), pending: false, timer: null });

  function clearPending() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    state.pending = false;
    root.classList.remove("mj-pending");
  }

  const selected = Array.isArray(data.selected) ? data.selected : [];
  if (state.rev !== data.rev) {
    // 新しい問題（または、サーバーが応答した）。選択を、はじめの状態に戻す
    clearPending();
    state.rev = data.rev;
    state.picked = new Set(selected);
    note.textContent = "";
  }

  const options = Array.isArray(data.options) ? data.options : [];
  const known = new Set(options.map((o) => o.key));
  for (const key of [...state.picked]) if (!known.has(key)) state.picked.delete(key);
  const multi = Boolean(data.multi);

  function refresh() {
    list.querySelectorAll(".mj-opt").forEach((el) => {
      el.setAttribute("aria-pressed", String(state.picked.has(el.dataset.key)));
    });
    confirm.hidden = !multi;
    confirm.textContent = data.confirmLabel || "これで答える";
    confirm.disabled = state.pending || state.picked.size === 0;
    if (state.pending) status.textContent = "送信中…";
    else if (!multi) status.textContent = "";
    else if (state.picked.size) status.textContent = state.picked.size + " つ選択中";
    else status.textContent = data.prompt || "";
  }

  function send() {
    if (state.pending || state.picked.size === 0) return;
    state.pending = true;
    root.classList.add("mj-pending");
    state.timer = setTimeout(() => {
      // 応答が返らないまま時間が過ぎた（通信切れなど）。押し直せるように戻す
      clearPending();
      note.textContent = "応答がありません。通信を確かめて、もう一度押してください。";
      refresh();
    }, PENDING_TIMEOUT_MS);
    refresh();
    // 選択肢の並び順で送る
    setTriggerValue("pick", { rev: data.rev, keys: options.map((o) => o.key).filter((key) => state.picked.has(key)) });
  }

  list.replaceChildren();
  for (const option of options) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mj-opt";
    btn.dataset.key = option.key;
    btn.setAttribute("aria-pressed", "false");
    if (option.img) {
      const img = document.createElement("img");
      img.alt = option.alt || "";
      img.decoding = "async";
      img.draggable = false;
      img.src = option.img;
      btn.appendChild(img);
    }
    const text = document.createElement("span");
    for (const part of Array.isArray(option.parts) ? option.parts : []) {
      const [chars, reading] = part;
      if (reading) {
        const ruby = document.createElement("ruby");
        ruby.appendChild(document.createTextNode(chars));
        const rt = document.createElement("rt");
        rt.textContent = reading;
        ruby.appendChild(rt);
        text.appendChild(ruby);
      } else {
        text.appendChild(document.createTextNode(chars));
      }
    }
    btn.appendChild(text);
    btn.onclick = () => {
      if (state.pending) return;
      note.textContent = "";
      if (!multi) {
        if (selected.includes(option.key)) return; // もう選んである（設定の切り替えで、同じ値をもう一度押した）
        state.picked = new Set([option.key]);
        send(); // 1 つ選ぶ問題は、押した選択肢がそのまま答え
        return;
      }
      if (state.picked.has(option.key)) state.picked.delete(option.key);
      else state.picked.add(option.key);
      refresh();
    };
    list.appendChild(btn);
  }

  confirm.onclick = send;
  root.classList.toggle("mj-row", data.layout === "row");
  root.classList.toggle("mj-chips", data.layout === "chips");
  refresh();

  // 画面から外れるときはタイマーを止める
  return () => {
    if (state.timer) clearTimeout(state.timer);
  };
}

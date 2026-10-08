// 牌譜を 1 手ずつ見る部品（Streamlit カスタムコンポーネント v2）。値は送り返さない（見るだけ）。
//
// 受け取るデータ（Python → ここ）:
//   ident    牌譜ごとに違う名前。変わったら、最初（startAt）から見せる
//   record   engine.kifu.Kifu.to_dict() の形に、読み（ルビ）つきの HTML を足したもの
//            { title, dealer, winds, names, start: { hands, drawn, scores, dora, live, honba, kyotaku },
//              steps: [{ i, s, text, html, ev: [...], mine, note: { mark, grade, label, labelHtml, text, textHtml } }],
//              result, startHtml }
//   images   牌ID ごとの画像と名前 [{ src, label }]（136 枚）
//   back     裏向きの牌の画像
//   startAt  最初に見せる手順の位置（0 ＝ 配牌）
//
// 盤面は、最初の盤面に手順の ev を順に当てはめて作る（engine/kifu.py の board_at と同じ当てはめ方）:
//   discard { s, t, g, q }      河に足す（g ＝ ツモ切り、q ＝ リーチ宣言牌）
//   called  { s, n }            河の n 枚目に「鳴かれた」の印
//   meld    { s, m, disp }      副露を足す（disp は [牌, 横向き, 裏向き] の並び）
//   kakan   { s, n, disp }      n 組目の副露（ポン）を加槓にする
//   dora    { t }               ドラ表示牌を足す
//   stick   { s }               リーチ棒（その人の点 −1000、供託 ＋1）
//   hand    { s, h, d }         門前の手牌とツモ牌を置き換える
//   live    { n }               山の残り枚数
//   scores  { v }               局の終わりの持ち点
// 位置を戻すときは、最初から当てはめ直す（手順は多くても数百なので、すぐに終わる）。

const ORDER = [1, 2, 3, 0]; // 下家・対面・上家・自分（対局の画面の河と同じ順）

export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".kf-root");
  const head = root.querySelector(".kf-head");
  const caption = root.querySelector(".kf-caption");
  const board = root.querySelector(".kf-board");
  const slider = root.querySelector(".kf-slider");
  const buttons = {};
  root.querySelectorAll(".kf-btn").forEach((el) => (buttons[el.dataset.go] = el));

  const record = data.record || {};
  const steps = Array.isArray(record.steps) ? record.steps : [];
  const images = Array.isArray(data.images) ? data.images : [];
  const state = root.__kf || (root.__kf = { pos: 0, ident: null });
  if (state.ident !== data.ident) {
    state.ident = data.ident;
    state.pos = Math.max(0, Math.min(steps.length, Number(data.startAt) || 0));
  }
  const mine = steps.map((s, i) => (s.mine ? i + 1 : null)).filter((x) => x !== null);

  function tileImg(id, cls) {
    const img = document.createElement("img");
    const info = images[id] || {};
    img.src = info.src || "";
    img.alt = info.label || "";
    img.title = info.label || "";
    img.draggable = false;
    if (cls) img.className = cls;
    return img;
  }

  // 文を入れる。読み（ルビ）つきの HTML があればそれを、無ければ文字のまま
  function setText(el, html, plain) {
    if (typeof html === "string" && html) el.innerHTML = html;
    else el.textContent = plain || "";
  }

  function backImg() {
    const img = document.createElement("img");
    img.src = data.back || "";
    img.alt = "裏向きの牌";
    img.draggable = false;
    return img;
  }

  function boardAt(n) {
    const start = record.start || {};
    const b = {
      hands: (start.hands || [[], [], [], []]).map((h) => h.slice()),
      drawn: (start.drawn || [null, null, null, null]).slice(),
      rivers: [[], [], [], []],
      melds: [[], [], [], []],
      scores: (start.scores || [0, 0, 0, 0]).slice(),
      riichi: [false, false, false, false],
      dora: (start.dora || []).slice(),
      live: start.live,
      kyotaku: start.kyotaku || 0,
      last: null,
    };
    for (const step of steps.slice(0, n)) {
      for (const ev of step.ev || []) {
        switch (ev.k) {
          case "discard":
            b.rivers[ev.s].push({ t: ev.t, g: ev.g, q: ev.q, called: false });
            if (ev.q) b.riichi[ev.s] = true;
            b.last = [ev.s, b.rivers[ev.s].length - 1];
            break;
          case "called":
            if (b.rivers[ev.s][ev.n]) b.rivers[ev.s][ev.n].called = true;
            break;
          case "meld":
            b.melds[ev.s].push({ m: ev.m, disp: ev.disp || [] });
            break;
          case "kakan":
            if (b.melds[ev.s][ev.n]) b.melds[ev.s][ev.n] = { m: "kakan", disp: ev.disp || [] };
            break;
          case "dora":
            b.dora.push(ev.t);
            break;
          case "stick":
            b.scores[ev.s] -= 1000;
            b.kyotaku += 1;
            break;
          case "hand":
            b.hands[ev.s] = (ev.h || []).slice();
            b.drawn[ev.s] = ev.d === undefined ? null : ev.d;
            break;
          case "live":
            b.live = ev.n;
            break;
          case "scores":
            b.scores = (ev.v || []).slice();
            break;
          default:
            break;
        }
      }
    }
    return b;
  }

  function seatBlock(b, seat, current) {
    const names = record.names || ["自分", "下家", "対面", "上家"];
    const winds = record.winds || ["", "", "", ""];
    const box = document.createElement("div");
    box.className = "kf-seat" + (current === seat ? " kf-turn" : "");
    const label = document.createElement("div");
    label.className = "kf-label";
    label.textContent = names[seat] + "（" + winds[seat] + "家）　" + Number(b.scores[seat]).toLocaleString("ja-JP");
    if (seat === record.dealer) {
      const tag = document.createElement("span");
      tag.className = "kf-tag kf-dealer";
      tag.textContent = "親";
      label.appendChild(tag);
    }
    if (b.riichi[seat]) {
      const tag = document.createElement("span");
      tag.className = "kf-tag kf-riichi";
      tag.textContent = "リーチ";
      label.appendChild(tag);
    }
    box.appendChild(label);

    const hand = document.createElement("div");
    hand.className = "kf-hand";
    hand.setAttribute("aria-label", names[seat] + "の手牌");
    for (const id of b.hands[seat] || []) hand.appendChild(tileImg(id));
    if (b.drawn[seat] !== null && b.drawn[seat] !== undefined) hand.appendChild(tileImg(b.drawn[seat], "kf-drawn"));
    if ((b.melds[seat] || []).length) {
      const melds = document.createElement("span");
      melds.className = "kf-melds";
      for (const meld of b.melds[seat]) {
        const group = document.createElement("span");
        group.className = "kf-meld";
        for (const [id, side, back] of meld.disp) {
          const img = back ? backImg() : tileImg(id);
          if (side) {
            const holder = document.createElement("span");
            holder.className = "kf-side";
            holder.appendChild(img);
            group.appendChild(holder);
          } else {
            group.appendChild(img);
          }
        }
        melds.appendChild(group);
      }
      hand.appendChild(melds);
    }
    box.appendChild(hand);

    const river = document.createElement("div");
    river.className = "kf-river";
    river.setAttribute("aria-label", names[seat] + "の河");
    (b.rivers[seat] || []).forEach((d, index) => {
      const cell = document.createElement("span");
      const classes = [];
      if (d.g) classes.push("kf-tg");
      if (d.called) classes.push("kf-called");
      if (b.last && b.last[0] === seat && b.last[1] === index) classes.push("kf-last");
      if (d.q) cell.className = "kf-riichi-tile";
      cell.appendChild(tileImg(d.t, classes.join(" ")));
      river.appendChild(cell);
    });
    box.appendChild(river);
    return box;
  }

  function render() {
    const pos = state.pos;
    const b = boardAt(pos);
    const step = pos > 0 ? steps[pos - 1] : null;

    head.replaceChildren();
    const title = document.createElement("span");
    title.textContent = record.title || "";
    head.appendChild(title);
    const where = document.createElement("span");
    where.className = "kf-sub";
    where.textContent = "手順 " + pos + " / " + steps.length + "・残り " + b.live + " 枚";
    head.appendChild(where);
    const dora = document.createElement("span");
    dora.className = "kf-sub";
    dora.append("ドラ表示牌 ");
    for (const id of b.dora) dora.appendChild(tileImg(id));
    head.appendChild(dora);

    caption.className = "kf-caption" + (step && step.note ? " " + step.note.grade : "");
    caption.replaceChildren();
    // 説明の文は、読み（ルビ）を付けた HTML（Python の側で、文字をエスケープしてから作ったもの）があれば、それを使う
    const text = document.createElement("span");
    setText(text, step ? step.html : record.startHtml, step ? step.text : "配牌。▶ で 1 手ずつ進む。");
    caption.appendChild(text);
    if (step && step.note) {
      const note = document.createElement("span");
      note.className = "kf-note";
      note.append(step.note.mark + " ");
      const label = document.createElement("span");
      setText(label, step.note.labelHtml, step.note.label);
      note.appendChild(label);
      caption.appendChild(note);
      if (step.note.text) {
        const more = document.createElement("span");
        more.className = "kf-note-text";
        setText(more, step.note.textHtml, step.note.text);
        caption.appendChild(more);
      }
    } else if (step && step.mine) {
      const note = document.createElement("span");
      note.className = "kf-note-text";
      note.textContent = "（自分の判断）";
      caption.appendChild(note);
    }

    board.replaceChildren();
    const current = step ? step.s : record.dealer;
    for (const seat of ORDER) board.appendChild(seatBlock(b, seat, current));

    slider.max = String(steps.length);
    slider.value = String(pos);
    buttons.first.disabled = buttons.prev.disabled = pos <= 0;
    buttons.last.disabled = buttons.next.disabled = pos >= steps.length;
    buttons.prevMine.disabled = !mine.some((p) => p < pos);
    buttons.nextMine.disabled = !mine.some((p) => p > pos);
  }

  function go(where) {
    const n = steps.length;
    if (where === "first") state.pos = 0;
    else if (where === "prev") state.pos = Math.max(0, state.pos - 1);
    else if (where === "next") state.pos = Math.min(n, state.pos + 1);
    else if (where === "last") state.pos = n;
    else if (where === "prevMine") state.pos = mine.filter((p) => p < state.pos).pop() ?? state.pos;
    else if (where === "nextMine") state.pos = mine.find((p) => p > state.pos) ?? state.pos;
    render();
  }

  for (const [where, el] of Object.entries(buttons)) el.onclick = () => go(where);
  slider.oninput = () => {
    state.pos = Number(slider.value) || 0;
    render();
  };
  root.tabIndex = 0;
  root.onkeydown = (event) => {
    if (event.key === "ArrowRight") go("next");
    else if (event.key === "ArrowLeft") go("prev");
  };
  render();
}

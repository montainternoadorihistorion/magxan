// ブラウザ内保存（localStorage）の読み書きを Python から行うための部品。画面には何も出さない。
//
// 受け取るデータ（Python → ここ）:
//   ns       保存名の接頭辞（他のアプリの保存と混ざらないようにする）
//   session  サーバー側のセッションごとに違う合言葉。通信が長く切れてセッションが作り直されると変わる
//   need     true なら、Python はまだブラウザの中身を知らない（「中身を送って」という依頼）
//   ops      まだ「届いた」と確認できていない書き込みの列。古い順。
//            { id, op: "set" | "remove" | "append", name, value, limit }
//              set     value（文字列）を保存する
//              remove  消す
//              append  保存されている JSON の配列の末尾に、value（JSON の文字列）を 1 件足す。limit 件を超えたら古いものを捨てる
//
// 送る値（ここ → Python）:
//   "snapshot"（1 回きりの値）  { session, values: { 名前: 文字列 }, error, again }
//        need が true のときだけ送る。中身が大きくても、送るのはセッションごとに 1 回で済む
//        （ずっと持ち続ける値にすると、画面を更新するたびに全部を送り直すことになる）。
//        again は、ページを開いたままセッションが作り直されたとき true（通信が長く切れたあとなど）。
//   "ack"（持ち続ける値）       { session, id, error }
//        id までの書き込みを済ませた、という報告。書き込みがたまったときと、失敗したときだけ送る
//        （送るたびに画面の再実行が起きるので、毎回は送らない）。
//
// 同じ書き込みが 2 回届いても結果が変わらないようにしてある（id で見分ける。append は同じ内容を重ねない）。
// この関数は、最初に表示されたときと、Python から届くデータが変わったときに呼ばれる。

const ACK_BATCH = 6; // 未確認の書き込みがこの数たまったら、まとめて報告する
const SNAPSHOT_RETRY_MS = 4000; // 中身を送ったのに返事が無いとき、送り直すまでの時間
const SNAPSHOT_RETRIES = 3;
const APPEND_LOOKBACK = 20; // append で、同じ内容がすでに入っていないか確かめる範囲（末尾から）

// 最後に見たセッションの合言葉（接頭辞ごと）。ページを開いているあいだ覚えておく。
// 部品が置き直されても（ページの切り替えなど）消えないように、要素ではなくここに持つ。
const lastSession = new Map();

function applyOp(storage, ns, op) {
  const key = ns + op.name;
  if (op.op === "remove") {
    storage.removeItem(key);
  } else if (op.op === "set") {
    storage.setItem(key, op.value);
  } else if (op.op === "append") {
    let list = [];
    try {
      const parsed = JSON.parse(storage.getItem(key) || "[]");
      if (Array.isArray(parsed)) list = parsed;
    } catch (e) {
      list = []; // 壊れていたら、空から始める
    }
    const item = JSON.parse(op.value);
    const text = JSON.stringify(item);
    if (!list.slice(-APPEND_LOOKBACK).some((entry) => JSON.stringify(entry) === text)) list.push(item);
    if (op.limit > 0 && list.length > op.limit) list = list.slice(-op.limit);
    storage.setItem(key, JSON.stringify(list));
  }
}

function readAll(ns) {
  const values = {};
  const storage = window.localStorage;
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (key && key.startsWith(ns)) values[key.slice(ns.length)] = storage.getItem(key);
  }
  return values;
}

function message(e) {
  return String(e && e.message ? e.message : e);
}

export default function (component) {
  const { data, parentElement, setStateValue, setTriggerValue } = component;
  const ns = data.ns;
  const ops = Array.isArray(data.ops) ? data.ops : [];
  // 呼び出しをまたいで覚えておくこと（部品の置き場所の要素に持たせる）
  const memo =
    parentElement.__mjStore ||
    (parentElement.__mjStore = { session: null, again: false, applied: 0, acked: 0, failed: false, tries: 0, timer: null });

  function stopRetry() {
    if (memo.timer) clearTimeout(memo.timer);
    memo.timer = null;
  }

  if (memo.session !== data.session) {
    // サーバー側のセッションが新しくなった（最初の表示か、通信が長く切れたあと）。数え直す
    stopRetry();
    // 前に別のセッションを見ている＝ページを開いたまま、セッションが作り直された
    memo.again = lastSession.has(ns) && lastSession.get(ns) !== data.session;
    lastSession.set(ns, data.session);
    memo.session = data.session;
    memo.applied = 0;
    memo.acked = 0;
    memo.failed = false;
    memo.tries = 0;
  }

  // 1) 書き込みを反映する（すでに済ませたものは飛ばす）
  let error = null;
  try {
    const storage = window.localStorage;
    for (const op of ops) {
      if (op.id <= memo.applied) continue;
      applyOp(storage, ns, op);
      memo.applied = op.id;
    }
  } catch (e) {
    // プライベートブラウズ、保存の禁止設定、容量の上限などで書けなかった
    error = message(e);
  }

  // 2) 中身を求められていたら送る（返事が無ければ、何回か送り直す）
  function sendSnapshot() {
    let values = {};
    let readError = null;
    try {
      values = readAll(ns);
    } catch (e) {
      readError = message(e);
    }
    memo.tries += 1;
    setTriggerValue("snapshot", { session: data.session, values, error: readError, again: memo.again });
    stopRetry();
    if (memo.tries < SNAPSHOT_RETRIES) {
      memo.timer = setTimeout(() => {
        memo.timer = null;
        if (memo.session === data.session) sendSnapshot();
      }, SNAPSHOT_RETRY_MS);
    }
  }

  if (data.need) {
    if (!memo.timer && memo.tries < SNAPSHOT_RETRIES) sendSnapshot();
  } else {
    stopRetry(); // 届いた
  }

  // 3) 書き込みの報告（たまったとき・失敗したときだけ）。同じ報告はくり返さない（再実行が止まらなくなるのを防ぐ）
  const failedNow = Boolean(error) && !memo.failed;
  const piledUp = ops.length >= ACK_BATCH && memo.applied > memo.acked;
  if (failedNow || piledUp) {
    memo.acked = memo.applied;
    if (error) memo.failed = true;
    setStateValue("ack", { session: data.session, id: memo.applied, error });
  }

  // 画面から外れるときはタイマーを止める
  return () => stopRetry();
}

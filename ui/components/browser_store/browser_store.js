// ブラウザ内保存（localStorage）の読み書きを Python から行うための部品。画面には何も出さない。
//
// 受け取るデータ（Python → ここ）:
//   ns        保存名の接頭辞（他のアプリの保存と混ざらないようにする）
//   writes    { 名前: 文字列 | null }  null は削除。まだブラウザに反映されたか分からない書き込み
//   expected  { 名前: 文字列 } | null  Python が「いまブラウザにはこう入っているはず」と考えている中身。
//             null は「まだ一度も読んでいない」
//   seq       Python 側で中身が変わるたびに増える番号
//
// 送る値（ここ → Python）: 中身が expected と違うとき（最初の 1 回を含む）だけ "snapshot" を送る
//   { values: { 名前: 文字列 }, error: 文字列 | null, seq }
// 同じなら何も送らない（＝余計な再実行を起こさない）。

export default function (component) {
  const { data, setStateValue } = component;
  const ns = data.ns;
  const values = {};
  let error = null;

  try {
    const storage = window.localStorage;
    for (const [name, value] of Object.entries(data.writes || {})) {
      if (value === null) storage.removeItem(ns + name);
      else storage.setItem(ns + name, value);
    }
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key && key.startsWith(ns)) values[key.slice(ns.length)] = storage.getItem(key);
    }
  } catch (e) {
    // プライベートブラウズや保存の禁止設定などで使えない場合
    error = String(e && e.message ? e.message : e);
  }

  const expected = data.expected;
  let same = !error && expected !== null && typeof expected === "object";
  if (same) {
    const a = Object.keys(values);
    const b = Object.keys(expected);
    same = a.length === b.length && a.every((k) => expected[k] === values[k]);
  }
  if (!same) setStateValue("snapshot", { values, error, seq: data.seq });
}

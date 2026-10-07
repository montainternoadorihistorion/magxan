// 文章をクリップボードにコピーするボタン。押しても Python 側の再実行は起こさない。
//
// 受け取るデータ: { text, label, doneText, failText }

export default function (component) {
  const { data, parentElement } = component;
  const button = parentElement.querySelector(".mj-copy");
  const note = parentElement.querySelector(".mj-copy-note");
  button.textContent = data.label;
  note.textContent = "";

  button.onclick = async () => {
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(data.text);
        ok = true;
      }
    } catch (e) {
      ok = false;
    }
    if (!ok) {
      // クリップボード API が使えない環境向けの古い方法
      const area = document.createElement("textarea");
      area.value = data.text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.top = "0";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      area.setSelectionRange(0, area.value.length);
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      area.remove();
    }
    note.textContent = ok ? data.doneText : data.failText;
  };
}

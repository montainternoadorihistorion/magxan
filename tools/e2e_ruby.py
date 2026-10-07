"""確認スクリプト（tools/e2e_*.py）で使う、ルビの振り忘れを探す道具。

麻雀の用語は、画面で最初に出てきたところに読み（ルビ）を付ける決まり。ブラウザに出ている文字を
上から順に読んで、「読みが付いていない初出」が無いかを調べる。入力欄や折りたたみの名前のように、
アプリの側でルビを振れない場所も含めて調べられる。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import Page  # noqa: E402

from ui.ruby import missing_ruby  # noqa: E402

#: 画面の文字を、出てくる順に（文字, 読みが付いているか, 範囲）の列にする式。
#: 範囲 0 は、いつも見えている部分。折りたたみの中身は、折りたたみごとに別の番号（見出しは外側の範囲）。
RUBY_PARTS = """() => {
    const parts = [];
    let counter = 0;
    const walk = (node, scope) => {
        if (node.nodeType === Node.TEXT_NODE) {
            const owner = node.parentElement;
            if (!node.textContent.trim() || !owner || owner.closest('rt, style, script, noscript')) return;
            // 読みが付いているのは、ルビを振った用語と、読みをすぐ横に並べて書いた名前（.mj-term）。
            // 読みを答えさせる問題の文（.mj-asked）は、わざと読みを隠しているので、同じ扱いにする
            parts.push([node.textContent, Boolean(owner.closest('ruby, .mj-term, .mj-asked')), scope]);
            return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.tagName === 'STYLE' || node.tagName === 'SCRIPT') return;
        if (node.matches('a[data-testid="stPageLink-NavLink"]')) {
            // ページへのリンクは、名前と読みを 1 行に並べて書くことがある（役図鑑の一覧）。1 つの文として読む
            const label = node.querySelector('[data-testid="stMarkdownContainer"]');
            if (label && label.textContent.trim()) parts.push([label.textContent, false, scope]);
            return;
        }
        const inner = node.tagName === 'DETAILS' ? ++counter : scope;
        for (const child of node.childNodes) {
            const summary = node.tagName === 'DETAILS' && child.nodeType === Node.ELEMENT_NODE && child.tagName === 'SUMMARY';
            walk(child, summary ? scope : inner);
        }
        if (node.shadowRoot) for (const child of node.shadowRoot.childNodes) walk(child, inner);
    };
    walk(document.querySelector('[data-testid="stMain"]'), 0);
    return parts;
}"""


def open_all(page: Page) -> None:
    """閉じている折りたたみを、すべて開く"""
    for _ in range(12):
        closed = page.locator("details:not([open]) > summary")
        if not closed.count():
            return
        closed.first.tap()
        page.wait_for_timeout(500)


def terms_without_ruby(page: Page) -> list[str]:
    """折りたたみをすべて開いて、初出なのに読みが付いていない用語を返す（無ければ空）"""
    open_all(page)
    return missing_ruby([tuple(part) for part in page.evaluate(RUBY_PARTS)])

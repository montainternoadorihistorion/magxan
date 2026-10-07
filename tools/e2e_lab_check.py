"""スマホ相当の画面で「点数計算ラボ」を通しで操作する確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、牌の画像・ルビ・入力欄の切り替えが
画面上で意図どおり動くかを確かめる。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で）
       python tools/e2e_lab_check.py http://localhost:8501 出力フォルダ

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_ruby import terms_without_ruby  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
WIDTH = 375          # 利用者の実機（iPhone）の幅
#: ホームに並んでいる、ページへのリンク
HOME_LINK = '[data-testid="stMain"] a[data-testid="stPageLink-NavLink"]'
TALL = 6000          # 縦に長いページを 1 枚に収めるための高さ（Streamlit は内側の枠でスクロールするため）


def settle(page: Page, ms: int = 900) -> None:
    page.wait_for_timeout(ms)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(250)


def big(page: Page) -> str:
    """まとめの大きな文字（点数、または「あがれない」）"""
    return page.locator(".mj-big").first.inner_text().split("\n")[0].strip()


#: 要素の中の文字を、ルビ（読みがな）を除いて取り出す式
TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""


def headings(page: Page) -> list[str]:
    """解説の見出し（ルビを除く）"""
    return [h.evaluate(TEXT_WITHOUT_RUBY) for h in page.locator("h3").all()]


def run(base_url: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"problems": []}
    console_errors: list[str] = []
    failed_requests: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            result["problems"].append(message)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": TALL},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent=IPHONE_UA,
            locale="ja-JP",
        )
        page = context.new_page()

        def is_base_path_probe(url: str) -> bool:
            # ページを直接開いたとき、Streamlit の画面側は「/ページ名/_stcore/...」も試してから正しい場所を使う
            return bool(re.search(r"/[^/]+/_stcore/(health|host-config)$", url))

        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and not is_base_path_probe(m.location.get("url", "")) else None)
        page.on("response", lambda r: failed_requests.append(f"{r.status} {r.url}") if r.status >= 400 and not is_base_path_probe(r.url) else None)

        def shot(name: str) -> None:
            page.screenshot(path=str(out_dir / f"lab_{name}.png"))
            expect(page.locator('[data-testid="stException"]').count() == 0, f"{name}: 画面に例外が出ている")
            overflow = page.evaluate("document.documentElement.scrollWidth")
            expect(overflow <= WIDTH, f"{name}: 横にはみ出している（{overflow}px）")

        # --- ホームからラボへ
        page.goto(base_url)
        page.locator(HOME_LINK, has_text="点数計算ラボ").wait_for(timeout=60000)
        page.locator(HOME_LINK, has_text="点数計算ラボ").tap()
        page.locator(".mj-big").first.wait_for(timeout=60000)
        settle(page)
        shot("1_first_example")
        result["first"] = big(page)
        expect(result["first"] == "1,300 点", f"最初の例題の点数が違う: {result['first']}")
        expect(headings(page)[:7] == ["① 手牌の読み方", "② 役", "③ ドラ", "④ 符", "⑤ 点数", "⑥ 誰がいくら払うか", "⑦ 卓での申告"], f"見出しが違う: {headings(page)}")

        # 牌の画像がすべて読めていて、ルビが付いている
        images = page.locator("img.mj-img")
        loaded = images.evaluate_all("els => els.filter(e => e.complete && e.naturalWidth > 0).length")
        result["tile_images"] = {"count": images.count(), "loaded": loaded}
        expect(images.count() >= 28 and loaded == images.count(), f"牌の画像が読めていない: {result['tile_images']}")
        result["ruby"] = page.locator("ruby").count()
        expect(result["ruby"] >= 10, f"ルビが少ない: {result['ruby']}")
        widths = page.locator(".mj-hand .mj-fit img.mj-img").evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().width * 10) / 10)")
        result["hand_tile_width"] = widths[0] if widths else None
        expect(bool(widths) and min(widths) >= 20, f"手牌の牌が小さすぎる: {widths[:3]}")
        formula = page.locator(".mj-formula").last.inner_text()
        result["formula"] = formula
        expect("40 符 1 翻・子のロン" in formula and "切り上げて 1,300 点" in formula, f"式が違う: {formula}")

        # --- 次の例題、状況を変える、元に戻す
        page.get_by_role("button", name="次の例題 ▶").tap()
        settle(page)
        expect("A-2" in page.locator(".mj-lesson b").inner_text(), "次の例題に進めていない")
        expect(big(page) == "2,000 点", f"A-2 の点数が違う: {big(page)}")
        page.get_by_text("状況を変えてみる").tap()
        settle(page, 500)
        page.get_by_role("radiogroup", name="あがり方").get_by_role("radio", name="ツモ").tap()
        settle(page)
        shot("2_changed_to_tsumo")
        result["tsumo"] = big(page)
        expect(result["tsumo"] == "700・1,300 点", f"ツモに変えた点数が違う: {result['tsumo']}")
        page.get_by_role("button", name="例題の条件に戻す").tap()
        settle(page)
        expect(big(page) == "2,000 点", "例題の条件に戻せていない")

        # --- URL で例題を開く（高点法の例）
        page.goto(base_url.rstrip("/") + "/lab?ex=F-1")
        page.locator(".mj-big").first.wait_for(timeout=60000)
        settle(page)
        shot("3_high_point_method")
        expect(big(page).startswith("12,000 点"), f"F-1 の点数が違う: {big(page)}")
        expect(page.locator(".mj-alt").count() == 2, "読み方の候補が 2 つ出ていない")

        # --- ランダム
        page.get_by_role("radio", name="ランダムに出す").tap()
        settle(page, 1400)
        first = page.locator(".mj-fit").first.inner_html()
        page.get_by_role("button", name="次の手を出す").tap()
        settle(page, 1400)
        shot("4_random")
        expect(page.locator(".mj-fit").first.inner_html() != first, "次の手に変わっていない")
        expect("kind=any" in page.url and "n=" in page.url, f"URL に手の番号が入っていない: {page.url}")

        # --- 自分で入力（誤りの知らせ → 直す）
        page.get_by_role("radio", name="自分で入力").tap()
        settle(page)
        for label, value in [
            ("副露（鳴いた面子と暗槓。「、」で区切る）", ""),
            ("ドラ表示牌", ""),
            ("裏ドラ表示牌（リーチしたときだけ）", ""),
            ("和了牌（1 枚）", "4s"),
            ("手牌（和了牌を除く。鳴いていなければ 13 枚）", "123m456p789s23s"),
        ]:
            box = page.get_by_label(label, exact=True)
            box.fill(value)
            box.press("Enter")
            settle(page, 600)
        shot("5_input_error")
        alert = page.locator('[data-testid="stAlert"]').first.inner_text()
        result["input_error"] = alert
        expect("13 枚のはずですが、11 枚あります" in alert, f"入力の誤りの知らせが違う: {alert}")
        box = page.get_by_label("手牌（和了牌を除く。鳴いていなければ 13 枚）", exact=True)
        box.fill("123m456p789s23s55z")
        box.press("Enter")
        settle(page)
        expect(page.locator('[data-testid="stAlert"]').count() == 0, "正しい入力なのに誤りの知らせが残っている")

        # --- 先に自分で計算する
        page.get_by_text("先に自分で計算する").tap()
        settle(page)
        shot("6_quiz")
        expect(page.get_by_text("この手は何点？").count() == 1 and headings(page) == [], "答えが隠れていない")
        page.get_by_role("button", name="答えと解説を見る").tap()
        settle(page)
        expect(len(headings(page)) >= 2, "答えが開いていない")
        shot("7_revealed")

        # --- 用語の初出に、読み（ルビ）が付いているか。折りたたみをすべて開いて、画面の上から順に調べる
        ruby_missing = {}

        def check_ruby(name: str) -> None:
            ruby_missing[name] = terms_without_ruby(page)
            expect(not ruby_missing[name], f"{name}: 初出なのにルビが無い用語: {ruby_missing[name]}")

        check_ruby("答えを開いたあと")
        for name, path in (("最初の例題", "/lab"), ("役満の例題", "/lab?ex=G-9"), ("鳴いた手", "/lab?kind=open&n=12")):
            page.goto(base_url.rstrip("/") + path)
            page.locator(".mj-big").first.wait_for(timeout=60000)
            settle(page)
            check_ruby(name)
        page.goto(base_url.rstrip("/") + "/lab")
        page.locator(".mj-big").first.wait_for(timeout=60000)
        page.get_by_role("radio", name="自分で入力").tap()
        settle(page)
        check_ruby("自分で入力")
        page.goto(base_url.rstrip("/") + "/lab")
        page.locator(".mj-big").first.wait_for(timeout=60000)
        page.get_by_text("先に自分で計算する").tap()
        settle(page)
        check_ruby("先に自分で計算する（答えを隠した状態）")
        page.goto(base_url)
        page.locator(HOME_LINK, has_text="点数計算ラボ").wait_for(timeout=60000)
        settle(page, 500)
        check_ruby("ホーム")
        result["ruby_missing"] = ruby_missing

        browser.close()

    result["console_errors"] = console_errors
    result["failed_requests"] = failed_requests
    expect(not console_errors, f"ブラウザのエラー: {console_errors[:3]}")
    expect(not failed_requests, f"読み込みに失敗: {failed_requests[:3]}")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    outcome = run(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    sys.exit(1 if outcome["problems"] else 0)

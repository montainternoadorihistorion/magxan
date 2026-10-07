"""スマホ相当の画面で実機チェックのページを通しで操作する確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、牌タップの部品とブラウザ内保存が
画面上で意図どおり動くかを確かめる。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で）
       python tools/e2e_mobile_check.py http://localhost:8501 出力フォルダ

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


def report_text(page: Page) -> str:
    return page.locator("[data-testid=stCode]").last.inner_text()


def field(report: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}: (.*)$", report, flags=re.MULTILINE)
    return match.group(1) if match else ""


def wait_hand(page: Page) -> None:
    page.locator(".mj-tile").nth(13).wait_for(timeout=60000)


def discard(page: Page, index: int, *, double_tap: bool = False) -> None:
    """index 番目の牌を切り、河が 1 枚増えるまで待つ"""
    river = page.locator('img[src*="app/static/tiles"][title]')
    before = river.count()
    page.locator(".mj-tile").nth(index).tap()
    if double_tap:
        page.locator(".mj-tile").nth(index).tap()
    else:
        page.locator(".mj-confirm").tap()
    page.wait_for_function("n => document.querySelectorAll('img[src*=\"app/static/tiles\"][title]').length > n", arg=before)
    page.wait_for_timeout(150)


def run(base_url: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"problems": []}
    console_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            user_agent=IPHONE_UA,
            locale="ja-JP",
        )
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()

        def is_base_path_probe(url: str) -> bool:
            # ページを直接開いたとき、Streamlit の画面側は「/ページ名/_stcore/...」も試してから正しい場所を使う。
            # この 404 は Streamlit 自身の動作で、アプリの不具合ではない
            return bool(re.search(r"/[^/]+/_stcore/(health|host-config)$", url))

        def on_console(message) -> None:
            if message.type == "error" and not is_base_path_probe(message.location.get("url", "")):
                console_errors.append(message.text)

        def on_response(response) -> None:
            if response.status >= 400 and not is_base_path_probe(response.url):
                failed_requests.append(f"{response.status} {response.url}")

        page.on("console", on_console)
        page.on("response", on_response)

        # --- ホーム → 実機チェック
        page.goto(base_url)
        page.get_by_text("実機チェックを始める").wait_for(timeout=60000)
        page.screenshot(path=str(out_dir / "01_home.png"))
        page.get_by_text("実機チェックを始める").tap()
        wait_hand(page)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / "02_check_initial.png"))

        tiles = page.locator(".mj-tile")
        boxes = tiles.evaluate_all("els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
        loaded = tiles.evaluate_all("els => els.filter(e => { const i = e.querySelector('img'); return i && i.naturalWidth > 0; }).length")
        result["tiles"] = {"count": len(boxes), "min_width": round(min(b[0] for b in boxes), 1), "min_height": round(min(b[1] for b in boxes), 1), "images_loaded": loaded}
        if len(boxes) != 14 or loaded != 14:
            result["problems"].append("手牌14枚の表示または画像の読み込みに失敗")

        # --- 選択だけした状態
        tiles.nth(13).tap()
        page.wait_for_timeout(300)
        result["status_after_select"] = page.locator(".mj-status").inner_text()
        page.screenshot(path=str(out_dir / "03_selected.png"))
        page.locator(".mj-confirm").tap()
        page.wait_for_function("() => document.querySelectorAll('img[src*=\"app/static/tiles\"][title]').length === 1")

        # --- ボタン確定と2度タップ確定を混ぜて切る
        for i in range(5):
            discard(page, i, double_tap=(i % 2 == 1))
        page.wait_for_timeout(500)
        rep = report_text(page)
        result["after_6_discards"] = {k: field(rep, k) for k in ("切った回数", "応答時間（牌タップ）", "画面", "ブラウザ内保存", "局面")}
        page.screenshot(path=str(out_dir / "04_after_discards.png"), full_page=True)
        if "牌タップ 6 回" not in field(rep, "切った回数"):
            result["problems"].append("切った回数が合わない")
        if "未計測" in field(rep, "応答時間（牌タップ）"):
            result["problems"].append("応答時間が計測されていない")
        position_before = field(rep, "局面")

        # --- 再読み込み（＝新しいセッション）で続きから再開できるか
        page.reload()
        wait_hand(page)
        page.wait_for_timeout(800)
        rep = report_text(page)
        result["after_reload"] = {"局面": field(rep, "局面"), "ブラウザ内保存": field(rep, "ブラウザ内保存"), "切った回数": field(rep, "切った回数")}
        if field(rep, "局面") != position_before:
            result["problems"].append("再読み込み後に局面が一致しない")
        if "今回は再開" not in field(rep, "ブラウザ内保存"):
            result["problems"].append("再開と判定されていない")
        result["after_reload"]["応答時間（牌タップ）"] = field(rep, "応答時間（牌タップ）")
        result["after_reload"]["画面"] = field(rep, "画面")
        if "牌タップ 6 回" not in field(rep, "切った回数") or "未計測" in field(rep, "応答時間（牌タップ）") or "未取得" in field(rep, "画面"):
            result["problems"].append("再読み込みで計測値が消えた")
        page.screenshot(path=str(out_dir / "05_after_reload.png"))

        # --- 予備の操作方法
        page.get_by_text("予備の操作方法（標準の部品）で試す").tap()
        page.locator("[data-testid=stPills] button, [data-testid=stButtonGroup] button").first.wait_for()
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / "06_fallback.png"))
        page.locator("[data-testid=stPills] button, [data-testid=stButtonGroup] button").nth(0).tap()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="この牌を切る").tap()
        page.wait_for_timeout(1000)
        rep = report_text(page)
        result["after_fallback"] = field(rep, "切った回数")
        if "予備の方法 1 回" not in result["after_fallback"]:
            result["problems"].append("予備の操作方法で切れていない")
        page.get_by_text("予備の操作方法（標準の部品）で試す").tap()
        wait_hand(page)

        # --- サーバー速度
        page.get_by_role("button", name="計測する（数秒）").tap()
        page.get_by_text("マイクロ秒").first.wait_for(timeout=60000)
        result["bench"] = field(report_text(page), "サーバーの速さ")

        # --- 局の終わりまで切る → 新しい局
        for _ in range(40):
            if page.get_by_role("button", name="新しい局を始める").count():
                break
            discard(page, 0, double_tap=True)
        page.get_by_role("button", name="新しい局を始める").wait_for(timeout=10000)
        page.screenshot(path=str(out_dir / "07_hand_finished.png"))
        page.get_by_role("button", name="新しい局を始める").tap()
        wait_hand(page)
        result["after_new_hand"] = field(report_text(page), "局面")

        # --- 結果のコピー
        page.get_by_role("button", name="結果をコピー").tap()
        page.get_by_text("コピーしました").wait_for(timeout=5000)
        copied = page.evaluate("() => navigator.clipboard.readText()")
        result["copy_matches_report"] = copied.strip() == report_text(page).strip()
        if not result["copy_matches_report"]:
            result["problems"].append("コピーした文章が結果と一致しない")

        # --- 記録を消す → 開いた回数などが最初に戻る
        page.get_by_role("button", name="記録を消して最初からやり直す").tap()
        page.wait_for_timeout(1200)
        wait_hand(page)
        result["after_reset"] = field(report_text(page), "ブラウザ内保存")
        if result["after_reset"] != "使える ／ 開いた回数 1 ／ 続きから再開 0 ／ 今回は新規":
            result["problems"].append("記録を消したあとの状態が想定と違う")

        result["final_report"] = report_text(page)
        context.close()

        # --- 幅の違う画面でのレイアウト
        widths = {}
        for width in (320, 360, 430, 1280):
            ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=2, has_touch=width < 800, is_mobile=width < 800, locale="ja-JP")
            pg = ctx.new_page()
            pg.goto(base_url.rstrip("/") + "/check")
            wait_hand(pg)
            pg.wait_for_timeout(600)
            box = pg.locator(".mj-tile").first.evaluate("e => { const r = e.getBoundingClientRect(); return [Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10]; }")
            overflow = pg.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
            images = pg.locator(".mj-tile").evaluate_all("els => els.filter(e => { const i = e.querySelector('img'); return i && i.naturalWidth > 0; }).length")
            widths[width] = {"tile": box, "horizontal_scroll": overflow, "images_loaded": images}
            pg.screenshot(path=str(out_dir / f"08_width_{width}.png"))
            if overflow:
                result["problems"].append(f"幅 {width}px で横スクロールが出る")
            if images != 14:
                result["problems"].append(f"幅 {width}px で牌画像が読めていない")
            ctx.close()
        result["widths"] = widths

        # --- ダークテーマ
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="dark", locale="ja-JP")
        pg = ctx.new_page()
        pg.goto(base_url.rstrip("/") + "/check")
        wait_hand(pg)
        pg.locator(".mj-tile").nth(3).tap()
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out_dir / "09_dark.png"))
        ctx.close()
        browser.close()

    result["console_errors"] = console_errors[:10]
    result["failed_requests"] = failed_requests[:10]
    if console_errors:
        result["problems"].append("ブラウザのコンソールにエラーあり")
    if failed_requests:
        result["problems"].append("失敗したリクエストあり")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    outcome = run(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(outcome, ensure_ascii=False, indent=1))
    sys.exit(1 if outcome["problems"] else 0)

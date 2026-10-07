"""ページを開いたまま通信が長く切れたあと、続きから打てるかを確かめるスクリプト（開発用）。

スマホで別のアプリをしばらく見てから戻る、という使い方の確認。通信が長く切れると、サーバー側の状態
（セッション）は消える。画面はブラウザに残っているので、戻ってきて最初に何か押したときに、新しい
セッションが作られる。そこで、ブラウザに残した記録から局を作り直して、続きから打てることを確かめる。

セッションが消えるまで待つので、消えるまでの時間を短くしたサーバーで試す。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8502 --server.disconnectedSessionTTL 6   （別の端末で）
       python tools/e2e_reconnect_check.py http://localhost:8502 出力フォルダ

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import contextlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from engine import practice  # noqa: E402
from engine.coach import analyze  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
OFFLINE_MS = 14_000      # 通信を切っておく時間。サーバーの disconnectedSessionTTL（6 秒）より長くする
NOTICE = "通信が切れていたので、続きから再開しました"

#: 通信（WebSocket）を、ページの中から切ったり戻したりするための仕掛け（ページを開く前に入れる）。
#: __wsDrop() で、いまの通信を切り、新しい通信もつながらないようにする。__wsAllow() で、つながるように戻す。
NETWORK_SWITCH = """
(() => {
  const Real = window.WebSocket;
  window.__sockets = [];
  window.__blocked = false;
  window.__created = 0;
  function Switched(url, protocols) {
    window.__created += 1;
    const target = window.__blocked ? 'ws://127.0.0.1:9/blocked' : url;
    const socket = protocols === undefined ? new Real(target) : new Real(target, protocols);
    window.__sockets.push(socket);
    return socket;
  }
  Switched.prototype = Real.prototype;
  for (const name of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) Switched[name] = Real[name];
  window.WebSocket = Switched;
  window.__wsDrop = () => {
    window.__blocked = true;
    for (const socket of window.__sockets) { try { socket.close(); } catch (e) {} }
    window.__sockets = [];
  };
  window.__wsAllow = () => { window.__blocked = false; };
})();
"""

#: 手牌の部品が「送信中」のまま止まっていないかを見る式
HAND_PENDING = """() => {
    for (const host of document.querySelectorAll('*')) {
        const root = host.shadowRoot && host.shadowRoot.querySelector('.mj-hand-root');
        if (root) return Boolean(root.__mj && root.__mj.pending);
    }
    return null;
}"""

TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt, style, script').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""


def find(settings: LuckSettings, stop) -> practice.PracticeState:
    """おすすめどおりに打って、stop(state) が真になる局面を探す"""
    for seed in range(500):
        state = practice.start(practice.PracticeConfig(seed=seed, luck=settings))
        while not state.finished and not stop(state):
            if state.can_tsumo:
                break
            state = practice.apply(state, practice.discard(analyze(practice.position_of(state)).pick.tile))
        if not state.finished and stop(state):
            return state
    raise SystemExit("確認に使う局面が見つかりません")


def storage_script(state: practice.PracticeState) -> str:
    luck = state.config.luck
    settings = {"deal": luck.deal, "draw": luck.draw, "tenpai_deal": False, "mark": True, "hint": "before", "level": 2}
    hand = json.dumps({"v": 1, "save": practice.to_save(state), "counted": True, "hinted": False})
    return (
        "if (!sessionStorage.getItem('mj-seeded')) { sessionStorage.setItem('mj-seeded', '1'); "
        f"localStorage.setItem('mjdojo:practice.settings', {json.dumps(json.dumps(settings))}); "
        f"localStorage.setItem('mjdojo:practice.hand', {json.dumps(hand)}); }}"
    )


def settle(page: Page, ms: int = 700) -> None:
    page.wait_for_timeout(ms)
    with contextlib.suppress(Exception):      # 通信を切っているあいだは、落ち着かないことがある
        page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(200)


def main_text(page: Page) -> str:
    return page.locator('[data-testid="stMain"]').evaluate(TEXT_WITHOUT_RUBY)


def river_count(page: Page) -> int:
    return page.locator(".mj-river:not(.mj-draws) img").count()


def saved_actions(page: Page) -> int | None:
    """ブラウザに残っている局の、行動の数"""
    raw = page.evaluate("() => localStorage.getItem('mjdojo:practice.hand')")
    return len(json.loads(raw)["save"]["actions"]) if raw else None


def discard(page: Page, index: int) -> None:
    before = page.locator('[data-testid="stMain"]').inner_text()
    page.locator(".mj-tile").nth(index).tap()
    page.wait_for_timeout(150)
    page.locator(".mj-hand-root .mj-confirm").tap()
    page.wait_for_function("t => document.querySelector('[data-testid=stMain]').innerText !== t", arg=before, timeout=20000)
    settle(page, 400)


def go_offline_until_the_session_is_gone(page: Page) -> float:
    """通信を切って、サーバー側のセッションが消えるまで待ち、つなぎ直す。つながるまでの秒数を返す"""
    page.evaluate("window.__wsDrop()")
    page.wait_for_timeout(OFFLINE_MS)
    created = page.evaluate("window.__created")
    page.evaluate("window.__wsAllow()")
    started = time.time()
    while time.time() - started < 70:
        page.wait_for_timeout(250)
        if page.evaluate("window.__created") > created and page.evaluate("window.__sockets.some(s => s.readyState === 1)"):
            break
    page.wait_for_timeout(1500)
    return round(time.time() - started, 1)


def run(base_url: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    result: dict = {"problems": []}
    playing = find(LuckSettings(50, 50), lambda s: s.turn == 6 and not s.can_tsumo and not s.riichi_discards)
    winning = find(LuckSettings(75, 75), lambda s: s.can_tsumo)
    won = practice.apply(winning, practice.TSUMO)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        cases = (("何もしないまま切れた", playing), ("何枚か切ったあとで切れた", playing), ("設定を変えようとした", playing), ("終わった局の画面で切れた", won))
        for number, (name, state) in enumerate(cases, start=1):
            problems: list[str] = []
            context = browser.new_context(
                viewport={"width": 375, "height": 900}, device_scale_factor=2, is_mobile=True, has_touch=True, user_agent=IPHONE_UA, locale="ja-JP",
            )
            context.add_init_script(NETWORK_SWITCH + storage_script(state))
            page = context.new_page()
            page.goto(base + "/practice")
            if state.finished:
                page.get_by_role("button", name="次の局へ").first.wait_for(timeout=60000)
            else:
                page.locator(".mj-tile").nth(13).wait_for(timeout=60000)
            settle(page)
            if name == "何枚か切ったあとで切れた":
                discard(page, 13)
                discard(page, 13)
            river, saved = river_count(page), saved_actions(page)
            seconds = go_offline_until_the_session_is_gone(page)

            # ---- 戻ってきて最初の操作。これはサーバーに届かない（届け先のセッションが、もう無い）
            if state.finished:
                page.get_by_role("button", name="次の局へ").first.tap()
            elif name == "設定を変えようとした":
                page.locator("summary", has_text="設定（ツキ補正・役指定・コーチ）").first.tap()
                page.wait_for_timeout(400)
                page.get_by_role("radio", name="オフ", exact=True).tap()
            else:
                page.locator(".mj-tile").nth(13).tap()
                page.wait_for_timeout(150)
                page.locator(".mj-hand-root .mj-confirm").tap()
            noticed = False
            for _ in range(10):
                page.wait_for_timeout(500)
                noticed = noticed or any(NOTICE in text for text in page.locator('[data-testid="stToast"]').all_inner_texts())
            settle(page, 300)
            text = main_text(page)
            page.screenshot(path=str(out_dir / f"reconnect_{number}.png"))
            if "確認しています" in text:
                problems.append("「記録を確認しています…」のまま止まっている")
            if page.locator('[data-testid="stException"]').count():
                problems.append("画面に例外が出ている")
            if "保存を使っていません" in text:
                problems.append("保存が使われなくなっている")
            if not noticed:
                problems.append("続きから再開したことの案内が出ていない")
            if "再開したものです" not in text:
                problems.append("ブラウザの記録から再開していない")
            if not state.finished:
                if page.locator(".mj-tile").count() != 14 or river_count(page) != river:
                    problems.append("切れる前の局面に戻っていない")
                if page.evaluate(HAND_PENDING):
                    problems.append("手牌が「送信中」のまま止まっている")
            if name == "設定を変えようとした":
                page.locator("summary", has_text="設定（ツキ補正・役指定・コーチ）").first.tap()
                page.wait_for_timeout(500)
                shown = page.get_by_role("radio", name="打つ前に表示", exact=True).get_attribute("aria-checked")
                if shown != "true":
                    problems.append("届かなかった設定の変更が、画面にだけ残っている")

            # ---- 2 回目の操作は、ふつうに効く
            if state.finished:
                page.get_by_role("button", name="次の局へ").first.tap()
                try:
                    page.locator(".mj-tile").nth(13).wait_for(timeout=20000)
                except Exception:
                    problems.append("2 回目の「次の局へ」で、新しい局が始まらない")
            elif name == "設定を変えようとした":
                page.get_by_role("radio", name="オフ", exact=True).tap()
                settle(page, 1200)
                if "コーチはオフです" not in main_text(page):
                    problems.append("2 回目の設定の変更が効かない")
            else:
                try:
                    discard(page, 13)
                except Exception as error:
                    problems.append(f"2 回目の打牌ができない: {error}")
                if river_count(page) != river + 1 or saved_actions(page) != saved + 1:
                    problems.append("2 回目の打牌が、画面かブラウザの記録に反映されていない")
            seed = re.search(r"局の番号 (\d+)", main_text(page))
            result[name] = {"reconnected_after_seconds": seconds, "notice": noticed, "seed": seed.group(1) if seed else "", "problems": problems}
            result["problems"].extend(f"{name}: {problem}" for problem in problems)
            context.close()
        browser.close()
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    outcome = run(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    sys.exit(1 if outcome["problems"] else 0)

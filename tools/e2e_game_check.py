"""スマホ相当の画面で「CPU と対局」を通しで打つ確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、東風戦を 1 回、最後まで打つ。
自分は、コーチのおすすめ（◎）どおりに切る。リーチを勧められたらリーチし、ロン・ツモはあがる。
そのあいだ、手牌とボタンの位置が動かないこと、応答の速さ、画面の例外・はみ出し・ルビの振り忘れを確かめる。
続けて、決まった局面（ロンの返事・リーチを受けている・局の終わり・対局の終わり）を用意して、それぞれの画面を確かめる。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で）
       python tools/e2e_game_check.py http://localhost:8501 出力フォルダ

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from e2e_ruby import terms_without_ruby  # noqa: E402
from playwright.sync_api import BrowserContext, Page, sync_playwright  # noqa: E402

from engine import game as g  # noqa: E402
from engine.cpu import advance  # noqa: E402
from engine.defense import threats  # noqa: E402
from engine.game import HUMAN, GameConfig, Phase  # noqa: E402
from engine.game_coach import coach_action  # noqa: E402
from ui.game_session import DEFAULT_SETTINGS  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
WIDTH, HEIGHT = 375, 606     # 利用者の実機（iPhone の Safari）で測った画面の大きさ
TALL = 5000                  # 縦に長いページを 1 枚に収めるための高さ
MAIN = '[data-testid="stMain"]'
HAND = ".mj-hand-root"
HOME_LINK = f'{MAIN} a[data-testid="stPageLink-NavLink"]'
MAX_STEPS = 600              # 1 回の対局で操作する回数の上限（無限に回らないように）
#: 要素の中の文字を、ルビ（読みがな）を除いて取り出す式。空白は 1 つにまとめる
TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt, style, script').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""
#: 画面の文字が 0.45 秒変わらなくなり、描き直しの途中の部品（data-stale）も無くなったら解決する
SETTLED = """() => new Promise(resolve => {
    const main = () => document.querySelector('[data-testid=stMain]');
    let last = main() ? main().innerText : '', same = 0, waited = 0;
    const timer = setInterval(() => {
        waited += 150;
        const now = main() ? main().innerText : '';
        const busy = document.querySelector('[data-stale="true"]') || document.querySelector('.mj-hand-root.mj-pending');
        if (now === last && !busy) { same += 1; } else { same = 0; last = now; }
        if (same >= 3 || waited > 30000) { clearInterval(timer); resolve(waited); }
    }, 150);
})"""
#: 牌の送信中（手牌の部品が応答を待っている）が終わったら真になる式
NOT_PENDING = "() => !document.querySelector('.mj-hand-root.mj-pending')"


# ---------------------------------------------------------------- 決まった局面を用意する


def find(kind: str) -> g.GameState:
    """その局面になる対局を探す（自分は、コーチのおすすめどおりに打つ）"""
    for seed in range(400):
        game = advance(g.start_game(GameConfig(seed=seed)))
        while not game.finished:
            if game.between_hands:
                if kind == "hand_end_win" and any(w.seat == HUMAN for w in game.current.result.wins):
                    return game
                game = advance(g.next_hand(game))
                continue
            hand = game.current
            if kind == "claim" and hand.phase is Phase.CLAIM and HUMAN in hand.pending:
                return game
            if (kind == "threat" and hand.phase is Phase.DRAW and threats(hand, HUMAN) and not hand.players[HUMAN].in_riichi
                    and len(hand.players[HUMAN].river) >= 6):
                return game
            game = advance(g.apply(game, coach_action(hand, HUMAN)))
        if kind == "finished":
            return game
    raise SystemExit(f"確かめに使う局面が見つかりません: {kind}")


def storage_script(game: g.GameState | None, **settings) -> str:
    """ページを開く前に、ブラウザ内保存に対局と設定を入れておくスクリプト（最初の 1 回だけ働く）"""
    full = {**DEFAULT_SETTINGS, **settings}
    lines = [f"localStorage.setItem('mjdojo:game.settings', {json.dumps(json.dumps(full))});"]
    if game is not None:
        data = {"v": 1, "save": g.to_save(game), "counted": True, "hinted": False, "recorded": False,
                "tally": {"n": 0, "f": 0, "d": 0, "s": 0}, "mark": len(game.current.actions)}
        lines.append(f"localStorage.setItem('mjdojo:game.current', {json.dumps(json.dumps(data))});")
    return "if (!sessionStorage.getItem('mj-seeded')) { sessionStorage.setItem('mj-seeded', '1'); " + " ".join(lines) + " }"


# ---------------------------------------------------------------- 画面を読む


def settle(page: Page) -> None:
    page.evaluate(SETTLED)


def main_text(page: Page) -> str:
    """画面の文字（ルビを除く。閉じている折りたたみの中身も含む）"""
    return page.locator(MAIN).evaluate(TEXT_WITHOUT_RUBY)


def text_of(page: Page, selector: str) -> str:
    found = page.locator(selector)
    return found.first.evaluate(TEXT_WITHOUT_RUBY) if found.count() else ""


def page_top(page: Page, selector: str) -> float:
    """要素の上端の、ページの先頭からの位置（スクロールしていても同じ値になる）"""
    return round(page.locator(selector).first.evaluate(
        "e => e.getBoundingClientRect().top + document.querySelector('[data-testid=stMain]').scrollTop"), 1)


def open_section(page: Page, label: str) -> None:
    """その見出しの折りたたみを開く（開いていれば、そのまま）"""
    details = page.locator("details", has=page.locator("summary", has_text=label)).first
    if not details.evaluate("e => e.open"):
        page.locator("summary", has_text=label).first.tap()
        page.wait_for_timeout(400)


def to_top(page: Page) -> None:
    """画面のいちばん上へ（折りたたみを開いて下へ動いた画面を、利用者が見る位置に戻す）"""
    page.evaluate("() => { const m = document.querySelector('[data-testid=stMain]'); if (m) m.scrollTop = 0; window.scrollTo(0, 0); }")
    page.wait_for_timeout(200)


#: 手牌より上にある部品の高さ（手牌の位置が動いたとき、どれのせいかを見る）
LAYOUT = """() => {
    const h = sel => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().height * 10) / 10 : null; };
    return {status: h('.mj-game-status'), seats: h('.mj-seats'), headline: h('.mj-headline'), title: h('[data-testid=stMain] h1')};
}"""


def screen_of(page: Page) -> str:
    """いまの画面：final（対局の終わり）・hand_end（局の終わり）・claim（ロンの返事）・turn（自分の打牌）・other"""
    if page.get_by_role("button", name="新しい対局を始める", exact=True).count():
        return "final"
    if page.get_by_role("button", name="次の局へ", exact=True).count():
        return "hand_end"
    if page.locator(f"{HAND} .mj-tile").count():
        keys = action_keys(page)
        return "claim" if "ron" in keys else "turn"
    return "other"


def action_keys(page: Page) -> list[str]:
    return page.locator(f"{HAND} .mj-action").evaluate_all("els => els.map(e => e.dataset.key)")


def marked_index(page: Page, mark: str = "◎") -> int:
    """その印の付いた牌の位置（無ければ −1）"""
    return page.locator(f"{HAND} .mj-tile").evaluate_all(
        "(els, m) => els.findIndex(e => (e.querySelector('.mj-mark') || {}).textContent === m)", mark)


def hand_labels(page: Page) -> list[str]:
    return page.locator(f"{HAND} .mj-tile").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")


def scores(page: Page) -> list[str]:
    return [re.sub(r"\s+", " ", t) for t in page.locator(".mj-seat").evaluate_all(
        "els => els.map(e => e.innerText)")]


# ---------------------------------------------------------------- 操作する


def tap_and_wait(page: Page, target) -> float:
    """押して、画面が描き直されるまで待つ。かかった秒数を返す"""
    t0 = time.monotonic()
    target.tap()
    page.wait_for_function(NOT_PENDING, timeout=60000)
    settle(page)
    return round(time.monotonic() - t0, 2)


def play_turn(page: Page, *, pass_claim: bool = False) -> tuple[str, float]:
    """自分の番を 1 回打つ（コーチのおすすめどおり）。→（したこと, かかった秒数）"""
    keys = action_keys(page)
    if "ron" in keys:
        key = "pass" if pass_claim else "ron"
        return key, tap_and_wait(page, page.locator(f'{HAND} .mj-action[data-key="{key}"]'))
    if "tsumo" in keys:
        return "tsumo", tap_and_wait(page, page.locator(f'{HAND} .mj-action[data-key="tsumo"]'))
    tiles = page.locator(f"{HAND} .mj-tile")
    index = marked_index(page)
    if index < 0:
        index = tiles.count() - 1
    riichi = page.locator(f"{HAND} .mj-riichi")
    did = "discard"
    if riichi.is_visible() and riichi.inner_text().startswith("◎"):
        riichi.tap()
        page.wait_for_timeout(150)
        did = "riichi"
    tiles.nth(index).tap()
    page.wait_for_timeout(150)
    return did, tap_and_wait(page, page.locator(f"{HAND} .mj-confirm"))


# ---------------------------------------------------------------- 本体


def run(base_url: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    result: dict = {"problems": []}
    console_errors: list[str] = []
    failed_requests: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            result["problems"].append(message)

    def is_base_path_probe(url: str) -> bool:
        # ページを直接開いたとき、Streamlit の画面側は「/ページ名/_stcore/...」も試してから正しい場所を使う
        return bool(re.search(r"/[^/]+/_stcore/(health|host-config)$", url))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def new_context(*, height: int = HEIGHT, width: int = WIDTH, dark: bool = False, script: str | None = None) -> BrowserContext:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                is_mobile=width < 600,
                has_touch=True,
                user_agent=IPHONE_UA if width < 600 else None,
                color_scheme="dark" if dark else "light",
                locale="ja-JP",
            )
            if script:
                context.add_init_script(script)
            return context

        def open_page(context: BrowserContext, path: str = "/game") -> Page:
            page = context.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and not is_base_path_probe(m.location.get("url", "")) else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on("response", lambda r: failed_requests.append(f"{r.status} {r.url}") if r.status >= 400 and not is_base_path_probe(r.url) else None)
            page.goto(base + path)
            return page

        def wait_screen(page: Page, timeout: float = 60) -> str:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                screen = screen_of(page)
                if screen != "other":
                    settle(page)
                    return screen_of(page)
                page.wait_for_timeout(300)
            return "other"

        def shot(page: Page, name: str, width: int = WIDTH, *, full: bool = False) -> None:
            page.screenshot(path=str(out_dir / f"game_{name}.png"), full_page=full)
            check_page(page, name, width)

        def check_page(page: Page, name: str, width: int = WIDTH) -> None:
            expect(page.locator('[data-testid="stException"]').count() == 0, f"{name}: 画面に例外が出ている")
            overflow = page.evaluate("document.documentElement.scrollWidth")
            expect(overflow <= width, f"{name}: 横にはみ出している（{overflow}px）")
            broken = page.locator("img").evaluate_all("els => els.filter(e => e.complete && e.naturalWidth === 0).map(e => e.src)")
            expect(not broken, f"{name}: 読めない画像がある: {broken[:3]}")

        def check_ruby(page: Page, name: str) -> None:
            """折りたたみをすべて開いて、初出なのにルビが付いていない用語が無いことを確かめる。終わったら、画面の上に戻す"""
            missing = terms_without_ruby(page)
            settle(page)
            to_top(page)
            result.setdefault("ruby_missing", {})[name] = missing
            expect(not missing, f"{name}: 初出なのにルビが無い用語: {missing}")

        # ---- 1. ホームから入って、東風戦を 1 回、最後まで打つ（実機と同じ大きさの画面）
        context = new_context()
        page = open_page(context, "/")
        page.locator(HOME_LINK, has_text="CPU と対局").first.wait_for(timeout=60000)
        page.locator(HOME_LINK, has_text="CPU と対局").first.tap()
        screen = wait_screen(page)
        expect(screen in ("turn", "claim", "hand_end"), f"対局の画面が出ない: {screen}")
        shot(page, "01_first_view")
        tiles = page.locator(f"{HAND} .mj-tile")
        boxes = tiles.evaluate_all("els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height, r.top]; })")
        bar_bottom = page.locator(f"{HAND} .mj-bar").evaluate("e => e.getBoundingClientRect().bottom")
        text = main_text(page)
        result["first_view"] = {
            "tiles": len(boxes), "tile_width": round(min(b[0] for b in boxes), 1) if boxes else None,
            "bar_bottom": round(bar_bottom), "status": text_of(page, ".mj-game-status"), "seats": scores(page),
        }
        expect(len(boxes) in (13, 14), f"手牌の枚数が違う: {len(boxes)}")
        expect(boxes and min(b[0] for b in boxes) >= 40, "牌が小さすぎる")
        expect(bar_bottom <= HEIGHT, f"「この牌を切る」の段が、最初の画面に収まっていない（下端 {bar_bottom:.0f}px ／ 画面 {HEIGHT}px）")
        expect("東 1 局" in text and "供託" in text and "残り" in text, "局の状況（東 1 局・供託・残り）が出ていない")
        expect(page.locator(".mj-seat").count() == 4, "4 人の持ち点が出ていない")
        expect(all("25,000" in s for s in scores(page)) or "あがり" in text, f"始めの持ち点が 25,000 点になっていない: {scores(page)}")
        check_ruby(page, "最初の画面")

        timings: list[float] = []
        hand_tops: set[float] = set()
        bar_tops: set[float] = set()
        seen: dict[str, int] = {}
        hands_done = 0
        passed_once = False
        reloaded = False
        each_checked = False
        for _step in range(MAX_STEPS):
            screen = screen_of(page)
            if screen == "final":
                break
            if screen == "hand_end":
                hands_done += 1
                banner = text_of(page, ".mj-result-card")
                result.setdefault("hands", []).append(banner[:80])
                expect(page.locator(".mj-reveal").count() == 4, f"局の終わりに、4 人の手牌が出ていない（{hands_done} 局目）")
                if hands_done == 1:
                    shot(page, "03_hand_end")
                    check_ruby(page, "局の終わり")
                button = page.get_by_role("button", name="次の局へ", exact=True).first
                button.scroll_into_view_if_needed()
                button.tap()
                wait_screen(page)
                expect("本場" in text_of(page, ".mj-game-status"), "次の局の状況が出ていない")
                continue
            if screen == "other":
                page.wait_for_timeout(500)
                seen["other"] = seen.get("other", 0) + 1
                expect(seen["other"] < 20, "対局の画面が、どれでもない状態のまま")
                if seen["other"] >= 20:
                    break
                continue
            # ---- 自分の番
            top = page_top(page, f"{HAND} .mj-tile")
            if top not in hand_tops:
                result.setdefault("layouts", []).append({"hand_top": top, "screen": screen, **page.evaluate(LAYOUT),
                                                         "headline_text": text_of(page, ".mj-headline")[:60]})
            hand_tops.add(top)
            if screen == "turn":
                bar_tops.add(page_top(page, f"{HAND} .mj-bar"))
            if page.locator(".mj-danger").count() and "threat" not in seen:
                seen["threat"] = 1
                shot(page, "04_threat")
                expect("ベタオリの手順" in main_text(page), "リーチを受けているのに、ベタオリの手順が出ていない")
                check_ruby(page, "リーチを受けている")
            if screen == "claim" and "claim" not in seen:
                seen["claim"] = 1
                shot(page, "05_claim")
                expect(not page.locator(f"{HAND} .mj-confirm").is_visible(), "ロンの返事のときに、「この牌を切る」が出ている")
                check_ruby(page, "ロンの返事")
            if not reloaded and screen == "turn" and len(result.get("turns", [])) >= 3:
                # 再読み込み（＝新しいセッション）で、同じ局面に戻るか
                reloaded = True
                before = (hand_labels(page), scores(page))
                page.reload()
                wait_screen(page)
                after = (hand_labels(page), scores(page))
                result["reload"] = {"same": before == after}
                expect(before == after, "再読み込みのあと、同じ局面に戻っていない")
                expect("再開したもの" in main_text(page), "再開したことが表示されていない")
                continue
            if not each_checked and screen == "turn" and len(result.get("turns", [])) >= 5:
                # CPU の打牌を「1 人ずつ」見せる。手牌の位置は変わらない
                each_checked = True
                open_section(page, "設定（対局")
                option = page.get_by_role("radio", name="1 人ずつ", exact=True)
                option.scroll_into_view_if_needed()
                option.tap()
                settle(page)
                to_top(page)
                did, seconds = play_turn(page)
                timings.append(seconds)
                result.setdefault("turns", []).append(did)
                if screen_of(page) in ("turn", "claim"):
                    expect(page.locator(".mj-steps-each").count() == 1 or not page.locator(".mj-moves").count(),
                           "「1 人ずつ」にしたのに、CPU の打牌が 1 人ずつ出ていない")
                    hand_tops.add(page_top(page, f"{HAND} .mj-tile"))
                    shot(page, "06_each")
                    option = page.get_by_role("radio", name="まとめて", exact=True)
                    option.scroll_into_view_if_needed()
                    option.tap()
                    settle(page)
                    to_top(page)
                continue
            if screen == "turn" and len(result.get("turns", [])) == 1:
                shot(page, "02_after_first_discard")
            pass_claim = screen == "claim" and not passed_once
            passed_once = passed_once or pass_claim
            did, seconds = play_turn(page, pass_claim=pass_claim)
            timings.append(seconds)
            result.setdefault("turns", []).append(did)
            if did == "pass" and screen_of(page) == "turn":
                expect("フリテン" in main_text(page), "ロンを見送ったあとの番に、フリテンの知らせが出ていない")
        else:
            expect(False, f"{MAX_STEPS} 回操作しても、対局が終わらない")

        result["play"] = {
            "hands": hands_done + 1, "turns": len(timings), "moves": {k: result.get("turns", []).count(k) for k in set(result.get("turns", []))},
            "seconds_median": statistics.median(timings) if timings else None, "seconds_max": max(timings) if timings else None,
            "hand_top": sorted(hand_tops), "bar_top": sorted(bar_tops),
        }
        result.pop("turns", None)
        expect(hand_tops and max(hand_tops) - min(hand_tops) <= 1, f"手牌の位置が動く: {sorted(hand_tops)}")
        expect(bar_tops and max(bar_tops) - min(bar_tops) <= 1, f"「この牌を切る」の段の位置が動く: {sorted(bar_tops)}")
        expect(timings and statistics.median(timings) <= 3.0, f"打牌の応答が遅い（中央値 {statistics.median(timings) if timings else None} 秒）")

        # ---- 2. 対局の終わり：順位・成績・新しい対局
        expect(screen_of(page) == "final", "対局が最後まで終わっていない")
        cards = page.locator(".mj-result-card").evaluate_all(f"els => els.map({TEXT_WITHOUT_RUBY})")
        final = next((c for c in cards if "対局終了" in c), "")
        result["final"] = final[:120]
        expect(re.search(r"対局終了：[1-4] 位", final) is not None, f"対局の終わりの表示が違う: {final[:60]}")
        shot(page, "07_final")
        check_ruby(page, "対局の終わり")
        stats = text_of(page, ".mj-lesson") + " " + " ".join(page.locator(".mj-stats").evaluate_all("els => els.map(e => e.innerText)"))
        result["stats"] = stats[:300]
        expect("1 戦" in stats and "ヒントあり" in stats, f"成績に、打った対局が入っていない: {stats[:120]}")
        history = page.evaluate("() => localStorage.getItem('mjdojo:game.history')")
        expect(history is not None and len(json.loads(history)) == 1, "ブラウザに、対局の成績が 1 つ保存されていない")
        button = page.get_by_role("button", name="新しい対局を始める", exact=True)
        button.scroll_into_view_if_needed()
        button.tap()
        wait_screen(page)
        expect("東 1 局" in text_of(page, ".mj-game-status"), "新しい対局が始まっていない")
        expect(page.evaluate("() => document.querySelector('[data-testid=stMain]').scrollTop") == 0, "新しい対局を始めても、画面の上に戻らない")
        context.close()

        # ---- 3. 決まった局面：ロンの返事 → ロン
        game = find("claim")
        context = new_context(script=storage_script(game))
        page = open_page(context)
        expect(wait_screen(page) == "claim", "ロンの返事の局面が出ない")
        shot(page, "08_claim_view")
        expect(action_keys(page) == ["ron", "pass"], f"ロンと見送るのボタンが違う: {action_keys(page)}")
        bottom = page.locator(f'{HAND} .mj-action[data-key="ron"]').evaluate("e => e.getBoundingClientRect().bottom")
        expect(bottom <= HEIGHT, f"「ロン」のボタンが、最初の画面に収まっていない（下端 {bottom:.0f}px）")
        page.locator(f"{HAND} .mj-tile").first.tap(force=True)      # 押せない作りなので、押せる状態かを確かめずに押す
        page.wait_for_timeout(200)
        expect(page.locator(f"{HAND} .mj-tile[aria-pressed=true]").count() == 0, "ロンの返事のときに、牌を選べてしまう")
        tap_and_wait(page, page.locator(f'{HAND} .mj-action[data-key="ron"]'))
        expect(wait_screen(page) in ("hand_end", "final"), "ロンしたのに、局が終わらない")
        text = main_text(page)
        expect(re.search(r"自分（.家）のロン", text) is not None and "あがりの解説（自分）" in text, "ロンのあがりの表示が違う")
        shot(page, "09_ron", full=True)
        context.close()

        # ---- 4. 決まった局面：リーチを受けている（守備の表とベタオリ）を、縦に長い画面で
        game = find("threat")
        context = new_context(height=TALL, script=storage_script(game))
        page = open_page(context)
        expect(wait_screen(page) == "turn", "リーチを受けた局面が出ない")
        text = main_text(page)
        expect(page.locator(".mj-danger").count() >= 1 and "ベタオリの手順" in text, "守備の表かベタオリの手順が出ていない")
        expect(any(word in text for word in ("現物", "スジ", "字牌", "無スジ")), "危険度の根拠が出ていない")
        shot(page, "10_threat_tall")
        check_ruby(page, "リーチを受けている（縦に長い画面）")
        context.close()

        # ---- 5. 決まった局面：対局の終わり（開いただけでは、成績に二重に入らない）
        game = find("finished")
        context = new_context(script=storage_script(game))
        page = open_page(context)
        expect(wait_screen(page) == "final", "対局の終わりの局面が出ない")
        shot(page, "11_finished")
        context.close()

        # ---- 6. ほかの画面幅と、暗い画面
        game = find("threat")
        widths = {}
        for width in (320, 430, 1280):
            context = new_context(width=width, height=900, script=storage_script(game))
            page = open_page(context)
            wait_screen(page)
            box = page.locator(f"{HAND} .mj-tile").first.evaluate("e => Math.round(e.getBoundingClientRect().width * 10) / 10")
            widths[width] = {"tile": box}
            shot(page, f"12_width_{width}", width)
            context.close()
        result["widths"] = widths
        context = new_context(height=900, dark=True, script=storage_script(game))
        page = open_page(context)
        wait_screen(page)
        shot(page, "13_dark")
        context.close()
        browser.close()

    result["console_errors"] = console_errors[:10]
    result["failed_requests"] = failed_requests[:10]
    expect(not console_errors, f"ブラウザのエラー: {console_errors[:3]}")
    expect(not failed_requests, f"読み込みに失敗: {failed_requests[:3]}")
    return result


def _main(argv: list[str], runner: Callable[[str, Path], dict] = run) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    outcome = runner(argv[1], Path(argv[2]))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 1 if outcome["problems"] else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

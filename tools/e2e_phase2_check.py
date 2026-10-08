"""スマホ相当の画面で、Phase 2 のページ（役図鑑・用語辞典・ドリル・卓で打つとき・ルールの違い・記録と保存）と
役指定練習を、通しで操作する確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、リンク・選択肢のボタン・牌タップ・
ファイルの保存と読み込みが、画面上で意図どおり動くかを確かめる。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で）
       python tools/e2e_phase2_check.py http://localhost:8501 出力フォルダ
       python tools/e2e_phase2_check.py http://localhost:8501 出力フォルダ drill,records   （一部だけ確かめる）

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable, Collection
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from e2e_ruby import terms_without_ruby  # noqa: E402
from playwright.sync_api import BrowserContext, Page, sync_playwright  # noqa: E402

from engine import practice  # noqa: E402
from engine.content import glossary, rule_book, table_guide, yaku_pages  # noqa: E402
from engine.drills import KINDS, question  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402
from engine.progress import Stamp, dump_stamps  # noqa: E402
from engine.records import HandRecord, dump_record  # noqa: E402
from engine.scoring.explain import explain  # noqa: E402
from engine.srs import DAY, Card, Deck, dump_deck  # noqa: E402
from engine.target_coach import target_result  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
WIDTH, HEIGHT = 375, 606     # 利用者の実機（iPhone の Safari）で測った画面の大きさ
TALL = 5000                  # 縦に長いページを 1 枚に収めるための高さ（Streamlit は内側の枠でスクロールするため）
HEADER = 60                  # 画面の上の帯（メニューのボタン）の高さ
MAIN = '[data-testid="stMain"]'
LINK = f'{MAIN} a[data-testid="stPageLink-NavLink"]'
PAGE_NAMES = ["ホーム", "CPU と対局", "一人練習", "点数計算ラボ", "役図鑑", "用語辞典", "ドリル", "卓で打つとき", "ルールの違い", "記録と保存", "実機チェック"]
#: 画面の文字が、渡した文字列（操作する前の内容）から変わったら真になる式
MAIN_CHANGED = "t => document.querySelector('[data-testid=stMain]').innerText !== t"
#: 要素の中の文字を、ルビ（読みがな）を除いて取り出す式。空白は 1 つにまとめる
TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt, style, script').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""
NOW = int(time.time())


# ---------------------------------------------------------------- 決まった記録・局面を用意する


def aim_step(state: practice.PracticeState) -> practice.Action:
    """狙う役のコーチのおすすめどおりに 1 手打つ（もう作れないときは、ツモ切り）"""
    advice = practice.target_advice_of(state)
    if advice is None or advice.pick is None:
        return practice.discard(state.drawn)
    return practice.discard(advice.pick.tile)


def find_target_win(key: str) -> practice.PracticeState:
    """狙う役のコーチに従って打ち、いまツモると狙った役が付く局面を探す"""
    for seed in range(300):
        state = practice.start(practice.PracticeConfig(seed=seed, luck=LuckSettings(75, 75), target=key))
        while not state.finished:
            if state.can_tsumo:
                win = practice.apply(state, practice.TSUMO).result.win
                if target_result(explain(win, state.config.rules), key).made:
                    return state
                break
            state = practice.apply(state, aim_step(state))
    raise SystemExit("確認に使う局面が見つかりません")


def record(when: int, seed: int, *, yaku: tuple[str, ...] = ("riichi",), target: str = "", made: bool = False) -> HandRecord:
    return HandRecord(
        time=when, seed=seed, deal=0, draw=0, hinted=False, win=True, turn=9, riichi=True, tenpai=True,
        points=1300, han=1, fu=40, yaku=yaku, decisions=8, best=7, target=target, made=made,
    )


def sample_records() -> dict[str, str]:
    """ブラウザに残っている進み具合の例（成績 2 局・スタンプ 2 役・ドリル 8 回）"""
    history = [record(NOW - 3000, 1), record(NOW - 2000, 2, yaku=("sanshoku",), target="sanshoku", made=True)]
    return {
        "practice.history": "[" + ",".join(dump_record(r) for r in history) + "]",
        "progress.stamps": dump_stamps({"riichi": Stamp(1, NOW - 3000, NOW - 3000, 1), "sanshoku": Stamp(1, NOW - 2000, NOW - 2000, 1)}),
        "drill.table": dump_deck(Deck({"cr:30:1": Card(2, NOW + 3 * DAY, 1, 1, NOW - 100)}, 3, 2)),
        "drill.score": dump_deck(Deck({}, 5, 5)),
    }


def storage_script(values: dict[str, str] | None = None, *, state: practice.PracticeState | None = None, **settings) -> str:
    """ページを開く前に、ブラウザ内保存に記録を入れておくスクリプト（最初の 1 回だけ働く）"""
    full = {"deal": 75, "draw": 75, "tenpai_deal": False, "mark": True, "hint": "before", "level": 2, "target": None, **settings}
    items = {"practice.settings": json.dumps(full), **(values or {})}
    if state is not None:
        items["practice.hand"] = json.dumps({"v": 1, "save": practice.to_save(state), "counted": True, "hinted": False})
    lines = [f"localStorage.setItem({json.dumps('mjdojo:' + name)}, {json.dumps(value)});" for name, value in items.items()]
    return "if (!sessionStorage.getItem('mj-seeded')) { sessionStorage.setItem('mj-seeded', '1'); " + " ".join(lines) + " }"


# ---------------------------------------------------------------- 画面の操作


def settle(page: Page, ms: int = 700) -> None:
    page.wait_for_timeout(ms)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(200)


def main_text(page: Page) -> str:
    """画面の文字（ルビを除く。閉じている折りたたみの中身も含む）"""
    return page.locator(MAIN).evaluate(TEXT_WITHOUT_RUBY)


def scroll_top(page: Page) -> float:
    """画面が、上からどれだけスクロールされているか"""
    return page.evaluate("() => document.querySelector('[data-testid=stMain]').scrollTop")


def stored(page: Page, name: str) -> str | None:
    """ブラウザ内保存の中身"""
    return page.evaluate("name => localStorage.getItem('mjdojo:' + name)", name)


def link(page: Page, text: str):
    """画面の中の、ページへのリンク"""
    return page.locator(LINK, has_text=text)


def tap_and_wait(page: Page, target, *, timeout: int = 20000) -> None:
    """押して、画面の文字が変わるまで待つ"""
    before = page.locator(MAIN).inner_text()
    target.tap()
    page.wait_for_function(MAIN_CHANGED, arg=before, timeout=timeout)
    settle(page, 500)


def open_section(page: Page, label: str) -> None:
    details = page.locator("details", has=page.locator("summary", has_text=label)).first
    if not details.evaluate("e => e.open"):
        details.locator("summary").tap()
        settle(page, 400)


def wait_hand(page: Page) -> None:
    page.locator(".mj-tile").nth(13).wait_for(timeout=60000)
    settle(page, 500)


def run(base_url: str, out_dir: Path, only: Collection[str] = ()) -> dict:
    """only に名前（home / yaku / target / terms / guides / drill / records / looks）を渡すと、その部分だけを確かめる"""
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

        def new_context(*, height: int = TALL, width: int = WIDTH, dark: bool = False, script: str | None = None) -> BrowserContext:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                is_mobile=width < 600,
                has_touch=width < 600,
                user_agent=IPHONE_UA if width < 600 else None,
                color_scheme="dark" if dark else "light",
                locale="ja-JP",
                accept_downloads=True,
            )
            if script:
                context.add_init_script(script)
            return context

        def open_page(context: BrowserContext, path: str, *, wait: str = "h1") -> Page:
            page = context.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and not is_base_path_probe(m.location.get("url", "")) else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on("response", lambda r: failed_requests.append(f"{r.status} {r.url}") if r.status >= 400 and not is_base_path_probe(r.url) else None)
            page.goto(base + path)
            page.locator(f"{MAIN} {wait}").first.wait_for(timeout=60000)
            settle(page, 800)
            return page

        def shot(page: Page, name: str, width: int = WIDTH) -> None:
            page.screenshot(path=str(out_dir / f"phase2_{name}.png"))
            expect(page.locator('[data-testid="stException"]').count() == 0, f"{name}: 画面に例外が出ている")
            overflow = page.evaluate("document.documentElement.scrollWidth")
            expect(overflow <= width, f"{name}: 横にはみ出している（{overflow}px）")
            images = page.locator(f"{MAIN} img")
            broken = images.evaluate_all("els => els.filter(e => e.complete && e.naturalWidth === 0).length")
            expect(broken == 0, f"{name}: 読めていない画像が {broken} 枚ある")

        pages = yaku_pages()
        parts: dict[str, Callable[[], None]] = {}

        def part(name: str):
            """確かめる内容のひとまとまり（名前を指定して、そこだけ動かせる）"""
            def register(check: Callable[[], None]) -> Callable[[], None]:
                parts[name] = check
                return check
            return register

        def check_ruby(page: Page, name: str) -> None:
            """折りたたみをすべて開いて、初出なのにルビが付いていない用語が無いことを確かめる"""
            missing = terms_without_ruby(page)
            if missing:
                result.setdefault("ruby_missing", {})[name] = missing
            result["ruby_checked"] = result.get("ruby_checked", 0) + 1
            expect(not missing, f"{name}: 初出なのにルビが無い用語: {missing}")

        # ================================================================ 1. ホームとメニュー
        @part("home")
        def check_home() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/")
            shot(page, "01_home")
            names = [a.inner_text().split("\n")[-1] for a in page.locator(LINK).all()]
            result["home_links"] = names
            expect(all(any(name in shown for shown in names) for name in PAGE_NAMES[1:]), f"ホームから行けないページがある: {names}")
            check_ruby(page, "ホーム")
            # 上の帯の「»」を押すと、ページの一覧が出る。選ぶと、一覧は閉じる
            page.locator('[data-testid="stExpandSidebarButton"]').tap()
            page.locator('[data-testid="stSidebarNavLink"]').first.wait_for(timeout=10000)
            page.wait_for_timeout(500)
            menu = [a.inner_text().split("\n")[-1].strip() for a in page.locator('[data-testid="stSidebarNavLink"]').all()]
            sections = [h.inner_text() for h in page.locator('[data-testid="stNavSectionHeader"]').all()]
            result["menu"] = {"pages": menu, "sections": sections}
            expect(menu == PAGE_NAMES and sections == ["打つ", "学ぶ", "記録"], f"メニューの並びが違う: {menu} / {sections}")
            shot(page, "02_menu")
            page.locator('[data-testid="stSidebarNavLink"]', has_text="用語辞典").tap()
            page.locator(f"{MAIN} h1", has_text="用語辞典").wait_for(timeout=20000)
            settle(page, 800)
            expect(page.locator('[data-testid="stSidebar"]').get_attribute("aria-expanded") == "false", "メニューからページを選んでも、メニューが閉じない")
            expect(page.url.endswith("/terms"), f"メニューから用語辞典に行けない: {page.url}")
            context.close()

        # ================================================================ 2. 役図鑑
        @part("yaku")
        def check_yaku() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/yaku")
            rows = page.locator(LINK)
            result["yaku_list"] = {"links": rows.count()}
            expect(rows.count() == len(pages), f"役の一覧の数が違う: {rows.count()}")
            shot(page, "03_yaku_list")
            check_ruby(page, "役図鑑（一覧）")
            # 一覧の途中から役を開くと、そのページのいちばん上が出る。URL も、その役のものになる
            target = link(page, "三色同順")
            target.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            scrolled = scroll_top(page)
            target.tap()
            page.locator(".mj-yaku-head").wait_for(timeout=20000)
            settle(page, 800)
            first_top = page.locator(LINK).first.evaluate("e => e.getBoundingClientRect().top")
            result["yaku_open"] = {"scrolled_before": round(scrolled), "scroll_after": round(scroll_top(page)), "url": page.url, "first_row_top": round(first_top)}
            expect(scrolled > 300 and scroll_top(page) == 0, f"一覧から役を開いたとき、ページの上に戻らない: {result['yaku_open']}")
            expect(page.url.endswith("/yaku?y=sanshoku"), f"役のページの URL が違う: {page.url}")
            expect(first_top >= HEADER - 2, f"いちばん上の行が、上の帯に隠れている（{first_top:.0f}px）")
            head = page.locator(".mj-yaku-head").evaluate(TEXT_WITHOUT_RUBY)
            expect(head == "三色同順 サンショクドウジュン", f"役の見出しが違う: {head}")
            shot(page, "04_yaku_page")
            text = main_text(page)
            for needed in ("成立する条件", "成立する例", "ひっかけ：付きそうで、付かない例", "狙い方のコツ", "出やすさの目安", "読み方と、名前の由来"):
                expect(needed in text, f"役のページに「{needed}」が無い")
            expect(page.locator(".mj-ex-ok").count() >= 2 and page.locator(".mj-ex-ng").count() >= 2, "成立例・ひっかけ例が 2 つずつ無い")
            expect(page.get_by_role("button", name="この役を実戦で練習する").count() == 1, "「この役を実戦で練習する」が無い")
            # いちばん下の「次の役」で進むと、次のページのいちばん上が出る。ブラウザの「戻る」で、前の役に戻る
            following = link(page, "次の役：")
            expect(following.inner_text().split("\n")[-1].strip() == "次の役：三色同刻 サンショクドウコー".replace(" ", "　"), f"下の「次の役」の文字が違う: {following.inner_text()!r}")
            following.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            scrolled = scroll_top(page)
            following.tap()
            page.wait_for_function("() => document.querySelector('.mj-yaku-head') && document.querySelector('.mj-yaku-head').innerText.includes('三色同刻')", timeout=20000)
            settle(page, 800)
            result["yaku_next"] = {"scrolled_before": round(scrolled), "scroll_after": round(scroll_top(page)), "url": page.url}
            expect(scrolled > 1000 and scroll_top(page) == 0, f"「次の役」で、ページの上に戻らない: {result['yaku_next']}")
            expect(page.url.endswith("/yaku?y=sanshoku_doukou"), f"次の役の URL が違う: {page.url}")
            page.go_back()
            page.wait_for_function("() => document.querySelector('.mj-yaku-head') && document.querySelector('.mj-yaku-head').innerText.includes('三色同順')", timeout=20000)
            settle(page, 500)
            page.go_back()
            page.locator(f"{MAIN} h1", has_text="役図鑑").wait_for(timeout=20000)
            settle(page, 500)
            expect(page.url.endswith("/yaku") and page.locator(LINK).count() == len(pages), f"「戻る」で一覧に戻れない: {page.url}")
            context.close()

            # いろいろな役のページで、ルビと画像を確かめる（役牌・役満・河の例・練習できない役）
            context = new_context()
            for key in ("riichi", "yakuhai", "sanshoku", "honroutou", "kokushi", "chankan", "nagashi_mangan"):
                page = open_page(context, f"/yaku?y={key}", wait=".mj-yaku-head")
                shot(page, f"05_yaku_{key}")
                check_ruby(page, f"役図鑑（{key}）")
                page.close()
            context.close()

        # ================================================================ 3. 役図鑑 → 役指定練習 → スタンプ
        @part("target")
        def check_target() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/yaku?y=sanshoku", wait=".mj-yaku-head")
            page.get_by_role("button", name="この役を実戦で練習する").tap()
            wait_hand(page)
            text = main_text(page)
            result["target_start"] = {"url": page.url, "headline": page.locator(".mj-headline").first.evaluate(TEXT_WITHOUT_RUBY)}
            expect(page.url.endswith("/practice"), f"役指定練習の URL に、役の指定が残っている: {page.url}")
            expect("役指定：三色同順" in text and "めざす形（三色同順）" in text, "役指定練習が始まっていない")
            expect("三色同順" in result["target_start"]["headline"], f"役を狙うヒントが出ていない: {result['target_start']['headline']}")
            expect(page.locator(".mj-hand-root .mj-mark").count() >= 1, "役に近い切り方の印（◎）が出ていない")
            bar_bottom = page.locator(".mj-hand-root .mj-bar").evaluate("e => e.getBoundingClientRect().bottom")
            expect(bar_bottom <= HEIGHT, f"役指定練習で、「この牌を切る」が最初の画面に収まっていない（{bar_bottom:.0f}px）")
            shot(page, "06_target_practice")
            # 印の付いた牌（おすすめ）を切る → 前の打牌の評価が、狙う役から見たものになる
            page.locator(".mj-hand-root .mj-tile", has=page.locator(".mj-mark")).first.tap()
            page.wait_for_timeout(200)
            tap_and_wait(page, page.locator(".mj-hand-root .mj-confirm"))
            if page.locator(".mj-tile").count() == 14:
                review = page.locator(".mj-review").first.evaluate(TEXT_WITHOUT_RUBY)
                result["target_review"] = review
                expect("三色同順" in review and "✓" in review, f"おすすめを切ったのに、評価が違う: {review}")
            # 何巡打っても、手牌の位置が動かない（案内の長さが変わっても、見出しの高さは同じ）。あがりの形の巡も含めて測る
            hand_tops = []
            for _ in range(8):
                if page.locator(".mj-hand-root .mj-tile").count() != 14:
                    break
                hand_tops.append(round(page.locator(".mj-hand-root .mj-tile").first.evaluate("e => e.getBoundingClientRect().top"), 1))
                if page.get_by_role("button", name="ツモ（あがる）").count():
                    tsumo = page.get_by_role("button", name="ツモ（あがる）").evaluate("e => e.getBoundingClientRect().bottom")
                    result["target_tsumo_bottom"] = round(tsumo)
                    expect(tsumo <= HEIGHT, f"役指定練習で、「ツモ（あがる）」が最初の画面に収まっていない（下端 {tsumo:.0f}px）")
                    break
                marked = page.locator(".mj-hand-root .mj-tile", has=page.locator(".mj-mark"))
                (marked.first if marked.count() else page.locator(".mj-hand-root .mj-tile").last).tap()
                page.wait_for_timeout(200)
                tap_and_wait(page, page.locator(".mj-hand-root .mj-confirm"))
            result["target_hand_tops"] = hand_tops
            expect(len(hand_tops) >= 3 and max(hand_tops) - min(hand_tops) <= 1, f"役指定練習で、巡目によって手牌の位置が動く: {hand_tops}")
            context.close()

            context = new_context()
            page = open_page(context, "/yaku?y=sanshoku", wait=".mj-yaku-head")
            page.get_by_role("button", name="この役を実戦で練習する").tap()
            wait_hand(page)
            check_ruby(page, "役指定練習（打っている途中）")
            context.close()

            # あがると、付いた役にスタンプが押される（役図鑑の一覧と、役のページに出る）
            state = find_target_win("tanyao")
            context = new_context(height=HEIGHT, script=storage_script(state=state, target="tanyao"))
            page = open_page(context, "/practice")
            wait_hand(page)
            expect("あがりの形です。断么九が付きます。" in main_text(page), "狙った役が付くあがりの形の案内が出ていない")
            page.get_by_role("button", name="ツモ（あがる）").tap()
            page.get_by_role("button", name="次の局へ").first.wait_for(timeout=20000)
            settle(page)
            text = main_text(page)
            expect("狙った断么九が付いた。" in text and "はじめて成立させた役" in text, "狙った役が付いたことと、スタンプの案内が出ていない")
            next_bottom = page.get_by_role("button", name="次の局へ").first.evaluate("e => e.getBoundingClientRect().bottom")
            result["target_win_next_bottom"] = round(next_bottom)
            expect(next_bottom <= HEIGHT, f"役指定練習であがったとき、「次の局へ」が最初の画面に収まっていない（下端 {next_bottom:.0f}px ／ 画面 {HEIGHT}px）")
            stamps = json.loads(stored(page, "progress.stamps") or "{}")
            result["stamps_after_win"] = sorted(stamps)
            expect("tanyao" in stamps, f"スタンプが保存されていない: {sorted(stamps)}")
            shot(page, "07_target_win")
            check_ruby(page, "役指定練習（あがった局）")
            link(page, "役図鑑で「断么九」を見る").tap()
            page.locator(".mj-yaku-head").wait_for(timeout=20000)
            settle(page, 800)
            expect("スタンプ：1 回 成立させた" in main_text(page), "役のページに、スタンプが出ていない")
            expect("役指定練習：1 局のうち、1 局で、この役の形ができた" in main_text(page), "役のページに、役指定練習の成績が出ていない")
            link(page, "一覧へ").first.tap()
            page.locator(f"{MAIN} h1", has_text="役図鑑").wait_for(timeout=20000)
            settle(page, 800)
            label = link(page, "断么九").inner_text()
            progress = page.locator('[data-testid="stProgress"]').inner_text()
            result["stamp_list"] = {"label": label.replace("\n", " "), "progress": progress}
            expect("✓1" in label and f"スタンプ {len(stamps)} / {len(pages)}" in progress, f"一覧に、スタンプが出ていない: {result['stamp_list']}")
            shot(page, "08_yaku_list_stamped")
            context.close()

            # 設定から、狙う役を選ぶ・やめる
            context = new_context()
            page = open_page(context, "/practice")
            wait_hand(page)
            open_section(page, "設定（ツキ補正・役指定・コーチ）")
            settings = page.locator("details", has=page.locator("summary", has_text="設定（ツキ補正・役指定・コーチ）")).first
            tap_and_wait(page, settings.locator(".mj-opt", has_text="役満"))
            expect("狙う役を 1 つ選んでください。" in main_text(page), "まとまりを選んだあと、役を選ぶ案内が出ない")
            tap_and_wait(page, settings.locator(".mj-opt", has_text="国士無双"))
            text = main_text(page)
            expect("目安：ツキ補正が「中」で" in text and "変更は次の局から反映されます" in text, "役を選んだあとの説明が出ない")
            expect(settings.locator('.mj-opt[aria-pressed="true"]', has_text="国士無双").count() == 1, "選んだ役に、選択中の印が付いていない")
            shot(page, "09_target_settings")
            page.get_by_role("button", name="この設定で新しい局を始める").tap()
            page.wait_for_function("() => document.querySelector('[data-testid=stMain]').innerText.includes('役指定：国士無双')", timeout=20000)
            wait_hand(page)
            expect("国士無双の形" in main_text(page), "国士無双のめざす形が出ていない")
            check_ruby(page, "役指定練習（国士無双）")
            open_section(page, "設定（ツキ補正・役指定・コーチ）")
            tap_and_wait(page, settings.locator(".mj-opt", has_text="なし").first)
            page.get_by_role("button", name="この設定で新しい局を始める").tap()
            page.wait_for_function("() => !document.querySelector('[data-testid=stMain]').innerText.includes('役指定：')", timeout=20000)
            wait_hand(page)
            expect(json.loads(stored(page, "practice.settings"))["target"] is None, "役指定をやめたことが、保存されていない")
            context.close()

        # ================================================================ 4. 用語辞典
        @part("terms")
        def check_terms() -> None:
            book = glossary()
            context = new_context()
            page = open_page(context, "/terms")
            first = next(iter(book.categories))
            expect(book.of(first)[0].term in main_text(page), "最初の分類の用語が出ていない")
            shot(page, "10_terms")
            check_ruby(page, f"用語辞典（{book.categories[first]}）")
            chips = page.locator(".mj-choices-root .mj-opt")
            result["term_categories"] = chips.count()
            expect(chips.count() == len(book.categories) + 1, f"分類の数が違う: {chips.count()}")
            for key, name in list(book.categories.items())[1:]:
                tap_and_wait(page, page.locator(f'.mj-choices-root .mj-opt[data-key="{key}"]'))      # 文字にはルビが入るので、鍵で探す
                expect(book.of(key)[0].term in main_text(page), f"分類「{name}」の用語が出ていない")
                expect(page.locator('.mj-choices-root .mj-opt[aria-pressed="true"]').count() == 1, f"分類「{name}」に、選択中の印が付いていない")
                check_ruby(page, f"用語辞典（{name}）")
            tap_and_wait(page, page.locator('.mj-choices-root .mj-opt[data-key="yaku"]'))
            expect(page.locator(".mj-termcard").count() == len(pages), "役の名前の一覧の数が違う")
            check_ruby(page, "用語辞典（役の名前）")
            # 言葉でさがす（ひらがなでも見つかる）
            box = page.get_by_label("言葉でさがす")
            box.fill("てんぱい")
            box.press("Enter")
            page.wait_for_function("() => document.querySelector('[data-testid=stMain]').innerText.includes('「てんぱい」で')", timeout=20000)
            settle(page, 500)
            found = [card.evaluate(TEXT_WITHOUT_RUBY) for card in page.locator(".mj-term-head").all()]
            result["term_search"] = found[:4]
            expect(found and found[0].startswith("聴牌 テンパイ"), f"「てんぱい」でさがした結果が違う: {found[:4]}")
            shot(page, "11_terms_search")
            check_ruby(page, "用語辞典（さがした結果）")
            page.close()
            # URL で用語を指定して開く
            page = open_page(context, "/terms?t=" + quote("振聴"))
            text = main_text(page)
            expect("さがした用語" in text and text.index("さがした用語") < text.index("分類を選ぶ"), "URL で指定した用語が、上に出ていない")
            expect(page.locator(".mj-term-head").first.evaluate(TEXT_WITHOUT_RUBY).startswith("振聴 フリテン"), "URL で指定した用語が違う")
            check_ruby(page, "用語辞典（URL で指定）")
            context.close()

        # ================================================================ 5. 卓で打つとき・ルールの違い
        @part("guides")
        def check_guides() -> None:
            guide = table_guide()
            context = new_context()
            page = open_page(context, "/table")
            heads = [h.evaluate(TEXT_WITHOUT_RUBY) for h in page.locator(".mj-guide-head").all()]
            result["table_heads"] = heads
            expect(heads == [f"{number}{section.title}" for number, section in enumerate(guide.sections, start=1)], f"手順の見出しが違う: {heads}")
            expect(page.locator("details").count() == len(guide.sections) + 1, "折りたたみの数が違う")
            shot(page, "12_table")
            check_ruby(page, "卓で打つとき")            # 折りたたみを、すべて開く
            shot(page, "13_table_open")
            expect(page.locator(".mj-score").count() == 2, "点数の早見表が出ていない")
            page.close()
            page = open_page(context, "/rules")
            rules = rule_book()
            # 「余裕があれば聞くこと」・まとまりごと・「調べた資料と、注意」
            expect(page.locator("details").count() == sum(1 for group in rules.groups if rules.of(group)) + 2, "ルールの違いの折りたたみの数が違う")
            expect("まず聞いておくこと（5 つ）" in main_text(page), "ルールの違いに「まず聞いておくこと」が出ていない")
            expect("★ 卓に着く前に確かめること" in main_text(page), "卓に着く前に確かめること、が出ていない")
            shot(page, "14_rules")
            check_ruby(page, "ルールの違い")
            expect(page.locator(".mj-termcard").count() == len(rules.items), "ルールの項目の数が違う")
            shot(page, "15_rules_open")
            context.close()

        # ================================================================ 6. ドリル
        @part("drill")
        def check_drill() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/drill")
            kinds = [b.inner_text() for b in page.locator(f"{MAIN} button").all() if b.inner_text() in {info.name for info in KINDS.values()}]
            result["drill_kinds"] = kinds
            expect(kinds == [info.name for info in KINDS.values()], f"ドリルの種類が違う: {kinds}")
            shot(page, "16_drill_menu")
            check_ruby(page, "ドリル（種類の一覧）")
            context.close()

            drills: dict[str, dict] = {}
            for kind, info in KINDS.items():
                context = new_context()
                page = open_page(context, f"/drill?k={kind}", wait=".mj-prompt")
                entry: dict = {"prompt": page.locator(".mj-prompt").evaluate(TEXT_WITHOUT_RUBY)}
                expect(page.url.endswith("/drill"), f"{info.name}: URL に種類の指定が残っている: {page.url}")
                if kind == "reading":
                    expect(page.locator(f"{MAIN} ruby").count() == 0, "読みのドリルで、答える前に読み（ルビ）が見えている")
                check_ruby(page, f"ドリル（{info.name}・答える前）")
                if kind in ("discard", "danger"):            # 手牌から 1 枚選ぶ問題（何切る・危険牌）
                    expect(page.locator(".mj-hand-root .mj-tile").count() == 14, f"{info.name}の手牌が 14 枚でない")
                    page.locator(".mj-hand-root .mj-tile").first.tap()
                    page.wait_for_timeout(200)
                    page.locator(".mj-hand-root .mj-confirm").tap()
                else:
                    options = page.locator(".mj-choices-root .mj-opt")
                    entry["options"] = options.count()
                    expect(options.count() >= 2, f"{info.name}: 選択肢が出ていない")
                    if kind in ("yaku", "wait"):          # いくつも選ぶ問題：選んでから確定する
                        confirm = page.locator(".mj-choices-root .mj-confirm")
                        expect(confirm.is_disabled(), f"{info.name}: 何も選んでいないのに、確定できる")
                        options.nth(0).tap()
                        options.nth(1).tap()
                        page.wait_for_timeout(200)
                        expect("2 つ選択中" in page.locator(".mj-choices-root .mj-status").inner_text(), f"{info.name}: 選んだ数が出ていない")
                        confirm.tap()
                    else:                                  # 1 つ選ぶ問題：押した選択肢が、そのまま答えになる
                        options.first.evaluate("e => { e.click(); e.click(); }")      # 続けて 2 回押しても、答えは 1 回だけ
                page.get_by_role("button", name="次の問題").first.wait_for(timeout=20000)
                settle(page, 500)
                banner = page.locator(".mj-verdict").first.evaluate(TEXT_WITHOUT_RUBY)
                entry["banner"] = banner
                expect(banner.startswith(("○ 正解", "✗ ちがう")), f"{info.name}: 正解・不正解が出ていない: {banner}")
                expect("この回 1 問・正解" in main_text(page), f"{info.name}: この回の数が違う（2 回数えた？）")
                saved = json.loads(stored(page, f"drill.{kind}") or "{}")
                entry["answered"] = saved.get("n")
                expect(saved.get("n") == 1, f"{info.name}: 答えた回数が保存されていない: {saved}")
                shot(page, f"17_drill_{kind}")
                check_ruby(page, f"ドリル（{info.name}・答えたあと）")
                drills[kind] = entry
                context.close()
            result["drills"] = drills

            # 答えた直後は、正解・不正解の帯と「次の問題」が、スマホの高さの画面に見えている（画面の下に隠れない）。
            # 何切るでは、切った牌に印が付き、押せない「この牌を切る」は消える
            reach: dict[str, dict] = {}
            for kind in ("discard", "score", "yaku", "reading"):
                context = new_context(height=HEIGHT)
                page = open_page(context, f"/drill?k={kind}", wait=".mj-prompt")
                if kind == "discard":
                    page.locator(".mj-hand-root .mj-tile").nth(3).tap()
                    page.wait_for_timeout(200)
                    page.locator(".mj-hand-root .mj-confirm").tap()
                else:
                    options = page.locator(".mj-choices-root .mj-opt")
                    if kind == "yaku":
                        options.first.tap()
                        page.wait_for_timeout(200)
                        confirm = page.locator(".mj-choices-root .mj-confirm")
                        confirm.scroll_into_view_if_needed()
                        confirm.tap()
                    else:
                        last = options.nth(options.count() - 1)
                        last.scroll_into_view_if_needed()          # いちばん下の選択肢まで送ってから答える
                        last.tap()
                page.get_by_role("button", name="次の問題").first.wait_for(timeout=20000)
                settle(page, 700)
                verdict = page.locator(".mj-verdict").first.evaluate("e => [e.getBoundingClientRect().top, e.getBoundingClientRect().bottom]")
                following = page.get_by_role("button", name="次の問題").first.evaluate("e => [e.getBoundingClientRect().top, e.getBoundingClientRect().bottom]")
                entry = {"verdict": [round(v) for v in verdict], "next": [round(v) for v in following]}
                if kind == "discard":
                    entry["chosen"] = page.locator(".mj-hand-root .mj-tile.mj-chosen").count()
                    entry["confirm_visible"] = page.locator(".mj-hand-root .mj-confirm").is_visible()
                    expect(entry["chosen"] == 1, "何切るで、切った牌に印が付いていない")
                    expect(not entry["confirm_visible"], "何切るで、答えたあとも「この牌を切る」が残っている")
                reach[kind] = entry
                expect(0 <= verdict[0] and verdict[1] <= HEIGHT, f"ドリル（{kind}）：答えた直後に、正解・不正解の帯が画面の外にある: {entry}")
                expect(0 <= following[0] and following[1] <= HEIGHT, f"ドリル（{kind}）：答えた直後に、「次の問題」が画面の外にある: {entry}")
                if kind == "discard":
                    shot(page, "17b_drill_discard_answered")
                context.close()
            result["drill_reach"] = reach

            # 次の問題へ進むと、画面の上に戻る（スマホの高さの画面で）。やめると、種類の一覧に戻る
            context = new_context(height=HEIGHT)
            page = open_page(context, "/drill?k=score", wait=".mj-prompt")
            page.locator(".mj-choices-root .mj-opt").first.tap()
            page.get_by_role("button", name="次の問題").first.wait_for(timeout=20000)
            following = page.get_by_role("button", name="次の問題").last         # 解説のいちばん下のほう
            settle(page, 500)
            following.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            scrolled = scroll_top(page)
            before = page.locator(".mj-prompt").evaluate(TEXT_WITHOUT_RUBY)
            following.tap()
            page.get_by_role("button", name="やめて、種類の一覧へ").wait_for(timeout=20000)
            settle(page, 600)
            result["drill_next"] = {"scrolled_before": round(scrolled), "scroll_after": round(scroll_top(page)), "prompt": before}
            expect(scrolled > 100 and scroll_top(page) == 0, f"次の問題に進んでも、画面の上に戻らない: {result['drill_next']}")
            expect(page.locator(".mj-choices-root .mj-opt").count() >= 2, "次の問題の選択肢が出ていない")
            page.get_by_role("button", name="やめて、種類の一覧へ").tap()
            page.get_by_role("button", name=KINDS["reading"].name).wait_for(timeout=20000)
            context.close()

            # 復習：時刻になった問題だけを出す。正解すると、次の間隔（1 日後）に進む
            due = {"drill.table": dump_deck(Deck({"cr:30:3": Card(0, NOW - 60, 1, 0, NOW - 700)}, 1, 0))}
            context = new_context(script=storage_script(due))
            page = open_page(context, "/drill")
            review = page.get_by_role("button", name="復習する（1 問）")
            expect(review.count() == 1, "復習のボタンが出ていない")
            shot(page, "18_drill_review_menu")
            review.tap()
            page.locator(".mj-prompt").wait_for(timeout=20000)
            settle(page, 500)
            prompt = page.locator(".mj-prompt").evaluate(TEXT_WITHOUT_RUBY)
            expect(prompt == question("table", "cr:30:3").prompt, f"復習の問題が違う: {prompt}")
            page.locator(".mj-choices-root .mj-opt", has_text="3,900 点").tap()
            page.get_by_role("button", name="次の問題").first.wait_for(timeout=20000)
            settle(page, 500)
            expect("○ 正解" in main_text(page), "復習の問題に正解したのに、正解と出ない")
            card = json.loads(stored(page, "drill.table"))["cards"]["cr:30:3"]
            result["review_card"] = card
            expect(card[0] == 1 and abs(card[1] - (int(time.time()) + DAY)) < 120, f"正解したのに、次の間隔に進んでいない: {card}")
            page.get_by_role("button", name="次の問題").first.tap()
            page.get_by_role("button", name=KINDS["reading"].name).wait_for(timeout=20000)
            settle(page, 500)
            expect("復習は、すべて終わりました。" in page.locator(MAIN).inner_text(), "復習が終わったことが出ていない")
            context.close()

        # ================================================================ 7. 記録と保存
        @part("records")
        def check_records() -> None:
            context = new_context(script=storage_script(sample_records()))
            page = open_page(context, "/records")
            text = main_text(page)
            expect("入るもの：一人練習 2 局・CPU との対局 0 回・スタンプ 2 役・ドリル 8 回ぶんの記録" in text, "記録のまとめが違う")
            shot(page, "19_records")
            check_ruby(page, "記録と保存")
            with page.expect_download() as download_info:
                page.get_by_role("button", name="進み具合をファイルに保存する").tap()
            download = download_info.value
            saved_file = out_dir / "phase2_export.json"
            download.save_as(str(saved_file))
            exported = json.loads(saved_file.read_text(encoding="utf-8"))
            result["export"] = {"file": download.suggested_filename, "app": exported.get("app"), "hands": len(exported["practice"]["history"]["hands"]), "stamps": sorted(exported["stamps"])}
            expect(re.fullmatch(r"mjdojo-\d{8}-\d{4}\.json", download.suggested_filename) is not None, f"保存するファイルの名前が違う: {download.suggested_filename}")
            expect(exported.get("app") == "mjdojo" and result["export"]["hands"] == 2 and result["export"]["stamps"] == ["riichi", "sanshoku"], f"保存したファイルの中身が違う: {result['export']}")
            context.close()

            # 別の端末（空のブラウザ）で、保存したファイルを読み込む。ほかのページを見たあとでも、読み込める
            context = new_context(height=HEIGHT)
            page = open_page(context, "/practice")
            wait_hand(page)
            page.goto(base + "/records")
            page.locator(f"{MAIN} h1", has_text="記録と保存").wait_for(timeout=60000)
            settle(page, 800)
            page.locator('input[type="file"]').set_input_files(str(saved_file))
            page.get_by_role("button", name="読み込む").wait_for(timeout=20000)
            expect("入っているもの：一人練習 2 局・CPU との対局 0 回・スタンプ 2 役・ドリル 8 回" in main_text(page), "読み込む前の、ファイルの中身の説明が違う")
            shot(page, "20_records_import")
            page.get_by_role("button", name="読み込む").tap()
            page.wait_for_function("() => document.querySelector('[data-testid=stMain]').innerText.includes('読み込みました')", timeout=20000)
            settle(page, 600)
            result["import"] = {"scroll_after": round(scroll_top(page)), "history": len(json.loads(stored(page, "practice.history") or "[]"))}
            expect(scroll_top(page) == 0, "読み込んだあと、結果の案内（ページの上）が見える位置に戻らない")
            expect(result["import"]["history"] == 2 and set(json.loads(stored(page, "progress.stamps"))) == {"riichi", "sanshoku"}, f"読み込んだ記録が、保存されていない: {result['import']}")
            expect("入るもの：一人練習 2 局・CPU との対局 0 回・スタンプ 2 役・ドリル 8 回ぶんの記録" in main_text(page), "読み込んだあとのまとめが違う")
            shot(page, "21_records_imported")
            # 読み込んだ記録が、ほかのページに出る
            page.goto(base + "/yaku")
            page.locator(LINK).first.wait_for(timeout=60000)
            settle(page, 800)
            expect("✓1" in link(page, "三色同順").inner_text(), "読み込んだスタンプが、役図鑑に出ていない")
            page.goto(base + "/practice")
            wait_hand(page)
            open_section(page, "成績")
            expect("三色同順" in page.locator(".mj-stats").last.evaluate(TEXT_WITHOUT_RUBY), "読み込んだ成績が、一人練習に出ていない")
            # 消す
            page.goto(base + "/records")
            page.locator(f"{MAIN} h1", has_text="記録と保存").wait_for(timeout=60000)
            settle(page, 800)
            opener = page.get_by_role("button", name="成績・スタンプ・ドリルの記録を、すべて消す")
            opener.scroll_into_view_if_needed()
            opener.tap()
            page.get_by_role("button", name="すべて消す", exact=True).tap()
            page.wait_for_function("() => document.querySelector('[data-testid=stMain]').innerText.includes('記録を消しました')", timeout=20000)
            settle(page, 600)
            left = page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('mjdojo:')).map(k => k.slice(7)).sort()")
            result["after_clear"] = left
            expect(set(left) <= {"practice.hand", "practice.settings"} and "practice.hand" in left, f"消したあとに残っている記録が違う: {left}")
            context.close()

            # ファイルを選べないとき：文字を貼り付けて読み込む
            context = new_context()
            page = open_page(context, "/records")
            open_section(page, "ファイルを選べないとき（文字を貼り付ける）")
            area = page.get_by_label("コピーしておいた記録の文字")
            area.fill(saved_file.read_text(encoding="utf-8"))
            area.press("Control+Enter")
            page.get_by_role("button", name="読み込む").wait_for(timeout=20000)
            page.get_by_role("radio", name="ファイルの中身で置き換える").tap(force=True)
            settle(page, 500)
            page.get_by_role("button", name="読み込む").tap()
            page.wait_for_function("() => document.querySelector('[data-testid=stMain]').innerText.includes('読み込みました（ファイルの中身で置き換えた）')", timeout=20000)
            settle(page, 600)           # ブラウザへの書き込みは、画面の文字が出たすぐあとに行われる
            expect(len(json.loads(stored(page, "practice.history") or "[]")) == 2, "貼り付けた記録が、保存されていない")
            # このアプリのものでない文字は、読み込まない
            open_section(page, "ファイルを選べないとき（文字を貼り付ける）")
            area = page.get_by_label("コピーしておいた記録の文字")
            area.fill("これは記録ではない")
            area.press("Control+Enter")
            page.locator('[data-testid="stAlert"]').first.wait_for(timeout=20000)
            expect(page.get_by_role("button", name="読み込む").count() == 0, "記録でない文字なのに、読み込むボタンが出ている")
            context.close()

        # ================================================================ 8. ほかの画面幅と、ダークテーマ
        @part("looks")
        def check_looks() -> None:
            widths: dict[str, list[int]] = {}
            for path, wait, name in (("/yaku?y=sanshoku", ".mj-yaku-head", "yaku"), ("/drill?k=table", ".mj-prompt", "drill"), ("/table", "h1", "table"), ("/terms", "h1", "terms"), ("/records", "h1", "records")):
                for width in (320, 430, 1280):
                    context = new_context(width=width, height=900)
                    page = open_page(context, path, wait=wait)
                    shot(page, f"22_{name}_{width}", width)
                    widths.setdefault(name, []).append(page.evaluate("document.documentElement.scrollWidth"))
                    context.close()
            result["widths"] = widths
            for path, wait, name in (("/yaku?y=kokushi", ".mj-yaku-head", "yaku"), ("/terms", "h1", "terms"), ("/table", "h1", "table")):
                context = new_context(height=900, dark=True)
                page = open_page(context, path, wait=wait)
                shot(page, f"23_dark_{name}")
                context.close()
            context = new_context(height=900, dark=True)
            page = open_page(context, "/drill?k=wait", wait=".mj-prompt")
            page.locator(".mj-choices-root .mj-opt").first.tap()
            page.locator(".mj-choices-root .mj-confirm").tap()
            page.get_by_role("button", name="次の問題").first.wait_for(timeout=20000)
            settle(page, 500)
            shot(page, "23_dark_drill")
            context.close()
        for name, check in parts.items():
            if not only or name in only:
                started = time.time()
                check()
                result.setdefault("seconds", {})[name] = round(time.time() - started)
        browser.close()

    result["console_errors"] = console_errors[:10]
    result["failed_requests"] = failed_requests[:10]
    expect(not console_errors, f"ブラウザのエラー: {console_errors[:3]}")
    expect(not failed_requests, f"読み込みに失敗: {failed_requests[:3]}")
    return result


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    outcome = run(sys.argv[1], Path(sys.argv[2]), sys.argv[3].split(",") if len(sys.argv) == 4 else ())
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    sys.exit(1 if outcome["problems"] else 0)

"""スマホ相当の画面で「一人練習」を通しで操作する確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、牌タップ・リーチ・ツモ・設定・
続きからの再開が、画面上で意図どおり動くかを確かめる。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で）
       python tools/e2e_practice_check.py http://localhost:8501 出力フォルダ

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from e2e_ruby import terms_without_ruby  # noqa: E402
from playwright.sync_api import BrowserContext, Page, sync_playwright  # noqa: E402

from engine import practice  # noqa: E402
from engine.coach import analyze  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
WIDTH, HEIGHT = 375, 606     # 利用者の実機（iPhone の Safari）で測った画面の大きさ
TALL = 5000                  # 縦に長いページを 1 枚に収めるための高さ（Streamlit は内側の枠でスクロールするため）
STEPS = ["① 手牌の読み方", "② 役", "③ ドラ", "④ 符", "⑤ 点数", "⑥ 誰がいくら払うか", "⑦ 卓での申告"]
SETTINGS = "設定（ツキ補正・コーチ）"
TABLE = "受け入れ表"
LAYOUT = "手の分け方"
#: 画面の文字が、渡した文字列（操作する前の内容）から変わったら真になる式
MAIN_CHANGED = "t => document.querySelector('[data-testid=stMain]').innerText !== t"

#: ブラウザ内保存への書き込みを数えるための仕掛け（ページを開く前に入れる）
COUNT_WRITES = """
(() => {
  window.__writes = [];
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = function (key, value) {
    if (String(key).startsWith('mjdojo:')) window.__writes.push(String(key).slice(7));
    return original.call(this, key, value);
  };
})();
"""


# ---------------------------------------------------------------- 決まった局面を用意する


def best_play(config: practice.PracticeConfig, stop) -> practice.PracticeState:
    """おすすめどおりに打ち、stop(state) が真になったところ（または局の終わり）で止める"""
    state = practice.start(config)
    while not state.finished and not stop(state):
        if state.can_tsumo:
            return state
        state = practice.apply(state, practice.discard(analyze(practice.position_of(state)).pick.tile))
    return state


def find(settings: LuckSettings, stop) -> practice.PracticeState:
    for seed in range(500):
        state = best_play(practice.PracticeConfig(seed=seed, luck=settings), stop)
        if not state.finished and stop(state):
            return state
    raise SystemExit("確認に使う局面が見つかりません")


def storage_script(state: practice.PracticeState | None, **settings) -> str:
    """ページを開く前に、ブラウザ内保存に局と設定を入れておくスクリプト（最初の 1 回だけ働く）"""
    full = {"deal": 75, "draw": 75, "tenpai_deal": False, "mark": True, "hint": "before", "level": 2, **settings}
    lines = [f"localStorage.setItem('mjdojo:practice.settings', {json.dumps(json.dumps(full))});"]
    if state is not None:
        hand = json.dumps({"v": 1, "save": practice.to_save(state), "counted": True, "hinted": False})
        lines.append(f"localStorage.setItem('mjdojo:practice.hand', {json.dumps(hand)});")
    return "if (!sessionStorage.getItem('mj-seeded')) { sessionStorage.setItem('mj-seeded', '1'); " + " ".join(lines) + " }"


# ---------------------------------------------------------------- 画面の操作


def settle(page: Page, ms: int = 700) -> None:
    page.wait_for_timeout(ms)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(200)


def wait_hand(page: Page) -> None:
    page.locator(".mj-tile").nth(13).wait_for(timeout=60000)
    settle(page, 500)


#: 要素の中の文字を、ルビ（読みがな）を除いて取り出す式。空白は 1 つにまとめる
TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt, style, script').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""


def main_text(page: Page) -> str:
    """画面の文字（ルビを除く。閉じている折りたたみの中身も含む）"""
    return page.locator('[data-testid="stMain"]').evaluate(TEXT_WITHOUT_RUBY)


def headline(page: Page) -> str:
    return page.locator(".mj-headline").first.evaluate(TEXT_WITHOUT_RUBY)


def headings(page: Page) -> list[str]:
    """解説の見出し（ルビを除く）"""
    return [h.evaluate(TEXT_WITHOUT_RUBY) for h in page.locator("h3").all()]


def river_count(page: Page) -> int:
    return page.locator(".mj-river:not(.mj-draws) img").count()


def seed_of(page: Page) -> str:
    found = re.search(r"局の番号 (\d+)", main_text(page))
    return found.group(1) if found else ""


def scroll_top(page: Page) -> float:
    """画面が、上からどれだけスクロールされているか"""
    return page.evaluate("() => document.querySelector('[data-testid=stMain]').scrollTop")


def top_of(page: Page, selector: str) -> float:
    return round(page.locator(selector).first.evaluate("e => e.getBoundingClientRect().top"), 1)


def is_open(page: Page, label: str) -> bool:
    """その見出しの折りたたみが開いているか"""
    details = page.locator("details", has=page.locator("summary", has_text=label))
    return bool(details.count() and details.first.evaluate("e => e.open"))


def open_section(page: Page, label: str) -> None:
    if not is_open(page, label):
        page.locator("summary", has_text=label).first.tap()
        settle(page, 400)


def chosen(page: Page, name: str) -> bool:
    """その名前の選択肢（段階・ヒント・表示の量）が選ばれているか"""
    return page.get_by_role("radio", name=name, exact=True).get_attribute("aria-checked") == "true"


def choose(page: Page, name: str) -> None:
    option = page.get_by_role("radio", name=name, exact=True)
    option.scroll_into_view_if_needed()
    option.tap()
    settle(page, 800)


def confirm(page: Page, *, by_second_tap: int | None = None) -> None:
    """選んである牌を確定し、画面が次の局面（または結果）に変わるまで待つ。

    by_second_tap に牌の位置を渡すと、確定ボタンの代わりに、その牌をもう一度タップして確定する。
    """
    before = page.locator('[data-testid="stMain"]').inner_text()       # MAIN_CHANGED と同じ取り出し方で比べる
    if by_second_tap is None:
        page.locator(".mj-confirm").tap()
    else:
        page.locator(".mj-tile").nth(by_second_tap).tap()
    page.wait_for_function(MAIN_CHANGED, arg=before, timeout=20000)
    settle(page, 500)


def discard(page: Page, index: int, *, double_tap: bool = False) -> None:
    """index 番目の牌を選んで切る"""
    page.locator(".mj-tile").nth(index).tap()
    page.wait_for_timeout(150)
    confirm(page, by_second_tap=index if double_tap else None)


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

        def new_context(*, height: int = TALL, width: int = WIDTH, dark: bool = False, script: str | None = None) -> BrowserContext:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                is_mobile=width < 600,
                has_touch=width < 600,
                user_agent=IPHONE_UA if width < 600 else None,
                color_scheme="dark" if dark else "light",
                locale="ja-JP",
            )
            if script:
                context.add_init_script(script)
            return context

        def open_page(context: BrowserContext, path: str = "/practice") -> Page:
            page = context.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and not is_base_path_probe(m.location.get("url", "")) else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on("response", lambda r: failed_requests.append(f"{r.status} {r.url}") if r.status >= 400 and not is_base_path_probe(r.url) else None)
            page.goto(base + path)
            return page

        def shot(page: Page, name: str, width: int = WIDTH) -> None:
            page.screenshot(path=str(out_dir / f"practice_{name}.png"))
            expect(page.locator('[data-testid="stException"]').count() == 0, f"{name}: 画面に例外が出ている")
            overflow = page.evaluate("document.documentElement.scrollWidth")
            expect(overflow <= width, f"{name}: 横にはみ出している（{overflow}px）")

        def check_ruby(page: Page, name: str) -> None:
            """折りたたみをすべて開いて、初出なのにルビが付いていない用語が無いことを確かめる"""
            missing = terms_without_ruby(page)
            result.setdefault("ruby_missing", {})[name] = missing
            expect(not missing, f"{name}: 初出なのにルビが無い用語: {missing}")

        # ---- 1. はじめて開く（実機と同じ大きさの画面）。ホームから入る
        context = new_context(height=HEIGHT, script=COUNT_WRITES)
        page = open_page(context, "/")
        page.get_by_text("一人練習を始める").wait_for(timeout=60000)
        page.get_by_text("一人練習を始める").tap()
        wait_hand(page)
        shot(page, "01_first_view")
        tiles = page.locator(".mj-tile")
        boxes = tiles.evaluate_all("els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height, r.top]; })")
        loaded = tiles.evaluate_all("els => els.filter(e => { const i = e.querySelector('img'); return i && i.naturalWidth > 0; }).length")
        bar_bottom = page.locator(".mj-bar").evaluate("e => e.getBoundingClientRect().bottom")
        result["first_view"] = {
            "tiles": len(boxes), "images_loaded": loaded, "tile_width": round(min(b[0] for b in boxes), 1),
            "confirm_button_bottom": round(bar_bottom), "viewport_height": HEIGHT, "headline": headline(page),
        }
        expect(len(boxes) == 14 and loaded == 14, "手牌 14 枚の表示または画像の読み込みに失敗")
        expect(min(b[0] for b in boxes) >= 43, "牌が小さすぎる")
        expect(bar_bottom <= HEIGHT, f"「この牌を切る」ボタンが、最初の画面に収まっていない（下端 {bar_bottom:.0f}px ／ 画面 {HEIGHT}px）")
        text = main_text(page)
        expect("ツキ補正：配牌 75・ツモ 75" in text, "ツキ補正の強さが画面に出ていない")
        expect("1 巡目（残りツモ 17 回）" in text, "巡目の表示が違う")
        expect(page.locator(".mj-mark").count() >= 1 or "あがりの形です" in text, "おすすめの印（◎）が出ていない")
        expect(page.locator(".mj-statusbar ruby").count() >= 1, "用語にルビが付いていない")

        # ---- 2. 選ぶ → 切る。河と評価が出ること。何巡打っても、手牌と確定ボタンの位置が動かないこと
        tiles.nth(13).tap()
        page.wait_for_timeout(300)
        result["status_after_select"] = page.locator(".mj-status").inner_text()
        expect(result["status_after_select"].startswith("選択中："), "牌を選んだあとの案内が違う")
        shot(page, "02_selected")
        hand_tops, confirm_tops, writes = {top_of(page, ".mj-tile")}, {top_of(page, ".mj-confirm")}, []
        for turn in range(1, 7):
            if page.locator(".mj-tile").count() < 14 or page.get_by_role("button", name="ツモ（あがる）").count():
                break
            page.evaluate("window.__writes = []")
            if turn == 1:
                confirm(page)                      # さっき選んだ牌（ツモ牌）を切る
            else:
                discard(page, 13 if turn % 2 else 0, double_tap=turn == 2)      # 2 巡目は、同じ牌の 2 度タップで切る
            if page.locator(".mj-tile").count() < 14:
                break
            writes.append(page.evaluate("window.__writes"))
            hand_tops.add(top_of(page, ".mj-tile"))
            confirm_tops.add(top_of(page, ".mj-confirm"))
            expect(river_count(page) == turn, f"{turn} 枚目を切ったあと、河の枚数が違う")
            expect(page.locator(".mj-review").count() == 1, "前の打牌の評価が出ていない")
        result["positions"] = {"hand_top": sorted(hand_tops), "confirm_top": sorted(confirm_tops), "writes_per_discard": writes}
        expect(max(hand_tops) - min(hand_tops) <= 1, f"巡目によって、手牌の位置が動く: {sorted(hand_tops)}")
        expect(max(confirm_tops) - min(confirm_tops) <= 1, f"巡目によって、確定ボタンの位置が動く: {sorted(confirm_tops)}")
        # 1 枚切るごとに書き直すのは、打っている局の記録だけ（設定や成績を、毎回書き直さない）
        expect(all(set(names) <= {"practice.hand"} for names in writes), f"打牌のたびに、変わっていない記録まで書き直している: {writes}")
        position_before = (seed_of(page), river_count(page))

        # ---- 3. 再読み込み（＝新しいセッション）で、続きから再開できるか
        page.reload()
        wait_hand(page)
        text = main_text(page)
        result["after_reload"] = {"seed": seed_of(page), "river": river_count(page)}
        expect((result["after_reload"]["seed"], result["after_reload"]["river"]) == position_before, "再読み込み後に、同じ局面に戻っていない")
        expect("再開したものです" in text, "再開したことが表示されていない")
        context.close()

        # ---- 4. 受け入れ表・分解図（「詳しい」では、最初から開いている）
        state = find(LuckSettings(50, 50), lambda s: s.turn == 4 and not s.can_tsumo and not s.riichi_discards)
        context = new_context(script=storage_script(state, level=3, deal=50, draw=50))
        page = open_page(context)
        wait_hand(page)
        shot(page, "03_detailed")
        text = main_text(page)
        expect(is_open(page, TABLE) and is_open(page, LAYOUT), "「詳しい」なのに、受け入れ表と分解図が開いていない")
        expect("のままの切り方（受け入れの広い順）" in text and "次のツモで引く確率 ＝" in text, "受け入れ表か確率が出ていない")
        expect("向聴数 ＝" in text and page.locator(".mj-part").count() >= 5, "分解図が出ていない")
        images = page.locator("img.mj-img")
        loaded = images.evaluate_all("els => els.filter(e => e.complete && e.naturalWidth > 0).length")
        result["detail_images"] = {"count": images.count(), "loaded": loaded}
        expect(images.count() >= 30 and loaded == images.count(), "表示用の牌画像が読めていない")
        check_ruby(page, "打っている途中（詳しい）")

        # 表示の量を変えると、表が閉じて／開いて出し直される
        open_section(page, SETTINGS)
        choose(page, "ふつう")
        expect(not is_open(page, TABLE) and not is_open(page, LAYOUT), "「ふつう」に変えても、表が開いたまま")
        choose(page, "詳しい")
        expect(is_open(page, TABLE) and is_open(page, LAYOUT), "「詳しい」に変えても、表が開かない")
        choose(page, "ふつう")
        expect(is_open(page, SETTINGS), "設定を変えたら、設定の折りたたみが閉じてしまった")
        # 選択中の項目をもう一度押しても、選択が消えない
        for name in ("ふつう", "打つ前に表示", "中"):
            choose(page, name)
            expect(chosen(page, name), f"選択中の「{name}」をもう一度押したら、選択が消えた")

        # 設定：段階を「なし」に → 次の局から反映
        choose(page, "なし")
        text = main_text(page)
        expect("変更は次の局から反映されます" in text and "ツキ補正：配牌 50・ツモ 50" in text, "設定を変えた直後の表示が違う")
        expect(is_open(page, SETTINGS), "設定を変えたら、設定の折りたたみが閉じてしまった")
        shot(page, "04_settings")
        start = page.get_by_role("button", name="この設定で新しい局を始める")
        start.scroll_into_view_if_needed()
        scrolled = scroll_top(page)
        start.tap()
        settle(page, 1000)
        wait_hand(page)
        expect("ツキ補正なし（通常の麻雀）" in main_text(page), "補正なしの局が始まっていない")

        # 開いた折りたたみは、局面が進んでも開いたまま
        open_section(page, TABLE)
        discard(page, 13)
        expect(is_open(page, TABLE), "1 枚切ったら、受け入れ表が閉じてしまった")

        # ヒントを「打った後に答え合わせ」に → 切ると評価が見出しに出る
        open_section(page, SETTINGS)
        choose(page, "打った後に答え合わせ")
        expect(page.locator(".mj-mark").count() == 0, "答え合わせモードなのに、おすすめの印が出ている")
        expect("受け入れ表（切る牌と" not in main_text(page), "答え合わせモードなのに、打つ前の受け入れ表が出ている")
        discard(page, 13)
        result["verdict_headline"] = headline(page)
        expect(any(mark in result["verdict_headline"] for mark in "✓△✗！"), f"答え合わせの見出しが違う: {result['verdict_headline']}")
        shot(page, "05_answer_check")
        check_ruby(page, "答え合わせ")
        context.close()

        # ---- 5. 局の番号を指定して始める（スマホの高さの画面。始めたら、画面の上に戻る）
        state = find(LuckSettings(50, 50), lambda s: s.turn == 6 and not s.can_tsumo)
        context = new_context(height=HEIGHT, script=storage_script(state, deal=50, draw=50))
        page = open_page(context)
        wait_hand(page)
        open_section(page, SETTINGS)
        box = page.get_by_label("番号を指定して始める")
        box.scroll_into_view_if_needed()
        scrolled = scroll_top(page)
        box.tap()
        page.keyboard.type("777", delay=40)
        page.get_by_role("button", name="この番号で始める").tap()          # 入力欄からフォーカスを外さずに、すぐ押す
        page.wait_for_function("() => /局の番号 777( |$)/.test(document.querySelector('[data-testid=stMain]').innerText)", timeout=20000)
        settle(page, 500)
        result["numbered"] = {"keyboard": box.get_attribute("type"), "seed": seed_of(page), "scroll_before": round(scrolled), "scroll_after": round(scroll_top(page))}
        expect(result["numbered"]["keyboard"] == "tel", "番号の入力欄で、数字のキーボードが出ない")
        expect(result["numbered"]["seed"] == "777", "番号を入れてボタンを 1 回押しただけでは、始まらない")
        expect(scrolled > 300 and scroll_top(page) == 0, f"新しい局を始めても、画面の上に戻らない: {result['numbered']}")
        expect("成績には入れていない" not in main_text(page), "打っている途中に、終わった局の注意書きが出ている")
        open_section(page, SETTINGS)
        box = page.get_by_label("番号を指定して始める")
        box.scroll_into_view_if_needed()
        box.fill("12ab")
        page.get_by_role("button", name="この番号で始める").tap()
        settle(page, 800)
        text = main_text(page)
        expect(seed_of(page) == "777" and "番号は、0〜999999 の数字で入れてください。" in text, "おかしな番号を入れたときの案内が違う")
        expect(not re.search(r"required|Value must|Please", text), "入力欄のそばに、英語の案内が出ている")
        shot(page, "06_numbered")
        context.close()

        # ---- 6. リーチ：切れる牌だけが明るく残る → リーチして切る → 局が終わる
        state = find(LuckSettings(75, 75), lambda s: bool(s.riichi_discards) and not s.can_tsumo)
        allowed = len(state.riichi_discards)
        context = new_context(script=storage_script(state))
        page = open_page(context)
        wait_hand(page)
        text = main_text(page)
        expect("聴牌にとれます" in text and "聴牌したときの待ちと点数" in text, "聴牌の案内か、待ちの表が出ていない")
        riichi = page.locator(".mj-riichi")
        expect(riichi.is_visible(), "リーチのボタンが出ていない")
        button_top = top_of(page, ".mj-confirm")
        expect(abs(button_top - min(confirm_tops)) <= 1, f"リーチのボタンが出ると、確定ボタンの位置が変わる（{min(confirm_tops)} → {button_top}px）")
        riichi.tap()
        page.wait_for_timeout(300)
        dim = page.locator(".mj-tile.mj-dim").count()
        result["riichi"] = {"allowed_tiles": allowed, "dimmed": dim, "confirm": page.locator(".mj-confirm").inner_text()}
        expect(dim == 14 - allowed, f"リーチで切れない牌の数が違う（暗い牌 {dim} 枚、切れる牌 {allowed} 枚）")
        expect(result["riichi"]["confirm"] == "リーチして切る", "確定ボタンの文字が変わっていない")
        page.locator(".mj-tile:not(.mj-dim)").first.tap()
        page.wait_for_timeout(300)
        moved = abs(top_of(page, ".mj-confirm") - button_top)
        expect(moved <= 1, f"牌を選んだとき、確定ボタンの位置が動いた（{moved:.1f}px）")
        shot(page, "07_riichi")
        check_ruby(page, "聴牌（リーチできる）")
        confirm(page)
        page.get_by_role("button", name="次の局へ").first.wait_for(timeout=20000)
        settle(page)
        text = main_text(page)
        result["after_riichi"] = "ツモあがり" if "ツモあがり" in text else ("流局" if "流局" in text else "?")
        expect(result["after_riichi"] in ("ツモあがり", "流局"), "リーチのあと、局が終わっていない")
        expect(page.locator(".mj-sideways").count() == 1, "リーチを宣言した牌が横向きになっていない")
        expect("リーチのあとのツモ" in text, "リーチのあとのツモの表示が無い")
        shot(page, "08_after_riichi")
        check_ruby(page, "リーチした局の結果")
        context.close()

        # ---- 7. ツモあがり → 解説 → 成績 → 解説の下のボタンから次の局へ（スマホの高さの画面）
        state = find(LuckSettings(75, 75), lambda s: s.can_tsumo)
        context = new_context(height=HEIGHT, script=storage_script(state))
        page = open_page(context)
        wait_hand(page)
        expect("あがりの形です" in headline(page), "あがりの形の案内が出ていない")
        expect(not page.locator(".mj-riichi").is_visible(), "あがれる局面で、リーチのボタンが出ている")
        expect(abs(top_of(page, ".mj-confirm") - min(confirm_tops)) <= 1, "あがれる局面で、確定ボタンの位置が変わる")
        tsumo = page.get_by_role("button", name="ツモ（あがる）")
        expect(tsumo.evaluate("e => e.getBoundingClientRect().bottom") <= HEIGHT, "「ツモ（あがる）」が、最初の画面に収まっていない")
        tsumo.tap()
        next_buttons = page.get_by_role("button", name="次の局へ")
        next_buttons.first.wait_for(timeout=20000)
        settle(page)
        shot(page, "09_win")
        text = main_text(page)
        heads = headings(page)
        result["win"] = {"big": page.locator(".mj-big").first.evaluate(TEXT_WITHOUT_RUBY), "headings": heads, "next_buttons": next_buttons.count()}
        expect(heads[:7] == STEPS, f"あがりの解説の見出しが違う: {heads}")
        expect("ツモあがり" in text and "「ツモ。" in text, "あがりのまとめか、申告の言い方が出ていない")
        expect(next_buttons.first.evaluate("e => e.getBoundingClientRect().bottom") <= HEIGHT, "「次の局へ」が、最初の画面に収まっていない")
        expect(next_buttons.count() == 2, "解説の下に、もう 1 つの「次の局へ」が無い")
        open_section(page, "成績")
        stats = page.locator(".mj-stats").evaluate(TEXT_WITHOUT_RUBY)
        result["stats"] = stats
        expect("配牌 75・ツモ 75" in stats and "ヒントあり" in stats and "100%" in stats, f"成績に 1 局ぶん入っていない: {stats}")
        check_ruby(page, "あがった局の結果")
        next_buttons.nth(1).scroll_into_view_if_needed()
        scrolled = scroll_top(page)
        next_buttons.nth(1).tap()
        wait_hand(page)
        expect("1 巡目（残りツモ 17 回）" in main_text(page), "次の局が始まっていない")
        expect(scrolled > 1000 and scroll_top(page) == 0, f"下の「次の局へ」で、画面の上に戻らない（{scrolled:.0f} → {scroll_top(page):.0f}）")
        context.close()

        # ---- 8. 流局
        last = find(LuckSettings(), lambda s: s.turn == 18 and not s.can_tsumo)
        context = new_context(script=storage_script(last, deal=0, draw=0, hint="off"))
        page = open_page(context)
        wait_hand(page)
        expect("コーチはオフです" in headline(page), "ヒントをオフにした表示になっていない")
        expect(abs(top_of(page, ".mj-tile") - min(hand_tops)) <= 1, "ヒントをオフにすると、手牌の位置が変わる")
        check_ruby(page, "打っている途中（ヒントはオフ・補正なし）")
        discard(page, 13)
        text = main_text(page)
        expect("流局" in text and "18 巡目で終了" in text, "流局の画面になっていない")
        shot(page, "10_exhausted")
        open_section(page, "成績")
        expect("なし（実力）" in page.locator(".mj-stats").evaluate(TEXT_WITHOUT_RUBY), "補正なし・ヒントなしの局が「実力」の行に入っていない")
        check_ruby(page, "流局した局の結果")
        context.close()

        # ---- 9. ほかの画面幅と、ダークテーマ
        state = find(LuckSettings(75, 75), lambda s: s.turn == 5 and not s.can_tsumo)
        widths = {}
        for width in (320, 430, 1280):
            context = new_context(width=width, height=900, script=storage_script(state))
            page = open_page(context)
            wait_hand(page)
            box = page.locator(".mj-tile").first.evaluate("e => { const r = e.getBoundingClientRect(); return [Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10]; }")
            widths[width] = {"tile": box}
            shot(page, f"11_width_{width}", width)
            context.close()
        result["widths"] = widths
        context = new_context(height=900, dark=True, script=storage_script(state, level=3))
        page = open_page(context)
        wait_hand(page)
        page.locator(".mj-tile").nth(3).tap()
        page.wait_for_timeout(400)
        shot(page, "12_dark")
        context.close()
        browser.close()

    result["console_errors"] = console_errors[:10]
    result["failed_requests"] = failed_requests[:10]
    expect(not console_errors, f"ブラウザのエラー: {console_errors[:3]}")
    expect(not failed_requests, f"読み込みに失敗: {failed_requests[:3]}")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    outcome = run(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    sys.exit(1 if outcome["problems"] else 0)

"""スマホ相当の画面で、Phase 5 の画面（「なぜ？」・点数の申告・カリキュラムと確認テスト・卒業判定・おまかせ補正）を、
通しで操作する確認スクリプト（開発用）。

アプリ本体のテスト（pytest）とは別。ブラウザを実際に動かして、折りたたみ・選択肢のボタン・ページの移動・
ブラウザ内保存が、画面上で意図どおり動くかを確かめる。AI のキーは使わない（キーが無いときの動き＝テンプレートの解説を確かめる）。

準備:  pip install playwright && playwright install chromium
実行:  streamlit run app.py --server.port 8501   （別の端末で。.streamlit/secrets.toml は置かない）
       python tools/e2e_phase5_check.py http://localhost:8501 出力フォルダ
       python tools/e2e_phase5_check.py http://localhost:8501 出力フォルダ why,auto   （一部だけ確かめる）

結果を JSON で表示し、スクリーンショットを出力フォルダに保存する。失敗があれば終了コード 1。
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable, Collection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from e2e_ruby import open_all, terms_without_ruby  # noqa: E402
from playwright.sync_api import BrowserContext, Page, sync_playwright  # noqa: E402

from engine import practice  # noqa: E402
from engine.coach import analyze  # noqa: E402
from engine.game_records import GOAL_GAMES, GameRecord, Tally, dump_record  # noqa: E402
from engine.luck import LuckSettings  # noqa: E402
from engine.records import HandRecord  # noqa: E402
from engine.records import dump_record as dump_hand  # noqa: E402
from engine.srs import Deck, dump_deck  # noqa: E402

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
WIDTH, HEIGHT = 375, 606     # 利用者の実機（iPhone の Safari）で測った画面の大きさ
TALL = 5000                  # 縦に長いページを 1 枚に収めるための高さ
MAIN = '[data-testid="stMain"]'
LINK = f'{MAIN} a[data-testid="stPageLink-NavLink"]'
TEXT_WITHOUT_RUBY = """e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('rt, style, script').forEach(x => x.remove());
    return copy.textContent.replace(/\\s+/g, ' ').trim();
}"""
NOW = int(time.time())
GRADUATION_DRILLS = ("han", "valid", "yaku", "table", "fu", "win", "danger", "manners", "declare")


# ---------------------------------------------------------------- 決まった記録・局面を用意する


def winning_hand() -> practice.PracticeState:
    """コーチのおすすめどおりに打って、ツモであがった局（申告の問題を出すため）"""
    for seed in range(300):
        state = practice.start(practice.PracticeConfig(seed=seed, luck=LuckSettings(75, 75)))
        while not state.finished and not state.can_tsumo:
            state = practice.apply(state, practice.discard(analyze(practice.position_of(state)).pick.tile))
        if state.can_tsumo:
            return practice.apply(state, practice.TSUMO)
    raise SystemExit("確認に使う局面が見つかりません")


def storage_script(items: dict[str, str]) -> str:
    """ページを開く前に、ブラウザ内保存に記録を入れておくスクリプト（最初の 1 回だけ働く）"""
    lines = [f"localStorage.setItem({json.dumps('mjdojo:' + name)}, {json.dumps(value)});" for name, value in items.items()]
    return "if (!sessionStorage.getItem('mj-seeded')) { sessionStorage.setItem('mj-seeded', '1'); " + " ".join(lines) + " }"


def practice_settings(**changes) -> str:
    base = {"deal": 75, "draw": 75, "tenpai_deal": False, "mark": True, "hint": "before", "level": 2, "target": None, "declare": True,
            "auto": False, "auto_since": 0, "auto_last": None}
    return json.dumps({**base, **changes})


def good_hands(count: int) -> str:
    """ヒントを見ずに打った局（10 回中 9 回、いちばん速い打牌）"""
    records = [HandRecord(time=NOW - 900 + i, seed=i, deal=75, draw=75, hinted=False, win=False, turn=18, riichi=False, tenpai=False,
                          decisions=10, best=9) for i in range(count)]
    return "[" + ",".join(dump_hand(r) for r in records) + "]"


def plain_games(count: int, *, good: int = 45, level: int = 0) -> str:
    """ヒントなし・CPU ふつう・初期のルールの東風戦（平均順位 2.0）。level は自分の補正（0 なら、卒業判定に数える対局）"""
    records = [GameRecord(time=NOW - 900 + i, seed=i, length="east", deal=level, draw=level, cpu_deal=0, cpu_draw=0, cpu_level="normal",
                          hinted=False, rank=1 + i % 3, score=25000, hands=5, tally=Tally(decisions=50, followed=40, good=good))
               for i in range(count)]
    return "[" + ",".join(dump_record(r) for r in records) + "]"


def perfect_decks() -> dict[str, str]:
    return {f"drill.{kind}": dump_deck(Deck(answered=20, right=20, recent="1" * 20)) for kind in GRADUATION_DRILLS}


# ---------------------------------------------------------------- 画面の操作


def settle(page: Page, ms: int = 700) -> None:
    page.wait_for_timeout(ms)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(200)


def main_text(page: Page) -> str:
    return page.locator(MAIN).evaluate(TEXT_WITHOUT_RUBY)


def stored(page: Page, name: str) -> str | None:
    return page.evaluate("name => localStorage.getItem('mjdojo:' + name)", name)


def open_section(page: Page, label: str) -> None:
    details = page.locator("details", has=page.locator("summary", has_text=label)).first
    if not details.evaluate("e => e.open"):
        details.locator("summary").tap()
        settle(page, 400)


def toast_texts(page: Page) -> list[str]:
    return [t.evaluate(TEXT_WITHOUT_RUBY) for t in page.locator('[data-testid="stToast"]').all()]


def run(base_url: str, out_dir: Path, only: Collection[str] = ()) -> dict:
    """only に名前（home / why / declare / curriculum / graduation / auto / looks）を渡すと、その部分だけを確かめる"""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    result: dict = {"problems": []}
    console_errors: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            result["problems"].append(message)

    def is_base_path_probe(url: str) -> bool:
        return bool(re.search(r"/[^/]+/_stcore/(health|host-config)$", url))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def new_context(*, height: int = TALL, width: int = WIDTH, dark: bool = False, script: str | None = None) -> BrowserContext:
            context = browser.new_context(
                viewport={"width": width, "height": height}, device_scale_factor=2, is_mobile=width < 600, has_touch=width < 600,
                user_agent=IPHONE_UA if width < 600 else None, color_scheme="dark" if dark else "light", locale="ja-JP",
            )
            if script:
                context.add_init_script(script)
            return context

        def open_page(context: BrowserContext, path: str, *, wait: str = "h1") -> Page:
            page = context.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and not is_base_path_probe(m.location.get("url", "")) else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.goto(base + path)
            page.locator(f"{MAIN} {wait}").first.wait_for(timeout=60000)
            settle(page, 900)
            return page

        def shot(page: Page, name: str, width: int = WIDTH) -> None:
            page.screenshot(path=str(out_dir / f"phase5_{name}.png"))
            expect(page.locator('[data-testid="stException"]').count() == 0, f"{name}: 画面に例外が出ている")
            overflow = page.evaluate("document.documentElement.scrollWidth")
            expect(overflow <= width, f"{name}: 横にはみ出している（{overflow}px）")

        def check_ruby(page: Page, name: str, *, expand: bool = True) -> None:
            if expand:
                open_all(page)
            missing = terms_without_ruby(page)
            if missing:
                result.setdefault("ruby_missing", {})[name] = missing
            result["ruby_checked"] = result.get("ruby_checked", 0) + 1
            expect(not missing, f"{name}: 初出なのにルビが無い用語: {missing}")

        parts: dict[str, Callable[[], None]] = {}

        def part(name: str):
            def register(check: Callable[[], None]) -> Callable[[], None]:
                parts[name] = check
                return check
            return register

        # ================================================================ 1. ホームとメニュー
        @part("home")
        def check_home() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/")
            names = [a.inner_text().split("\n")[-1] for a in page.locator(LINK).all()]
            result["home_links"] = names
            expect(any("カリキュラム" in n for n in names) and any("卒業判定" in n for n in names), f"ホームに、カリキュラム・卒業判定へのリンクが無い: {names}")
            shot(page, "01_home")
            check_ruby(page, "ホーム")
            context.close()

        # ================================================================ 2. 「なぜ？」（キーなし）
        @part("why")
        def check_why() -> None:
            context = new_context(height=900)
            page = open_page(context, "/practice", wait=".mj-tile")
            page.locator(".mj-tile").nth(13).wait_for(timeout=60000)
            settle(page, 500)
            open_section(page, "なぜ？（この局面について質問する）")
            chips = page.locator("details[open] .mj-choices-root .mj-opt")
            result["why_chips"] = chips.count()
            expect(chips.count() >= 2, "「なぜ？」によくある質問のボタンが無い")
            first = chips.first
            first.scroll_into_view_if_needed()
            first.tap()
            page.locator(".mj-qa").first.wait_for(timeout=30000)
            settle(page, 500)
            card = page.locator(".mj-qa").first
            result["why_answer"] = card.evaluate(TEXT_WITHOUT_RUBY)[:160]
            expect("mj-qa-template" in (card.get_attribute("class") or ""), "キーが無いのに、テンプレートの答えになっていない")
            expect("アプリの計算より" in result["why_answer"], "答えの出どころ（アプリの計算より）が出ていない")
            expect("AI のキーが要ります" in main_text(page), "キーが無いときの、自分で質問する欄の案内が無い")
            card.scroll_into_view_if_needed()
            shot(page, "02_why")
            check_ruby(page, "一人練習（なぜ？）", expand=False)
            context.close()

        # ================================================================ 3. あがったときの点数の申告
        @part("declare")
        def check_declare() -> None:
            state = winning_hand()
            # 成績に入れる局で、打つ前のヒントを見ていない局（その申告だけを、記録に入れる）
            hand = json.dumps({"v": 1, "save": practice.to_save(state), "counted": True, "hinted": False})
            items = {"practice.settings": practice_settings(hint="after"), "practice.hand": hand}
            context = new_context(height=HEIGHT, script=storage_script(items))
            page = open_page(context, "/practice", wait=".mj-big")
            expect("あがり！ 何点？" in main_text(page), "あがったのに、申告の問題が出ていない")
            shot(page, "03_declare_quiz")
            check_ruby(page, "一人練習（申告の問題）", expand=False)
            options = page.locator(".mj-choices-root .mj-opt")
            result["declare_options"] = options.count()
            expect(options.count() >= 3, "申告の選択肢が少ない")
            before = main_text(page)
            options.first.tap()
            page.wait_for_function("t => document.querySelector('[data-testid=stMain]').innerText !== t", arg=before, timeout=20000)
            settle(page, 800)
            text = main_text(page)
            banner = page.locator(".mj-headline", has_text="申告").first
            result["declare_banner"] = banner.evaluate(TEXT_WITHOUT_RUBY)
            expect("申告：正解" in text or "が正解" in text, "申告の答え合わせが出ていない")
            # 答えたら画面の上へ戻す：答え合わせの札が、最初の画面の中に見えている
            top = banner.evaluate("e => e.getBoundingClientRect().top")
            result["declare_banner_top"] = round(top, 1)
            expect(0 <= top < HEIGHT - 40, f"申告の答え合わせが、画面の外にある（上端 {top:.0f}px）")
            saved = json.loads(stored(page, "drill.declare") or "{}")
            expect(saved.get("n") == 1, f"申告の記録が残っていない: {saved}")
            shot(page, "04_declare_result")
            context.close()
            # 申告しないで結果を見る：記録しない
            context = new_context(height=HEIGHT, script=storage_script(items))
            page = open_page(context, "/practice", wait=".mj-big")
            page.get_by_role("button", name="申告しないで結果を見る").tap()
            page.get_by_role("button", name="次の局へ").first.wait_for(timeout=20000)
            settle(page, 500)
            expect(stored(page, "drill.declare") is None, "申告しなかったのに、記録が残った")
            context.close()

        # ================================================================ 4. カリキュラムと確認テスト
        @part("curriculum")
        def check_curriculum() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/curriculum")
            summaries = [s.evaluate(TEXT_WITHOUT_RUBY) for s in page.locator(f"{MAIN} details > summary").all()]
            result["curriculum_steps"] = summaries
            expect(len(summaries) == 4 and "いまの段階" in summaries[0], f"段階の折りたたみが違う: {summaries}")
            shot(page, "05_curriculum")
            check_ruby(page, "カリキュラム")
            page.get_by_role("button", name="確認テストを受ける").first.tap()
            page.locator(".mj-prompt").wait_for(timeout=30000)
            settle(page, 800)
            text = main_text(page)
            expect(page.url.endswith("/drill"), f"確認テストで、ドリルのページに移らない: {page.url}")
            expect("確認テスト：" in text and "1 / 10 問目" in text, "確認テストの札（何問目）が出ていない")
            shot(page, "06_curriculum_test")
            check_ruby(page, "確認テスト（1 問目）", expand=False)
            page.get_by_role("button", name="確認テストをやめる").tap()
            page.wait_for_url("**/curriculum", timeout=20000)
            settle(page, 1200)
            text = main_text(page)
            expect("確認テスト：" not in text, "確認テストをやめても、テストの札が残っている")
            expect("確認テストをやめました" in text, "確認テストをやめたことが、カリキュラムのページに出ていない")
            expect(stored(page, "progress.curriculum") is None, "途中でやめた確認テストが、記録に残った")
            context.close()

        # ================================================================ 5. 卒業判定
        @part("graduation")
        def check_graduation() -> None:
            context = new_context(height=HEIGHT)
            page = open_page(context, "/graduation")
            text = main_text(page)
            expect("満たした条件 0 / 6" in text, "記録が無いのに、満たした条件の数が 0 でない")
            expect(page.locator(LINK, has_text="ドリル：").count() >= 5, "練習する場所へのリンクが少ない")
            shot(page, "07_graduation_empty")
            check_ruby(page, "卒業判定（記録なし）")
            context.close()
            items = {**perfect_decks(), "game.history": plain_games(GOAL_GAMES)}
            context = new_context(height=HEIGHT, script=storage_script(items))
            page = open_page(context, "/graduation")
            text = main_text(page)
            result["graduation_full"] = text[:200]
            expect("○ 卒業" in text, "すべて満たしたのに、卒業と出ない")
            expect(page.locator(LINK, has_text="ドリル：").count() == 0, "満たした条件にも、練習のリンクが出ている")
            shot(page, "08_graduation_passed")
            check_ruby(page, "卒業判定（すべて満たした）")
            context.close()

        # ================================================================ 6. おまかせ補正
        @part("auto")
        def check_auto() -> None:
            # 一人練習：おまかせを始めてから、ヒントなしで 5 局（どれも 90%）。開くと新しい局が始まり、補正が「中」に下がる
            items = {"practice.settings": practice_settings(auto=True, auto_since=NOW - 1000, hint="after"), "practice.history": good_hands(5)}
            context = new_context(height=HEIGHT, script=storage_script(items))
            page = open_page(context, "/practice", wait=".mj-tile")
            settle(page, 800)
            toasts = toast_texts(page)
            result["auto_practice_toast"] = toasts
            expect(any("「強」から「中」に下げました" in t for t in toasts), f"補正を下げた知らせが出ない: {toasts}")
            expect("ツキ補正：配牌 50・ツモ 50" in main_text(page), "新しい局の補正が 50 になっていない")
            saved = json.loads(stored(page, "practice.settings") or "{}")
            expect(saved.get("deal") == 50 and saved.get("auto_last", {}).get("to") == 50, f"設定に、下げた補正が残っていない: {saved}")
            shot(page, "09_auto_toast")
            open_section(page, "設定（ツキ補正・役指定・コーチ）")
            text = main_text(page)
            expect("いまの段階は「中」" in text and "前回の変更" in text, "設定に、おまかせの段階と前回の変更が出ていない")
            disabled = page.locator('[data-testid="stSlider"] input[type="range"][disabled]').count()
            result["auto_disabled_sliders"] = disabled
            expect(disabled >= 2, "おまかせなのに、自分の補正のスライダーが動かせる")
            page.get_by_text("いまの段階は").first.scroll_into_view_if_needed()
            settle(page, 300)
            shot(page, "10_auto_settings")
            check_ruby(page, "一人練習（おまかせの設定）", expand=False)
            context.close()
            # CPU 戦：ヒントなしの対局が 2 回（どちらも 90%）。開くと新しい対局が始まり、補正が「弱」から「なし」に下がる
            settings = {"length": "east", "cpu_level": "normal", "deal": 25, "draw": 25, "cpu_deal": 0, "cpu_draw": 0, "hint": "after", "level": 2,
                        "mark": True, "moves": "together", "rules": {}, "declare": True, "auto": True, "auto_since": NOW - 1000, "auto_last": None}
            items = {"game.settings": json.dumps(settings), "game.history": plain_games(2, level=25)}
            context = new_context(height=HEIGHT, script=storage_script(items))
            page = open_page(context, "/game", wait=".mj-tile")
            settle(page, 800)
            toasts = toast_texts(page)
            result["auto_game_toast"] = toasts
            expect(any("「弱」から「なし」に下げました" in t for t in toasts), f"CPU 戦で、補正を下げた知らせが出ない: {toasts}")
            open_section(page, "設定（対局・ツキ補正・コーチ）")
            expect("いまの段階は「なし」" in main_text(page), "CPU 戦の設定に、おまかせの段階が出ていない")
            shot(page, "11_auto_game")
            context.close()

        # ================================================================ 7. 画面の幅と、暗い画面
        @part("looks")
        def check_looks() -> None:
            sizes = {}
            for width in (320, 768, 1280):
                context = new_context(width=width, height=1600)
                for path in ("/curriculum", "/graduation"):
                    page = open_page(context, path)
                    sizes[f"{path}@{width}"] = page.evaluate("document.documentElement.scrollWidth")
                    shot(page, f"12_{path.strip('/')}_{width}", width)
                    page.close()
                context.close()
            result["widths"] = sizes
            context = new_context(height=1600, dark=True)
            for path in ("/curriculum", "/graduation"):
                page = open_page(context, path)
                shot(page, f"13_{path.strip('/')}_dark")
                page.close()
            context.close()

        for name, check in parts.items():
            if only and name not in only:
                continue
            try:
                check()
            except Exception as error:  # 1 つの部分で止まっても、ほかの部分は確かめる
                result["problems"].append(f"{name}: {type(error).__name__}: {error}")
        browser.close()
    result["console_errors"] = console_errors
    if console_errors:
        result["problems"].append(f"ブラウザのコンソールにエラー: {console_errors[:5]}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    picked = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else set()
    report = run(sys.argv[1], Path(sys.argv[2]), picked)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if report["problems"] else 0)

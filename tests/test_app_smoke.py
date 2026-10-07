"""アプリを画面なしで動かして、ページが例外なく描けることと、基本の流れを確かめる。

Streamlit の AppTest はブラウザを使わないので、JavaScript の部品（牌タップ・ブラウザ内保存）は動かない。
ここでは「部品から値が届いたあとの Python 側の動き」と「予備の操作方法」を確かめる。
"""
import json
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine import solo
from engine.tiles import format_tiles

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"


def new_app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def open_check_page(at: AppTest, known: dict | None) -> AppTest:
    """実機チェックのページを開く。known はブラウザに残っていた保存内容（None なら保存を使わない）"""
    at.run()
    if known is None:
        at.switch_page("views/device_check.py").run()
        skip = next(b for b in at.button if b.label == "保存を使わずに始める")
        skip.click().run()
    else:
        at.session_state[STORE_STATE] = {"known": dict(known), "pending": {}, "seq": 0, "error": None, "skipped": False}
        at.switch_page("views/device_check.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def report(at: AppTest) -> str:
    return at.code[-1].value


def field(at: AppTest, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}: (.*)$", report(at), flags=re.MULTILINE)
    assert match, f"結果に「{name}」の行がありません"
    return match.group(1)


def test_home_page_renders():
    at = new_app().run()
    assert not at.exception
    assert at.title[0].value == "ツキ付き麻雀道場"


def test_check_page_waits_for_browser_storage_then_starts_without_it():
    at = new_app().run()
    at.switch_page("views/device_check.py").run()
    assert not at.exception
    assert any("確認しています" in i.value for i in at.info)
    assert not at.code                      # まだ本体は描かれていない

    next(b for b in at.button if b.label == "保存を使わずに始める").click().run()
    assert not at.exception
    assert field(at, "ブラウザ内保存").startswith("使えない")
    assert field(at, "切った回数") == "牌タップ 0 回 ／ 予備の方法 0 回"


def test_fallback_controls_discard_a_tile():
    at = open_check_page(new_app(), known={})
    before = at.session_state["chk_state"]
    assert field(at, "ブラウザ内保存") == "使える ／ 開いた回数 1 ／ 続きから再開 0 ／ 今回は新規"

    at.toggle(key="chk_use_fallback").set_value(True).run()
    pills = at.button_group[0]
    # ツモ牌を選ぶ（表示名に「（ツモ）」が付くので必ず 1 つに決まる。同じ種類が 2 枚ある牌は、
    # 画面なしのテストではどちらが選ばれたか区別できない）
    target = before.drawn
    pills.set_value(target).run()
    next(b for b in at.button if b.label == "この牌を切る").click().run()
    assert not at.exception

    after = at.session_state["chk_state"]
    assert after.discards == (target,) and after.hand == before.hand
    assert field(at, "切った回数") == "牌タップ 0 回 ／ 予備の方法 1 回"
    # ブラウザに保存する内容が、いまの局面になっている
    saved = json.loads(at.session_state[STORE_STATE]["known"]["check.solo"])
    assert saved == {"seed": after.seed, "discards": [target]}


def test_saved_position_is_restored_in_a_new_session():
    state = solo.start(4242)
    for _ in range(4):
        state = solo.discard(state, state.tiles_in_hand[2])
    saved = {
        "check.solo": json.dumps({"seed": 4242, "discards": list(state.discards)}),
        "check.meta": json.dumps({"opens": 3, "restores": 1}),
    }
    at = open_check_page(new_app(), known=saved)
    assert at.session_state["chk_state"] == state
    assert field(at, "ブラウザ内保存") == "使える ／ 開いた回数 4 ／ 続きから再開 2 ／ 今回は再開"
    assert field(at, "局面") == f"シード 4242 ／ 手牌 {format_tiles(state.tiles_in_hand)} ／ 河 4 枚"
    assert any("再開したもの" in s.value for s in at.success)


def test_broken_saved_data_starts_a_fresh_hand():
    for broken in ("これはJSONではない", json.dumps({"seed": 1}), json.dumps({"seed": 1, "discards": [999]}), json.dumps([1, 2])):
        at = open_check_page(new_app(), known={"check.solo": broken, "check.meta": "{壊れている"})
        assert field(at, "ブラウザ内保存") == "使える ／ 開いた回数 1 ／ 続きから再開 0 ／ 今回は新規"
        assert len(at.session_state["chk_state"].discards) == 0


def test_measurements_and_ratings_survive_a_reload():
    """計測値と感想はブラウザに残り、開き直しても結果に載る"""
    stats = {
        "latencies": [120, 300, 180],
        "env": {"vw": 390, "vh": 844, "dpr": 3, "img_ng": 0},
        "counts": {"tap": 4, "fallback": 1},
        "bench_us": 55.5,
        "ratings": {"tap": "◎", "look": "○", "speed": "△"},
        "comment": "右端の牌が少し押しにくい",
    }
    at = open_check_page(new_app(), known={"check.stats": json.dumps(stats, ensure_ascii=False)})
    assert field(at, "応答時間（牌タップ）") == "3 回 ／ 中央値 0.18 秒 ／ 最大 0.30 秒"
    assert field(at, "画面") == "幅 390 × 高さ 844 px ／ 画素比 3 ／ 読めなかった牌画像 0 枚"
    assert field(at, "切った回数") == "牌タップ 4 回 ／ 予備の方法 1 回"
    assert field(at, "サーバーの速さ").startswith("56 マイクロ秒/回") or field(at, "サーバーの速さ").startswith("55 マイクロ秒/回")
    assert field(at, "押しやすさ") == "◎ ／ 見やすさ: ○ ／ 反応の速さ: △"
    assert field(at, "メモ") == "右端の牌が少し押しにくい"
    # 次の保存内容にも同じ値が入っている
    saved = json.loads(at.session_state[STORE_STATE]["known"]["check.stats"])
    assert saved["latencies"] == [120, 300, 180] and saved["ratings"]["speed"] == "△"


def test_broken_measurements_are_ignored():
    for broken in ("{壊れている", json.dumps([1, 2]), json.dumps({"latencies": "x", "counts": {"tap": "多い"}, "ratings": {"tap": "最高"}})):
        at = open_check_page(new_app(), known={"check.stats": broken})
        assert field(at, "応答時間（牌タップ）").startswith("未計測")
        assert field(at, "切った回数") == "牌タップ 0 回 ／ 予備の方法 0 回"
        assert field(at, "押しやすさ").startswith("未回答")


def test_benchmark_and_reset():
    at = open_check_page(new_app(), known={})
    next(b for b in at.button if b.label.startswith("計測する")).click().run()
    assert not at.exception
    assert "マイクロ秒/回" in field(at, "サーバーの速さ")

    first_seed = at.session_state["chk_state"].seed
    next(b for b in at.button if b.label == "記録を消して最初からやり直す").click().run()
    assert not at.exception
    assert field(at, "サーバーの速さ") == "未計測"
    assert field(at, "ブラウザ内保存") == "使える ／ 開いた回数 1 ／ 続きから再開 0 ／ 今回は新規"
    assert isinstance(at.session_state["chk_state"].seed, int) and first_seed is not None

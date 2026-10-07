"""画面部品の Python 側（届いた値の検査と、ブラウザ内保存のやり取り）のテスト。

ブラウザの中で動く JavaScript 側は、tools/e2e_mobile_check.py で実際に画面を動かして確かめる。
"""
from types import SimpleNamespace

from ui.components.browser_store import BrowserStore
from ui.components.tile_hand import parse_pick

HAND = [4, 8, 12, 52, 132]


def test_parse_pick_accepts_a_valid_pick():
    pick = parse_pick({"id": 52, "rev": 3, "prevMs": 240, "vw": 390, "vh": 844, "dpr": 3, "imgNg": 0}, rev=3, tile_ids=HAND)
    assert pick is not None
    assert (pick.tile_id, pick.prev_response_ms, pick.viewport_width, pick.device_pixel_ratio) == (52, 240, 390, 3.0)


def test_parse_pick_ignores_stale_or_malformed_values():
    ok = {"id": 52, "rev": 3}
    assert parse_pick(ok, rev=3, tile_ids=HAND) is not None
    assert parse_pick(ok, rev=4, tile_ids=HAND) is None              # 古い画面からの確定（二重送信）
    assert parse_pick({"id": 53, "rev": 3}, rev=3, tile_ids=HAND) is None   # 手牌にない牌
    assert parse_pick({"id": "52", "rev": 3}, rev=3, tile_ids=HAND) is None
    assert parse_pick({"id": True, "rev": 3}, rev=3, tile_ids=HAND) is None
    assert parse_pick({"rev": 3}, rev=3, tile_ids=HAND) is None
    assert parse_pick(None, rev=3, tile_ids=HAND) is None
    assert parse_pick([52, 3], rev=3, tile_ids=HAND) is None


def test_parse_pick_tolerates_missing_measurements():
    pick = parse_pick({"id": 4, "rev": 0, "prevMs": None}, rev=0, tile_ids=HAND)
    assert pick is not None and pick.prev_response_ms is None and pick.image_errors == 0


def browser_reply(session: dict, store_key: str, values: dict, seq: int, error: str | None = None) -> None:
    """ブラウザ側の部品が snapshot を送ってきた状況を作る"""
    session[store_key] = SimpleNamespace(snapshot={"values": values, "error": error, "seq": seq})


def test_store_waits_for_the_first_reply_then_reads():
    session: dict = {}
    store = BrowserStore("s", session=session)
    assert not store.ready and not store.available and store.get("a") is None
    store.set("a", "ignored")                      # まだ読めていない間の書き込みは捨てる
    assert session["s::state"]["pending"] == {}

    browser_reply(session, "s", {"a": "1", "b": "2"}, seq=0)
    store._on_snapshot_change()
    assert store.ready and store.available
    assert store.get("a") == "1" and store.get("b") == "2" and store.get("zzz") is None


def test_store_writes_are_optimistic_and_stale_replies_are_ignored():
    session: dict = {}
    store = BrowserStore("s", session=session)
    browser_reply(session, "s", {"a": "1"}, seq=0)
    store._on_snapshot_change()

    store.set("a", "2")
    store.set("c", "3")
    store.remove("zzz")                            # 無いものを消しても何も起きない
    state = session["s::state"]
    assert store.get("a") == "2" and store.get("c") == "3"
    assert state["pending"] == {"a": "2", "c": "3"} and state["seq"] == 2

    store._on_snapshot_change()                    # 前の返事（seq=0）がまだ残っていても、上書きされない
    assert store.get("a") == "2"

    store.set("a", "2")                            # 同じ値の書き込みは何もしない
    assert state["seq"] == 2

    store.remove("c")
    assert store.get("c") is None and state["pending"] == {"a": "2", "c": None} and state["seq"] == 3

    browser_reply(session, "s", {"a": "9"}, seq=3)   # 最新の問い合わせへの返事は、ブラウザの実際の中身として採用する
    store._on_snapshot_change()
    assert store.get("a") == "9" and state["pending"] == {}


def test_store_reports_when_the_browser_storage_is_unavailable():
    session: dict = {}
    store = BrowserStore("s", session=session)
    browser_reply(session, "s", {}, seq=0, error="SecurityError")
    store._on_snapshot_change()
    assert store.ready and not store.available and store.error == "SecurityError"
    store.set("a", "1")                            # 使えないと分かったあとは、書き込みを試みない
    assert session["s::state"]["pending"] == {} and session["s::state"]["seq"] == 0


def test_store_can_be_skipped():
    session: dict = {}
    store = BrowserStore("s", session=session)
    store.skip()
    assert store.ready and not store.available
    store.set("a", "1")
    assert store.get("a") is None
    # 実行のたびに作り直しても、状態は session に残る
    assert BrowserStore("s", session=session).ready

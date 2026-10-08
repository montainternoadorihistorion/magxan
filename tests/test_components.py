"""画面部品の Python 側（届いた値の検査と、ブラウザ内保存のやり取り）のテスト。

ブラウザの中で動く JavaScript 側は、tools/e2e_mobile_check.py で実際に画面を動かして確かめる。
"""
from types import SimpleNamespace

import pytest

from ui.components.browser_store import BrowserStore, initial_state
from ui.components.tile_hand import parse_action, parse_pick

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


def test_parse_pick_accepts_riichi_only_for_tiles_that_allow_it():
    declared = {"id": 52, "rev": 3, "riichi": True}
    assert parse_pick(declared, rev=3, tile_ids=HAND, riichi_ids=[52, 132]).riichi is True
    assert parse_pick(declared, rev=3, tile_ids=HAND, riichi_ids=[132]).riichi is False     # その牌ではリーチできない
    assert parse_pick(declared, rev=3, tile_ids=HAND).riichi is False                      # リーチできない局面
    assert parse_pick({"id": 52, "rev": 3}, rev=3, tile_ids=HAND, riichi_ids=[52]).riichi is False
    assert parse_pick({"id": 52, "rev": 3, "riichi": "yes"}, rev=3, tile_ids=HAND, riichi_ids=[52]).riichi is False
    assert parse_pick({"id": 52, "rev": 3, "riichi": False}, rev=3, tile_ids=HAND, riichi_ids=[52]).riichi is False


def test_parse_pick_tolerates_missing_measurements():
    pick = parse_pick({"id": 4, "rev": 0, "prevMs": None}, rev=0, tile_ids=HAND)
    assert pick is not None and pick.prev_response_ms is None and pick.image_errors == 0


def test_action_button_values_are_told_apart_from_picks():
    """牌を切らずにする操作（ツモあがり）のボタンの値は、牌の確定とは別に受け取る"""
    action = {"action": True, "rev": 3, "prevMs": 120, "vw": 375}
    assert parse_action(action, rev=3) is True
    assert parse_action(action, rev=4) is False                      # 古い画面から届いた
    assert parse_action({"action": "yes", "rev": 3}, rev=3) is False
    assert parse_action({"id": 52, "rev": 3}, rev=3) is False        # ふつうの確定
    assert parse_action(None, rev=3) is False and parse_action([True, 3], rev=3) is False
    # 操作のボタンの値に牌IDが入っていても、牌を切ったことにはしない
    assert parse_pick({"action": True, "id": 52, "rev": 3}, rev=3, tile_ids=HAND) is None


def browser_reply(state: dict, store_key: str, name: str, *, to: str | None = None, **value) -> None:
    """ブラウザ側の部品が値（snapshot や ack）を送ってきた状況を作る。to は宛先の合言葉（既定は、いまのセッション）"""
    value["session"] = state[f"{store_key}::state"]["session"] if to is None else to
    current = vars(state.get(store_key) or SimpleNamespace())
    state[store_key] = SimpleNamespace(**{**current, name: value})


def ready_store(values: dict | None = None) -> tuple[BrowserStore, dict, dict]:
    """ブラウザの中身を受け取ったあとの状態"""
    session: dict = {}
    store = BrowserStore("s", session=session)
    browser_reply(session, "s", "snapshot", values=dict(values or {}), error=None)
    store._on_snapshot_change()
    return store, session, session["s::state"]


def queued(state: dict) -> list[tuple]:
    return [(op["id"], op["op"], op["name"], op["value"]) for op in state["ops"]]


def test_store_waits_for_the_first_reply_then_reads():
    session: dict = {}
    store = BrowserStore("s", session=session)
    assert not store.ready and not store.available and store.get("a") is None
    store.set("a", "ignored")                      # まだ読めていない間の書き込みは捨てる
    store.append("log", "{}", limit=5)
    store.remove("a")
    assert session["s::state"]["ops"] == []

    browser_reply(session, "s", "snapshot", values={"a": "1", "b": "2", "c": 3}, error=None)
    store._on_snapshot_change()
    assert store.ready and store.available
    assert store.get("a") == "1" and store.get("b") == "2" and store.get("zzz") is None
    assert store.get("c") is None                  # 文字列でない値は読まない


def test_store_queues_each_write_once_and_keeps_only_the_last_value_per_name():
    store, session, state = ready_store({"a": "1"})
    store.set("a", "2")
    store.set("c", "3")
    store.remove("zzz")                            # 無いものを消しても何も起きない
    assert store.get("a") == "2" and store.get("c") == "3"
    assert queued(state) == [(1, "set", "a", "2"), (2, "set", "c", "3")]

    store.set("a", "2")                            # 同じ値の書き込みは何もしない
    assert len(state["ops"]) == 2
    store.set("a", "5")                            # 同じ名前への古い書き込みは、列から外す（最後の値だけ届けばよい）
    assert queued(state) == [(2, "set", "c", "3"), (3, "set", "a", "5")]
    store.remove("c")
    assert store.get("c") is None and queued(state) == [(3, "set", "a", "5"), (4, "remove", "c", None)]
    # 実行のたびに作り直しても、状態は session に残る
    assert BrowserStore("s", session=session).get("a") == "5"


def test_store_append_adds_one_item_to_a_json_list():
    store, _, state = ready_store({"log": '[{"n":1}]', "bad": "こわれている", "obj": '{"x":1}'})
    store.append("log", '{"n":2}', limit=3)
    store.append("log", '{"n":3}', limit=3)
    store.append("log", '{"n":4}', limit=3)        # 上限を超えたら、古いものから捨てる
    assert store.get("log") == '[{"n":2},{"n":3},{"n":4}]'
    assert [(op["op"], op["value"], op["limit"]) for op in state["ops"]] == [("append", '{"n":2}', 3), ("append", '{"n":3}', 3), ("append", '{"n":4}', 3)]
    # 配列でないもの・壊れているものに足すときは、空の配列から始める
    store.append("bad", "1", limit=5)
    store.append("obj", "2", limit=5)
    store.append("new", '"x"', limit=5)
    assert (store.get("bad"), store.get("obj"), store.get("new")) == ("[1]", "[2]", '["x"]')
    # そのあと全体を書き直したら、足した分の書き込みはもう要らない
    store.set("log", "[]")
    assert [op["op"] for op in state["ops"] if op["name"] == "log"] == ["set"]
    with pytest.raises(ValueError):
        store.append("log", "{JSON でない", limit=5)


def test_store_drops_writes_when_the_browser_reports_them_done():
    store, session, state = ready_store()
    for n in range(4):
        store.append("log", str(n), limit=10)
    store.set("a", "1")
    assert [op["id"] for op in state["ops"]] == [1, 2, 3, 4, 5]
    browser_reply(session, "s", "ack", id=3, error=None)
    store._on_ack_change()
    assert [op["id"] for op in state["ops"]] == [4, 5]
    store._on_ack_change()                         # 同じ報告がもう一度来ても、何も変わらない
    assert [op["id"] for op in state["ops"]] == [4, 5] and store.available
    browser_reply(session, "s", "ack", id="5", error=None)      # 形のおかしい報告は無視する
    store._on_ack_change()
    assert [op["id"] for op in state["ops"]] == [4, 5]
    # 書き込みに失敗したという報告が来たら、以後は保存を使わない
    browser_reply(session, "s", "ack", id=4, error="QuotaExceededError")
    store._on_ack_change()
    assert not store.available and store.ready and store.error == "QuotaExceededError" and state["ops"] == []
    store.set("b", "2")
    assert state["ops"] == []
    assert store.get("b") == "2" and store.get("a") == "1"       # このセッションのあいだは、手元の控えで動き続ける


def test_store_ignores_replies_meant_for_another_session():
    """通信が切れてセッションが作り直されたあと、前のセッション宛ての返事が届いても使わない"""
    session: dict = {}
    store = BrowserStore("s", session=session)
    browser_reply(session, "s", "snapshot", to="前のセッション", values={"a": "古い"}, error=None)
    store._on_snapshot_change()
    assert not store.ready
    browser_reply(session, "s", "snapshot", values={"a": "1"}, error=None)
    store._on_snapshot_change()
    store.set("a", "2")
    browser_reply(session, "s", "ack", to="前のセッション", id=99, error="x")
    store._on_ack_change()
    assert store.available and len(session["s::state"]["ops"]) == 1
    # 中身を受け取ったあとに、送り直しの snapshot が重なって届いても、手元の内容を巻き戻さない
    browser_reply(session, "s", "snapshot", values={"a": "1"}, error=None)
    store._on_snapshot_change()
    assert store.get("a") == "2"


def test_store_reports_when_the_browser_storage_is_unavailable():
    session: dict = {}
    store = BrowserStore("s", session=session)
    browser_reply(session, "s", "snapshot", values={}, error="SecurityError")
    store._on_snapshot_change()
    assert store.ready and not store.available and store.error == "SecurityError"
    store.set("a", "1")                            # 使えないと分かったあとは、ブラウザへの書き込みを試みない
    store.append("log", '{"n":1}', limit=5)
    assert session["s::state"]["ops"] == []
    # それでも、このセッションの中では読み書きできる（成績やドリルの記録が、開いているあいだは残る）
    assert store.get("a") == "1" and store.get("log") == '[{"n":1}]'
    store.remove("a")
    assert store.get("a") is None and session["s::state"]["ops"] == []


def test_store_can_be_skipped_and_then_never_writes_to_the_browser():
    session: dict = {}
    store = BrowserStore("s", session=session)
    store.skip()
    assert store.ready and not store.available and store.get("a") is None
    # ブラウザには書かないが、このセッションの中では読み書きできる
    store.set("a", "1")
    store.append("log", "1", limit=5)
    assert store.get("a") == "1" and store.get("log") == "[1]" and session["s::state"]["ops"] == []
    # 実行のたびに作り直しても、状態は session に残る
    again = BrowserStore("s", session=session)
    assert again.ready and again.get("a") == "1"
    # 待たずに始めたあとで返事が届いても、使わない（読まないまま、ブラウザに残っていた記録を上書きしないため）
    browser_reply(session, "s", "snapshot", values={"a": "残っていた記録", "b": "これも"}, error=None)
    store._on_snapshot_change()
    assert not store.available and store.get("a") == "1" and store.get("b") is None
    store.set("a", "新しい値")
    store.remove("log")
    assert store.get("a") == "新しい値" and store.get("log") is None and session["s::state"]["ops"] == []


def test_store_skipped_before_the_memory_slot_existed_still_works():
    """アプリを更新する前に「待たずに始めた」セッションには、セッションの中の置き場所がまだ無い。使うときに作る"""
    session: dict = {}
    store = BrowserStore("s", session=session)
    state = session["s::state"]
    state["skipped"] = True
    del state["memory"]
    store.set("a", "1")
    assert store.get("a") == "1" and state["memory"] == {"a": "1"}


def test_store_state_of_an_older_shape_is_replaced():
    """アプリを更新したとき、セッションに古い形の状態が残っていることがある。作り直して、中身を聞き直す"""
    session = {"s::state": {"known": {"a": "1"}, "pending": {}, "seq": 3, "error": None, "skipped": False}}
    store = BrowserStore("s", session=session)
    assert session["s::state"]["v"] == 2 and not store.ready and store.get("a") is None
    assert initial_state({"a": "1"})["known"] == {"a": "1"} and initial_state()["known"] is None
    assert initial_state()["session"] != initial_state()["session"]          # 合言葉は毎回違う


# ---------------------------------------------------------------- 選択肢の部品（ドリル）


def test_parse_choice_accepts_valid_answers():
    from ui.components.choices import parse_choice

    keys = ["a", "b", "c"]
    assert parse_choice({"rev": 7, "keys": ["b"]}, rev=7, keys=keys, multi=False) == ["b"]
    assert parse_choice({"rev": 7.0, "keys": ["a", "c"]}, rev=7, keys=keys, multi=True) == ["a", "c"]
    assert parse_choice({"rev": 7, "keys": ["c"]}, rev=7, keys=keys, multi=True) == ["c"]


def test_parse_choice_ignores_stale_or_malformed_values():
    from ui.components.choices import parse_choice

    keys = ["a", "b", "c"]
    assert parse_choice({"rev": 6, "keys": ["b"]}, rev=7, keys=keys, multi=False) is None        # 前の問題の画面からの答え
    assert parse_choice({"rev": 7, "keys": ["z"]}, rev=7, keys=keys, multi=False) is None        # 選択肢に無い
    assert parse_choice({"rev": 7, "keys": ["a", "b"]}, rev=7, keys=keys, multi=False) is None   # 1 つ選ぶ問題に 2 つ
    assert parse_choice({"rev": 7, "keys": []}, rev=7, keys=keys, multi=True) is None
    assert parse_choice({"rev": 7, "keys": ["a", "a"]}, rev=7, keys=keys, multi=True) is None
    assert parse_choice({"rev": 7, "keys": "a"}, rev=7, keys=keys, multi=False) is None
    assert parse_choice({"rev": 7, "keys": [1]}, rev=7, keys=keys, multi=False) is None
    assert parse_choice({"rev": True, "keys": ["a"]}, rev=1, keys=keys, multi=False) is None
    assert parse_choice({"keys": ["a"]}, rev=7, keys=keys, multi=False) is None
    assert parse_choice(None, rev=7, keys=keys, multi=False) is None
    assert parse_choice(["a"], rev=7, keys=keys, multi=False) is None


def test_choice_buttons_rejects_unknown_layout():
    from ui.components.choices import Option, choice_buttons

    with pytest.raises(ValueError):
        choice_buttons([Option("a", [("A", "")])], key="k", rev=1, on_pick=lambda keys: None, layout="grid")


def test_session_rev_differs_between_sessions_and_keeps_order(monkeypatch):
    """部品に渡す番号は、セッションごとに違う土台を足す（作り直されたセッションで、たまたま前と同じ番号にならないように）"""
    from ui.components import _base

    first: dict = {}
    monkeypatch.setattr(_base.st, "session_state", first)
    numbers = [_base.session_rev(n) for n in (0, 1, 2, 250)]
    assert numbers[1] - numbers[0] == 1 and numbers[3] - numbers[0] == 250          # 同じセッションの中では、差がそのまま残る
    assert _base.session_rev(0) == numbers[0] and isinstance(first[_base.REV_BASE_KEY], int)
    assert max(numbers) < 2**53                                                       # JavaScript が正確に扱える整数

    second: dict = {}
    monkeypatch.setattr(_base.st, "session_state", second)
    assert _base.session_rev(0) != numbers[0]                                         # 新しいセッションは、土台が違う
    assert abs(_base.session_rev(0) - numbers[0]) >= 1_000_000                        # 前のセッションの番号と重ならない
    # 土台がおかしな値になっていたら、作り直す
    second[_base.REV_BASE_KEY] = "こわれた値"
    assert isinstance(_base.session_rev(3), int) and isinstance(second[_base.REV_BASE_KEY], int)

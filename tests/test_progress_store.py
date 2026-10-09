"""ブラウザに残した進み具合の読み書き（ui/progress_store.py）のテスト。書き出し → 読み込みで、元に戻ることを確かめる"""
from __future__ import annotations

import json

from engine.curriculum import Progress
from engine.drills import KINDS
from engine.progress import Stamp, dump_stamps, load_stamps, parse_export
from engine.records import HandRecord, dump_record, load_history
from engine.srs import Card, Deck, dump_deck, load_deck
from ui.practice_session import DEFAULT_SETTINGS, clean_settings
from ui.progress_store import (
    CURRICULUM_NAME,
    DECLARE,
    DRILL_PREFIX,
    HAND_NAME,
    HISTORY_NAME,
    SETTINGS_NAME,
    STAMPS_NAME,
    Summary,
    apply_import,
    clear_all,
    export_text,
    read_curriculum,
    read_deck,
    read_decks,
    read_history,
    read_stamps,
    summary_of_export,
    summary_of_store,
    write_curriculum,
    write_deck,
    write_history,
    write_stamps,
)

NOW = 1_800_000_000


class FakeStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def remove(self, name: str) -> None:
        self.values.pop(name, None)

    def append(self, name: str, item: str, *, limit: int) -> None:
        raise AssertionError("ここでは使わない")


def record(time: int, seed: int, *, yaku=("riichi",), win=True, target="", made=False) -> HandRecord:
    return HandRecord(
        time=time, seed=seed, deal=0, draw=0, hinted=False, win=win, turn=9, riichi=True, tenpai=True,
        points=1300 if win else 0, han=1 if win else 0, fu=40 if win else 0, yaku=tuple(yaku) if win else (),
        decisions=8, best=7, target=target, made=made,
    )


def history_text(records) -> str:
    return "[" + ",".join(dump_record(r) for r in records) + "]"


def filled_store() -> FakeStore:
    store = FakeStore()
    store.set(SETTINGS_NAME, json.dumps({**DEFAULT_SETTINGS, "deal": 50, "target": "sanshoku"}))
    store.set(HISTORY_NAME, history_text([record(NOW, 1), record(NOW + 60, 2, yaku=("sanshoku",), target="sanshoku", made=True)]))
    store.set(STAMPS_NAME, dump_stamps({"riichi": Stamp(1, NOW, NOW, 1), "sanshoku": Stamp(1, NOW + 60, NOW + 60, 1)}))
    store.set(DRILL_PREFIX + "table", dump_deck(Deck({"cr:30:1": Card(0, NOW + 600, 1, 0, NOW)}, 3, 2)))
    store.set(DRILL_PREFIX + "score", dump_deck(Deck({}, 5, 5)))
    store.set(HAND_NAME, '{"v":1}')
    return store


# ---------------------------------------------------------------- 読み書き


def test_read_stamps_falls_back_to_history():
    store = FakeStore({HISTORY_NAME: history_text([record(NOW, 1, yaku=("riichi", "pinfu")), record(NOW + 5, 2, win=False)])})
    assert read_stamps(store) == {"riichi": Stamp(1, NOW, NOW, 1), "pinfu": Stamp(1, NOW, NOW, 1)}
    store.set(STAMPS_NAME, "{broken")
    assert set(read_stamps(store)) == {"riichi", "pinfu"}           # 壊れた記録は、無いものとして扱う
    write_stamps(store, {"tanyao": Stamp(2, NOW, NOW + 9, 0)})
    assert read_stamps(store) == {"tanyao": Stamp(2, NOW, NOW + 9, 0)}       # スタンプの記録があれば、それを使う
    assert read_stamps(FakeStore()) == {}


def test_history_and_decks_round_trip():
    store = FakeStore()
    records = [record(NOW, 1), record(NOW + 5, 2, win=False)]
    write_history(store, records)
    assert read_history(store) == records and json.loads(store.values[HISTORY_NAME])[0]["seed"] == 1
    write_history(store, [])
    assert HISTORY_NAME not in store.values and read_history(store) == []

    deck = Deck().review("h:riichi", False, NOW)
    write_deck(store, "han", deck)
    assert read_deck(store, "han") == deck and read_deck(store, "table") == Deck()
    assert set(read_decks(store)) == {*KINDS, DECLARE}


# ---------------------------------------------------------------- 書き出し・読み込み


def test_export_contains_everything_but_the_hand_in_progress():
    store = filled_store()
    data = parse_export(export_text(store, time=NOW + 100, app_version="9.9.9"))
    assert data.exported == NOW + 100 and data.app_version == "9.9.9"
    assert data.settings["target"] == "sanshoku" and data.settings["deal"] == 50
    assert [r.seed for r in data.history] == [1, 2]
    assert set(data.stamps) == {"riichi", "sanshoku"}
    assert set(data.drills) == {"table", "score"}                    # 1 回も答えていない種類は、入れない
    assert "practice.hand" not in export_text(store, time=NOW, app_version="x")
    assert summary_of_store(store) == summary_of_export(data) == Summary(hands=2, stamps=2, answers=8)


def test_export_of_an_empty_store():
    data = parse_export(export_text(FakeStore(), time=NOW, app_version="1"))
    assert data.settings is None and data.history == [] and data.stamps == {} and data.drills == {}
    assert summary_of_export(data) == Summary(0, 0, 0)


def test_replace_makes_the_store_equal_to_the_file():
    source = filled_store()
    text = export_text(source, time=NOW, app_version="1")
    target = FakeStore()
    target.set(HISTORY_NAME, history_text([record(NOW + 999, 77)]))
    target.set(STAMPS_NAME, dump_stamps({"chinitsu": Stamp(4, NOW, NOW, 0)}))
    target.set(DRILL_PREFIX + "han", dump_deck(Deck({}, 9, 9)))
    target.set(SETTINGS_NAME, json.dumps(DEFAULT_SETTINGS))
    target.set(HAND_NAME, '{"keep":"me"}')

    after = apply_import(target, parse_export(text), merge=False, clean_settings=clean_settings)
    assert after == Summary(hands=2, stamps=2, answers=8)
    assert read_history(target) == read_history(source)
    assert read_stamps(target) == read_stamps(source)
    assert read_decks(target) == read_decks(source)
    assert DRILL_PREFIX + "han" not in target.values                 # ファイルに無い種類の記録は、消える
    assert json.loads(target.values[SETTINGS_NAME])["target"] == "sanshoku"
    assert target.values[HAND_NAME] == '{"keep":"me"}'               # 打っている局には触れない


def test_merge_keeps_both_sides_without_double_counting():
    source = filled_store()
    text = export_text(source, time=NOW, app_version="1")
    target = FakeStore()
    target.set(HISTORY_NAME, history_text([record(NOW, 1), record(NOW + 999, 77, yaku=("tanyao",))]))
    target.set(STAMPS_NAME, dump_stamps({"riichi": Stamp(3, NOW - 50, NOW + 5, 0), "tanyao": Stamp(1, NOW + 999, NOW + 999, 1)}))
    target.set(DRILL_PREFIX + "table", dump_deck(Deck({"cr:30:1": Card(2, NOW + 9999, 2, 1, NOW + 50), "cr:30:2": Card(2, NOW, 1, 1, NOW)}, 7, 4)))
    target.set(SETTINGS_NAME, json.dumps({**DEFAULT_SETTINGS, "deal": 25}))

    after = apply_import(target, parse_export(text), merge=True, clean_settings=clean_settings)
    assert [r.seed for r in read_history(target)] == [1, 2, 77]      # 同じ局は 1 つに。古い順
    stamps = read_stamps(target)
    assert stamps["riichi"] == Stamp(3, NOW - 50, NOW + 5, 1)        # 回数は多いほう（足さない）
    assert set(stamps) == {"riichi", "sanshoku", "tanyao"}
    table = read_deck(target, "table")
    assert table.cards["cr:30:1"].box == 2                           # あとで答えたほうの状態
    assert "cr:30:2" in table.cards and (table.answered, table.right) == (7, 4)
    assert read_deck(target, "score").answered == 5
    assert json.loads(target.values[SETTINGS_NAME])["deal"] == 25    # 設定は、いまのまま
    assert after == Summary(hands=3, stamps=3, answers=12)

    again = apply_import(target, parse_export(text), merge=True, clean_settings=clean_settings)
    assert again == after                                            # 同じファイルを 2 回読み込んでも、増えない


def test_file_without_stamps_gets_them_from_its_history():
    text = export_text(FakeStore({HISTORY_NAME: history_text([record(NOW, 1, yaku=("pinfu",))])}), time=NOW, app_version="1")
    data = json.loads(text)
    del data["stamps"]
    parsed = parse_export(json.dumps(data))
    assert summary_of_export(parsed).stamps == 1
    target = FakeStore()
    apply_import(target, parsed, merge=False)
    assert load_stamps(target.values[STAMPS_NAME]) == {"pinfu": Stamp(1, NOW, NOW, 1)}


def test_settings_in_a_file_are_checked_before_use():
    data = json.loads(export_text(filled_store(), time=NOW, app_version="1"))
    data["practice"]["settings"] = {"deal": 9999, "hint": "bad", "target": "toitoi", "level": 3}
    target = FakeStore()
    apply_import(target, parse_export(json.dumps(data)), merge=False, clean_settings=clean_settings)
    saved = json.loads(target.values[SETTINGS_NAME])
    assert saved == {**DEFAULT_SETTINGS, "level": 3}                 # おかしな値は、初期値に戻す


def test_clear_all_removes_progress_but_keeps_the_hand_and_settings():
    store = filled_store()
    clear_all(store)
    assert set(store.values) == {SETTINGS_NAME, HAND_NAME}
    assert summary_of_store(store) == Summary(0, 0, 0)
    assert load_history(store.get(HISTORY_NAME)) == [] and load_deck(store.get(DRILL_PREFIX + "table")) == Deck()


# ---------------------------------------------------------------- Phase 5：点数の申告の記録と、カリキュラムの進み具合


def test_declare_records_and_curriculum_travel_in_the_file():
    """書き出したファイルに、点数の申告の記録とカリキュラムの進み具合が入り、置き換え・合わせのどちらでも元に戻る"""
    source = filled_store()
    write_deck(source, DECLARE, Deck().review("c-r-30-3", True, NOW).review("p-t-40-2", False, NOW + 5))
    progress = Progress().with_result("step1", 9, 10, NOW + 10).with_result("step2", 6, 10, NOW + 20)
    write_curriculum(source, progress)
    text = export_text(source, time=NOW + 30, app_version="1")
    data = parse_export(text)
    assert set(data.drills) == {"table", "score", DECLARE} and data.curriculum is not None
    assert summary_of_export(data) == summary_of_store(source) == Summary(hands=2, stamps=2, answers=8, declares=2)

    replaced = FakeStore()
    apply_import(replaced, data, merge=False, clean_settings=clean_settings)
    assert read_deck(replaced, DECLARE) == read_deck(source, DECLARE)
    assert read_curriculum(replaced) == progress and read_curriculum(replaced).passed("step1")
    assert not read_curriculum(replaced).passed("step2")

    merged = FakeStore()
    write_curriculum(merged, Progress().with_result("step2", 8, 10, NOW + 99))           # こちらでは、2 つ目の段階にも合格している
    after = apply_import(merged, data, merge=True, clean_settings=clean_settings)
    both = read_curriculum(merged)
    assert both.passed("step1") and both.passed("step2") and both.record("step2").last == 8   # 合格は残し、最後の結果は新しいほう
    assert after.declares == 2 and read_deck(merged, DECLARE).answered == 2

    clear_all(merged)
    assert CURRICULUM_NAME not in merged.values and read_deck(merged, DECLARE) == Deck()   # すべて消すと、どちらも消える

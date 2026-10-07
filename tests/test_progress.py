"""進み具合の記録（スタンプ、ファイルへの書き出し・読み込み）のテスト"""
import json

import pytest

from engine.content import yaku_pages
from engine.progress import (
    APP_ID,
    EXPORT_VERSION,
    MAX_EXPORT_CHARS,
    Stamp,
    add_stamps,
    build_export,
    completion,
    dump_stamps,
    load_stamps,
    merge_history,
    merge_stamps,
    parse_export,
    stamp_keys,
    stamps_from_data,
    stamps_from_history,
)
from engine.records import MAX_RECORDS, HandRecord

NOW = 1_800_000_000


def record(time=NOW, seed=1, *, win=True, yaku=("riichi", "pinfu"), deal=0, draw=0, target="", made=False) -> HandRecord:
    return HandRecord(
        time=time, seed=seed, deal=deal, draw=draw, hinted=False, win=win, turn=9, riichi=True, tenpai=True,
        points=2000 if win else 0, han=2 if win else 0, fu=30 if win else 0, yaku=tuple(yaku) if win else (),
        decisions=8, best=6, target=target, made=made,
    )


# ---------------------------------------------------------------- スタンプ


def test_stamp_keys_map_yaku_to_book_pages():
    assert stamp_keys(["riichi", "pinfu"]) == ["riichi", "pinfu"]
    # 役牌はどれも 1 ページ。同じページは 1 回だけ
    assert stamp_keys(["yakuhai_haku", "yakuhai_seat", "tanyao"]) == ["yakuhai", "tanyao"]
    assert stamp_keys(["kokushi_13"]) == ["kokushi"]
    assert stamp_keys(["suuankou_tanki"]) == ["suuankou"]
    assert stamp_keys(["junsei_chuuren"]) == ["chuuren"]
    assert stamp_keys(["no_such_yaku"]) == []


def test_every_yaku_has_a_page_to_stamp():
    from engine.yaku_table import YAKU

    for key in YAKU:
        assert len(stamp_keys([key])) == 1, key


def test_add_stamps_counts_and_reports_first_time_pages():
    stamps, fresh = add_stamps({}, ["riichi", "pinfu"], time=NOW, plain=False)
    assert fresh == ["riichi", "pinfu"]
    assert stamps["riichi"] == Stamp(1, NOW, NOW, 0)

    stamps, fresh = add_stamps(stamps, ["riichi", "tanyao"], time=NOW + 60, plain=True)
    assert fresh == ["tanyao"]
    assert stamps["riichi"] == Stamp(2, NOW, NOW + 60, 1)
    assert stamps["pinfu"] == Stamp(1, NOW, NOW, 0)
    assert stamps["tanyao"] == Stamp(1, NOW + 60, NOW + 60, 1)


def test_add_stamps_does_not_change_the_given_book():
    before = {"riichi": Stamp(1, NOW, NOW)}
    after, _ = add_stamps(before, ["riichi"], time=NOW + 1, plain=False)
    assert before == {"riichi": Stamp(1, NOW, NOW)}
    assert after["riichi"].count == 2


def test_stamps_from_history_uses_wins_only_and_marks_plain_hands():
    records = [
        record(NOW + 20, 2, yaku=("riichi", "menzen_tsumo"), deal=75, draw=75),
        record(NOW + 10, 1, yaku=("riichi", "pinfu")),
        record(NOW + 30, 3, win=False),
    ]
    stamps = stamps_from_history(records)
    assert set(stamps) == {"riichi", "pinfu", "menzen_tsumo"}
    assert stamps["riichi"] == Stamp(2, NOW + 10, NOW + 20, 1)      # 時刻の古い順に数える。補正なしは 1 回
    assert stamps["menzen_tsumo"].plain == 0


def test_merge_stamps_takes_the_larger_count_not_the_sum():
    mine = {"riichi": Stamp(5, NOW, NOW + 500, 2), "pinfu": Stamp(1, NOW + 9, NOW + 9, 0)}
    theirs = {"riichi": Stamp(3, NOW - 100, NOW + 800, 3), "tanyao": Stamp(2, NOW, NOW + 1, 1)}
    merged = merge_stamps(mine, theirs)
    assert merged["riichi"] == Stamp(5, NOW - 100, NOW + 800, 3)
    assert merged["pinfu"] == mine["pinfu"]
    assert merged["tanyao"] == theirs["tanyao"]
    assert merge_stamps(mine, mine) == mine                          # 同じファイルを 2 回読み込んでも増えない


def test_completion_counts_pages():
    pages = yaku_pages()
    done = completion({"riichi": Stamp(1, NOW, NOW), "pinfu": Stamp(2, NOW, NOW)})
    assert (done.done, done.total) == (2, len(pages))
    assert done.reachable == sum(1 for page in pages if page.solo)
    assert 0 < done.reachable < done.total
    assert done.rate == pytest.approx(2 / len(pages))
    assert completion({}).rate == 0.0


def test_stamps_round_trip_and_broken_entries_are_skipped():
    stamps = {"riichi": Stamp(3, NOW, NOW + 5, 1), "kokushi": Stamp(1, NOW, NOW, 0)}
    assert load_stamps(dump_stamps(stamps)) == stamps
    assert load_stamps(None) is None
    assert load_stamps("") is None
    assert load_stamps("{broken") is None
    assert load_stamps("[1, 2]") is None
    assert load_stamps("{}") == {}                                   # 記録はあるが、まだ 1 つも無い
    data = {
        "riichi": {"n": 2, "first": NOW, "last": NOW + 1, "plain": 9},      # plain は回数を超えない
        "pinfu": {"n": 0, "first": NOW},
        "tanyao": {"n": 1},
        "ittsu": {"n": True, "first": NOW},
        "chanta": "x",
        "unknown_page": {"n": 1, "first": NOW},
        "honitsu": {"n": 1, "first": NOW + 9, "last": NOW},                 # last は first より前にならない
    }
    assert stamps_from_data(data) == {"riichi": Stamp(2, NOW, NOW + 1, 2), "honitsu": Stamp(1, NOW + 9, NOW + 9, 0)}
    assert stamps_from_data(None) == {}


# ---------------------------------------------------------------- 成績の合わせ方


def test_merge_history_drops_duplicates_and_sorts_by_time():
    a, b, c = record(NOW, 1), record(NOW + 10, 2), record(NOW + 20, 3)
    merged = merge_history([a, c], [b, a])
    assert merged == [a, b, c]
    # 同じ時刻・同じ番号でも、狙った役が違えば別の局
    aimed = record(NOW, 1, target="sanshoku")
    assert merge_history([a], [aimed]) == [a, aimed]


def test_merge_history_keeps_the_newest_records_within_the_limit():
    mine = [record(NOW + i, i) for i in range(MAX_RECORDS)]
    theirs = [record(NOW - 1 - i, 10_000 + i) for i in range(10)]
    merged = merge_history(mine, theirs)
    assert len(merged) == MAX_RECORDS
    assert merged[-1] == mine[-1] and merged[0].time == NOW


# ---------------------------------------------------------------- 書き出し・読み込み


def export_text(**changes) -> str:
    values = {
        "settings": {"deal": 50, "draw": 25, "hint": "after"},
        "history": [record(NOW, 1), record(NOW + 5, 2, win=False), record(NOW + 9, 3, target="sanshoku", made=True, yaku=("sanshoku",))],
        "stamps": {"riichi": Stamp(1, NOW, NOW, 1), "sanshoku": Stamp(1, NOW + 9, NOW + 9, 0)},
        "drills": {"table": {"v": 1, "n": 3, "right": 2, "cards": {"c:r:30:3": [0, NOW + 600, 1, 0, NOW]}}},
        "time": NOW + 100,
        "app_version": "0.4.0",
    }
    values.update(changes)
    return build_export(**values)


def test_export_round_trip():
    text = export_text()
    data = json.loads(text)
    assert (data["app"], data["kind"], data["v"]) == (APP_ID, "progress", EXPORT_VERSION)
    parsed = parse_export(text)
    assert parsed.exported == NOW + 100
    assert parsed.app_version == "0.4.0"
    assert parsed.settings == {"deal": 50, "draw": 25, "hint": "after"}
    assert [r.seed for r in parsed.history] == [1, 2, 3]
    assert parsed.history[2].target == "sanshoku" and parsed.history[2].made
    assert parsed.stamps == {"riichi": Stamp(1, NOW, NOW, 1), "sanshoku": Stamp(1, NOW + 9, NOW + 9, 0)}
    assert parsed.drills["table"]["n"] == 3
    assert parsed.skipped == 0
    assert parsed.parts == ("settings", "history", "stamps", "drills")


def test_export_is_readable_text_and_small():
    text = export_text(history=[record(NOW + i, i) for i in range(MAX_RECORDS)])
    assert "\n" in text                                  # 人が読める形（字下げあり）
    assert "立直" not in text and "riichi" in text      # 役は鍵で残す
    assert len(text) < MAX_EXPORT_CHARS / 4


def test_export_without_optional_parts():
    parsed = parse_export(export_text(settings=None, drills=None, history=[], stamps={}))
    assert parsed.settings is None and parsed.drills is None
    assert parsed.history == [] and parsed.stamps == {}
    assert parsed.parts == ("history", "stamps")


@pytest.mark.parametrize(
    "text, word",
    [
        ("", "空"),
        ("   \n", "空"),
        ("not json at all", "JSON"),
        ("[" * 100000, "JSON"),
        ("[1, 2, 3]", "このアプリ"),
        ('{"app": "other", "kind": "progress", "v": 1}', "このアプリ"),
        ('{"app": "mjdojo", "kind": "hand", "v": 1}', "このアプリ"),
        ('{"app": "mjdojo", "kind": "progress"}', "版"),
        ('{"app": "mjdojo", "kind": "progress", "v": true}', "版"),
        ('{"app": "mjdojo", "kind": "progress", "v": 0}', "版"),
        ('{"app": "mjdojo", "kind": "progress", "v": 999}', "新しい版"),
        ("x" * (MAX_EXPORT_CHARS + 1), "大きすぎ"),
    ],
)
def test_bad_files_are_refused_with_a_reason(text, word):
    with pytest.raises(ValueError) as error:
        parse_export(text)
    assert word in str(error.value)


def test_parse_export_rejects_non_text():
    with pytest.raises(ValueError):
        parse_export(None)  # type: ignore[arg-type]


def test_broken_parts_are_skipped_one_by_one():
    data = json.loads(export_text())
    data["practice"]["history"]["hands"].insert(1, {"t": "yesterday"})
    data["practice"]["history"]["hands"].append("junk")
    data["practice"]["settings"] = "loud"
    data["stamps"]["pinfu"] = {"n": -1, "first": NOW}
    data["drills"] = [1, 2]
    data["exported"] = "now"
    data["app_version"] = 7
    parsed = parse_export(json.dumps(data))
    assert [r.seed for r in parsed.history] == [1, 2, 3]
    assert parsed.skipped == 2
    assert parsed.settings is None and parsed.drills is None
    assert set(parsed.stamps) == {"riichi", "sanshoku"}
    assert parsed.exported == 0 and parsed.app_version == ""
    assert parsed.parts == ("history", "stamps")


def test_history_can_also_be_a_plain_list_and_unknown_versions_are_ignored():
    data = json.loads(export_text())
    rows = data["practice"]["history"]["hands"]
    data["practice"]["history"] = rows
    assert len(parse_export(json.dumps(data)).history) == 3
    data["practice"]["history"] = {"v": 99, "hands": rows}
    parsed = parse_export(json.dumps(data))
    assert parsed.history == [] and "history" not in parsed.parts
    data["practice"] = None
    assert parse_export(json.dumps(data)).history == []

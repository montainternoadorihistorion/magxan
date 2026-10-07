"""記録と保存のページを、画面なしで動かして確かめる（まとめ、ファイルへの書き出し、読み込み、消去）。

ファイルを選ぶ欄は、ここでは動かせない（文字を貼り付ける欄で、同じ読み込みの流れを確かめる）。
"""
from __future__ import annotations

import json
from pathlib import Path

from html_helpers import page_html, page_parts, text_of
from streamlit.testing.v1 import AppTest

from engine.progress import Stamp, dump_stamps, parse_export
from engine.records import HandRecord, dump_record, load_history
from engine.srs import Card, Deck, dump_deck, load_deck
from ui.components.browser_store import initial_state
from ui.practice_session import DEFAULT_SETTINGS
from ui.progress_store import DRILL_PREFIX, HAND_NAME, HISTORY_NAME, SETTINGS_NAME, STAMPS_NAME
from ui.ruby import missing_ruby
from ui.version import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
NOW = 1_760_000_000
MERGE, REPLACE = "いまの記録と合わせる", "ファイルの中身で置き換える"


def record(time: int, seed: int, *, yaku=("riichi",), win=True, target="", made=False) -> HandRecord:
    return HandRecord(
        time=time, seed=seed, deal=0, draw=0, hinted=False, win=win, turn=9, riichi=True, tenpai=True,
        points=1300 if win else 0, han=1 if win else 0, fu=40 if win else 0, yaku=tuple(yaku) if win else (),
        decisions=8, best=7, target=target, made=made,
    )


def history_text(records) -> str:
    return "[" + ",".join(dump_record(r) for r in records) + "]"


def filled() -> dict[str, str]:
    """ブラウザに残っている進み具合（成績 2 局・スタンプ 2 役・ドリル 8 回）と、打っている途中の局・設定"""
    return {
        SETTINGS_NAME: json.dumps({**DEFAULT_SETTINGS, "deal": 50}),
        HISTORY_NAME: history_text([record(NOW, 1), record(NOW + 60, 2, yaku=("sanshoku",), target="sanshoku", made=True)]),
        STAMPS_NAME: dump_stamps({"riichi": Stamp(1, NOW, NOW, 1), "sanshoku": Stamp(1, NOW + 60, NOW + 60, 1)}),
        DRILL_PREFIX + "table": dump_deck(Deck({"cr:30:1": Card(0, NOW + 600, 1, 0, NOW)}, 3, 2)),
        DRILL_PREFIX + "score": dump_deck(Deck({}, 5, 5)),
        HAND_NAME: '{"v":1}',
    }


def open_records(known: dict[str, str] | None = None, *, storage: bool = True) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if storage:
        at.session_state[STORE_STATE] = initial_state(known or {})
    at.switch_page("views/records.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at: AppTest) -> str:
    return text_of(page_html(at))


def known(at: AppTest) -> dict[str, str]:
    """ブラウザに保存される（されている）内容"""
    return at.session_state[STORE_STATE]["known"]


def exported(at: AppTest) -> str:
    """「ファイルに保存する」で落ちてくる文字（コピー用の部品にも、同じ文字を渡している）"""
    copy = next(c for c in at.get("bidi_component") if c.proto.component_name == "mjdojo_copy_button")
    return json.loads(copy.proto.json)["text"]


def paste(at: AppTest, text: str) -> AppTest:
    next(area for area in at.text_area if area.label == "コピーしておいた記録の文字").set_value(text).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------- 開く・まとめ


def test_page_waits_for_browser_storage_and_can_open_without_it():
    at = open_records(storage=False)
    assert at.title[0].value == "記録と保存" and any("確認しています" in i.value for i in at.info)
    click(at, "保存を使わずに開く")
    assert any("記録をブラウザに残せません" in w.value for w in at.warning)
    assert "まだ記録がありません" in page_text(at)


def test_empty_records():
    at = open_records()
    text = page_text(at)
    assert "まだ記録がありません" in text and "入るもの：成績 0 局・スタンプ 0 役・ドリル 0 回ぶんの記録" in text
    assert not at.warning and not at.error
    progress = at.get("progress")
    assert len(progress) == 1 and progress[0].proto.text.startswith("スタンプ 0 / ")
    assert missing_ruby(page_parts(at)) == []


def test_summary_of_existing_records():
    at = open_records(filled())
    text = page_text(at)
    assert "入るもの：成績 2 局・スタンプ 2 役・ドリル 8 回ぶんの記録" in text
    assert "三色同順111（100%）" in text                         # 役指定練習の成績
    assert "3 回答えて、正答率 67%" in text and "5 回答えて、正答率 100%" in text and "まだ答えていない" in text
    assert at.get("progress")[0].proto.text.startswith("スタンプ 2 / ")
    assert missing_ruby(page_parts(at)) == []


def test_export_holds_everything_but_the_hand_in_progress():
    at = open_records(filled())
    data = parse_export(exported(at))
    assert data.app_version == APP_VERSION and data.exported > NOW
    assert [r.seed for r in data.history] == [1, 2] and set(data.stamps) == {"riichi", "sanshoku"}
    assert data.settings["deal"] == 50 and set(data.drills) == {"table", "score"}
    raw = json.loads(exported(at))
    assert set(raw) == {"app", "kind", "v", "exported", "app_version", "practice", "stamps", "drills"}
    assert set(raw["practice"]) == {"settings", "history"} and "practice.hand" not in exported(at)      # 打っている途中の局は入れない
    download = at.get("download_button")
    assert len(download) == 1 and download[0].proto.label == "進み具合をファイルに保存する"


# ---------------------------------------------------------------- 読み込み


def test_import_merges_with_the_current_records():
    theirs = open_records({
        HISTORY_NAME: history_text([record(NOW + 60, 2, yaku=("sanshoku",), target="sanshoku", made=True), record(NOW + 500, 3, yaku=("pinfu",))]),
        STAMPS_NAME: dump_stamps({"pinfu": Stamp(4, NOW, NOW + 500, 0), "riichi": Stamp(3, NOW - 10, NOW, 0)}),
        DRILL_PREFIX + "han": dump_deck(Deck({"h:riichi": Card(2, NOW + 9000, 1, 1, NOW)}, 1, 1)),
    })
    text = exported(theirs)

    at = paste(open_records(filled()), text)
    card = page_text(at)
    assert "入っているもの：成績 2 局・スタンプ 2 役・ドリル 1 回" in card and "保存した日時：" in card
    assert at.radio[0].options == [MERGE, REPLACE] and at.radio[0].value == MERGE
    assert any("多いほうを採ります（足しません）" in c.value for c in at.caption)
    at.session_state["pr_state"] = "一人練習の控え"
    at.session_state["dr_kind"] = "table"
    click(at, "読み込む")

    assert any(s.value == "読み込みました（いまの記録と合わせた）。成績 3 局・スタンプ 3 役・ドリル 9 回。" for s in at.success)
    saved = known(at)
    assert [r.seed for r in load_history(saved[HISTORY_NAME])] == [1, 2, 3]          # 同じ局は 1 つに
    stamps = json.loads(saved[STAMPS_NAME])
    assert set(stamps) == {"riichi", "sanshoku", "pinfu"} and stamps["riichi"]["n"] == 3      # 回数は、多いほうを採る
    assert load_deck(saved[DRILL_PREFIX + "han"]).answered == 1 and load_deck(saved[DRILL_PREFIX + "table"]).answered == 3
    assert json.loads(saved[SETTINGS_NAME])["deal"] == 50 and saved[HAND_NAME] == '{"v":1}'     # 設定と、途中の局はそのまま
    # ほかのページが持っている控えは捨てる（次に開いたとき、読み込んだ記録から読み直す）
    assert "pr_state" not in at.session_state and "dr_kind" not in at.session_state
    # 読み込んだあと、貼り付けの欄は空に戻る
    assert all(not area.value for area in at.text_area) and "入るもの：成績 3 局・スタンプ 3 役・ドリル 9 回ぶんの記録" in page_text(at)


def test_import_can_replace_everything():
    theirs = open_records({
        SETTINGS_NAME: json.dumps({**DEFAULT_SETTINGS, "deal": 100, "hint": "off"}),
        HISTORY_NAME: history_text([record(NOW + 500, 3, yaku=("pinfu",))]),
        STAMPS_NAME: dump_stamps({"pinfu": Stamp(4, NOW, NOW + 500, 0)}),
    })
    at = paste(open_records(filled()), exported(theirs))
    at.radio[0].set_value(REPLACE).run()
    assert any("いまの記録（成績 2 局・スタンプ 2 役・ドリル 8 回）は消えて" in c.value for c in at.caption)
    click(at, "読み込む")
    assert any(s.value == "読み込みました（ファイルの中身で置き換えた）。成績 1 局・スタンプ 1 役・ドリル 0 回。" for s in at.success)
    saved = known(at)
    assert [r.seed for r in load_history(saved[HISTORY_NAME])] == [3] and set(json.loads(saved[STAMPS_NAME])) == {"pinfu"}
    assert DRILL_PREFIX + "table" not in saved and DRILL_PREFIX + "score" not in saved
    settings = json.loads(saved[SETTINGS_NAME])
    assert settings["deal"] == 100 and settings["hint"] == "off"
    assert saved[HAND_NAME] == '{"v":1}'                    # 打っている途中の局は、そのまま


def test_import_rejects_text_that_is_not_ours():
    for text in ("これはファイルの中身ではない", "[1, 2, 3]", json.dumps({"app": "ほかのアプリ", "kind": "progress", "v": 1})):
        at = paste(open_records(filled()), text)
        assert at.error and not at.radio and "読み込む" not in [b.label for b in at.button], text
    assert known(at)[HISTORY_NAME] == filled()[HISTORY_NAME]


def test_import_skips_broken_records_and_says_so():
    data = json.loads(exported(open_records(filled())))
    data["practice"]["history"]["hands"].append({"こわれた": "記録"})
    at = paste(open_records(), json.dumps(data, ensure_ascii=False))
    assert "読めなかった成績が 1 件あった（その記録は飛ばす）。" in page_text(at)
    click(at, "読み込む")
    assert len(load_history(known(at)[HISTORY_NAME])) == 2


def test_records_can_be_carried_without_browser_storage():
    """ブラウザに保存できない端末でも、開いているあいだは記録を持ち、ファイルに出せる"""
    text = exported(open_records(filled()))
    at = open_records(storage=False)
    click(at, "保存を使わずに開く")
    click(paste(at, text), "読み込む")
    assert any("成績 2 局・スタンプ 2 役・ドリル 8 回" in s.value for s in at.success)
    assert "入るもの：成績 2 局・スタンプ 2 役・ドリル 8 回ぶんの記録" in page_text(at)
    assert at.session_state[STORE_STATE]["ops"] == [] and at.session_state[STORE_STATE]["known"] is None
    again = parse_export(exported(at))
    assert [r.seed for r in again.history] == [1, 2] and set(again.stamps) == {"riichi", "sanshoku"}


# ---------------------------------------------------------------- 消す


def test_clear_removes_progress_but_keeps_the_hand_and_settings():
    at = open_records(filled())
    at.session_state["dr_item"] = "cr:30:1"
    click(at, "すべて消す")
    assert any(s.value == "成績・スタンプ・ドリルの記録を消しました。" for s in at.success)
    saved = known(at)
    assert set(saved) == {SETTINGS_NAME, HAND_NAME} and "dr_item" not in at.session_state
    assert "入るもの：成績 0 局・スタンプ 0 役・ドリル 0 回ぶんの記録" in page_text(at)

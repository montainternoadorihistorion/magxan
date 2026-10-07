"""一人練習のページを、画面なしで動かして確かめる。

牌をタップする部品はブラウザの中で動くので、ここでは動かせない（操作の流れは test_practice_session.py、
実際の画面は tools/e2e_practice_check.py で確かめる）。ここで見るのは、いろいろな局面でページが正しく描かれることと、
ボタンや設定の入力欄の動き。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from html_helpers import headings_of, page_html, ruby_terms
from practice_helpers import nearest_discard
from streamlit.testing.v1 import AppTest

from engine import practice
from engine.coach import analyze
from engine.luck import LuckSettings
from engine.practice import Outcome, PracticeConfig
from engine.records import HandRecord, dump_record, load_history
from ui.components.browser_store import initial_state
from ui.practice_session import DEFAULT_SETTINGS, HAND_NAME, HISTORY_NAME, SETTINGS_NAME

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
ALL_STEPS = ["① 手牌の読み方", "② 役", "③ ドラ", "④ 符", "⑤ 点数", "⑥ 誰がいくら払うか", "⑦ 卓での申告"]
TABLE = "受け入れ表（切る牌と、手が進む牌）"
LAYOUT = "手の分け方（分解図）"
REVIEW = "この局の振り返り（切った牌の評価）"


# ---------------------------------------------------------------- 道具


def open_practice(known: dict[str, str] | None = None, *, skip: bool = False) -> AppTest:
    """一人練習のページを開く。known はブラウザに残っていた保存内容"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if not skip:
        at.session_state[STORE_STATE] = initial_state(known or {})
    at.switch_page("views/practice.py").run()
    if skip:
        next(b for b in at.button if b.label == "保存を使わずに始める").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at: AppTest) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", page_html(at)))


def steps(at: AppTest) -> list[str]:
    """あがりの解説の見出し（「ルールによって変わるところ」は、出る手と出ない手があるので除く）"""
    return [title for title in headings_of(page_html(at)) if title != "ルールによって変わるところ"]


def history_json(records) -> str:
    """ブラウザに残っている成績（記録の配列）"""
    return "[" + ",".join(dump_record(r) for r in records) + "]"


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def labels(at: AppTest) -> list[str]:
    return [e.label for e in at.expander]


def stored(at: AppTest, name: str) -> str | None:
    """ブラウザに保存される（されている）内容"""
    return at.session_state[STORE_STATE]["known"].get(name)


def play(config: PracticeConfig, stop) -> practice.PracticeState:
    """おすすめどおりに打ち、stop(state) が真になったところ（または局の終わり）で止める"""
    state = practice.start(config)
    while not state.finished and not stop(state):
        if state.can_tsumo:
            return state
        state = practice.apply(state, practice.discard(analyze(practice.position_of(state)).pick.tile))
    return state


def find(settings: LuckSettings, stop, seeds=range(300)) -> practice.PracticeState:
    for seed in seeds:
        state = play(PracticeConfig(seed=seed, luck=settings), stop)
        if not state.finished and stop(state):
            return state
    raise AssertionError("局面が見つからない")


def hand_json(state: practice.PracticeState, *, counted: bool = True, hinted: bool = False) -> str:
    return json.dumps({"v": 1, "save": practice.to_save(state), "counted": counted, "hinted": hinted})


def settings_json(**values) -> str:
    return json.dumps({**DEFAULT_SETTINGS, **values})


def exhausted_state() -> practice.PracticeState:
    state = practice.start(PracticeConfig(seed=1))
    while not state.finished:
        state = practice.apply(state, practice.discard(state.drawn))
    return state


# ---------------------------------------------------------------- 開く


def test_page_waits_for_browser_storage_then_starts_without_it():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    at.switch_page("views/practice.py").run()
    assert not at.exception and at.title[0].value == "一人練習"
    assert any("確認しています" in i.value for i in at.info) and "pr_state" not in at.session_state
    click(at, "保存を使わずに始める")
    assert "pr_state" in at.session_state and "ツキ補正：配牌 75・ツモ 75" in page_text(at)
    assert any("保存を使っていません" in c.value for c in at.caption)


def test_first_visit_starts_a_hand_with_hints():
    at = open_practice()
    state = at.session_state["pr_state"]
    text = page_text(at)
    assert state.turn == 1 and state.config.luck == LuckSettings(75, 75)
    assert "1 巡目（残りツモ 17 回）" in text and "ドラ表示牌" in text and "河（切った牌）：まだ切っていません" in text
    assert "おすすめ：" in text or "聴牌にとれます" in text or "あがりの形です" in text
    assert labels(at)[-3:] == ["設定（ツキ補正・コーチ）", "成績", "このページの使い方"]
    assert any(f"局の番号 {state.config.seed}" in c.value for c in at.caption)
    # 始めた局が、ブラウザに保存される
    assert json.loads(stored(at, HAND_NAME))["save"] == practice.to_save(state)
    assert json.loads(stored(at, SETTINGS_NAME)) == DEFAULT_SETTINGS


def test_saved_hand_is_resumed():
    state = find(LuckSettings(50, 50), lambda s: s.turn == 6)
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(deal=50, draw=50)})
    assert at.session_state["pr_state"] == state
    text = page_text(at)
    assert "6 巡目（残りツモ 12 回）" in text and "ツキ補正：配牌 50・ツモ 50" in text and "河（切った牌） 5 枚" in text
    assert "5 巡目の打牌" in text                                   # 前の打牌の評価も、作り直して出す
    assert any("再開したものです" in c.value for c in at.caption)


def test_broken_storage_starts_a_fresh_hand():
    at = open_practice({HAND_NAME: "こわれている", SETTINGS_NAME: "{だめ", HISTORY_NAME: "[]"})
    assert at.session_state["pr_state"].turn == 1 and at.session_state["pr_settings"] == DEFAULT_SETTINGS
    assert not any("再開したもの" in c.value for c in at.caption)


DEEP = "[" * 100_000        # 入れ子が深すぎて、JSON として読めない


@pytest.mark.parametrize(
    "hand",
    [
        '{"v":1,"save":{"v":1,"config":"x","actions":[]},"counted":true,"hinted":false}',
        '{"v":1,"save":{"v":1,"config":{"seed":4,"luck":[1]},"actions":[]},"counted":true,"hinted":false}',
        '{"v":1,"save":{"v":1,"config":{"seed":4,"rules":{"aka_dora":[]}},"actions":[]},"counted":true,"hinted":false}',
        '{"v":1,"save":{"v":1,"config":{"seed":Infinity},"actions":[]},"counted":true,"hinted":false}',
        DEEP,
    ],
)
def test_saved_data_of_a_wrong_shape_never_breaks_the_page(hand):
    """ブラウザに残っているデータの型がおかしくても、ページは例外を出さずに、新しい局から始まる"""
    at = open_practice({HAND_NAME: hand, SETTINGS_NAME: DEEP, HISTORY_NAME: DEEP})
    assert at.session_state["pr_state"].turn == 1 and at.session_state["pr_resumed"] is False
    assert at.session_state["pr_settings"] == DEFAULT_SETTINGS and at.session_state["pr_history"] == []
    click(at, "この局をやめて、新しい局を始める")                       # そのあとも、ふつうに使える
    assert json.loads(stored(at, HAND_NAME))["save"]["actions"] == []


def test_reopening_after_a_long_disconnect_tells_the_player():
    """ページを開いたまま通信が長く切れると、サーバー側の状態は消える。続きから再開したことを知らせる"""
    state = find(LuckSettings(50, 50), lambda s: s.turn == 6)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    at.session_state[STORE_STATE] = {**initial_state({HAND_NAME: hand_json(state)}), "again": True}
    at.switch_page("views/practice.py").run()
    assert not at.exception and at.session_state["pr_state"] == state
    assert [t.value for t in at.toast] == ["通信が切れていたので、続きから再開しました。もう一度操作してください。"]
    at.run()
    assert not at.toast                                                 # 案内は、再開したときの 1 回だけ
    assert not open_practice({HAND_NAME: hand_json(state)}).toast       # ふつうに開いたときは出さない


def test_objects_are_rebuilt_when_the_code_generation_changes():
    """アプリを更新したあとも、打っていた局はそのまま続けられる（古い型のオブジェクトを、控えから作り直す）"""
    state = find(LuckSettings(50, 50), lambda s: s.turn == 6)
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(deal=50, draw=50)})
    before = at.session_state["pr_state"]
    at.session_state["pr_generation"] = -1                              # 前の世代のコードが作ったセッション、という状況
    at.run()
    assert not at.exception
    after = at.session_state["pr_state"]
    assert after == before and after is not before and at.session_state["pr_generation"] == 0
    assert "6 巡目（残りツモ 12 回）" in page_text(at) and len(at.session_state["pr_decisions"]) == 5


# ---------------------------------------------------------------- 打っている途中の表示


def test_hint_before_shows_table_and_diagram():
    state = find(LuckSettings(50, 50), lambda s: s.turn == 4 and not s.can_tsumo and not s.riichi_discards)
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(level=3)})
    text = page_text(at)
    assert TABLE in labels(at) and LAYOUT in labels(at)
    assert "おすすめ：" in text and "のままの切り方（受け入れの広い順）" in text
    assert "次のツモで引く確率 ＝" in text and "向聴数 ＝" in text
    assert "役や打点は見ていない" in text


def test_tenpai_shows_waits_and_scores():
    state = find(LuckSettings(75, 75), lambda s: bool(s.riichi_discards) and not s.can_tsumo)
    at = open_practice({HAND_NAME: hand_json(state)})
    text = page_text(at)
    assert "聴牌したときの待ちと点数" in labels(at)
    assert "聴牌にとれます" in text and "リーチもできます" in text and "リーチしない" in text and "リーチする" in text


def test_hint_after_shows_the_previous_verdict_instead_of_advice():
    state = find(LuckSettings(50, 50), lambda s: s.turn == 4)
    worst = analyze(practice.position_of(state)).candidates[-1]
    state = practice.apply(state, practice.discard(worst.tile))
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(hint="after")})
    text = page_text(at)
    assert "おすすめ：" not in text and TABLE not in labels(at) and LAYOUT not in labels(at)
    assert "おすすめは" in text and "4 巡目の打牌" in text
    assert "さっきの局面の受け入れ表（答え合わせ）" in labels(at) and "点線の枠：切った牌" in text

    fresh = open_practice({SETTINGS_NAME: settings_json(hint="after")})
    assert "切ったあとに、答え合わせを表示します" in page_text(fresh)


def test_showing_a_hint_marks_the_hand_as_hinted():
    """打つ前のヒントを 1 回でも出した局は、成績で「ヒントあり」に分ける。出していなければ分けない"""
    for hint, expected in (("before", True), ("after", False), ("off", False)):
        at = open_practice({SETTINGS_NAME: settings_json(hint=hint)})
        assert at.session_state["pr_hinted"] is expected
        assert json.loads(stored(at, HAND_NAME))["hinted"] is expected
    # 途中でヒントを出すように変えたら、その局は「ヒントあり」。あとで消しても戻らない
    at.button_group(key="pr_w_hint").set_value("打つ前に表示").run()
    assert at.session_state["pr_hinted"] is True
    at.button_group(key="pr_w_hint").set_value("オフ").run()
    assert at.session_state["pr_hinted"] is True and json.loads(stored(at, HAND_NAME))["hinted"] is True
    click(at, "この局をやめて、新しい局を始める")                       # 次の局は、また「ヒントなし」から
    assert at.session_state["pr_hinted"] is False


def test_hint_off_and_minimum_level_show_less():
    state = find(LuckSettings(50, 50), lambda s: s.turn == 4)
    off = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(hint="off")})
    text = page_text(off)
    assert "コーチはオフです" in text and "巡目の打牌" not in text and TABLE not in labels(off)
    minimum = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(level=1)})
    assert "おすすめ：" in page_text(minimum) and "3 巡目の打牌" in page_text(minimum)
    assert labels(minimum) == ["設定（ツキ補正・コーチ）", "成績", "このページの使い方"]


def test_last_draw_explains_that_only_tenpai_matters():
    state = find(LuckSettings(), lambda s: s.turn == 18 and not s.can_tsumo)
    at = open_practice({HAND_NAME: hand_json(state)})
    text = page_text(at)
    assert "最後のツモ" in text and "18 巡目（残りツモ 0 回）" in text and TABLE not in labels(at)


def test_lucky_draw_is_marked_unless_turned_off():
    state = find(LuckSettings(75, 75), lambda s: s.last_draw.luck.swapped and not s.can_tsumo)
    marked = open_practice({HAND_NAME: hand_json(state)})
    assert "ツキ補正で引き寄せた牌です" in page_text(marked)
    plain = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(mark=False)})
    assert "ツキ補正で引き寄せた牌です" not in page_text(plain)


# ---------------------------------------------------------------- あがり・流局・次の局


def test_tsumo_button_shows_the_full_explanation_and_records_the_hand():
    state = find(LuckSettings(75, 75), lambda s: s.can_tsumo)
    at = open_practice({HAND_NAME: hand_json(state)})
    assert "あがりの形です" in page_text(at)
    click(at, "ツモ（あがる）")
    won = at.session_state["pr_state"]
    assert won.finished and won.result.outcome is Outcome.TSUMO
    text = page_text(at)
    assert "ツモあがり" in text and f"{won.result.turn} 巡目で終了" in text
    assert steps(at) == ALL_STEPS
    assert "配牌：候補 64 個から" in text and "「ツモ。" in text
    assert REVIEW in labels(at)
    assert [b.label for b in at.button].count("次の局へ") == 2          # 解説を読み終えた下にも、もう 1 つ
    assert "ヒントあり" in text                                         # 打つ前のヒントを出した局
    # 成績に 1 局ぶん入り、ブラウザにも保存される
    history = load_history(stored(at, HISTORY_NAME))
    assert len(history) == 1 and history[0].win and history[0].seed == won.config.seed and (history[0].deal, history[0].draw) == (75, 75)
    assert history[0].hinted is True and json.loads(stored(at, HISTORY_NAME)) == [history[0].to_dict()]
    assert json.loads(stored(at, HAND_NAME))["save"]["actions"][-1] == ["t"]

    click(at, "同じ局をもう一度")
    again = at.session_state["pr_state"]
    assert again == practice.start(won.config) and at.session_state["pr_counted"] is False
    click(at, "この局をやめて、新しい局を始める")
    assert at.session_state["pr_state"].config.seed != won.config.seed and at.session_state["pr_counted"] is True


def test_riichi_hand_shows_which_draws_were_brought_by_luck():
    """リーチのあとは自動でツモ切りになる。そのあいだに補正で引き寄せた牌にも、印を付けて見せる"""
    for seed in range(300):
        state = practice.start(PracticeConfig(seed=seed, luck=LuckSettings(100, 100, True)))
        if not state.riichi_discards:
            continue
        state = practice.apply(state, practice.riichi(state.riichi_discards[0]))
        if state.result.outcome == Outcome.TSUMO and state.draws[-1].luck.swapped:      # あがり牌を、補正で引き寄せた局
            break
    else:
        raise AssertionError("局面が見つからない")
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(deal=100, draw=100, tenpai_deal=True)})
    text = page_text(at)
    assert "リーチのあとのツモ" in text and "★ は、ツキ補正で引き寄せた牌" in text and 'class="mj-star"' in page_html(at)
    assert "あがり牌も、補正で引き寄せた牌。" in text
    plain = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(deal=100, draw=100, tenpai_deal=True, mark=False)})
    assert 'class="mj-star"' not in page_html(plain)                   # 印を付けない設定


def test_exhausted_hand_screen_and_next_hand():
    state = exhausted_state()
    at = open_practice({HAND_NAME: hand_json(state), SETTINGS_NAME: settings_json(deal=0, draw=0)})
    text = page_text(at)
    assert "流局（ノーテン" in text and "18 巡目で終了" in text and "ツキ補正なし（通常の麻雀）" in text
    assert "配牌：補正なし（山の並びのまま）。" in text and headings_of(page_html(at)) == []
    assert [b.label for b in at.button].count("次の局へ") == 1 and ruby_terms(page_html(at)).count("流局") == 1
    assert load_history(stored(at, HISTORY_NAME)) == []                 # 開き直しただけでは、成績に入れない
    click(at, "次の局へ")
    fresh = at.session_state["pr_state"]
    assert not fresh.finished and fresh.turn == 1 and fresh.config.luck == LuckSettings(0, 0)


# ---------------------------------------------------------------- 設定


def test_luck_settings_apply_from_the_next_hand():
    at = open_practice()
    first = at.session_state["pr_state"]
    assert at.slider(key="pr_w_deal").value == 75 and at.button_group(key="pr_w_preset").value == "強"
    at.button_group(key="pr_w_preset").set_value("なし").run()
    assert not at.exception
    assert (at.slider(key="pr_w_deal").value, at.slider(key="pr_w_draw").value) == (0, 0)
    assert at.session_state["pr_state"] == first                       # いまの局はそのまま
    assert "ツキ補正：配牌 75・ツモ 75" in page_text(at) and any("次の局から反映" in c.value for c in at.caption)
    assert "配牌：補正なし（山の並びのまま）" in page_text(at)
    click(at, "この設定で新しい局を始める")
    assert at.session_state["pr_state"].config.luck == LuckSettings(0, 0) and "ツキ補正なし（通常の麻雀）" in page_text(at)
    assert json.loads(stored(at, SETTINGS_NAME))["deal"] == 0

    at.slider(key="pr_w_draw").set_value(40).run()                     # 段階に当てはまらない値にすると、段階の選択が外れる
    assert at.button_group(key="pr_w_preset").value is None
    assert "ツモ：1 回ごとに 9% の確率で" in page_text(at)
    at.toggle(key="pr_w_tenpai").set_value(True).run()
    click(at, "この設定で新しい局を始める")
    assert at.session_state["pr_state"].config.luck == LuckSettings(0, 40, True)


def test_coach_settings_change_the_page_at_once():
    at = open_practice()
    at.button_group(key="pr_w_hint").set_value("オフ").run()
    assert "コーチはオフです" in page_text(at) and TABLE not in labels(at)
    at.button_group(key="pr_w_hint").set_value("打つ前に表示").run()
    at.button_group(key="pr_w_level").set_value("最小").run()
    assert TABLE not in labels(at) and at.session_state["pr_settings"]["level"] == 1
    at.button_group(key="pr_w_level").set_value("詳しい").run()
    assert TABLE in labels(at) and json.loads(stored(at, SETTINGS_NAME))["level"] == 3


def test_changing_the_level_reopens_the_tables_with_the_new_default():
    """「詳しい」では表を開いて、「ふつう」では閉じて出す。折りたたみは開閉を覚えているので、量ごとに別の部品にしてある"""
    at = open_practice()
    opened = {e.label: e.proto.expanded for e in at.expander}
    assert opened[TABLE] is False and opened[LAYOUT] is False
    at.button_group(key="pr_w_level").set_value("詳しい").run()
    opened = {e.label: e.proto.expanded for e in at.expander}
    assert opened[TABLE] is True and opened[LAYOUT] is True
    at.button_group(key="pr_w_level").set_value("ふつう").run()
    assert not any(e.proto.expanded for e in at.expander if e.label in (TABLE, LAYOUT))


def test_tapping_the_selected_choice_again_keeps_it_selected():
    """選択中の項目をもう一度押すと、選択が外れた値（None）が届く。設定はそのままにして、表示も元に戻す"""
    at = open_practice()
    for key, label in (("pr_w_hint", "打つ前に表示"), ("pr_w_level", "ふつう"), ("pr_w_preset", "強")):
        assert at.button_group(key=key).value == label
        at.session_state[key] = None
        at.run()
        assert not at.exception and at.button_group(key=key).value == label
    assert at.session_state["pr_settings"] == DEFAULT_SETTINGS


def test_settings_survive_a_visit_to_another_page():
    at = open_practice()
    at.button_group(key="pr_w_hint").set_value("オフ").run()
    at.slider(key="pr_w_deal").set_value(20).run()
    state = at.session_state["pr_state"]
    at.switch_page("views/score_lab.py").run()
    assert not at.exception
    at.switch_page("views/practice.py").run()
    assert not at.exception
    assert at.button_group(key="pr_w_hint").value == "オフ" and at.slider(key="pr_w_deal").value == 20
    assert at.session_state["pr_state"] == state and "コーチはオフです" in page_text(at)


def test_numbered_hand_is_reproducible_and_not_counted():
    at = open_practice()
    at.text_input(key="pr_w_seed").set_value("4242")
    click(at, "この番号で始める")
    state = at.session_state["pr_state"]
    assert state == practice.start(PracticeConfig(seed=4242, luck=LuckSettings(75, 75)))
    assert at.session_state["pr_counted"] is False
    assert any("局の番号 4242" in c.value for c in at.caption)


def test_bad_hand_number_shows_a_hint_and_changes_nothing():
    at = open_practice()
    state = at.session_state["pr_state"]
    for text in ("", "12ab", "-3", "1.5"):          # 7 桁以上は、入力欄が 6 文字までしか受け付けない
        at.text_input(key="pr_w_seed").set_value(text)
        click(at, "この番号で始める")
        assert at.session_state["pr_state"] == state
        assert any("0〜999999 の数字で入れてください" in c.value for c in at.caption)
        at.run()                                                        # 案内は 1 回だけ。次に画面を描くときには消える
        assert not any("数字で入れてください" in c.value for c in at.caption)
    at.text_input(key="pr_w_seed").set_value("００７")                  # 全角の数字も受け付ける
    click(at, "この番号で始める")
    assert at.session_state["pr_state"].config.seed == 7


# ---------------------------------------------------------------- 成績


def test_stats_table_and_clearing():
    records = [
        HandRecord(time=1, seed=1, deal=0, draw=0, hinted=False, win=True, turn=12, riichi=True, tenpai=True, points=2700, han=3, fu=20, yaku=("riichi",), decisions=11, best=10),
        HandRecord(time=2, seed=2, deal=0, draw=0, hinted=False, win=False, turn=18, riichi=False, tenpai=False, decisions=18, best=9),
        HandRecord(time=3, seed=3, deal=75, draw=75, hinted=True, win=True, turn=6, riichi=True, tenpai=True, points=8000, han=5, fu=30, decisions=5, best=5),
    ]
    at = open_practice({HISTORY_NAME: history_json(records)})
    text = page_text(at)
    assert "なし（実力）250%12.02,70066%" in text and "配牌 75・ツモ 75ヒントあり1100%6.08,000—" in text
    click(at, "消す")
    assert "まだ記録がありません" in page_text(at) and stored(at, HISTORY_NAME) is None
    assert at.session_state["pr_history"] == []


def test_playing_through_the_session_object_updates_the_page():
    """牌タップの代わりに、同じ処理（PracticeSession）を呼んで 1 局打ち、画面と成績が付いてくることを確かめる"""
    from ui.practice_session import PracticeSession

    at = open_practice({SETTINGS_NAME: settings_json(hint="after", deal=50, draw=50)})

    class StoreProxy:
        """テストの中から、ページと同じブラウザ内保存の状態に書き込む"""

        def get(self, name):
            return at.session_state[STORE_STATE]["known"].get(name)

        def set(self, name, value):
            at.session_state[STORE_STATE]["known"][name] = value

        def remove(self, name):
            at.session_state[STORE_STATE]["known"].pop(name, None)

        def append(self, name, item, *, limit):
            known = at.session_state[STORE_STATE]["known"]
            known[name] = json.dumps([*json.loads(known.get(name) or "[]"), json.loads(item)][-limit:])

    class StateProxy(dict):
        def __getitem__(self, key):
            return at.session_state[key]

        def __setitem__(self, key, value):
            at.session_state[key] = value

        def get(self, key, default=None):
            return at.session_state.get(key, default)

        def __contains__(self, key):
            return key in at.session_state

    session = PracticeSession(StateProxy(), StoreProxy(), now=lambda: 1000.0)
    steps = 0
    while not at.session_state["pr_state"].finished:
        state = at.session_state["pr_state"]
        if state.can_tsumo:
            click(at, "ツモ（あがる）")
        else:
            session.pick(nearest_discard(state))
            at.run()
            assert not at.exception, [e.value for e in at.exception]
            if not at.session_state["pr_state"].finished:
                assert "巡目の打牌" in page_text(at)                    # 答え合わせが出る
        steps += 1
        assert steps < 40
    assert len(at.session_state["pr_history"]) == 1 and at.session_state["pr_history"][0].hinted is False
    assert "次の局へ" in [b.label for b in at.button]

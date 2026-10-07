"""一人練習の画面の状態（ui/practice_session.py）のテスト。画面なしで、操作の流れと保存を確かめる"""
from __future__ import annotations

import importlib
import json
import sys

from practice_helpers import nearest_discard

from engine import practice
from engine.coach import analyze
from engine.luck import LuckSettings
from engine.practice import Outcome, PracticeConfig
from engine.progress import Stamp, load_stamps, stamp_keys
from engine.records import load_history, target_stats
from engine.scoring.explain import explain
from engine.target_coach import target_result
from ui.practice_session import (
    DEFAULT_SETTINGS,
    HAND_NAME,
    HISTORY_NAME,
    MAX_SEED,
    SETTINGS_NAME,
    PracticeSession,
    clean_settings,
    parse_seed,
    preset_name,
)
from ui.practice_view import HINT_AFTER, HINT_OFF, LEVEL_FULL, LEVEL_MIN, LEVEL_NORMAL
from ui.progress_store import STAMPS_NAME


class FakeStore:
    """ブラウザ内保存の代わり（ただの辞書）"""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def remove(self, name: str) -> None:
        self.values.pop(name, None)

    def append(self, name: str, item: str, *, limit: int) -> None:
        try:
            items = json.loads(self.values.get(name) or "[]")
        except ValueError:
            items = []
        items = [*(items if isinstance(items, list) else []), json.loads(item)][-limit:]
        self.values[name] = json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def new_session(store: FakeStore | None = None, *, seeds=(101, 102, 103, 104, 105), now: float = 5000.0):
    store = store or FakeStore()
    numbers = iter(seeds)
    session = PracticeSession({}, store, now=lambda: now, new_seed=lambda: next(numbers))
    return session, store


def reopen(store: FakeStore) -> PracticeSession:
    """別のセッション（ページを開き直した状況）で、同じブラウザ内保存から始める"""
    session = PracticeSession({}, store, now=lambda: 9000.0, new_seed=lambda: 999)
    session.start()
    return session


def play_to_end(session: PracticeSession, *, use_best: bool = True) -> None:
    """あがれるときはあがり、そうでなければ聴牌に近づく牌を切って、局を終わらせる"""
    while not session.state.finished:
        state = session.state
        if state.can_tsumo:
            assert session.tsumo()
        elif use_best:
            assert session.pick(analyze(practice.position_of(state)).pick.tile)
        else:
            assert session.pick(nearest_discard(state))


# ---------------------------------------------------------------- 設定


def test_clean_settings_keeps_good_values_and_resets_bad_ones():
    assert clean_settings(None) == DEFAULT_SETTINGS and clean_settings("x") == DEFAULT_SETTINGS
    good = {"deal": 0, "draw": 100, "tenpai_deal": True, "mark": False, "hint": HINT_OFF, "level": LEVEL_FULL, "target": "sanshoku"}
    assert clean_settings(good) == good
    assert clean_settings({**good, "target": None})["target"] is None
    bad = {"deal": 101, "draw": "50", "tenpai_deal": 1, "mark": None, "hint": "いつも", "level": 9, "余分": 1, "target": "toitoi"}
    assert clean_settings(bad) == DEFAULT_SETTINGS                      # 対々和は、役指定練習で選べない
    for target in (5, "", ["sanshoku"], True):
        assert clean_settings({"target": target}, base=good)["target"] == "sanshoku"     # おかしな値は、前の値のまま
    assert clean_settings({"deal": True, "level": True}) == DEFAULT_SETTINGS         # 真偽値を数として読まない
    assert clean_settings({"deal": 30})["deal"] == 30 and clean_settings({"deal": 30})["draw"] == DEFAULT_SETTINGS["draw"]


def test_preset_name():
    assert [preset_name(v, v) for v in (0, 25, 50, 75, 100)] == ["なし", "弱", "中", "強", "最大"]
    assert preset_name(75, 50) is None and preset_name(10, 10) is None


def test_parse_seed_accepts_only_whole_numbers_in_range():
    assert [parse_seed(text) for text in ("0", "7", "007", " 42 ", "999999", "１２３")] == [0, 7, 7, 42, MAX_SEED, 123]
    for bad in ("", " ", "1000000", "-5", "+81", "1.5", "12a", "٣", None, 5, 5.0, ["1"]):
        assert parse_seed(bad) is None


def test_first_visit_starts_a_hand_with_the_default_settings():
    session, store = new_session()
    assert not session.started
    session.start()
    assert session.started and session.settings == DEFAULT_SETTINGS and session.history == []
    assert session.state.config == PracticeConfig(seed=101, luck=LuckSettings(75, 75))
    assert (session.decisions, session.counted, session.hinted, session.resumed) == ([], True, False, False)
    assert session.last_decision is None and not session.luck_changed
    saved = json.loads(store.values[HAND_NAME])
    assert saved == {"v": 1, "save": practice.to_save(session.state), "counted": True, "hinted": False}


def test_settings_are_saved_and_apply_from_the_next_hand():
    session, store = new_session()
    session.start()
    session.update_settings({"deal": 0, "draw": 0, "hint": HINT_AFTER, "level": LEVEL_MIN, "mark": False})
    assert session.settings["deal"] == 0 and session.luck == LuckSettings(0, 0) and session.luck_changed
    assert session.state.config.luck == LuckSettings(75, 75)            # いまの局は、始めたときの補正のまま
    assert json.loads(store.values[SETTINGS_NAME]) == session.settings
    session.update_settings({"deal": 999, "hint": "x"})                 # おかしな値は無視する
    assert session.settings["deal"] == 0 and session.settings["hint"] == HINT_AFTER

    session.begin()
    assert session.state.config == PracticeConfig(seed=102, luck=LuckSettings(0, 0)) and not session.luck_changed
    again = reopen(store)
    assert again.settings == session.settings


# ---------------------------------------------------------------- 打つ


def test_pick_advances_the_hand_and_records_the_decision():
    session, store = new_session()
    session.start()
    before = session.state
    rev = session.rev
    tile = before.hand[0]
    assert session.pick(tile)
    assert session.state.discards == (tile,) and session.rev == rev + 1
    decision = session.last_decision
    assert decision.turn == 1 and decision.action == practice.discard(tile) and decision.analysis.position.tiles == before.tiles
    assert not session.hinted                                           # 画面がヒントを出していなければ、「ヒントあり」にならない
    assert json.loads(store.values[HAND_NAME])["save"]["actions"] == [["d", tile]]
    assert json.loads(store.values[HAND_NAME])["hinted"] is False


def test_stale_or_illegal_actions_change_nothing_but_still_answer():
    session, _ = new_session()
    session.start()
    state, rev = session.state, session.rev
    missing = next(t for t in range(136) if t not in state.tiles)
    assert session.pick(missing) is False                               # 古い画面から届いた牌
    assert session.pick(state.hand[0], riichi=True) is False            # 聴牌していないのにリーチ
    assert session.tsumo() is False                                     # あがれないのにツモ
    assert session.state == state and session.decisions == []
    assert session.rev == rev + 3                                       # 番号は進める（画面の「送信中」を解くため）


def test_hand_counts_as_hinted_once_a_hint_was_shown():
    """「ヒントあり」は、打つ前のヒントを画面に出したかどうかで決める（切る瞬間の設定では決めない）"""
    session, store = new_session()
    session.start()
    session.pick(session.state.hand[0])
    assert not session.hinted
    session.note_hint_shown()                                           # 画面がヒントを出した
    assert session.hinted and json.loads(store.values[HAND_NAME])["hinted"] is True
    saved = store.values[HAND_NAME]
    session.note_hint_shown()                                           # 2 回目からは、何も書き直さない
    assert store.values[HAND_NAME] is saved
    # ヒントを見たあとで設定をオフに変えて切っても、「ヒントあり」のまま
    session.update_settings({"hint": HINT_OFF})
    session.pick(session.state.hand[0])
    assert session.hinted
    # 次の局は、また「ヒントなし」から
    session.begin()
    assert not session.hinted
    play_to_end(session)
    assert [r.hinted for r in session.history] == [False]
    # 開き直しても、印は残る
    session.begin()
    session.note_hint_shown()
    assert reopen(store).hinted


def test_finished_hand_is_recorded_once_with_its_luck():
    session, store = new_session(now=7777.9)
    session.start()
    play_to_end(session)
    state = session.state
    assert state.finished and len(session.history) == 1
    made = session.history[0]
    assert (made.seed, made.deal, made.draw, made.time, made.hinted) == (101, 75, 75, 7777, False)
    assert made.win == (state.result.outcome is Outcome.TSUMO) and made.turn == state.result.turn
    assert made.decisions == len(session.decisions) == made.best        # おすすめどおりに打った
    assert load_history(store.values[HISTORY_NAME]) == session.history
    assert json.loads(store.values[HISTORY_NAME]) == [made.to_dict()]   # ブラウザには、記録の配列をそのまま置く

    # 終わった局を開き直しても、もう一度は記録しない
    again = reopen(store)
    assert again.state == state and again.resumed and len(again.history) == 1
    assert again.decisions == session.decisions and again.counted

    session.begin()
    session.note_hint_shown()
    play_to_end(session, use_best=False)
    assert [(r.seed, r.hinted) for r in session.history] == [(101, False), (102, True)]
    assert load_history(store.values[HISTORY_NAME]) == session.history   # 2 件目は、末尾に足しただけ


def test_finished_hand_is_added_without_losing_records_from_another_tab():
    """成績は、ブラウザに残っている配列の末尾に 1 件足す。別のタブが足した記録を、上書きで消さない"""
    session, store = new_session()
    session.start()
    play_to_end(session)
    other = {**session.history[0].to_dict(), "seed": 555555}            # 別のタブが、あとから 1 件足した
    store.values[HISTORY_NAME] = json.dumps([*json.loads(store.values[HISTORY_NAME]), other])
    session.begin()
    play_to_end(session)
    assert [row["seed"] for row in json.loads(store.values[HISTORY_NAME])] == [101, 555555, 102]
    assert [r.seed for r in session.history] == [101, 102]              # このタブの表示は、自分が知っているぶん
    assert [r.seed for r in reopen(store).history] == [101, 555555, 102]


def test_replayed_and_numbered_hands_are_not_recorded():
    session, store = new_session()
    session.start()
    play_to_end(session)
    first = session.state
    assert len(session.history) == 1

    session.again()                                                     # 同じ局をもう一度
    assert session.state == practice.start(first.config) and not session.counted and session.decisions == []
    play_to_end(session)
    assert len(session.history) == 1

    session.begin(4242)                                                 # 番号を指定した局
    assert session.state.config.seed == 4242 and not session.counted
    play_to_end(session)
    assert len(session.history) == 1
    assert json.loads(store.values[HAND_NAME])["counted"] is False

    session.begin()                                                     # ふつうの次の局は、また記録する
    assert session.counted and session.state.config.seed == 102
    play_to_end(session)
    assert len(session.history) == 2


def test_clear_history():
    session, store = new_session()
    session.start()
    play_to_end(session)
    assert HISTORY_NAME in store.values
    session.clear_history()
    assert session.history == [] and HISTORY_NAME not in store.values
    assert reopen(store).history == []


# ---------------------------------------------------------------- 続きから再開


def test_hand_in_progress_is_resumed_with_its_decisions():
    session, store = new_session()
    session.start()
    session.update_settings({"hint": HINT_OFF, "deal": 50})
    for _ in range(5):
        if session.state.finished:
            break
        session.pick(nearest_discard(session.state))
    again = reopen(store)
    assert again.resumed and again.state == session.state
    assert again.decisions == session.decisions and again.hinted is False and again.counted is True
    assert again.settings == session.settings and again.luck_changed      # 設定は変えたが、局は元の補正のまま
    assert not again.take_scroll()                                        # 続きから再開したときは、画面を動かさない
    rev = again.rev
    again.pick(nearest_discard(again.state))
    assert not again.resumed and len(again.decisions) == len(session.decisions) + 1 and again.rev == rev + 1


def test_rev_starts_from_a_different_number_in_each_session():
    """通信が切れてセッションが作り直されたとき、手牌の部品が「番号が変わった」と気づけるように"""
    store = FakeStore()
    first = PracticeSession({}, store, now=lambda: 1000.0, new_seed=lambda: 1)
    first.start()
    for _ in range(3):
        first.pick(first.state.hand[0])
    later = PracticeSession({}, store, now=lambda: 1003.5, new_seed=lambda: 2)      # 3.5 秒後に作り直された
    later.start()
    assert later.resumed and later.rev > first.rev + 1000
    assert later.rev < 2**53                                              # JavaScript が正確に扱える範囲


def test_new_hand_asks_the_page_to_scroll_to_the_top_once():
    session, _ = new_session()
    session.start()                                                       # 保存が無いので、新しい局で始まる
    assert session.take_scroll() and not session.take_scroll()
    session.pick(session.state.hand[0])
    assert not session.take_scroll()
    session.begin()
    assert session.take_scroll() and not session.take_scroll()
    session.again()
    assert session.take_scroll()
    session.begin(4242)
    assert session.take_scroll()


def test_broken_saved_data_starts_fresh():
    good_hand = None
    session, store = new_session()
    session.start()
    good_hand = store.values[HAND_NAME]
    for hand in ("こわれている", "[]", json.dumps({"v": 2}), json.dumps({"v": 1, "save": {"v": 1, "config": {"seed": -1}, "actions": []}}),
                 json.dumps({"v": 1, "save": {**json.loads(good_hand)["save"], "actions": [["d", 999]]}})):
        store = FakeStore({HAND_NAME: hand, SETTINGS_NAME: "{だめ", HISTORY_NAME: "これも"})
        fresh = reopen(store)
        assert not fresh.resumed and fresh.state.config.seed == 999 and fresh.state.actions == ()
        assert fresh.settings == DEFAULT_SETTINGS and fresh.history == []
    # counted / hinted が欠けていたら、成績に入れない・ヒントなしとして扱う
    data = json.loads(good_hand)
    del data["counted"], data["hinted"]
    partial = reopen(FakeStore({HAND_NAME: json.dumps(data)}))
    assert partial.resumed and partial.counted is False and partial.hinted is False


def test_saved_data_of_any_shape_never_stops_the_page():
    """ブラウザに残っているデータの型がおかしくても、例外を出さずに新しい局から始める（開くたびに止まるのを防ぐ）"""
    session, store = new_session()
    session.start()
    save = json.loads(store.values[HAND_NAME])["save"]
    config = save["config"]
    deep = "[" * 100_000                                                # 入れ子が深すぎて、JSON として読めない
    odd_saves = [
        {**save, "config": "x"}, {**save, "config": []}, {**save, "config": None},
        {**save, "config": {**config, "luck": "強"}}, {**save, "config": {**config, "luck": [1]}}, {**save, "config": {**config, "luck": 5}},
        {**save, "config": {**config, "rules": {"aka_dora": []}}}, {**save, "config": {**config, "rules": {"aka_dora": "no"}}},
        {**save, "actions": [["d", 1]] * 5000}, {**save, "actions": {"0": ["d", 1]}},
    ]
    texts = [json.dumps({"v": 1, "save": odd, "counted": True, "hinted": False}) for odd in odd_saves]
    texts += [
        '{"v":1,"save":{"v":1,"config":{"seed":Infinity},"actions":[]},"counted":true,"hinted":false}',
        '{"v":1,"save":{"v":1,"config":{"seed":1e400},"actions":[]},"counted":true,"hinted":false}',
        deep, '{"v":1,"save":' + deep, "null", "0", '"x"',
    ]
    for text in texts:
        fresh = reopen(FakeStore({HAND_NAME: text, SETTINGS_NAME: deep, HISTORY_NAME: deep}))
        assert not fresh.resumed and fresh.state.actions == () and fresh.state.config.seed == 999
        assert fresh.settings == DEFAULT_SETTINGS and fresh.history == []


def test_objects_are_rebuilt_when_the_code_is_updated():
    """アプリの更新でモジュールが読み直されたあと、セッションに残っている古い型のオブジェクトを作り直す"""
    session_data: dict = {}
    store = FakeStore()
    old = PracticeSession(session_data, store, now=lambda: 5000.0, new_seed=iter([101, 102]).__next__)
    old.start(generation=3)
    play_to_end(old)                                                     # 1 局打ち終えて、成績が 1 件
    old.begin()
    old.note_hint_shown()
    old.pick(nearest_discard(old.state))
    old_state, old_record, rev = old.state, old.history[0], old.rev
    old.sync_code(3)                                                     # 世代が同じなら、何もしない
    assert old.state is old_state and old.history[0] is old_record

    ours = {name: module for name, module in sys.modules.items() if name.split(".")[0] in ("engine", "ui")}
    try:
        for name in ours:                                                # ui/fresh.py と同じこと：自作モジュールを捨てる
            del sys.modules[name]
        fresh_module = importlib.import_module("ui.practice_session")
        fresh_practice = importlib.import_module("engine.practice")
        fresh_records = importlib.import_module("engine.records")
        assert fresh_practice.PracticeState is not practice.PracticeState          # 読み直すと、同じ名前でも別のクラスになる
        new = fresh_module.PracticeSession(session_data, store, now=lambda: 6000.0, new_seed=lambda: 777)
        assert type(new.state) is practice.PracticeState                           # まだ古い型のまま残っている
        new.sync_code(4)
        assert type(new.state) is fresh_practice.PracticeState and type(new.history[0]) is fresh_records.HandRecord
        assert all(type(d) is fresh_practice.Decision for d in new.decisions)
        # 中身は同じ：同じ局・同じ行動・同じ成績。番号も続き
        assert fresh_practice.to_save(new.state) == practice.to_save(old_state)
        assert new.history[0].to_dict() == old_record.to_dict() and len(new.decisions) == 1
        assert (new.hinted, new.counted, new.rev, new.settings) == (True, True, rev, DEFAULT_SETTINGS)
        # 作り直したあとは、新しい型どうしで正しく比べられる（古い型のままだと、あがりが流局に見えた）
        assert new.pick(new.state.hand[0]) and type(new.state) is fresh_practice.PracticeState
        new.sync_code(4)                                                 # 2 回目は何もしない
        # 控えが作り直せないほど変わっていたら、新しい局から始める（設定と成績は残す）
        session_data["pr_save"] = {"v": 999}
        new.sync_code(5)
        assert new.state.config.seed == 777 and new.state.actions == () and len(new.history) == 1
    finally:
        for name in [n for n in sys.modules if n.split(".")[0] in ("engine", "ui")]:
            del sys.modules[name]
        sys.modules.update(ours)                                         # ほかのテストのために、元のモジュールに戻す


def test_levels_are_plain_values():
    assert {LEVEL_MIN, LEVEL_NORMAL, LEVEL_FULL} == {1, 2, 3}


# ---------------------------------------------------------------- 役指定練習


def play_for_target(session: PracticeSession) -> None:
    """役を狙うコーチのおすすめどおりに打つ。狙った役が付くあがりの形になったら、あがる"""
    while not session.state.finished:
        state = session.state
        key = state.config.target
        if state.can_tsumo:
            win = practice.apply(state, practice.TSUMO).result.win
            if target_result(explain(win), key).achieved or state.draws_left == 0:
                assert session.tsumo()
                continue
        advice = practice.target_advice_of(state)
        tile = advice.pick.tile if advice is not None and advice.pick is not None else analyze(practice.position_of(state)).pick.tile
        assert session.pick(tile)


def test_target_setting_applies_from_the_next_hand_and_survives_a_reopen():
    session, store = new_session()
    session.start()
    assert session.target is None and not session.target_changed
    session.update_settings({"target": "sanshoku"})
    assert session.target == "sanshoku" and session.target_changed       # いまの局は、ふつうの局のまま
    assert session.state.config.target is None
    session.begin()
    state = session.state
    assert state.config.target == "sanshoku" and not session.target_changed
    assert state.deal.target == "sanshoku" and state.deal.chosen_distance is not None
    assert session.counted

    assert session.pick(practice.target_advice_of(state).pick.tile)
    decision = session.last_decision
    assert decision.target is not None and decision.target.is_best and decision.target_advice.key == "sanshoku"

    again = reopen(store)
    assert again.settings["target"] == "sanshoku" and again.state.config.target == "sanshoku"
    assert again.decisions[-1].target is not None and again.decisions[-1].target.label == decision.target.label

    session.again()
    assert session.state.config == state.config and not session.counted
    session.update_settings({"target": None})
    session.begin()
    assert session.state.config.target is None


def test_begin_skips_walls_where_the_target_cannot_be_made():
    """必要な牌が王牌にしか無い山は、どう打っても役が作れない。そういう番号は飛ばす"""
    luck = LuckSettings(75, 75)

    def feasible(seed: int) -> bool:
        return practice.start(PracticeConfig(seed=seed, luck=luck, target="daisuushii")).deal.chosen_distance is not None

    seeds = range(200)
    dead = [seed for seed in seeds if not feasible(seed)][:2]
    live = next(seed for seed in seeds if feasible(seed))
    assert len(dead) == 2
    session, _ = new_session(seeds=(1, *dead, live, 7))
    session.start()
    session.update_settings({"target": "daisuushii"})
    session.begin()
    assert session.state.config.seed == live and session.state.deal.chosen_distance is not None

    # 番号を指定した局は、作れない山でもそのまま始める（同じ番号は、いつも同じ局にするため）。
    # コーチは山の中を見ないので、「作れない」とは言わない（実際の麻雀で、欲しい牌が王牌に眠っているのと同じ）
    session.begin(dead[0])
    assert session.state.config.seed == dead[0] and session.state.deal.chosen_distance is None and not session.counted
    assert practice.target_advice_of(session.state).possible


def test_target_hand_is_recorded_with_the_target_and_kept_out_of_the_usual_stats():
    session, store = new_session(seeds=(1, 2, 3, 4))
    session.start()
    session.update_settings({"deal": 100, "draw": 100, "target": "tanyao"})
    session.begin()
    play_for_target(session)
    assert session.state.result.outcome is Outcome.TSUMO
    record = session.history[-1]
    assert (record.target, record.made, record.win) == ("tanyao", True, True)
    assert "tanyao" in record.yaku
    stats = target_stats(load_history(store.values[HISTORY_NAME]))
    assert (stats["tanyao"].tries, stats["tanyao"].made) == (1, 1)


# ---------------------------------------------------------------- スタンプ


def win_a_hand(session: PracticeSession) -> list[str]:
    """あがるまで局をくり返し、あがった手に付いた役（図鑑のページの鍵）を返す"""
    for _ in range(10):
        play_to_end(session)
        if session.state.result.outcome is Outcome.TSUMO:
            best = explain(session.state.result.win).best
            return stamp_keys(item.key for item in best.evaluation.yaku)
        session.begin()
    raise AssertionError("あがれる局が出なかった")


def test_winning_stamps_the_yaku_once():
    session, store = new_session(seeds=range(300, 330), now=7000.0)
    session.start()
    session.update_settings({"deal": 100, "draw": 100})
    session.begin()
    assert STAMPS_NAME not in store.values and session.fresh_stamps == []
    pages = win_a_hand(session)
    stamps = load_stamps(store.values[STAMPS_NAME])
    assert set(stamps) == set(pages) and session.fresh_stamps == pages
    assert all(stamp == Stamp(1, 7000, 7000, 0) for stamp in stamps.values())       # 補正ありの局なので、plain は 0

    # 開き直しても、押し直さない
    again = reopen(store)
    assert again.state.finished and again.fresh_stamps == []
    assert load_stamps(store.values[STAMPS_NAME]) == stamps

    # もう 1 回あがると、回数が増える。はじめての役だけが fresh に入る
    session.begin()
    assert session.fresh_stamps == []
    more = win_a_hand(session)
    after = load_stamps(store.values[STAMPS_NAME])
    assert session.fresh_stamps == [page for page in more if page not in pages]
    for page in more:
        assert after[page].count == stamps[page].count + 1 if page in stamps else after[page].count == 1


def test_replayed_hands_are_stamped_but_not_recorded():
    session, store = new_session(seeds=range(300, 330))
    session.start()
    session.update_settings({"deal": 100, "draw": 100})
    session.begin()
    pages = win_a_hand(session)
    hands = len(session.history)
    session.again()
    play_to_end(session)
    assert session.state.result.outcome is Outcome.TSUMO and len(session.history) == hands
    replayed = stamp_keys(item.key for item in explain(session.state.result.win).best.evaluation.yaku)
    stamps = load_stamps(store.values[STAMPS_NAME])
    assert all(stamps[page].count == 1 + (page in pages) for page in replayed)


def test_plain_hands_are_marked_and_old_history_becomes_stamps():
    old = [{"t": 100, "seed": 1, "deal": 0, "draw": 0, "hinted": False, "win": True, "turn": 9, "riichi": True, "tenpai": True,
            "pts": 8000, "han": 5, "fu": 30, "yaku": ["riichi", "honitsu"], "n": 8, "best": 8}]
    store = FakeStore({HISTORY_NAME: json.dumps(old)})          # スタンプができる前の版で打った成績だけがある
    session, _ = new_session(store, seeds=range(300, 400), now=8000.0)
    session.start()
    session.update_settings({"deal": 100, "draw": 100})
    session.begin()
    win_a_hand(session)
    stamps = load_stamps(store.values[STAMPS_NAME])
    assert stamps["honitsu"] == Stamp(1, 100, 100, 1)           # 前の成績ぶんも、スタンプになっている（補正なしの局）
    assert stamps["riichi"].first == 100 and stamps["riichi"].plain == 1


def test_draws_and_missing_storage_do_not_stamp():
    session, store = new_session(seeds=(11, 12))
    session.start()
    session.update_settings({"deal": 0, "draw": 0})
    session.begin()
    while not session.state.finished:                           # ツモ切りを続けて流局させる
        assert session.pick(session.state.drawn)
    assert session.state.result.outcome is Outcome.EXHAUSTED
    assert STAMPS_NAME not in store.values and session.fresh_stamps == []

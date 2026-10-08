"""CPU との対局のページを、画面なしで動かして確かめる。

操作の流れそのものは test_game_session.py、実際の画面は tools/e2e_game_check.py で確かめる。ここで見るのは、
いろいろな局面（自分の番・ロンの返事・リーチを受けている・局の終わり・対局の終わり）でページが正しく描かれること、
ボタンの動き、用語の初出のルビ。
"""
from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from component_helpers import action_keys, component_data, pick_tile, press_action
from html_helpers import check_tile_images, page_html, page_parts
from streamlit.testing.v1 import AppTest

from engine import game as g
from engine.cpu import advance
from engine.defense import threats
from engine.game import HUMAN, GameConfig, Phase
from engine.game_coach import coach_action
from engine.game_records import load_history
from engine.luck import LuckSettings
from ui.components.browser_store import initial_state
from ui.game_session import GAME_HISTORY_NAME, GAME_NAME
from ui.ruby import missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"


def open_game(known: dict[str, str] | None = None, *, skip: bool = False) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    if not skip:
        at.session_state[STORE_STATE] = initial_state(known or {})
    at.switch_page("views/game.py").run()
    if skip:
        next(b for b in at.button if b.label == "保存を使わずに始める").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at: AppTest) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", page_html(at)))


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def saved(game: g.GameState, *, mark: int | None = None) -> str:
    size = len(game.current.actions)
    return json.dumps({"v": 1, "save": g.to_save(game), "counted": True, "hinted": False, "recorded": False,
                       "tally": {"n": 0, "f": 0, "d": 0, "s": 0}, "mark": size if mark is None else mark})


def stored(at: AppTest, name: str) -> str | None:
    return at.session_state[STORE_STATE]["known"].get(name)


@cache
def find(kind: str) -> g.GameState:
    """その局面になる対局を探す（自分はコーチのおすすめどおりに打つ）"""
    for seed in range(400):
        luck = LuckSettings(100, 100) if kind == "riichi_tsumo" else LuckSettings()
        game = advance(g.start_game(GameConfig(seed=seed, luck=luck)))
        while not game.finished:
            if game.between_hands:
                if kind == "hand_end_win" and any(w.seat == HUMAN for w in game.current.result.wins):
                    return game
                if kind == "exhausted" and game.current.result.kind is g.EndKind.EXHAUSTED:
                    return game
                game = advance(g.next_hand(game))
                continue
            hand = game.current
            if kind == "claim" and hand.phase is Phase.CLAIM and HUMAN in hand.pending:
                return game
            if kind == "threat" and hand.phase is Phase.DRAW and threats(hand, HUMAN) and not hand.players[HUMAN].in_riichi:
                return game
            if kind == "riichi_tsumo" and hand.phase is Phase.DRAW and hand.players[HUMAN].in_riichi and hand.can_tsumo(HUMAN):
                return game
            game = advance(g.apply(game, coach_action(hand, HUMAN)))
        if kind == "finished":
            return game
    raise AssertionError(f"局面が見つからない: {kind}")


def no_missing_ruby(at: AppTest) -> None:
    missing = missing_ruby(page_parts(at))
    assert missing == [], missing


# ---------------------------------------------------------------- 開く


def test_page_waits_for_storage_then_starts():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.switch_page("views/game.py").run()
    assert any("記録を確認しています" in i.value for i in at.info)
    click(at, "保存を使わずに始める")
    data = component_data(at, "mjdojo_tile_hand")
    assert data["discard"] is True and len(data["tiles"]) in (13, 14)
    body = text(at)
    assert "東 1 局" in body and "供託" in body and "残り" in body
    check_tile_images(page_html(at))


def test_new_page_has_no_missing_ruby():
    at = open_game()
    assert stored(at, GAME_NAME) is not None
    no_missing_ruby(at)


def test_discarding_advances_the_cpus_and_shows_their_moves():
    at = open_game()
    data = component_data(at, "mjdojo_tile_hand")
    rev = data["rev"]
    pick_tile(at, data["tiles"][-1]["id"])
    after = component_data(at, "mjdojo_tile_hand") if at.get("bidi_component") else None
    html = page_html(at)
    if after is not None and after["discard"]:
        assert after["rev"] != rev
        assert "mj-moves" in html and "mj-new" in html          # CPU の動きと、新しく切られた牌の印
    saved_game = json.loads(stored(at, GAME_NAME))
    assert saved_game["mark"] >= 1
    no_missing_ruby(at)


def test_threat_shows_danger_table_and_fold_advice():
    game = find("threat")
    at = open_game({GAME_NAME: saved(game)})
    html = page_html(at)
    assert "mj-danger" in html and "ベタオリの手順" in text(at)
    assert any("守備" in e.label for e in at.expander)
    no_missing_ruby(at)
    check_tile_images(html)


def test_ron_prompt_offers_ron_and_pass():
    game = find("claim")
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    assert data["discard"] is False and action_keys(at) == ["ron", "pass"]
    assert "ロンできます" in text(at)
    no_missing_ruby(at)
    press_action(at, "ron")
    after = json.loads(stored(at, GAME_NAME))
    rebuilt = g.from_save(after["save"])
    assert any(a.seat == HUMAN and a.move is g.Move.RON for h in rebuilt.hands for a in h.actions)


def test_passing_a_ron_continues_the_hand():
    game = find("claim")
    at = open_game({GAME_NAME: saved(game)})
    assert component_data(at, "mjdojo_tile_hand")["prompt"].startswith("見送ると、")     # 見送ったらどうなるかを、押す前に
    press_action(at, "pass")
    rebuilt = g.from_save(json.loads(stored(at, GAME_NAME))["save"])
    assert any(m.seat == HUMAN and m.passed for h in rebuilt.hands for m in h.misses)
    if rebuilt.current.result is not None:              # そのまま局が終わったら、見送ったことを結果の画面で知らせる
        assert "ロンできたが見送った" in text(at)


def test_riichi_tsumo_is_declared_by_pressing_the_button():
    """リーチのあとにあがり牌を引いたら、自動ではあがらない。「ツモ（あがる）」だけが押せる（牌は切れない）"""
    game = find("riichi_tsumo")
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    assert action_keys(at) == ["tsumo"] and data["discard"] is False
    assert "あがりの形です" in text(at)
    no_missing_ruby(at)
    press_action(at, "tsumo")
    rebuilt = g.from_save(json.loads(stored(at, GAME_NAME))["save"])
    assert any(w.seat == HUMAN for w in rebuilt.current.result.wins)


def test_hand_end_reveals_hands_and_explains_the_win():
    game = find("hand_end_win")
    at = open_game({GAME_NAME: saved(game)})
    body = text(at)
    assert "全員の手牌と待ち" in body and "自分" in body
    assert any(e.label.startswith("あがりの解説") for e in at.expander)
    assert "次の局へ" in [b.label for b in at.button]
    no_missing_ruby(at)
    check_tile_images(page_html(at))
    click(at, "次の局へ")
    assert len(g.from_save(json.loads(stored(at, GAME_NAME))["save"]).hands) == len(game.hands) + 1


def test_exhausted_draw_shows_tenpai_and_payments():
    game = find("exhausted")
    at = open_game({GAME_NAME: saved(game)})
    body = text(at)
    assert "流局" in body and "→" in body
    no_missing_ruby(at)


def test_finished_game_shows_the_ranking_and_records_once():
    game = find("finished")
    data = json.loads(saved(game))
    at = open_game({GAME_NAME: json.dumps(data)})
    body = text(at)
    assert "対局終了" in body and "位" in body
    assert "新しい対局を始める" in [b.label for b in at.button]
    no_missing_ruby(at)
    # 開いただけでは記録しない（終わった瞬間に記録する。保存の recorded は、ここでは偽のまま渡している）
    assert load_history(stored(at, GAME_HISTORY_NAME)) == []
    click(at, "新しい対局を始める")
    assert not g.from_save(json.loads(stored(at, GAME_NAME))["save"]).finished


def test_settings_change_applies_to_the_next_game():
    at = open_game()
    at.segmented_control(key="gm_w_length").set_value("半荘戦").run()
    assert "この設定で新しい対局を始める" in [b.label for b in at.button]
    click(at, "この設定で新しい対局を始める")
    rebuilt = g.from_save(json.loads(stored(at, GAME_NAME))["save"])
    assert rebuilt.config.length is g.Length.SOUTH


def test_hint_off_and_after():
    at = open_game()
    at.segmented_control(key="gm_w_hint").set_value("オフ").run()
    assert "コーチはオフ" in text(at)
    at.segmented_control(key="gm_w_hint").set_value("打った後に答え合わせ").run()
    assert "自分で考えて切って" in text(at)
    data = component_data(at, "mjdojo_tile_hand")
    pick_tile(at, data["tiles"][-1]["id"])
    no_missing_ruby(at)

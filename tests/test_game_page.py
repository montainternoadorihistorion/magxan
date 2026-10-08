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
from engine.tiles import kind_of
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


#: 探し始める対局の番号（見つかるまで時間のかかる局面は、見つかっている番号から探す。打ち方が変わって外れても、先を探す）
FIND_FROM = {"kan_offer": 11}


@cache
def find(kind: str) -> g.GameState:
    """その局面になる対局を探す（自分はコーチのおすすめどおりに打つ）"""
    from engine.game_coach import kan_advice

    for seed in range(FIND_FROM.get(kind, 0), 400):
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
            if kind == "claim" and hand.phase is Phase.CLAIM and HUMAN in hand.pending and HUMAN in hand.claim.ron:
                return game
            if kind == "call" and hand.phase is Phase.CLAIM and g.waiting_for(hand) == HUMAN and HUMAN not in hand.claim.ron:
                return game
            if kind == "after_call" and hand.phase is Phase.DRAW and hand.turn == HUMAN and hand.players[HUMAN].drawn is None and hand.forbidden:
                return game
            if kind == "threat" and hand.phase is Phase.DRAW and threats(hand, HUMAN) and not hand.players[HUMAN].in_riichi:
                return game
            if kind == "riichi_tsumo" and hand.phase is Phase.DRAW and hand.players[HUMAN].in_riichi and hand.can_tsumo(HUMAN):
                return game
            if (kind == "kan_offer" and hand.phase is Phase.DRAW and hand.turn == HUMAN and not hand.can_tsumo(HUMAN)
                    and any(a.recommend for a in kan_advice(hand, HUMAN))):
                return game
            game = advance(g.apply(game, coach_action(hand, HUMAN)))
        if kind == "finished":
            return game
    raise AssertionError(f"局面が見つからない: {kind}")


@cache
def first_turn() -> g.GameState:
    """自分が最初に切る番の局面（決まった配牌。鳴けるときは見送って進める）。
    新しい対局は毎回配牌が違い、最初に鳴きの返事を求められることもあるので、切る操作を確かめるテストはこれを使う"""
    game = advance(g.start_game(GameConfig(seed=1)))
    while not (game.current.phase is Phase.DRAW and game.current.turn == HUMAN):
        assert g.waiting_for(game.current) == HUMAN
        game = advance(g.apply(game, g.pass_(HUMAN)))
    return game


@cache
def ron_and_call() -> g.GameState:
    """ロンも鳴き（チー・ポン）もできる局面。自分は CPU（ふつう）と同じ打ち方で、リーチはしない（ダマの聴牌を作る）"""
    from engine.cpu import decide

    for seed in range(34, 300):
        game = g.start_game(GameConfig(seed=seed))
        while not game.finished:
            if game.between_hands:
                game = g.next_hand(game)
                continue
            hand = game.current
            seat = g.waiting_for(hand)
            if seat == HUMAN and hand.phase is Phase.CLAIM:
                moves = {a.move for a in hand.call_actions(HUMAN)}
                if g.Move.RON in moves and moves & {g.Move.CHI, g.Move.PON}:
                    return game
            action = decide(hand, seat, g.CpuLevel.NORMAL)
            if seat == HUMAN and action.move is g.Move.RIICHI:
                action = g.discard(HUMAN, action.tile)
            game = g.apply(game, action)
    raise AssertionError("ロンも鳴きもできる局面が見つからない")


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
    # 自分が切る番か、鳴き（またはロン）の返事を求められている（新しい対局は、毎回配牌が違う）
    assert data["discard"] is True or "pass" in action_keys(at)
    assert len(data["tiles"]) in (13, 14)
    body = text(at)
    assert "東 1 局" in body and "供託" in body and "残り" in body
    check_tile_images(page_html(at))


def test_new_page_has_no_missing_ruby():
    at = open_game()
    assert stored(at, GAME_NAME) is not None
    no_missing_ruby(at)


def test_discarding_advances_the_cpus_and_shows_their_moves():
    game = first_turn()
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    assert data["discard"] is True
    rev = data["rev"]
    pick_tile(at, data["tiles"][-1]["id"])
    after = component_data(at, "mjdojo_tile_hand") if at.get("bidi_component") else None
    html = page_html(at)
    if after is not None and after["discard"]:
        assert after["rev"] != rev
        assert "mj-moves" in html and "mj-new" in html          # CPU の動きと、新しく切られた牌の印
    saved_game = json.loads(stored(at, GAME_NAME))
    assert saved_game["mark"] > len(game.current.actions)       # 自分が切ったところまでを「見た」にする
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
    at = open_game({GAME_NAME: saved(first_turn())})
    at.segmented_control(key="gm_w_hint").set_value("オフ").run()
    assert "コーチはオフ" in text(at)
    at.segmented_control(key="gm_w_hint").set_value("打った後に答え合わせ").run()
    assert "自分で考えて切って" in text(at)
    data = component_data(at, "mjdojo_tile_hand")
    pick_tile(at, data["tiles"][-1]["id"])
    no_missing_ruby(at)


# ---------------------------------------------------------------- 鳴き（Phase 4）


def test_call_prompt_offers_calls_and_pass_with_the_coach_table():
    game = find("call")
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    keys = action_keys(at)
    assert data["discard"] is False and keys[-1] == "pass" and len(keys) >= 2
    assert all(k == "chi" or k.startswith("call:") for k in keys[:-1])
    assert "できます" in text(at)
    assert any(e.label.startswith("鳴きの判断") for e in at.expander)          # 打つ前のヒント（初期値）なら、比べ方の表
    assert "mj-call-table" in page_html(at)
    no_missing_ruby(at)
    check_tile_images(page_html(at))
    press_action(at, "pass")
    assert not at.exception
    assert any(c.action.move is g.Move.PASS for c in at.session_state["gm_calls"])


def test_calling_records_the_decision_and_shows_the_meld():
    game = find("call")
    at = open_game({GAME_NAME: saved(game)})
    keys = action_keys(at)
    if keys[0] == "chi":                                        # チーの組み合わせが 2 つ以上：組み合わせを選ぶ画面へ
        press_action(at, "chi")
        keys = action_keys(at)
        assert keys[-1] == "back"
    press_action(at, keys[0])
    assert not at.exception
    calls = at.session_state["gm_calls"]
    assert calls and calls[-1].called
    rebuilt = g.from_save(json.loads(stored(at, GAME_NAME))["save"])
    assert any(a.seat == HUMAN and a.move in (g.Move.CHI, g.Move.PON) for h in rebuilt.hands for a in h.actions)
    no_missing_ruby(at)


def test_after_a_call_the_kuikae_tiles_are_locked_and_the_melds_are_shown():
    game = find("after_call")
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    hand = game.current
    assert data["discard"] is True and data["lockedIds"]
    assert {kind_of(t) for t in data["lockedIds"]} <= set(hand.forbidden)
    assert data["melds"] and all(len(m["tiles"]) >= 3 for m in data["melds"])
    assert "喰い替え" in data["lockedNote"]
    locked = data["lockedIds"][0]
    pick_tile(at, locked)                                       # 切れない牌は、押しても受け付けない
    assert g.from_save(json.loads(stored(at, GAME_NAME))["save"]).current.actions == hand.actions
    no_missing_ruby(at)


def test_kifu_viewer_opens_at_the_end_of_a_hand():
    game = find("hand_end_win")
    at = open_game({GAME_NAME: saved(game)})
    assert not at.get("bidi_component") or all(
        getattr(c.proto, "component_name", "") != "mjdojo_kifu_view" for c in at.get("bidi_component")
    )
    click(at, "牌譜を見る")
    data = component_data(at, "mjdojo_kifu_view")
    record = data["record"]
    assert record["steps"] and record["title"] and len(data["images"]) == 136
    assert any(step["mine"] for step in record["steps"])
    assert record["steps"][-1]["text"].startswith("結果：")
    # 説明の文には、読み（ルビ）を付けた HTML を添える。ルビを除くと、元の文（エスケープしたもの）に戻る
    from html import escape
    for step in record["steps"]:
        assert re.sub(r"<rt>.*?</rt>|</?ruby>", "", step["html"]) == escape(step["text"])
        if step["note"]:
            assert re.sub(r"<rt>.*?</rt>|</?ruby>", "", step["note"]["labelHtml"]) == escape(step["note"]["label"])
    assert "<ruby>配牌<rt>" in record["startHtml"]
    no_missing_ruby(at)


def test_ron_and_call_prompt_does_not_recommend_the_call():
    """ロンも鳴きもできるとき、鳴きに ◎ を付けない（あがるのがいちばん）。鳴くと「ロンできた」と評価する"""
    game = ron_and_call()
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    labels = {a["key"]: a["label"] for a in data["actions"]}
    assert "ron" in labels and "pass" in labels and any(key.startswith("call:") or key == "chi" for key in labels)
    assert not any(label.startswith("◎") for label in labels.values())
    assert not any("鳴きの判断" in e.label for e in at.expander)
    no_missing_ruby(at)
    keys = [key for key in labels if key.startswith("call:")]
    if not keys:                                        # チーの組み合わせが 2 つ以上：「チー」→ 組み合わせ
        press_action(at, "chi")
        keys = [key for key in action_keys(at) if key.startswith("call:")]
    press_action(at, keys[0])
    decision = at.session_state["gm_calls"][-1]
    assert decision.ron_missed and decision.label == "ロンできた"


def test_recommended_kan_is_offered_in_the_headline_instead_of_a_discard():
    """カンをすすめるときは、案内がカン（「カンできます　おすすめ：暗槓 ○」）で、ボタンに ◎。打牌の ◎ は付けない（どちらか迷わないように）"""
    game = find("kan_offer")
    at = open_game({GAME_NAME: saved(game)})
    data = component_data(at, "mjdojo_tile_hand")
    labels = {a["key"]: a["label"] for a in data["actions"]}
    assert any(key.startswith("kan:") and label.startswith("◎") for key, label in labels.items()), labels
    assert "カンできます" in text(at) and "嶺上牌を 1 枚引ける" in text(at)
    assert all(tile["mark"] == "" for tile in data["tiles"])
    no_missing_ruby(at)


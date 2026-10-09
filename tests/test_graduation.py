"""卒業判定（engine/graduation.py・ui/graduation_view.py・views/graduation.py）のテスト"""
from __future__ import annotations

import json
import re
from pathlib import Path

from html_helpers import page_html, page_parts
from streamlit.testing.v1 import AppTest

from engine.game_records import GOAL_GAMES, GameRecord, Tally
from engine.graduation import DECLARE, RECENT, WHERE_DRILL, WHERE_GAME, WHERE_PLAY, drill_check, report
from engine.srs import Deck, dump_deck
from ui.components.browser_store import initial_state
from ui.game_session import GAME_HISTORY_NAME
from ui.graduation_view import condition_html, summary_html
from ui.progress_store import DRILL_PREFIX
from ui.ruby import Rubifier, missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
DRILLS = ("han", "valid", "yaku", "table", "fu", "win", "danger", "manners")


def deck(recent: str) -> Deck:
    return Deck(answered=len(recent), right=recent.count("1"), recent=recent)


def plain_game(time: int, *, rank: int = 2, deal_ins: int = 0, misses: int = 0, bad_calls: int = 0, **changes) -> GameRecord:
    values = {"time": time, "seed": time, "length": "east", "deal": 0, "draw": 0, "cpu_deal": 0, "cpu_draw": 0, "cpu_level": "normal",
              "hinted": False, "rank": rank, "score": 25000, "hands": 5, "deal_ins": deal_ins, "misses": misses,
              "tally": Tally(decisions=40, followed=30, calls=bad_calls, bad_calls=bad_calls, good=35)}
    values.update(changes)
    return GameRecord(**values)


def perfect_decks() -> dict[str, Deck]:
    return {**{kind: deck("1" * RECENT) for kind in DRILLS}, DECLARE: deck("1" * RECENT)}


def perfect_games() -> list[GameRecord]:
    return [plain_game(1000 + i, rank=1 + i % 3) for i in range(GOAL_GAMES)]       # 平均順位 2.0


def test_nothing_yet():
    result = report({}, [])
    assert [c.key for c in result.conditions] == ["yaku", "points", "calls", "defense", "manners", "record"]
    assert result.done == 0 and not result.passed
    checks = [check for condition in result.conditions for check in condition.checks]
    assert not any(check.ready or check.passed for check in checks)
    assert {check.where for check in checks} == {WHERE_DRILL, WHERE_GAME, WHERE_PLAY}


def test_drill_check_uses_the_recent_answers():
    decks = {"han": deck("0" * 30 + "1" * 16 + "0" * 4)}              # 前に間違えていても、直近 20 問で 16 問正解なら 80%
    check = drill_check(decks, "han", 80)
    assert check.passed and check.ready and check.status == "直近 20 問で 16 問正解（80%）" and check.name == "「役の翻数」のドリル"
    assert not drill_check({"han": deck("1" * 15 + "0" * 5)}, "han", 80).passed
    few = drill_check({"han": deck("1" * 19)}, "han", 80)
    assert not few.ready and not few.passed and few.status == "いままでに 19 問。判定は 20 問たまってから"
    declare = drill_check({DECLARE: deck("1" * 17 + "0" * 3)}, DECLARE, 90, name="点数の申告", unit="回")
    assert not declare.passed and declare.status == "直近 20 回で 17 回正解（85%）" and declare.goal == "直近 20 回で 90% 以上"
    assert drill_check({}, DECLARE, 90, unit="回").status == "まだ申告していない"


def test_everything_passed():
    result = report(perfect_decks(), perfect_games())
    assert result.passed and result.done == 6
    record = next(c for c in result.conditions if c.key == "record").checks[0]
    assert record.status == f"直近 {GOAL_GAMES} 戦で 2.00" and record.passed
    defense = next(c for c in result.conditions if c.key == "defense").checks[1]
    assert defense.status == f"直近 {GOAL_GAMES} 戦で 0.0%（150 局で 0 回）"


def test_game_conditions():
    decks = perfect_decks()
    # 1 回でも役なしの鳴き・見落としがあれば、直近 10 戦のうちは満たさない
    games = perfect_games()
    games[-1] = plain_game(5000, bad_calls=1)
    calls = next(c for c in report(decks, games).conditions if c.key == "calls")
    assert [check.passed for check in calls.checks] == [True, False, True]
    assert calls.checks[1].status == "直近 10 戦で 1 回（鳴いた 1 回のうち）"
    games[-1] = plain_game(5000, misses=2)
    assert [check.passed for check in next(c for c in report(decks, games).conditions if c.key == "calls").checks] == [True, True, False]
    # 放銃率：150 局で 23 回（15.3%）は、15% を超える
    games = perfect_games()
    for index in range(23):
        games[index] = plain_game(1000 + index, rank=1 + index % 3, deal_ins=1)
    defense = next(c for c in report(decks, games).conditions if c.key == "defense")
    assert defense.checks[1].status == "直近 30 戦で 15.3%（150 局で 23 回）" and not defense.checks[1].passed
    # 対局が足りないうちは、判定しない（いまの値は出す）
    short = report(decks, perfect_games()[:12])
    record = next(c for c in short.conditions if c.key == "record").checks[0]
    assert not record.ready and not record.passed and record.status == "いまは 12 戦で 2.00。判定は 30 戦たまってから"
    # 数えない対局（補正あり・ヒントあり・鳴きなし・半荘戦）
    others = [plain_game(1, deal=25), plain_game(2, hinted=True), plain_game(3, rules=(("calls", False),)), plain_game(4, length="south")]
    assert next(c for c in report(decks, others).conditions if c.key == "record").checks[0].status == "対象の対局が、まだ無い"
    # 平均順位 2.5 ちょうどは達成
    edge = [plain_game(1000 + i, rank=2 + i % 2) for i in range(GOAL_GAMES)]
    assert next(c for c in report(decks, edge).conditions if c.key == "record").passed


def test_views():
    rb = Rubifier()
    result = report({"han": deck("1" * 20)}, [])
    html = summary_html(result, rb)
    assert "満たした条件　0 / 6" in re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", html))
    body = condition_html(1, result.conditions[0], rb)
    assert "1 / 3" in body and "mj-mark-ok" in body and "mj-mark-wait" in body
    assert "卒業" in summary_html(report(perfect_decks(), perfect_games()), Rubifier())


# ---------------------------------------------------------------- ページ


def open_page(known: dict | None = None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.session_state[STORE_STATE] = initial_state(known or {})
    at.switch_page("views/graduation.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at: AppTest) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", page_html(at)))


def test_page_without_records():
    at = open_page()
    body = text(at)
    assert "満たした条件　0 / 6" in body and "まだ答えていない" in body and "学びの進み具合" in body
    links = [e.proto.label for e in at.get("page_link")]
    assert "ドリル：役の翻数" in links and "CPU と対局" in links and "カリキュラム" in links
    assert missing_ruby(page_parts(at)) == []


def test_page_with_everything_passed():
    known = {DRILL_PREFIX + kind: dump_deck(d) for kind, d in perfect_decks().items()}
    known[GAME_HISTORY_NAME] = json.dumps([g.to_dict() for g in perfect_games()])
    at = open_page(known)
    body = text(at)
    assert "○ 卒業" in body and "すべて満たしています" in body
    assert not [e for e in at.get("page_link") if e.proto.label.startswith("ドリル：")]       # 満たした条件には、練習のリンクを出さない
    assert missing_ruby(page_parts(at)) == []


def test_game_link_sets_the_counted_conditions():
    from test_game_page import open_game, text

    at = open_game()
    at.query_params["graduation"] = "1"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    settings = at.session_state["gm_settings"]
    assert (settings["deal"], settings["draw"], settings["cpu_deal"], settings["cpu_draw"]) == (0, 0, 0, 0)
    assert settings["length"] == "east" and settings["cpu_level"] == "normal" and settings["hint"] == "after" and not settings["auto"]
    assert "卒業判定に数える設定にしました" in " ".join(i.value for i in at.info)
    next(b for b in at.button if b.key == "gm_b_graduation_new").click().run()
    config = at.session_state["gm_game"].config
    assert config.luck.is_off and config.cpu_luck.is_off and config.length.value == "east"
    assert "この対局は、卒業判定に数える" in text(at)
    assert "この対局は、卒業判定に数えない（ツキ補正あり" in text(open_game())             # 初期設定（補正「弱」）の対局は数えない

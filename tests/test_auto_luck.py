"""おまかせ補正（engine/auto_luck.py・ui/auto_state.py・一人練習と CPU 戦の設定）のテスト"""
from __future__ import annotations

import json

import pytest
from test_practice_session import FakeStore

from engine.auto_luck import (
    LEVELS,
    MIN_DRILLS,
    MIN_GAMES,
    MIN_HANDS,
    RECENT_GAMES,
    RECENT_HANDS,
    Play,
    Rate,
    current_level,
    decide,
    decision_data,
    decision_from_data,
    drill_rate,
    game_play,
    practice_play,
    reason,
    start_level,
)
from engine.drills import KINDS
from engine.game_records import GameRecord, Tally
from engine.records import HandRecord
from engine.srs import Deck, dump_deck
from ui.auto_state import clean_auto, last_change, step_values, turn_on
from ui.auto_view import GAME, PRACTICE, auto_html, news_text, rule_text
from ui.game_session import GAME_HISTORY_NAME, GAME_SETTINGS_NAME, GameSession
from ui.game_session import clean_settings as clean_game_settings
from ui.practice_session import HISTORY_NAME, SETTINGS_NAME, PracticeSession, clean_settings
from ui.progress_store import DRILL_PREFIX
from ui.ruby import Rubifier


def hand(time: int, best: int, decisions: int = 10, *, hinted: bool = False, target: str = "", level: int = 75) -> HandRecord:
    return HandRecord(time=time, seed=time, deal=level, draw=level, hinted=hinted, win=False, turn=18, riichi=False, tenpai=False,
                      decisions=decisions, best=best, target=target)


def game(time: int, good: int, decisions: int = 50, *, hinted: bool = False, level: int = 25) -> GameRecord:
    return GameRecord(time=time, seed=time, length="east", deal=level, draw=level, cpu_deal=0, cpu_draw=0, cpu_level="normal",
                      hinted=hinted, rank=2, score=25000, hands=5, tally=Tally(decisions=decisions, followed=0, good=good))


def play(rate: tuple[int, int], count: int = 10, used: int | None = None) -> Play:
    return Play(Rate(*rate), count, count if used is None else used)


# ---------------------------------------------------------------- 段階と判断


def test_start_level_is_the_nearest_stage():
    assert [start_level(d, d) for d in (100, 75, 60, 50, 40, 25, 10, 0)] == [75, 75, 50, 50, 50, 25, 0, 0]
    assert start_level(60, 40) == 50 and start_level(37, 38) == 50          # 同じ近さ（25 と 50 の真ん中）なら、強いほう
    assert current_level(50, 50) == 50 and current_level(55, 45) == 50 and current_level(100, 100) == 75


def test_drill_rate_needs_enough_answers():
    decks = {"yaku": Deck(answered=12, right=12, recent="1" * 12), "han": Deck(answered=30, right=20, recent="0" * 15 + "1" * 15)}
    rate = drill_rate(decks, KINDS)
    assert rate == Rate(10 + 10, 10 + 10)               # 種類ごとに直近 10 問まで
    assert drill_rate({"yaku": decks["yaku"]}, KINDS) is None        # 10 問ぶんしか無い（20 問に足りない）
    assert drill_rate({}, KINDS) is None and MIN_DRILLS == 20


def test_practice_play_uses_recent_unhinted_hands_after_the_change():
    records = [
        hand(100, 0),                              # 段階を変える前
        hand(200, 9), hand(210, 9, hinted=True),   # ヒントを見た局は数えない
        hand(220, 0, target="pinfu"),              # 役指定練習の局も数えない
        hand(230, 0, decisions=0),                 # 自分で選んだ打牌が無い局（配牌であがった、など）
        hand(240, 0, level=100),                   # ほかの補正で打った局（おまかせを入れたときに打っていた局）
        *[hand(300 + i, 8) for i in range(RECENT_HANDS)],
    ]
    result = practice_play(records, since=150, level=75)
    assert result.count == 1 + RECENT_HANDS and result.used == RECENT_HANDS
    assert result.rate == Rate(8 * RECENT_HANDS, 10 * RECENT_HANDS)          # 直近 10 局だけ（200 の局は外れる）
    assert practice_play(records, since=10_000, level=75) == Play(Rate(0, 0), 0, 0)
    assert practice_play(records, since=150, level=50).count == 0


def test_game_play_counts_good_turns():
    records = [game(100, 50), game(200, 40), game(210, 50, hinted=True), game(220, 0, level=50), *[game(300 + i, 30) for i in range(RECENT_GAMES)]]
    result = game_play(records, since=150, level=25)
    assert result.count == 1 + RECENT_GAMES and result.used == RECENT_GAMES and result.rate == Rate(90, 150)


def test_decide_moves_one_stage_at_a_time():
    good, bad, middle = (9, 10), (5, 10), (7, 10)
    assert decide(75, play(good, 3), MIN_HANDS, None).waiting == 2           # 5 局たまるまで、判断しない
    assert decide(75, play(good), MIN_HANDS, None).level == 50
    assert decide(75, play(good), MIN_HANDS, Rate(16, 20)).level == 50       # どちらも 80% 以上
    assert decide(75, play(good), MIN_HANDS, Rate(15, 20)).level == 75       # ドリルが 80% に届かない
    assert decide(50, play(bad), MIN_HANDS, Rate(20, 20)).level == 75        # 打牌が 60% より低い
    assert decide(50, play(good), MIN_HANDS, Rate(11, 20)).level == 75       # ドリルが 60% より低い
    assert decide(50, play(middle), MIN_HANDS, None).level == 50
    assert decide(0, play(good), MIN_HANDS, None).level == 0                 # もう「なし」
    assert decide(75, play(bad), MIN_HANDS, None).level == 75                # いちばん強い段階より上はない
    assert decide(60, play(good), MIN_HANDS, None).level == 50               # 段階どおりでない値は、強から数える
    down, up = decide(25, play(good), MIN_HANDS, None), decide(25, play(bad), MIN_HANDS, None)
    assert (down.changed, up.changed, decide(25, play(middle), MIN_HANDS, None).changed) == (-1, 1, 0)
    assert (down.before, down.level, up.level) == (25, 0, 50) and down.judged


def test_reason_texts():
    waiting = decide(75, play((9, 10), 3), MIN_HANDS, None)
    assert reason(waiting, unit="局", counter="局") == "ヒントを見ずに打った局が、あと 2 局たまったら判断します。"
    games = decide(25, play((9, 10), 1), MIN_GAMES, None)
    assert reason(games, unit="対局", counter="回") == "ヒントを見ずに打った対局が、あと 1 回たまったら判断します。"
    down = decide(75, play((90, 100)), MIN_HANDS, Rate(17, 20))
    assert reason(down, unit="局", counter="局") == (
        "打牌の評価 90%（直近 10 局）・ドリルの正答率 85%（直近 20 問）。どちらも 80% 以上なので、補正を「強」から「中」に下げました。")
    assert reason(down, unit="局", counter="局", ahead=True).endswith("どちらも 80% 以上なので、次の局を始めるとき、補正を「強」から「中」に下げます。")
    up = decide(50, play((5, 10)), MIN_HANDS, None)
    assert reason(up, unit="局", counter="局").endswith("。打牌の評価が 60% より低いので、補正を「中」から「強」に上げました。")
    up2 = decide(50, play((9, 10)), MIN_HANDS, Rate(5, 20))
    assert "ドリルの正答率が 60% より低いので" in reason(up2, unit="局", counter="局")             # どれが低かったのかを書く
    stay = decide(50, play((7, 10)), MIN_HANDS, None)
    assert reason(stay, unit="局", counter="局").endswith("補正は「中」のままです（80% 以上で下げ、60% より低いものがあれば上げます）。")
    # 百分率は切り捨てで書く（79.9% を「80%」と書くと、「80% 以上で下げる」と食い違って見える）
    edge = decide(50, play((119, 149)), MIN_HANDS, None)
    assert edge.level == 50 and edge.play.rate.percent == 79 and "打牌の評価 79%" in reason(edge, unit="局", counter="局")
    assert reason(decide(0, play((9, 10)), MIN_HANDS, None), unit="局", counter="局").endswith("80% 以上です。補正は、もう「なし」です。")
    assert reason(decide(75, play((1, 10)), MIN_HANDS, None), unit="局", counter="局").endswith("補正は、いちばん強い段階の「強」のままです。")


def test_decision_data_round_trip_and_broken_data():
    decision = decide(75, play((18, 20), 6, 5), MIN_HANDS, Rate(17, 20))
    data = decision_data(decision, 1_700_000_000)
    back, time = decision_from_data(json.loads(json.dumps(data)))
    assert time == 1_700_000_000 and (back.before, back.level, back.play.rate, back.drill) == (75, 50, Rate(18, 20), Rate(17, 20))
    assert reason(back, unit="局", counter="局") == reason(decision, unit="局", counter="局")
    no_drill = decision_data(decide(50, play((1, 10)), MIN_HANDS, None), 5)
    assert "dr" not in no_drill and decision_from_data(no_drill)[0].drill is None
    for broken in (None, [], {**data, "from": 60}, {**data, "to": data["from"]}, {**data, "from": False}, {**data, "pr": 99},
                   {**data, "t": -1}, {**data, "pn": "20"}, {**data, "dr": 21}, {k: v for k, v in data.items() if k != "dn"}):
        assert decision_from_data(broken) is None, broken


# ---------------------------------------------------------------- 設定（ui/auto_state.py）


def test_clean_auto_keeps_only_valid_values():
    result = {"auto": False, "auto_since": 0, "auto_last": None}
    clean_auto({"auto": "yes", "auto_since": True, "auto_last": {"from": 1}}, result)
    assert result == {"auto": False, "auto_since": 0, "auto_last": None}
    good = decision_data(decide(75, play((9, 10)), MIN_HANDS, None), 10)
    clean_auto({"auto": True, "auto_since": 123, "auto_last": good}, result)
    assert result == {"auto": True, "auto_since": 123, "auto_last": good}
    clean_auto({"auto_last": None}, result)
    assert result["auto_last"] is None
    assert clean_settings({"auto": True, "auto_since": 5})["auto"] is True
    assert clean_game_settings({"auto": True, "auto_since": 5})["auto_since"] == 5


def test_turn_on_and_step_values():
    assert turn_on({"deal": 60, "draw": 40}, 99) == {"auto": True, "deal": 50, "draw": 50, "auto_since": 99, "auto_last": None}
    settings = {"deal": 75, "draw": 75, "auto_since": 400}
    down = decide(75, play((9, 10)), MIN_HANDS, None)
    values = step_values(settings, down, 500)
    assert values["deal"] == values["draw"] == 50 and values["auto_since"] == 500 and decision_from_data(values["auto_last"])[1] == 500
    stay = decide(75, play((7, 10)), MIN_HANDS, None)
    assert step_values(settings, stay, 500) is None
    assert step_values({"deal": 80, "draw": 70, "auto_since": 400}, stay, 500) == {"deal": 75, "draw": 75}     # 段階にそろえるだけ（数え直さない）
    assert step_values({**settings, "auto_since": 9_999}, stay, 500) == {"auto_since": 500}   # 先の時刻は、いまから数え直す
    assert last_change({"auto_last": values["auto_last"]})[0].level == 50 and last_change({}) is None


# ---------------------------------------------------------------- 一人練習


def practice_session(store: FakeStore, *, now: list[float]) -> PracticeSession:
    numbers = iter(range(300, 400))
    session = PracticeSession({}, store, now=lambda: now[0], new_seed=lambda: next(numbers))
    session.start()
    return session


def put_history(store: FakeStore, records: list[HandRecord]) -> None:
    store.set(HISTORY_NAME, json.dumps([r.to_dict() for r in records]))


def test_practice_auto_lowers_the_luck_after_good_hands():
    store, now = FakeStore(), [1000.0]
    session = practice_session(store, now=now)
    assert not session.auto and session.settings["deal"] == 75
    session.update_settings({"deal": 70, "draw": 80})
    session.set_auto(True)
    assert session.auto and session.settings["deal"] == session.settings["draw"] == 75 and session.settings["auto_since"] == 1000
    assert session.auto_preview().waiting == MIN_HANDS
    # 判断に足りないうちは、新しい局でも変えない
    put_history(store, [hand(1100 + i, 9) for i in range(MIN_HANDS - 1)])
    session = practice_session(store, now=now)
    now[0] = 2000.0
    session.begin()
    assert session.settings["deal"] == 75 and session.take_auto_news() is None and session.state.config.luck.deal == 75
    # 5 局たまった：次の局から「中」
    put_history(store, [hand(1100 + i, 9) for i in range(MIN_HANDS)])
    session = practice_session(store, now=now)
    assert session.auto_preview().level == 50
    session.begin()
    assert session.settings["deal"] == session.settings["draw"] == 50 and session.state.config.luck.deal == 50
    assert session.settings["auto_since"] == 2000
    news = session.take_auto_news()
    assert news is not None and news.changed == -1 and session.take_auto_news() is None       # 知らせは 1 回だけ
    assert news_text(news) == "おまかせ：ツキ補正を「強」から「中」に下げました（理由は、設定のツキ補正のところ）。"
    # 設定はブラウザに残る（開き直しても、前回の変更が分かる）
    saved = json.loads(store.get(SETTINGS_NAME))
    assert saved["auto"] is True and saved["deal"] == 50 and last_change(saved)[0].before == 75
    # 変えた直後は、また 5 局たまるまで判断しない（前の局は数えない）
    assert practice_session(store, now=now).auto_preview().waiting == MIN_HANDS


def test_practice_auto_raises_the_luck_and_ignores_numbered_hands():
    store, now = FakeStore(), [1000.0]
    session = practice_session(store, now=now)
    session.update_settings({"deal": 25, "draw": 25})
    session.set_auto(True)
    put_history(store, [hand(1100 + i, 4, level=25) for i in range(MIN_HANDS)])
    session = practice_session(store, now=now)
    session.begin(123)                              # 番号を指定した局では、決め直さない
    assert session.settings["deal"] == 25
    session.again()
    assert session.settings["deal"] == 25
    session.begin()
    assert session.settings["deal"] == 50 and session.take_auto_news().changed == 1


def test_practice_auto_uses_the_drills_too():
    store, now = FakeStore(), [1000.0]
    session = practice_session(store, now=now)
    session.update_settings({"deal": 50, "draw": 50})
    session.set_auto(True)
    put_history(store, [hand(1100 + i, 9, level=50) for i in range(MIN_HANDS)])
    assert practice_session(store, now=now).auto_preview().level == 25           # ドリルの答えが足りない：打牌だけで決める
    store.set(DRILL_PREFIX + "yaku", dump_deck(Deck(answered=10, right=10, recent="1" * 10)))
    store.set(DRILL_PREFIX + "han", dump_deck(Deck(answered=10, right=0, recent="0" * 10)))
    preview = practice_session(store, now=now).auto_preview()
    assert preview.drill == Rate(10, 20) and preview.level == 75                  # ドリルが 50%：1 段階戻す


def test_turning_auto_off_keeps_the_current_luck():
    store, now = FakeStore(), [1000.0]
    session = practice_session(store, now=now)
    session.update_settings({"deal": 30, "draw": 30})
    session.set_auto(True)
    assert session.settings["deal"] == 25
    session.set_auto(True)                          # もう入っている：数え直さない
    assert session.settings["auto_since"] == 1000
    session.set_auto(False)
    assert not session.auto and session.settings["deal"] == 25


# ---------------------------------------------------------------- CPU 戦


def game_session(store: FakeStore, *, now: list[float]) -> GameSession:
    numbers = iter(range(500, 600))
    session = GameSession({}, store, now=lambda: now[0], new_seed=lambda: next(numbers))
    session.start()
    return session


def test_game_auto_changes_only_my_luck():
    store, now = FakeStore(), [1000.0]
    session = game_session(store, now=now)
    session.update_settings({"cpu_deal": 10, "cpu_draw": 10})
    session.set_auto(True)
    assert session.settings["deal"] == 25                    # 初期値の「弱」から
    store.set(GAME_HISTORY_NAME, json.dumps([game(1100 + i, 45).to_dict() for i in range(MIN_GAMES)]))
    session = game_session(store, now=now)
    assert session.auto_preview().level == 0
    session.begin()
    assert session.settings["deal"] == session.settings["draw"] == 0
    assert session.game.config.luck.deal == 0 and session.game.config.cpu_luck.deal == 10      # CPU の補正は変えない
    assert session.take_auto_news().level == 0
    assert json.loads(store.get(GAME_SETTINGS_NAME))["auto_since"] == 1000
    session.begin(77)                                        # 番号を指定した対局では、決め直さない
    assert session.settings["auto_since"] == 1000


# ---------------------------------------------------------------- 表示


def test_auto_html_explains_the_state():
    preview = decide(75, play((9, 10), 2), MIN_HANDS, None)
    html = auto_html(preview, None, Rubifier(), mode=PRACTICE, hint_before=True)
    assert "いまの段階は「強」" in html and "数えません" in html and "あと 3 局" in html
    last = (decide(75, play((9, 10)), MIN_HANDS, None), 1_700_000_000)
    html = auto_html(decide(50, play((9, 10), 2), MIN_HANDS, None), last, Rubifier(), mode=GAME, hint_before=False)
    assert "前回の変更（2023/11/15）" in html and "数えません" not in html and "対局" in html
    assert "直近 10 局まで" in rule_text(PRACTICE) and "いちばん安全な牌" in rule_text(GAME) and "2 回たまるまで" in rule_text(GAME)
    assert set(LEVELS) == {0, 25, 50, 75}


@pytest.mark.parametrize("mode", [PRACTICE, GAME])
def test_every_auto_text_mentions_both_thresholds(mode):
    text = rule_text(mode)
    assert "80% 以上なら 1 段階下げ" in text and "60% より低いものがあれば 1 段階上げる" in text


# ---------------------------------------------------------------- ページ


def test_practice_page_auto_toggle_and_news():
    from html_helpers import page_parts
    from test_practice_page import click, open_practice, page_text

    from ui.ruby import missing_ruby

    at = open_practice()
    assert not at.slider(key="pr_w_deal").disabled
    at.toggle(key="pr_w_auto").set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["pr_settings"]["auto"] is True
    assert at.slider(key="pr_w_deal").disabled and at.slider(key="pr_w_draw").disabled and at.button_group(key="pr_w_preset").disabled
    body = page_text(at)
    assert "おまかせ：いまの段階は「強」（配牌・ツモの良さ 75）。" in body and "数えません" in body       # ヒントが「打つ前」のまま
    assert missing_ruby(page_parts(at)) == []
    # ヒントを見ずに打った局が 5 局たまった（成績を直接入れる）→ 新しい局で「中」に下がる
    at.button_group(key="pr_w_hint").set_value("打った後に答え合わせ").run()
    # おまかせを始めたのが少し前で、そのあとに 5 局打った、ことにする（局の時刻が、新しい局を始める時刻より前になるように）
    since = at.session_state["pr_settings"]["auto_since"] - 100
    at.session_state["pr_settings"] = {**at.session_state["pr_settings"], "auto_since": since}
    at.session_state["pr_history"] = [hand(since + 1 + i, 9) for i in range(MIN_HANDS)]
    at.run()
    assert "次の局を始めるとき、補正を「強」から「中」に下げます" in page_text(at) and "数えません" not in page_text(at)
    click(at, "この局をやめて、新しい局を始める")
    assert [t.value for t in at.toast] == ["おまかせ：ツキ補正を「強」から「中」に下げました（理由は、設定のツキ補正のところ）。"]
    assert at.session_state["pr_state"].config.luck.deal == 50 and at.slider(key="pr_w_deal").value == 50
    assert "ツキ補正：配牌 50・ツモ 50（おまかせ：中）" in page_text(at)                    # いつも見える札にも、段階の名前
    body = page_text(at)
    assert "いまの段階は「中」" in body and "前回の変更（" in body and "あと 5 局たまったら判断します" in body
    # おまかせを切ると、スライダーがまた動かせる（補正は、そのとき の段階のまま）
    at.toggle(key="pr_w_auto").set_value(False).run()
    assert not at.slider(key="pr_w_deal").disabled and at.slider(key="pr_w_deal").value == 50 and "いまの段階は" not in page_text(at)


def test_game_page_auto_toggle():
    from html_helpers import page_parts
    from test_game_page import open_game, text

    from ui.ruby import missing_ruby

    at = open_game()
    at.toggle(key="gm_w_auto").set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.slider(key="gm_w_deal").disabled and not at.slider(key="gm_w_cpu_deal").disabled
    body = text(at)
    assert "おまかせ：いまの段階は「弱」（配牌・ツモの良さ 25）。" in body and "あと 2 回たまったら判断します" in body
    assert "いちばん安全な牌" in body
    assert missing_ruby(page_parts(at)) == []

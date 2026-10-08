"""CPU との対局の表示（ui/game_view.py）のテスト。HTML の形と、文の中身を確かめる"""
from __future__ import annotations

import re

import pytest
from html_helpers import check_html, check_tile_images, text_of

from engine import game as g
from engine.game import HUMAN, GameConfig, Phase
from engine.game_coach import judge_turn, ron_preview, tsumo_preview, turn_advice
from engine.tiles import kind_of, parse_tiles
from tests.game_helpers import build_hand, game_of
from ui.game_view import (
    advice_headline_html,
    claim_headline_html,
    danger_html,
    decision_headline_html,
    gain_text,
    reveal_html,
    scores_html,
    status_html,
    table_html,
)
from ui.ruby import Rubifier

OTHERS = ["147m258p369s3467z", "258m369p147s3467z", "369m147p258s3557z"]
#: 1 巡ずつ切ったあとの河（最初のツモではない＝天和・地和にならない）
RIVERS = ("9m", "9p", "9s", "8m")
#: 案内の上の行に入れてよい文字数の目安（幅 375px の画面で 1 行に収まる長さ。牌の絵は 1 文字ぶん）
HEAD_CHARS = 21


def rb() -> Rubifier:
    return Rubifier()


def k(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def tile_in(hand: g.HandState, seat: int, text: str) -> int:
    return next(t for t in hand.players[seat].tiles if kind_of(t) == k(text))


def lines_of(html: str) -> tuple[str, str]:
    """案内（ヘッドライン）を、上の行と下の行の文字に分ける"""
    check_html(html)
    check_tile_images(html)
    assert html.count('class="mj-headline ') == 1
    subs = re.findall(r'<span class="mj-sub mj-headline-sub">(.*?)</span>(?=</div>)', html, flags=re.DOTALL)
    assert len(subs) <= 1, "下の行は 1 つだけ"
    head_html = html.split('<span class="mj-sub mj-headline-sub">')[0]
    head = re.sub(r" +", " ", text_of(head_html)).strip()          # 牌の絵の前後の空白は 1 つにまとめる
    return head, text_of(subs[0]).strip() if subs else ""


def head_width(head: str) -> int:
    """上の行の幅の目安（全角 1、半角の数字や空白は 0.5 として数える）"""
    return round(sum(0.5 if ch.isascii() else 1 for ch in head))


# ---------------------------------------------------------------- 手牌のすぐ上の案内（2 行に固定）


def test_free_tenpai_headline_keeps_to_two_lines():
    hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="5z")
    advice = turn_advice(hand, HUMAN)
    head, sub = lines_of(advice_headline_html(advice, hand, rb(), win=None, can_nine=False))
    assert head.startswith("聴牌にとれます") and head.endswith("切り") and "白" in head
    assert sub.startswith("待ち 2 種 ")
    if advice.riichi is not None and advice.riichi.recommend_riichi:
        assert "リーチで" in head and sub.endswith("先に「◎ リーチ」を押す")
    else:
        assert "ダマ" in sub
    assert head_width(head) <= HEAD_CHARS


def test_free_headline_puts_the_acceptance_on_the_second_line():
    hand = build_hand(["13m479p2589s1357z", *OTHERS], turn=0, drawn="9m")
    advice = turn_advice(hand, HUMAN)
    head, sub = lines_of(advice_headline_html(advice, hand, rb(), win=None, can_nine=True))
    assert re.match(r"\d 向聴　おすすめ：", head) and head.endswith("切り")
    assert sub.startswith("受け入れ ") and sub.endswith("九種九牌で流すこともできる")
    assert head_width(head) <= HEAD_CHARS


def _threat_hand(mine: str, drawn: str, *, two: bool = False) -> g.HandState:
    return build_hand(
        [mine, "234m567m78p345s66s", "222z444z666z1m2m3m8m", "258p369s147m3z6z7z5z"],
        turn=0, drawn=drawn, rivers=("", "9p", "1s" if two else "", ""), riichi=(None, 0, 0 if two else None, None),
        kyotaku=2 if two else 1, scores=(25_000, 24_000, 24_000 if two else 25_000, 25_000),
    )


def test_fold_headline_names_the_riichi_and_the_reason():
    hand = _threat_hand("13m479p2589s1357z", "9m")
    advice = turn_advice(hand, HUMAN)
    head, sub = lines_of(advice_headline_html(advice, hand, rb(), win=None, can_nine=False))
    assert head.startswith("下家のリーチ　オリる：") and head.endswith("切り")
    assert sub == "聴牌していないので守る。安全・現物"
    assert head_width(head) <= HEAD_CHARS
    two = _threat_hand("13m479p2589s1357z", "9m", two=True)
    head, _ = lines_of(advice_headline_html(turn_advice(two, HUMAN), two, rb(), win=None, can_nine=False))
    assert head.startswith("2 人がリーチ　オリる：")


def test_win_and_claim_headlines():
    win_hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="1z", rivers=RIVERS)
    advice = turn_advice(win_hand, HUMAN)
    head, sub = lines_of(advice_headline_html(advice, win_hand, rb(), win=tsumo_preview(win_hand, HUMAN), can_nine=False))
    assert re.fullmatch(r"あがりの形です　ツモで [\d,]+ 点", head) and "ツモ" in sub and "トン" in sub
    # 上家が 東 を切って、自分がロンできる
    hand = build_hand(["123m456p789s1122z", *OTHERS[:2], "369m147p258s355z1z"], turn=3, drawn="7z")
    game = g.apply(game_of(hand), g.discard(3, tile_in(hand, 3, "1z")))
    claim = game.current
    assert claim.phase is Phase.CLAIM and HUMAN in claim.pending
    head, sub = lines_of(claim_headline_html(claim, ron_preview(claim, HUMAN), rb(), bumped=False))
    assert head == "ロンできます　上家の 東" and re.fullmatch(r"ロンすると [\d,]+ 点（.+）", sub)
    head, sub = lines_of(claim_headline_html(claim, None, rb(), bumped=True))
    assert sub.startswith("頭ハネ：")


def test_decision_headline_shows_the_recommendation_when_not_followed():
    hand = build_hand(["13m479p2589s1357z", *OTHERS], turn=0, drawn="9m")
    advice = turn_advice(hand, HUMAN)
    other = next(t for t in hand.players[HUMAN].tiles if kind_of(t) != kind_of(advice.pick))
    decision = judge_turn(advice, g.discard(HUMAN, other), number=1)
    head, sub = lines_of(decision_headline_html(decision, rb(), aka=True))
    assert "切り：" in head and sub.startswith("おすすめは ")
    followed = judge_turn(advice, g.discard(HUMAN, advice.pick), number=1)
    head, sub = lines_of(decision_headline_html(followed, rb(), aka=True))
    assert sub == ""


# ---------------------------------------------------------------- 守備の表


def test_danger_table_does_not_repeat_the_basis_name():
    two = _threat_hand("13m479p2589s1357z", "9m", two=True)
    html = danger_html(turn_advice(two, HUMAN), rb(), detail=False)
    check_html(html)
    table = text_of(html.split("</table>")[0])
    assert "下家に対して：" in table and "対面に対して：" in table
    for name in ("現物", "無スジ", "スジ", "字牌"):
        assert f"{name}：{name}" not in table, name
    # 表の下に、表に出てきた根拠の意味を並べる（「ふつう」の表示）
    legend = text_of(html.split("</table>")[1])
    assert "現物：リーチした人の河にある牌" in legend
    one = _threat_hand("13m479p2589s1357z", "9m")
    text = text_of(danger_html(turn_advice(one, HUMAN), rb(), detail=False))
    assert "に対して" not in text and "現物" in text
    detail = text_of(danger_html(turn_advice(one, HUMAN), rb(), detail=True))
    assert "現物" in detail and "下家" in detail


# ---------------------------------------------------------------- 点数と局の終わり


def test_gain_text_breaks_down_honba_and_riichi_sticks():
    hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="1z", honba=2, kyotaku=1, rivers=RIVERS,
                      scores=(25_000, 24_000, 25_000, 26_000))
    game = g.apply(game_of(hand), g.tsumo(HUMAN))
    win = game.current.result.wins[0]
    text = gain_text(win)
    assert re.fullmatch(r"[\d,]+ 点（あがり [\d,]+ ＋ 本場 600 ＋ 供託 1,000）", text), text
    gain = win.payments[HUMAN]
    assert text.startswith(f"{gain:,} 点（あがり {gain - 1600:,} ")
    plain = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="1z", rivers=RIVERS)
    win = g.apply(game_of(plain), g.tsumo(HUMAN)).current.result.wins[0]
    assert gain_text(win) == f"{win.payments[HUMAN]:,} 点"


def test_scores_after_the_hand_show_the_settled_points():
    hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="1z")
    game = g.apply(game_of(hand), g.tsumo(HUMAN))
    html = scores_html(game, rb())
    check_html(html)
    after = game.current.result.scores
    for score in after:
        assert f"{score:,}" in html
    assert "mj-seat-turn" not in html             # 局が終わったら、手番の印は付けない


@pytest.mark.parametrize("kyotaku", [0, 2])
def test_status_table_and_reveal_render(kyotaku):
    hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="5z", rivers=("1z", "2m", "3p", "4s"), kyotaku=kyotaku)
    game = game_of(hand)
    for html in (status_html(game, rb()), table_html(hand, 0, rb()), reveal_html(hand, rb())):
        check_html(html)
        check_tile_images(html)
    assert f"供託 {kyotaku}" in text_of(status_html(game, rb()))


# ---------------------------------------------------------------- 点検の指摘を直したところ


def test_passed_ron_is_explained_at_the_end_of_the_hand():
    from ui.game_view import passed_html

    hand = build_hand(["123m456p789s1122z", *OTHERS[:2], "369m147p258s355z1z"], turn=3, drawn="7z")
    game = g.apply(game_of(hand), g.discard(3, tile_in(hand, 3, "1z")))
    game = g.apply(game, g.pass_(HUMAN))
    text = text_of(passed_html(game.current, rb()))
    assert "上家の 東 で、ロンできたが見送った。" in text and "同巡内フリテン" in text


def test_nine_terminals_reveal_shows_all_fourteen_tiles():
    hand = build_hand(["19m19p19s1234567z", *OTHERS], turn=0, drawn="5m")
    assert hand.can_nine(HUMAN)
    game = g.apply(game_of(hand), g.nine(HUMAN))
    html = reveal_html(game.current, rb())
    mine = html.split('<div class="mj-reveal">')[-1]               # 自分は最後に出す
    assert "九種九牌（么九牌 13 種類）" in text_of(mine) and mine.count("<img") >= 14


def test_status_keeps_two_rows_when_the_cpus_have_luck():
    from engine.luck import LuckSettings

    hand = build_hand(["123m456p789s1122z", *OTHERS], turn=0, drawn="5z", dora="1m")
    plain = text_of(status_html(game_of(hand, config=GameConfig(seed=1, luck=LuckSettings(25, 25))), rb()))
    assert "ドラ表示牌" in plain and "ツキ補正：配牌 25・ツモ 25" in plain
    both = text_of(status_html(game_of(hand, config=GameConfig(seed=1, luck=LuckSettings(25, 25), cpu_luck=LuckSettings(50, 40))), rb()))
    assert "ツキ補正：自分 25・25／CPU 50・40" in both and "ドラ表示牌" not in both and both.count("ツキ補正") == 1


def test_graduation_is_written_in_words():
    from engine.game_records import Graduation
    from ui.game_view import graduation_html

    text = text_of(graduation_html(Graduation(5, 2.2, 0.05, 0), rb()))
    assert "対局数：5 / 30（あと 25 回）" in text and "平均順位：2.20（目標 2.5 以下：達成）" in text
    assert "放銃率：5%（目標 12% 以下：達成）" in text and "10 戦そろったら判定" in text and "…" not in text
    done = text_of(graduation_html(Graduation(30, 2.4, 0.1, 0), rb()))
    assert "すべての目標を達成した" in done

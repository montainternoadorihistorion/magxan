"""AI に渡す事実の文と、よくある質問（テンプレートの答え）のテスト（narration/facts.py）。

事実の文に書く数・牌・役は、エンジンの値そのものであること。よくある質問の答えは、事実の文（と参考）だけで
裏付けられること（AI に言い直してもらうとき、照らし合わせで引っかからないように）を確かめる。
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import game as g
from engine.call_coach import call_advice, judge_call
from engine.coach import analyze
from engine.game_coach import Stance, judge_turn, turn_advice
from engine.practice import PracticeConfig, assess, discard, start, target_advice_of
from engine.practice import position_of as practice_position
from engine.rules import DEFAULT_RULES
from engine.scoring.examples import EXAMPLES
from engine.scoring.explain import explain
from engine.tiles import kind_of, parse_tiles
from narration.check import allowed_from, violations
from narration.facts import (
    DETAIL_KINDS,
    call_facts,
    call_review_facts,
    practice_facts,
    practice_review_facts,
    turn_facts,
    turn_review_facts,
    win_facts,
)
from narration.reference import reference_text
from tests.game_helpers import build_hand, game_of

FREE = ["123m456p789s1122z", "147m258p369s3467z", "258m369p147s3467z", "369m147p258s3567z"]
THREAT = ["13m479p2589s1357z", "234m567m78p345s66s", "222z444z666z1m2m3m8m", "258p369s147m3z6z7z5z"]
OPEN_HAND = ["67p234s55s88p9p", "147m258p369s1234z", "19m19p19s5z5z6z6z7z7z2s", "258m147p369s6m7m9s1z"]
KUITAN = ["345m67p345s66s2p8s7m", "147m258p369s1234z", "19m19p19s4z4z5z5z6z6z7z", "258m147p369s1z7z9p8m"]


def example(key: str):
    found = next(e for e in EXAMPLES if e.key == key)
    return explain(found.context(), found.rules)


def k(text: str) -> int:
    return kind_of(parse_tiles(text)[0])


def free_hand():
    return build_hand(FREE, turn=0, drawn="5z")


def threat_hand():
    return build_hand(THREAT, turn=0, drawn="9m", rivers=("", "9p", "", ""), riichi=(None, 0, None, None),
                      kyotaku=1, scores=(25_000, 24_000, 25_000, 25_000))


def claim_state():
    hand = build_hand(KUITAN, turn=3, drawn="5p")
    game = g.apply(game_of(hand), g.discard(3, hand.players[3].drawn))
    while g.waiting_for(game.current) not in (0, None):
        game = g.apply(game, g.pass_(g.waiting_for(game.current)))
    return game.current


def assert_answers_backed_by_facts(facts) -> None:
    """よくある質問の答え（テンプレート）は、事実と参考だけで裏付けられる"""
    for suggestion in facts.suggestions:
        allowed = allowed_from([facts.text, reference_text(facts, suggestion.question)], point_texts=[facts.point_text])
        assert violations(suggestion.text, allowed) == [], (suggestion.key, suggestion.text)


# ---------------------------------------------------------------- あがり


def test_win_facts_carry_the_engine_numbers():
    explanation = example("G-1")
    facts = win_facts(explanation, who="自分")
    assert facts.context == "win" and facts.title == "あがりの解説（自分のロン）"
    text = facts.text
    assert "立直 1 翻" in text and "平和 1 翻" in text and "断么九 1 翻" in text and "合計 3 翻" in text
    assert "合計 30 符 → 30 符" in text and "3,900 点" in text and explanation.declaration in text
    assert "満貫以上のロンの点（子／親）：満貫 8,000 点／12,000 点" in text
    assert [s.key for s in facts.suggestions] == ["points", "yaku", "fu", "say", "near"]
    answer = facts.suggestion("points").answer
    assert answer[0] == "立直・平和・断么九。30 符 3 翻。" and answer[-1] == "あがった人が受け取る点の合計：3,900 点。"
    assert sum("3,900 点" in line for line in answer) == 2                  # 式の最後と、合計（同じ支払いを、何度も書かない）
    assert "鳴いていない（門前）。" in text and "副露" not in text
    assert_answers_backed_by_facts(facts)


@pytest.mark.parametrize("key", [e.key for e in EXAMPLES])
def test_every_example_makes_consistent_facts(key):
    facts = win_facts(example(key))
    assert facts.suggestions
    assert_answers_backed_by_facts(facts)


def test_yakuman_has_no_fu_question():
    facts = win_facts(example("G-8"))
    assert "国士無双 役満" in facts.text and "合計：役満" in facts.text
    assert "役満は、符に関係なく点数が決まる。" in facts.text
    assert "fu" not in [s.key for s in facts.suggestions]


def test_hand_without_yaku_explains_why_it_cannot_win():
    facts = win_facts(example("I-1"))
    assert "役がないので、あがれない。" in facts.text
    assert [s.key for s in facts.suggestions] == ["why"] and facts.suggestions[0].question == "なぜあがれないの？"


def test_extra_lines_and_key():
    explanation = example("G-1")
    plain, extra = win_facts(explanation), win_facts(explanation, extra=["放銃した人：対面。"])
    assert "放銃した人：対面。" in extra.text and plain.key != extra.key
    assert plain.key == win_facts(explanation).key and len(plain.key) == 16


def test_basics_follow_the_red_five_rule():
    explanation = example("G-1")
    no_red = replace(explanation, rules=replace(DEFAULT_RULES, aka_dora=False))
    assert "赤 5 は 1 枚ごとに 1 翻のドラ" in win_facts(explanation).text
    assert "赤 5 は" not in win_facts(no_red).text and "赤ドラ：なし" in win_facts(no_red).text


# ---------------------------------------------------------------- 対局：自分が切る番


def test_turn_facts_free_tenpai():
    hand = free_hand()
    advice = turn_advice(hand, 0)
    facts = turn_facts(hand, 0, advice)
    text = facts.text
    assert "自分の番は 1 巡目（ここまでに 0 枚切った）。" in text and "自分は 東家（親）。場風は 東。" in text
    assert "手牌：1萬・2萬・3萬・4筒・5筒・6筒・7索・8索・9索・東・東・南・南。ツモ牌 白。" in text
    assert "白切り：聴牌・待ち 2 種 3 枚（東（残り 1 枚）・南（残り 2 枚））" in text
    assert "コーチのおすすめ：白切り。" in text and "次のツモで有効牌を引く確率は 2%" in text
    assert "ダマでロン" in text and "リーチしてツモ" in text
    assert [s.key for s in facts.suggestions] == ["why", "compare", "riichi", "yaku"]
    assert facts.suggestion("why").question == "なぜ白（ハク）を切るの？"
    assert_answers_backed_by_facts(facts)


def test_turn_facts_fold_shows_danger_and_no_draw_chance():
    hand = threat_hand()
    advice = turn_advice(hand, 0)
    assert advice.stance is Stance.FOLD
    facts = turn_facts(hand, 0, advice)
    text = facts.text
    assert "押し引き：オリる（守る）。" in text and "リーチしている人：下家。" in text
    assert "9筒：安全・現物" in text and "（当たりうる待ち：" in text
    assert "有効牌を引く確率" not in text                       # オリるときは、速さの見込みを書かない
    assert "速さだけで選ぶなら 2索切り：5 向聴・受け入れ 27 種 96 枚。" in text
    why = facts.suggestion("why")
    assert why is not None and "9筒の危険度：安全・現物。" in why.answer
    assert facts.suggestion("danger") is not None
    assert_answers_backed_by_facts(facts)


def test_long_acceptance_lists_are_left_out():
    hand = threat_hand()
    facts = turn_facts(hand, 0, turn_advice(hand, 0))
    line = next(line for line in facts.text.splitlines() if line.startswith("2索切り："))
    assert line == "2索切り：5 向聴・受け入れ 27 種 96 枚" and 27 > DETAIL_KINDS


def test_turn_facts_open_hand_keeps_the_yaku():
    hand = build_hand(OPEN_HAND, melds=["c345m", "", "", ""], turn=0, drawn="4z")
    advice = turn_advice(hand, 0)
    facts = turn_facts(hand, 0, advice)
    text = facts.text
    assert "副露：チー 345萬（鳴いているので、リーチはできない）。" in text
    assert "コーチのおすすめ：9筒切り。" in text and "速さだけで選ぶなら 北切り：聴牌・待ち 1 種 3 枚" in text
    assert "9筒を切ると：役の見込みあり（遠回りせずに作れる）（断么九）・1 向聴" in text
    assert_answers_backed_by_facts(facts)


def test_closed_kan_is_not_a_call():
    """暗槓は鳴きではない（門前のまま。リーチもできる）。副露と書かない"""
    hand = build_hand(["234m567p78s55s", "147m258p369s1234z", "19m19p19s5z5z6z6z7z7z2s", "258m147p369s6m7m9s1z"],
                      melds=["a4444s", "", "", ""], turn=0, drawn="4z")
    facts = turn_facts(hand, 0, turn_advice(hand, 0))
    text = facts.text
    assert "暗槓：暗槓 4444索（暗槓は鳴きではない。ほかに鳴いていなければ門前のままで、リーチもできる）。" in text
    assert "副露：" not in text and "リーチはできない" not in text
    assert_answers_backed_by_facts(facts)


def test_tsumo_payments_say_each():
    facts = win_facts(example("A-3"))
    assert "子 2 人が、1 人 400 点ずつ払う。" in facts.text and "親が 700 点を払う。" in facts.text
    answer = facts.suggestion("points").answer
    assert answer[-1].startswith("あがった人が受け取る点の合計") and "子 2 人が、1 人 400 点ずつ払う。" in answer       # ツモは、だれがいくら払うかも書く


def test_turn_facts_with_previous_decision_and_win():
    hand = free_hand()
    advice = turn_advice(hand, 0)
    tile = next(t for t in hand.players[0].tiles if kind_of(t) == k("1m"))
    decision = judge_turn(advice, g.discard(0, tile), number=1)
    facts = turn_facts(hand, 0, advice, last=decision, win=example("G-1"))
    assert "前の打牌：1萬切り。" in facts.text and facts.suggestion("last") is not None
    assert facts.suggestions[0].key == "win" and "いまのツモ牌で、ツモあがりできる：" in facts.text


# ---------------------------------------------------------------- 対局：鳴ける牌が出た


def test_call_facts():
    state = claim_state()
    advice = call_advice(state, 0)
    facts = call_facts(state, 0, advice)
    text = facts.text
    assert "上家が切った 5筒 を鳴ける。" in text and "チー 6筒7筒：567筒 の面子になる。" in text
    assert "見送る：役の見込みあり（遠回りせずに作れる）（平和・断么九）・打点の目安 2 翻・2 向聴" in text
    assert "コーチのおすすめ：チー 6筒7筒。" in text
    assert [s.key for s in facts.suggestions] == ["why", "yaku"]
    assert_answers_backed_by_facts(facts)


# ---------------------------------------------------------------- 一人練習


def test_practice_facts():
    state = start(PracticeConfig(seed=12345))
    analysis = analyze(practice_position(state))
    facts = practice_facts(state, analysis)
    text = facts.text
    assert "一人練習（相手なし。放銃の心配はない）。自分のツモは 1 回目（最大 18 回）。" in text
    pick = analysis.pick
    assert f"受け入れ {pick.kinds} 種 {pick.total} 枚" in text
    nxt = facts.suggestion("next")
    assert nxt is not None and len(nxt.answer[1].split("・")) == pick.kinds        # おすすめの有効牌は、すべて書く
    assert_answers_backed_by_facts(facts)


def test_practice_facts_for_a_target():
    state = start(PracticeConfig(seed=7, target="tanyao"))
    target = target_advice_of(state)
    assert target is not None and target.pick is not None
    facts = practice_facts(state, analyze(practice_position(state)), target=target)
    assert "狙う役：断么九（役指定練習）。" in facts.text
    why = facts.suggestion("why")
    assert why is not None and why.answer[0].startswith("役を狙うおすすめ：")
    assert_answers_backed_by_facts(facts)


# ---------------------------------------------------------------- 答え合わせ


def test_review_of_a_risky_discard_compares_safety():
    hand = threat_hand()
    advice = turn_advice(hand, 0)
    tile = next(t for t in hand.players[0].tiles if kind_of(t) == k("4p"))
    facts = turn_review_facts(judge_turn(advice, g.discard(0, tile), number=1))
    how, better = facts.suggestion("how"), facts.suggestion("better")
    assert how is not None and how.answer[0].startswith("4筒はとても危険。")         # オリる局面では、安全度が先
    assert better is not None and better.question == "9筒を切っていたら、どうなった？"
    assert "おすすめの 9筒：安全・現物。" in better.answer
    assert_answers_backed_by_facts(facts)


def test_review_of_a_slower_discard_in_practice():
    state = start(PracticeConfig(seed=12345))
    decision = assess(state, discard(state.hand[0]))
    facts = practice_review_facts(decision)
    assert facts.context == "review" and "切った牌：1萬。評価：受け入れが 6 枚少ない。" in facts.text
    better = facts.suggestion("better")
    assert better is not None and better.question == "白（ハク）を切っていたら、どうなった？"
    assert_answers_backed_by_facts(facts)


def test_review_of_a_call_decision():
    state = claim_state()
    advice = call_advice(state, 0)
    facts = call_review_facts(judge_call(advice, g.pass_(0), number=2), state.rules)
    assert facts.title == "対局：さっきの鳴きの判断（2 巡目）の答え合わせ"
    assert "自分の返事：見送った。" in facts.text and "コーチのおすすめ：チー 6筒7筒。" in facts.text
    assert [s.key for s in facts.suggestions] == ["how", "yaku"]
    assert_answers_backed_by_facts(facts)

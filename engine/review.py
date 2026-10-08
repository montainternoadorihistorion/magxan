"""局の振り返り：局を最初から作り直して、自分の判断（打牌・鳴き）を 1 つずつ評価し直す。

    found = human_decisions(config, hand)     [(行動の番号, 打牌の評価 または 鳴きの評価), …]

対局の画面で、その場で作った評価と同じものができる（コーチの計算は、局面だけで決まるので）。
続きから再開したときと、牌譜で前の局を振り返るときに使う。リーチのあとの自動のツモ切りは、判断に数えない。
"""
from __future__ import annotations

from engine.call_coach import CallDecision, call_advice, judge_call
from engine.game import HUMAN, GameConfig, HandState, Move, Phase, apply_hand, start_hand
from engine.game_coach import TurnDecision, judge_turn, turn_advice

Decision = TurnDecision | CallDecision


def decision_number(hand: HandState, seat: int) -> int:
    """その人の何巡目の判断か（それまでに切った枚数 ＋ 1。鳴いた直後の打牌も、1 巡と数える）"""
    return len(hand.players[seat].river) + 1


def judge_action(hand: HandState, seat: int, action) -> Decision | None:
    """その局面での自分の行動を評価する（評価しない行動なら None）"""
    if action.seat != seat:
        return None
    player = hand.players[seat]
    if action.move in (Move.DISCARD, Move.RIICHI) and hand.phase is Phase.DRAW and not player.in_riichi:
        return judge_turn(turn_advice(hand, seat), action, number=decision_number(hand, seat))
    if hand.phase is Phase.CLAIM and action.move in (Move.PASS, Move.CHI, Move.PON, Move.KAN):
        advice = call_advice(hand, seat)
        if advice is None:
            return None
        could_ron = hand.ron_check(seat).ok
        if could_ron and action.move is Move.PASS:
            return None         # ロンも鳴きも見送った：ロンの見送り（フリテンの知らせで伝える）として扱い、鳴きの評価はしない
        return judge_call(advice, action, number=decision_number(hand, seat), could_ron=could_ron)
    return None


def human_decisions(config: GameConfig, hand: HandState, seat: int = HUMAN) -> list[tuple[int, Decision]]:
    """局の自分の判断と、その評価（行動の番号の順）"""
    state = start_hand(config, hand.start)
    found: list[tuple[int, Decision]] = []
    for index, action in enumerate(hand.actions):
        decision = judge_action(state, seat, action)
        if decision is not None:
            found.append((index, decision))
        state = apply_hand(config, state, action)
    return found

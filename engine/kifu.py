"""局の牌譜（局後の振り返り）：局の行動の列を、1 手ずつ見られる「手順」の列にする。

    record = kifu_of(config, hand, notes)     notes は {行動の番号: 自分の判断の評価}（無ければ空）

各手順（Step）は「その手のあとに盤面がどう変わったか」（打牌・鳴き・カン・ドラ・リーチ棒・手牌）と、説明の文を持つ。
盤面そのもの（4 人の手牌・副露・河）は、画面の側で、最初の盤面に手順を順に当てはめて作る（送るデータを小さくするため）。
手順は、エンジンで局を最初から作り直し、1 手ごとの状態を比べて作る（ルールの判断を、ここや画面の側で繰り返さない）。

CPU が鳴かずに見送った返事は、盤面が変わらなければ手順にしない。自分の返事（見送る・鳴く・ロン）は手順にする。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from engine.game import (
    END_NAMES,
    NUM_PLAYERS,
    SEAT_NAMES,
    Action,
    EndKind,
    GameConfig,
    HandState,
    Move,
    Phase,
    apply_hand,
    start_hand,
)
from engine.melds import MeldType, display_order
from engine.scoring.texts import kind_text
from engine.tiles import kind_of

WIND_NAMES = ("東", "南", "西", "北")
MELD_WORDS = {MeldType.CHI: "チー", MeldType.PON: "ポン", MeldType.MINKAN: "大明槓", MeldType.ANKAN: "暗槓", MeldType.KAKAN: "加槓"}


@dataclass(frozen=True)
class Note:
    """自分の判断 1 つの評価（手順に添える）"""

    mark: str           # ✓ ・ △ ・ ✗ など
    grade: str          # good ・ soso ・ bad（色分け）
    label: str          # 短い評価
    text: str = ""      # ひとこと（おすすめなど）


@dataclass(frozen=True)
class Step:
    index: int                                  # 行動の番号（局の行動の列の何番目か。最後の「結果」は −1）
    seat: int                                   # 行動した席
    text: str                                   # 説明の文
    events: tuple[dict[str, Any], ...]          # 盤面の変化（画面の側で当てはめる）
    mine: bool = False                          # 自分の判断（打牌・鳴き・見送り・ロン・ツモなど）
    note: Note | None = None


@dataclass(frozen=True)
class Kifu:
    title: str                                  # 例：東 1 局 0 本場
    dealer: int
    winds: tuple[str, ...]                      # 席ごとの自風
    start: dict[str, Any]                       # 最初の盤面（配牌・持ち点・ドラ表示牌など）
    steps: tuple[Step, ...]
    result: str                                 # 結果の文

    @property
    def decisions(self) -> tuple[int, ...]:
        """自分の判断の手順の位置"""
        return tuple(i for i, step in enumerate(self.steps) if step.mine)

    def to_dict(self) -> dict[str, Any]:
        """画面の部品に渡す形"""
        return {
            "title": self.title,
            "dealer": self.dealer,
            "winds": list(self.winds),
            "names": list(SEAT_NAMES),
            "start": self.start,
            "steps": [
                {
                    "i": s.index, "s": s.seat, "text": s.text, "ev": list(s.events), "mine": s.mine,
                    "note": None if s.note is None else {"mark": s.note.mark, "grade": s.note.grade, "label": s.note.label, "text": s.note.text},
                }
                for s in self.steps
            ],
            "result": self.result,
        }


def _name(tile: int) -> str:
    return kind_text(kind_of(tile))


def _diff(before: HandState, after: HandState) -> list[dict[str, Any]]:
    """2 つの状態の差を、盤面の変化の列にする（打牌 → 鳴かれた印 → 副露 → ドラ → リーチ棒 → 手牌 → 山の残り）"""
    events: list[dict[str, Any]] = []
    for seat in range(NUM_PLAYERS):
        old, new = before.players[seat], after.players[seat]
        for discard in new.river[len(old.river):]:
            events.append({"k": "discard", "s": seat, "t": discard.tile, "g": discard.tsumogiri, "q": discard.riichi})
    for seat in range(NUM_PLAYERS):
        old, new = before.players[seat], after.players[seat]
        for index, discard in enumerate(new.river):
            if discard.called_by is not None and (index >= len(old.river) or old.river[index].called_by is None):
                events.append({"k": "called", "s": seat, "n": index})
    for seat in range(NUM_PLAYERS):
        old, new = before.players[seat], after.players[seat]
        for index, furo in enumerate(new.furo):
            meld = furo.meld
            source = None if furo.from_seat is None else (furo.from_seat - seat) % NUM_PLAYERS
            shown = [list(item) for item in display_order(meld, source, furo.added)]       # （牌, 横向き, 裏向き）を、卓に置く並びで
            if index >= len(old.furo):
                events.append({
                    "k": "meld", "s": seat, "m": meld.type.value, "tiles": list(meld.tiles), "c": meld.called_tile, "f": furo.from_seat,
                    "disp": shown,
                })
            elif old.furo[index].meld.type is MeldType.PON and meld.type is MeldType.KAKAN:
                events.append({"k": "kakan", "s": seat, "n": index, "t": furo.added, "disp": shown})
    for indicator in after.dora_indicators[len(before.dora_indicators):]:
        events.append({"k": "dora", "t": indicator})
    for seat in range(NUM_PLAYERS):
        if after.players[seat].riichi_paid and not before.players[seat].riichi_paid:
            events.append({"k": "stick", "s": seat})
    # 手牌（門前の牌とツモ牌）は、変わった席だけ丸ごと送る（並べ替え・鳴き・カンを、画面の側で計算しなくて済むように）
    for seat in range(NUM_PLAYERS):
        old, new = before.players[seat], after.players[seat]
        if old.hand != new.hand or old.drawn != new.drawn:
            events.append({"k": "hand", "s": seat, "h": list(new.hand), "d": new.drawn, "r": new.rinshan})
    if after.live_remaining != before.live_remaining:
        events.append({"k": "live", "n": after.live_remaining})
    return events


def _own_text(before: HandState, action: Action) -> str:
    """その人の手の説明（例：下家：5萬 を切った（ツモ切り）、対面：ポン（自分の 5萬）、上家：見送った）"""
    seat, move = action.seat, action.move
    who = SEAT_NAMES[seat]
    claim = before.claim
    source = f"{SEAT_NAMES[claim.seat]}の {_name(claim.tile)}" if claim is not None else ""
    if move in (Move.DISCARD, Move.RIICHI):
        assert action.tile is not None
        tsumogiri = before.players[seat].drawn == action.tile
        how = "リーチ宣言牌" if move is Move.RIICHI else ("ツモ切り" if tsumogiri else "手出し")
        return f"{who}：{_name(action.tile)} を切った（{how}）"
    if move in (Move.CHI, Move.PON, Move.KAN):
        word = {Move.CHI: "チー", Move.PON: "ポン", Move.KAN: "カン（大明槓）"}[move]
        return f"{who}：{word}（{source}）"
    if move in (Move.ANKAN, Move.KAKAN):
        assert action.tile is not None
        word = "暗槓" if move is Move.ANKAN else "加槓"
        return f"{who}：カン（{word}・{_name(action.tile)}）"
    if move is Move.PASS:
        return f"{who}：見送った（{source}）"
    return f"{who}：" + {Move.RON: "ロン", Move.TSUMO: "ツモ", Move.NINE: "九種九牌"}.get(move, move.value)


CALL_WORDS = {Move.CHI: "チー", Move.PON: "ポン", Move.KAN: "大明槓"}


def _follow_text(before: HandState, after: HandState, action: Action, human: int) -> list[str]:
    """その手のあとに続いて決まったこと（鳴きが通った・カンドラ・自分のツモ）"""
    parts = []
    if action.move in CALL_WORDS and after.phase is Phase.CLAIM:
        parts.append("（ほかの人の返事を待つ）")
    for seat in range(NUM_PLAYERS):
        old, new = before.players[seat], after.players[seat]
        if seat != action.seat and len(new.furo) > len(old.furo):
            parts.append(f"{SEAT_NAMES[seat]}が{MELD_WORDS[new.furo[-1].meld.type]}")
    added = after.dora_indicators[len(before.dora_indicators):]
    if added:
        parts.append("カンドラの表示牌 " + "・".join(_name(t) for t in added))
    me_before, me_after = before.players[human], after.players[human]
    if me_after.drawn is not None and me_after.drawn != me_before.drawn:
        word = "嶺上牌をツモ" if me_after.rinshan else "ツモ"
        parts.append(f"{SEAT_NAMES[human]}：{word} {_name(me_after.drawn)}")
    return parts


def _result_text(hand: HandState) -> str:
    result = hand.result
    if result is None:
        return "（局の途中）"
    if result.kind.is_win:
        lines = []
        for win in result.wins:
            how = "ツモ" if win.from_seat is None else f"ロン（{SEAT_NAMES[win.from_seat]}から）"
            lines.append(f"{SEAT_NAMES[win.seat]}の{how}：{win.payments[win.seat]:,} 点")
        return "／".join(lines)
    if result.kind is EndKind.EXHAUSTED:
        tenpai = [SEAT_NAMES[s] for s in range(NUM_PLAYERS) if result.tenpai[s]]
        return "流局（聴牌：" + ("・".join(tenpai) if tenpai else "なし") + "）"
    return f"途中流局（{END_NAMES[result.kind]}）"


def steps_of(
    config: GameConfig, first: HandState, actions: Sequence[Action], notes: Mapping[int, Note] | None = None, *, human: int = 0,
) -> tuple[list[Step], HandState]:
    """局面 first から行動を順に当てはめて、牌譜の手順を作る（→ 手順と、最後の局面）"""
    notes = notes or {}
    state = first
    steps = []
    declared: list[Action] = []         # いまの牌への返事で、宣言された鳴き（返事がそろったとき、通ったかを書く）
    for index, action in enumerate(actions):
        before = state
        state = apply_hand(config, state, action)
        events = tuple(_diff(before, state))
        follow = _follow_text(before, state, action, human)
        if before.phase is Phase.CLAIM:
            if action.move in CALL_WORDS:
                declared.append(action)
            if state.phase is not Phase.CLAIM:
                # 返事がそろった：宣言したのに通らなかった鳴き（ほかの人のロン・ポンが優先された）を書く
                for call in declared:
                    if len(state.players[call.seat].furo) == len(before.players[call.seat].furo):
                        follow.append(f"（{SEAT_NAMES[call.seat]}の{CALL_WORDS[call.move]}は、ほかの人のロン・ポン・カンが優先され、通らなかった）")
                declared = []
        mine = action.seat == human
        if action.move is Move.PASS and not mine:
            if events:          # 見送りで返事がそろい、盤面が変わった（次の人のツモなど）。誰が何を見送ったかを書く
                steps.append(Step(index, action.seat, "。".join([_own_text(before, action), *follow]), events))
            continue
        # リーチのあとの自動のツモ切りは、自分の判断に数えない（暗槓もできたのに、ツモ切りを選んだときは数える）
        auto = mine and before.players[human].in_riichi and action.move is Move.DISCARD and not before.ankan_tiles(human)
        text = "。".join([_own_text(before, action), *follow])
        steps.append(Step(index, action.seat, text, events, mine and not auto, notes.get(index)))
    return steps, state


def kifu_of(config: GameConfig, hand: HandState, notes: Mapping[int, Note] | None = None, *, human: int = 0) -> Kifu:
    """局を最初から作り直して、牌譜の手順を作る。notes は {行動の番号: 自分の判断の評価}"""
    state = start_hand(config, hand.start)
    start = {
        "hands": [list(p.hand) for p in state.players],
        "drawn": [p.drawn for p in state.players],
        "scores": list(state.scores),
        "dora": list(state.dora_indicators),
        "live": state.live_remaining,
        "honba": hand.start.honba,
        "kyotaku": hand.start.kyotaku,
    }
    steps, state = steps_of(config, state, hand.actions, notes, human=human)
    if state.result is not None:
        steps.append(Step(-1, -1, "結果：" + _result_text(state), ({"k": "scores", "v": list(state.result.scores)},)))
    start_info = hand.start
    title = f"{WIND_NAMES[start_info.round_wind - 27]} {start_info.round_number} 局 {start_info.honba} 本場"
    winds = tuple(WIND_NAMES[hand.seat_wind(s) - 27] for s in range(NUM_PLAYERS))
    return Kifu(title, hand.dealer, winds, start, tuple(steps), _result_text(state))


def board_at(record: Kifu, upto: int) -> dict[str, Any]:
    """最初の盤面に、手順を upto 個当てはめた盤面（画面の部品と同じ当てはめ方。テストで、エンジンの状態と比べる）"""
    start = record.start
    board: dict[str, Any] = {
        "hands": [list(h) for h in start["hands"]],
        "drawn": list(start["drawn"]),
        "rivers": [[] for _ in range(NUM_PLAYERS)],
        "melds": [[] for _ in range(NUM_PLAYERS)],
        "scores": list(start["scores"]),
        "riichi": [False] * NUM_PLAYERS,
        "dora": list(start["dora"]),
        "live": start["live"],
        "kyotaku": start["kyotaku"],
    }
    for step in record.steps[:upto]:
        for event in step.events:
            kind = event["k"]
            if kind == "discard":
                board["rivers"][event["s"]].append({"t": event["t"], "g": event["g"], "q": event["q"], "called": False})
                if event["q"]:
                    board["riichi"][event["s"]] = True
            elif kind == "called":
                board["rivers"][event["s"]][event["n"]]["called"] = True
            elif kind == "meld":
                board["melds"][event["s"]].append(
                    {"m": event["m"], "tiles": list(event["tiles"]), "c": event["c"], "f": event["f"], "disp": event["disp"]}
                )
            elif kind == "kakan":
                meld = board["melds"][event["s"]][event["n"]]
                meld["m"] = MeldType.KAKAN.value
                meld["tiles"] = [*meld["tiles"], event["t"]]
                meld["added"] = event["t"]
                meld["disp"] = event["disp"]
            elif kind == "dora":
                board["dora"].append(event["t"])
            elif kind == "stick":
                board["scores"][event["s"]] -= 1000
                board["kyotaku"] += 1
            elif kind == "hand":
                board["hands"][event["s"]] = list(event["h"])
                board["drawn"][event["s"]] = event["d"]
            elif kind == "live":
                board["live"] = event["n"]
            elif kind == "scores":
                board["scores"] = list(event["v"])
    return board

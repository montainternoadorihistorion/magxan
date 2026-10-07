"""一人練習：相手なしで、配牌からツモと打牌をくり返す。

牌効率（どれを切ると聴牌に近いか）と役作りだけに集中するためのモード。

進み方
    配牌 13 枚 → ツモ → 1 枚切る → ツモ → …  を最大 18 回（4 人で打つときの 1 人ぶんのツモ回数）。
    あがりの形になったら「ツモ」を宣言できる。聴牌したら、リーチを宣言して切ることもできる。
    リーチのあとは、あがり牌が来るまで自動でツモ切りになる（実戦と同じ）。
    18 回ツモってもあがれなければ流局。

あがりはツモだけ（相手がいないのでロンは無い）。鳴きもカンも無いので、手はいつも門前。
海底摸月（山の最後の 1 枚でのあがり）は付けない。一人練習の 18 枚目は、本当の山の最後の牌ではないため。

状態は「設定（シード・ツキ補正・ルール）＋行動の列」から完全に作り直せる（replay）。
通信が切れてセッションが消えても、ブラウザに残した小さな記録から続きを打てる。

役指定練習（設定の target に、狙う役を入れる）
    配牌を、その役の形に近づける。ツモの補正が引き寄せる牌も、その役に近づく牌になる。
    ツキ補正が 0 なら、何も変えない（狙う役が決まっているだけの、通常の麻雀）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.target import SHAPELESS_KEYS, TARGET_KEYS, target_distance, target_tiles
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.analysis.waits import is_win_shape, wait_kinds
from engine.coach import Analysis, Position, Verdict, analyze, judge_discard
from engine.luck import (
    NO_DRAW_LUCK,
    DealReport,
    DrawReport,
    LuckSettings,
    aim_deal,
    draw_probability,
    improve_deal,
    improve_draw,
)
from engine.rng import Rng
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.tiles import EAST, NORTH, NUM_TILES, SOUTH, WEST, counts34, kind_of, sort_tiles
from engine.wall import DORA_START, HAND_SIZE, LIVE_START, URA_START, Wall

#: 1 局でツモれる回数（4 人打ちの 1 人ぶんにほぼ相当: 70 枚 ÷ 4 人 ≒ 18）
MAX_DRAWS = 18
SEAT_WINDS = (EAST, SOUTH, WEST, NORTH)
SAVE_VERSION = 1
#: 局の番号（シード）の上限。保存したデータに極端な値が入っていても困らないように、範囲を決めておく
MAX_SEED = 10**12
#: 役指定練習で「一発」を狙うとき、リーチの次のツモだけ、ツモの補正の確率を何倍にするか
IPPATSU_BOOST = 4
#: 配牌で聴牌していないと成立しない役（役指定練習では、配牌を聴牌にする）
DEAL_TENPAI_TARGETS = frozenset({"double_riichi"})


def _is_int(value: object) -> bool:
    """整数か（True / False と小数は、整数として扱わない）"""
    return isinstance(value, int) and not isinstance(value, bool)


class PracticeError(ValueError):
    """できない操作（手牌にない牌を切る、聴牌していないのにリーチする、など）"""


@dataclass(frozen=True)
class PracticeConfig:
    seed: int
    luck: LuckSettings = field(default_factory=LuckSettings)
    rules: Rules = DEFAULT_RULES
    seat_wind: int | None = None      # 自風。None なら、シードから決める（東南西北のどれか）
    round_wind: int = EAST
    target: str | None = None         # 役指定練習で狙う役（図鑑のページの鍵）。None なら、ふつうの一人練習

    def __post_init__(self) -> None:
        if self.target is not None and self.target not in TARGET_KEYS:
            raise ValueError(f"役指定練習で選べない役です: {self.target!r}")
        if not _is_int(self.seed) or not 0 <= self.seed <= MAX_SEED:
            raise ValueError(f"局の番号（シード）は 0〜{MAX_SEED} の整数です: {self.seed!r}")
        if not isinstance(self.luck, LuckSettings) or not isinstance(self.rules, Rules):
            raise ValueError("ツキ補正とルールの設定の形が違います")
        if self.seat_wind is not None and (not _is_int(self.seat_wind) or self.seat_wind not in SEAT_WINDS):
            raise ValueError(f"自風は 27（東）〜30（北）です: {self.seat_wind!r}")
        if not _is_int(self.round_wind) or self.round_wind not in SEAT_WINDS:
            raise ValueError(f"場風は 27（東）〜30（北）です: {self.round_wind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "luck": self.luck.to_dict(),
            "rules": self.rules.to_dict(),
            "seat_wind": self.seat_wind,
            "round_wind": self.round_wind,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PracticeConfig:
        """保存した形から作る。形や値がおかしければ ValueError（数値は __post_init__ で確かめる）"""
        if not isinstance(data, dict):
            raise ValueError("設定の記録の形が違います")
        return cls(
            seed=data.get("seed"),
            luck=LuckSettings.from_dict(data.get("luck", {})),
            rules=Rules.from_dict(data.get("rules", {})),
            seat_wind=data.get("seat_wind"),
            round_wind=data.get("round_wind", EAST),
            target=data.get("target"),
        )


class Move(StrEnum):
    DISCARD = "d"     # 1 枚切る
    RIICHI = "r"      # リーチを宣言して 1 枚切る
    TSUMO = "t"       # ツモあがり


@dataclass(frozen=True)
class Action:
    move: Move
    tile: int | None = None     # 切る牌（ツモあがりでは None）

    def to_list(self) -> list:
        return [self.move.value] if self.tile is None else [self.move.value, self.tile]

    @classmethod
    def from_list(cls, data: Sequence) -> Action:
        """保存した形（["d", 牌ID] など）から作る。形がおかしければ ValueError"""
        if not isinstance(data, (list, tuple)) or not 1 <= len(data) <= 2 or not isinstance(data[0], str):
            raise ValueError(f"行動の形がおかしい: {data!r}")
        move = Move(data[0])            # 知らない文字なら ValueError
        tile = data[1] if len(data) > 1 else None
        if (move is Move.TSUMO) != (tile is None):
            raise ValueError(f"行動の形がおかしい: {list(data)!r}")
        if tile is not None and (not _is_int(tile) or not 0 <= tile < NUM_TILES):
            raise ValueError(f"牌の番号がおかしい: {tile!r}")
        return cls(move, tile)


def discard(tile: int) -> Action:
    return Action(Move.DISCARD, tile)


def riichi(tile: int) -> Action:
    return Action(Move.RIICHI, tile)


TSUMO = Action(Move.TSUMO)


@dataclass(frozen=True)
class Draw:
    turn: int               # 何回目のツモか（1 始まり）
    tile: int
    luck: DrawReport        # このツモに補正が働いたか
    auto: bool = False      # リーチ後の自動ツモ切りで、そのまま河に出たか


class Outcome(StrEnum):
    TSUMO = "tsumo"            # ツモあがり
    EXHAUSTED = "exhausted"    # 流局（ツモれる回数を使い切った）


@dataclass(frozen=True)
class Result:
    outcome: Outcome
    turn: int                           # 終わったときのツモ回数
    win: WinContext | None = None       # あがったときの状況（解説は engine.scoring.explain に渡して作る）
    tenpai: bool = False                # 流局したとき、聴牌していたか
    waits: tuple[int, ...] = ()         # 流局したときの待ち牌（種類）
    shanten: int | None = None          # 流局したときの手牌の向聴数（あがった局は None）


@dataclass(frozen=True)
class PracticeState:
    config: PracticeConfig
    actions: tuple[Action, ...]
    seat_wind: int
    wall_tiles: tuple[int, ...]         # いまの山の並び（補正で入れ替えたあと）
    hand: tuple[int, ...]               # 手牌 13 枚（理牌済み）
    drawn: int | None                   # いまのツモ牌（局が終わっていれば None）
    discards: tuple[int, ...]           # 河（切った順）
    riichi_index: int | None            # リーチを宣言した打牌が、河の何枚目か（0 始まり）。していなければ None
    draws: tuple[Draw, ...]             # ツモの記録
    deal: DealReport                    # 配牌の補正の記録
    result: Result | None = None

    # ------------------------------------------------------------ 状態の読み取り

    @property
    def finished(self) -> bool:
        return self.result is not None

    @property
    def turn(self) -> int:
        """これまでにツモった回数"""
        return len(self.draws)

    @property
    def draws_left(self) -> int:
        """このあとツモれる回数"""
        return MAX_DRAWS - self.turn

    @property
    def tiles(self) -> tuple[int, ...]:
        """手牌 13 枚＋ツモ牌（あれば）"""
        return self.hand if self.drawn is None else (*self.hand, self.drawn)

    @property
    def in_riichi(self) -> bool:
        return self.riichi_index is not None

    @property
    def dora_indicators(self) -> tuple[int, ...]:
        return (self.wall_tiles[DORA_START],)

    @property
    def ura_indicators(self) -> tuple[int, ...]:
        """裏ドラ表示牌（リーチしてあがったときだけ見る）"""
        return (self.wall_tiles[URA_START],)

    @property
    def visible(self) -> tuple[int, ...]:
        """自分から見えている、手牌以外の牌（河とドラ表示牌）"""
        return (*self.discards, *self.dora_indicators)

    @property
    def remaining(self) -> list[int]:
        """種類ごとの「まだ見えていない枚数」"""
        return remaining_counts(self.tiles, self.visible)

    @property
    def unseen_total(self) -> int:
        """見えていない牌の合計枚数"""
        return 136 - len(self.tiles) - len(self.visible)

    @property
    def last_draw(self) -> Draw | None:
        return self.draws[-1] if self.draws else None

    @property
    def can_tsumo(self) -> bool:
        """いま「ツモ」を宣言できるか"""
        return not self.finished and self.drawn is not None and is_win_shape(self.tiles)

    @property
    def riichi_discards(self) -> tuple[int, ...]:
        """リーチを宣言して切れる牌（切っても聴牌が残る牌）。リーチできなければ空"""
        if self.finished or self.drawn is None or self.in_riichi or self.draws_left < 1:
            return ()
        counts = counts34(self.tiles)
        tenpai_kinds = set()
        for kind in {kind_of(t) for t in self.tiles}:
            counts[kind] -= 1
            if shanten_of(counts) == TENPAI:
                tenpai_kinds.add(kind)
            counts[kind] += 1
        return tuple(t for t in self.tiles if kind_of(t) in tenpai_kinds)


# ---------------------------------------------------------------- 進行


def seat_wind_of(config: PracticeConfig) -> int:
    if config.seat_wind is not None:
        return config.seat_wind
    return Rng(config.seed, "seat").choice(SEAT_WINDS)


def _wall(state: PracticeState) -> Wall:
    return Wall(list(state.wall_tiles), live_drawn=state.turn, sealed=True)


def _next_draw(
    wall: Wall,
    state: PracticeState,
    hand: Sequence[int],
    discards: Sequence[int],
    *,
    riichi: bool = False,
    first_after_riichi: bool = False,
) -> tuple[int, DrawReport]:
    """次の 1 枚をツモる（その前に、ツモの補正を試す）。

    補正が引き寄せるのは、ふつうは有効牌（向聴数が進む牌）。役指定練習では、狙う役に近づく牌。
    その役に近づく牌が山に残っていなければ、有効牌にする。
    riichi はリーチ後のツモか、first_after_riichi はリーチのすぐ次のツモか。
    """
    probability = draw_probability(state.config.luck.draw)
    if probability <= 0:              # 補正なし：乱数も作らず、山の先頭をそのままツモる
        return wall.draw(), NO_DRAW_LUCK
    target = state.config.target
    turn = wall.live_drawn + 1
    if target in DEAL_TENPAI_TARGETS and turn == 1:
        # ダブル立直を狙う練習：配牌が聴牌なので、最初のツモを引き寄せると、リーチする前にあがってしまう
        return wall.draw(), NO_DRAW_LUCK
    if target == "ippatsu" and first_after_riichi:
        probability = min(1.0, probability * IPPATSU_BOOST)        # 一発を狙う練習：リーチの次のツモを引き寄せやすくする
    visible = (*discards, *state.dora_indicators)

    def wanted() -> list[int]:
        counts = counts34(hand)
        if target is not None and target not in SHAPELESS_KEYS:
            winds = {"seat_wind": state.seat_wind, "round_wind": state.config.round_wind}
            in_wall = counts34(wall.tiles[wall.next_live_position:wall.live_end])       # これからツモる山に残っている牌
            # リーチのあとは手を変えられない。その役の聴牌になっているときだけ、役の付くあがり牌を引き寄せる
            if not riichi or target_distance(counts, target, available=in_wall, **winds) == TENPAI:
                closer = target_tiles(counts, target, available=in_wall, **winds)
                if closer:
                    return list(closer)
        return [kind for kind, _ in acceptance(counts, remaining_counts(hand, visible)).tiles]

    report = improve_draw(wall, probability, wanted, Rng(state.config.seed, f"luck:draw:{turn}"))
    return wall.draw(), report


def _win_context(state: PracticeState, hand: Sequence[int], win_tile: int, turn: int, riichi_index: int | None) -> WinContext:
    in_riichi = riichi_index is not None
    first_draw = turn == 1
    return WinContext(
        closed_tiles=(*hand, win_tile),
        win_tile=win_tile,
        is_tsumo=True,
        seat_wind=state.seat_wind,
        round_wind=state.config.round_wind,
        riichi=in_riichi,
        double_riichi=riichi_index == 0,                               # 最初の打牌でリーチ
        ippatsu=in_riichi and turn == riichi_index + 2,                # リーチの次のツモであがった
        tenhou=first_draw and state.seat_wind == EAST,                 # 親が最初のツモであがっていた
        chiihou=first_draw and state.seat_wind != EAST,                # 子が最初のツモであがった
        dora_indicators=state.dora_indicators,
        ura_indicators=state.ura_indicators if in_riichi else (),
    )


def start(config: PracticeConfig) -> PracticeState:
    """配牌 13 枚を取り、最初の 1 枚をツモった状態"""
    seat = seat_wind_of(config)
    wall = Wall.from_seed(config.seed)
    target = config.target
    if target is None or (target in SHAPELESS_KEYS and target not in DEAL_TENPAI_TARGETS):
        deal = improve_deal(wall, 0, config.luck, config.seed, seat_wind=seat, round_wind=config.round_wind)
    else:           # 役指定練習：配牌を、狙う役の形に近づける
        deal = aim_deal(
            wall, 0, config.luck, config.seed, target=target, seat_wind=seat, round_wind=config.round_wind,
            need_tenpai=target in DEAL_TENPAI_TARGETS,
            unused_positions=range(HAND_SIZE, LIVE_START),      # 一人練習では、ほかの 3 人ぶんの配牌は誰も使わない
        )
    wall.seal()
    hand = tuple(sort_tiles(wall.dealt_hand(0)))
    state = PracticeState(
        config=config,
        actions=(),
        seat_wind=seat,
        wall_tiles=tuple(wall.tiles),
        hand=hand,
        drawn=None,
        discards=(),
        riichi_index=None,
        draws=(),
        deal=deal,
    )
    tile, report = _next_draw(wall, state, hand, ())
    return replace(state, wall_tiles=tuple(wall.tiles), drawn=tile, draws=(Draw(1, tile, report),))


def apply(state: PracticeState, action: Action) -> PracticeState:
    """行動を 1 つ進める。できない行動なら PracticeError"""
    if state.finished or state.drawn is None:
        raise PracticeError("この局は終わっています")
    actions = (*state.actions, action)

    if action.move is Move.TSUMO:
        if not state.can_tsumo:
            raise PracticeError("あがりの形になっていません")
        win = _win_context(state, state.hand, state.drawn, state.turn, state.riichi_index)
        return replace(state, actions=actions, hand=tuple(sort_tiles(state.hand)), result=Result(Outcome.TSUMO, state.turn, win=win))

    tile = action.tile
    if tile not in state.tiles:
        raise PracticeError(f"手牌にない牌は切れません: {tile}")
    # リーチした局は、その場で最後まで進めて終わらせる。だから、ここに来る局面は必ずリーチ前
    riichi_index = None
    if action.move is Move.RIICHI:
        if state.draws_left < 1:
            raise PracticeError("もうツモが残っていないので、リーチできません")
        if tile not in state.riichi_discards:
            raise PracticeError("その牌を切ると聴牌にならないので、リーチできません")
        riichi_index = len(state.discards)

    hand = tuple(sort_tiles(t for t in state.tiles if t != tile))
    discards = (*state.discards, tile)
    draws = list(state.draws)
    wall = _wall(state)

    while True:
        if len(draws) >= MAX_DRAWS:
            waits = wait_kinds(hand)
            result = Result(Outcome.EXHAUSTED, len(draws), tenpai=bool(waits), waits=waits, shanten=shanten_of(counts34(hand)))
            return replace(
                state, actions=actions, wall_tiles=tuple(wall.tiles), hand=hand, drawn=None, discards=discards,
                riichi_index=riichi_index, draws=tuple(draws), result=result,
            )
        in_riichi = riichi_index is not None
        first_after = in_riichi and len(draws) == riichi_index + 1
        drawn, report = _next_draw(wall, state, hand, discards, riichi=in_riichi, first_after_riichi=first_after)
        turn = len(draws) + 1
        if riichi_index is None:
            draws.append(Draw(turn, drawn, report))
            return replace(
                state, actions=actions, wall_tiles=tuple(wall.tiles), hand=hand, drawn=drawn, discards=discards,
                riichi_index=None, draws=tuple(draws),
            )
        # リーチ後：あがり牌ならあがり、そうでなければツモ切りして次へ
        if is_win_shape((*hand, drawn)):
            draws.append(Draw(turn, drawn, report))
            win = _win_context(state, hand, drawn, turn, riichi_index)
            return replace(
                state, actions=actions, wall_tiles=tuple(wall.tiles), hand=hand, drawn=drawn, discards=discards,
                riichi_index=riichi_index, draws=tuple(draws), result=Result(Outcome.TSUMO, turn, win=win),
            )
        draws.append(Draw(turn, drawn, report, auto=True))
        discards = (*discards, drawn)


def replay(config: PracticeConfig, actions: Sequence[Action]) -> PracticeState:
    """設定と行動の列から、状態を作り直す"""
    state = start(config)
    for action in actions:
        state = apply(state, action)
    return state


# ---------------------------------------------------------------- コーチ


@dataclass(frozen=True)
class Decision:
    """自分で選んだ打牌 1 回ぶんの評価"""

    turn: int             # 何回目のツモのあとの打牌か（1 始まり）
    action: Action
    verdict: Verdict
    analysis: Analysis    # 切る前の局面の分析（答え合わせで、候補の表を見せるため）


def position_of(state: PracticeState) -> Position:
    """いまの局面を、コーチに見せる形にする（打牌の前だけ）"""
    if state.finished or state.drawn is None:
        raise PracticeError("この局は終わっています")
    return Position(
        tiles=state.tiles,
        visible=state.visible,
        seat_wind=state.seat_wind,
        round_wind=state.config.round_wind,
        dora_indicators=state.dora_indicators,
        draws_left=state.draws_left,
        drawn=state.drawn,
        can_riichi=not state.in_riichi and state.draws_left >= 1,
        rules=state.config.rules,
    )


def assess(state: PracticeState, action: Action) -> Decision | None:
    """これからする打牌を評価する（apply の前に呼ぶ）。ツモあがりは評価の対象外なので None"""
    if action.move is Move.TSUMO or action.tile is None:
        return None
    analysis = analyze(position_of(state))
    verdict = judge_discard(analysis, action.tile, riichi=action.move is Move.RIICHI)
    return Decision(state.turn, action, verdict, analysis)


def decisions_of(config: PracticeConfig, actions: Sequence[Action]) -> tuple[Decision, ...]:
    """行動の列を最初からたどり、自分で選んだ打牌をすべて評価する（続きから再開したときに使う）"""
    state = start(config)
    found = []
    for action in actions:
        decision = assess(state, action)
        if decision is not None:
            found.append(decision)
        state = apply(state, action)
    return tuple(found)


# ---------------------------------------------------------------- 保存


def to_save(state: PracticeState) -> dict[str, Any]:
    """ブラウザなどに残すための小さな記録（設定＋行動の列）"""
    return {"v": SAVE_VERSION, "config": state.config.to_dict(), "actions": [a.to_list() for a in state.actions]}


def from_save(data: dict[str, Any]) -> PracticeState:
    """記録から状態を作り直す。形が違う・できない行動が入っている場合は ValueError。

    記録はブラウザに置いてあるので、壊れていたり、書き換えられていたりすることがある。
    どんな中身でも、ValueError 以外の例外を出さないようにする（開くたびにエラーで止まるのを防ぐ）。
    """
    if not isinstance(data, dict) or data.get("v") != SAVE_VERSION:
        raise ValueError("記録の形が違います")
    items = data.get("actions")
    # 1 局の行動は、多くても「ツモの回数ぶんの打牌＋ツモあがり」
    if not isinstance(items, list) or len(items) > MAX_DRAWS + 1:
        raise ValueError("記録の形が違います（行動の列）")
    try:
        config = PracticeConfig.from_dict(data.get("config"))
        actions = [Action.from_list(item) for item in items]
        return replay(config, actions)
    except ValueError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError, ArithmeticError) as error:
        raise ValueError(f"記録を読めません: {error}") from error

"""CPU 3 人との対局：4 人で打つ局と、試合（東風戦・半荘戦）の進行。

いまは門前だけ（ポン・チー・カンは Phase 4 で足す）。決めごとは雀魂の段位戦に合わせ、
流派で分かれるものはルールの設定（engine/rules.py）で切り替える。

局の進み方
    親から順に、ツモって 1 枚切る。切った牌でロンできる人がいれば、その人たちの返事（ロン／見送る）を待つ。
    自分の番では、打牌のほかに、ツモあがり・リーチ・九種九牌（途中流局）を選べる。
    山（ツモ山 70 枚）が尽きたら流局。聴牌の人が、聴牌していない人から点をもらう（ノーテン罰符 3000 点）。

決めごと（雀魂の段位戦。出典は docs/DESIGN.md の 7 章）
    リーチ        門前で聴牌、持ち点 1000 点以上、このあとツモ番がある（ツモ山が 4 枚以上残っている）こと。
                  宣言した牌が通ったら（ロンされなかったら）、1000 点を卓に出す（供託）。リーチのあとはツモ切りだけ
    フリテン      自分の河に待ち牌があるとロンできない（ツモはできる）。あがり牌を見逃すと、次に自分が切るまで
                  ロンできない（同巡内フリテン）。リーチのあとに見逃すと、その局のあいだずっとロンできない
    複数ロン      2 人・3 人が同じ牌でロンしたら、全員のあがり。本場と供託は、捨てた人から見て順番が先の人だけがもらう
                  （上家取り）。ルールで「頭ハネ」（先の 1 人だけ）にもできる
    流局          聴牌の人が 1〜3 人なら、聴牌していない人から合わせて 3000 点（役がない聴牌も聴牌に数える）。
                  流し満貫（捨て牌がすべて么九牌）の人がいれば、罰符の代わりに満貫のツモと同じ点をもらう（本場は付けない）
    途中流局      九種九牌（最初のツモで么九牌が 9 種類以上。宣言したとき）、四風連打（最初の 1 巡で 4 人が同じ風牌）、
                  四家立直（4 人のリーチが成立）。点の動きは無く、親は続ける
    連荘          親があがったとき、流局で親が聴牌していたとき、途中流局のとき。本場が 1 つ増える
    試合の終わり  予定の局（東風戦は東 4 局、半荘戦は南 4 局）が終わったとき、誰かが 30000 点以上なら終わり。
                  いなければ延長（東風戦は南場、半荘戦は西場）に入り、誰かが 30000 点以上になった局で終わる
                  （サドンデス。延長の 4 局目が終われば、それで終わり）。
                  最後の局で、親があがるか聴牌して、30000 点以上の 1 位なら、そこで終わる（あがりやめ・聴牌やめ）。
                  誰かの持ち点が 0 点より少なくなったら終わる（飛び。0 点ちょうどは続ける）。
                  終わったときに卓に残っているリーチ棒は、1 位がもらう。同点なら、起家に近い人が上の順位

状態は「設定（シードなど）＋局ごとの行動の列」から完全に作り直せる（replay）。行動の列には CPU の行動も入るので、
CPU の打ち方を変えたあとでも、記録した対局はそのまま作り直せる。CPU の打ち方は engine/cpu.py にある。

ツキ補正は、席ごとに配牌とツモに働く（自分は config.luck、CPU 3 人は config.cpu_luck。CPU の初期値は 0）。
補正は、まだ誰も見ていない牌どうしの入れ替えだけ（engine/luck.py）。補正 0 の席では、乱数も引かず山にも触れない。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.analysis.waits import is_win_shape, wait_kinds
from engine.luck import NO_DRAW_LUCK, DealReport, DrawReport, LuckSettings, draw_probability, improve_deal, improve_draw
from engine.rng import Rng
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.judge import Judgement, judge
from engine.tiles import EAST, NORTH, NUM_TILES, counts34, is_yaochu_kind, kind_of, sort_tiles
from engine.wall import DORA_START, NUM_LIVE, URA_START, Wall

NUM_PLAYERS = 4
#: 自分の席（席の番号は試合のあいだ変わらない。自分から見て 1 ＝ 下家、2 ＝ 対面、3 ＝ 上家）
HUMAN = 0
START_POINTS = 25_000
#: 延長と「あがりやめ」の基準（雀魂の 4 人打ち）
GOAL_POINTS = 30_000
RIICHI_STICK = 1_000
#: 流局のときに、聴牌していない人から聴牌の人へ移る点の合計
NOTEN_TOTAL = 3_000
#: リーチできるのは、このあと自分のツモ番がある（ツモ山がこの枚数以上残っている）とき
RIICHI_MIN_WALL = NUM_PLAYERS
#: 九種九牌：最初のツモで、么九牌がこの種類数以上あれば、流局にできる
NINE_KINDS = 9
MAX_SEED = 10**12
SAVE_VERSION = 1
#: 保存した記録の大きさの上限（壊れた記録で、作り直しに何分もかからないように）
MAX_HANDS = 64
MAX_ACTIONS = 400

SEAT_NAMES = ("自分", "下家", "対面", "上家")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class GameError(ValueError):
    """できない行動（手番でない人の打牌、手牌にない牌、聴牌していないリーチ、など）"""


class Length(StrEnum):
    EAST = "east"       # 東風戦（東場の 4 局）
    SOUTH = "south"     # 半荘戦（東場・南場の 8 局）

    @property
    def planned(self) -> int:
        """予定の局数（親が交代する回数で数える。連荘した局は数えない）"""
        return 4 if self is Length.EAST else 8

    @property
    def label(self) -> str:
        return "東風戦" if self is Length.EAST else "半荘戦"


class CpuLevel(StrEnum):
    NORMAL = "normal"   # ふつう：牌効率で打ち、聴牌したらリーチ。リーチを受けたら、聴牌していなければオリる
    WEAK = "weak"       # 弱い：受け入れの広さを見ずに切り、オリない

    @property
    def label(self) -> str:
        return "ふつう" if self is CpuLevel.NORMAL else "弱い"


@dataclass(frozen=True)
class GameConfig:
    seed: int
    length: Length = Length.EAST
    luck: LuckSettings = field(default_factory=LuckSettings)        # 自分のツキ補正
    cpu_luck: LuckSettings = field(default_factory=LuckSettings)    # CPU 3 人のツキ補正（初期値 0）
    cpu_level: CpuLevel = CpuLevel.NORMAL
    rules: Rules = DEFAULT_RULES

    def __post_init__(self) -> None:
        if not _is_int(self.seed) or not 0 <= self.seed <= MAX_SEED:
            raise ValueError(f"対局の番号（シード）は 0〜{MAX_SEED} の整数です: {self.seed!r}")
        if not isinstance(self.length, Length) or not isinstance(self.cpu_level, CpuLevel):
            raise ValueError("対局の長さと CPU の強さの指定が違います")
        if not isinstance(self.luck, LuckSettings) or not isinstance(self.cpu_luck, LuckSettings):
            raise ValueError("ツキ補正の設定の形が違います")
        if not isinstance(self.rules, Rules):
            raise ValueError("ルールの設定の形が違います")

    def luck_of(self, seat: int) -> LuckSettings:
        return self.luck if seat == HUMAN else self.cpu_luck

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "length": self.length.value,
            "luck": self.luck.to_dict(),
            "cpu_luck": self.cpu_luck.to_dict(),
            "cpu_level": self.cpu_level.value,
            "rules": self.rules.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameConfig:
        """保存した形から作る。形や値がおかしければ ValueError"""
        if not isinstance(data, dict):
            raise ValueError("対局の設定の記録の形が違います")
        length, level = data.get("length", Length.EAST.value), data.get("cpu_level", CpuLevel.NORMAL.value)
        if not isinstance(length, str) or not isinstance(level, str):
            raise ValueError("対局の設定の記録の値がおかしい")
        return cls(
            seed=data.get("seed"),
            length=Length(length),                     # 知らない値なら ValueError
            luck=LuckSettings.from_dict(data.get("luck", {})),
            cpu_luck=LuckSettings.from_dict(data.get("cpu_luck", {})),
            cpu_level=CpuLevel(level),
            rules=Rules.from_dict(data.get("rules", {})),
        )


# ---------------------------------------------------------------- 行動


class Move(StrEnum):
    DISCARD = "d"     # 1 枚切る
    RIICHI = "r"      # リーチを宣言して 1 枚切る
    TSUMO = "t"       # ツモあがり
    RON = "n"         # ロン（捨て牌であがる）
    PASS = "p"        # ロンできる牌を見送る
    NINE = "k"        # 九種九牌で流局にする


@dataclass(frozen=True)
class Action:
    seat: int
    move: Move
    tile: int | None = None     # 切る牌（打牌とリーチだけ）

    def to_list(self) -> list:
        return [self.seat, self.move.value] + ([] if self.tile is None else [self.tile])

    @classmethod
    def from_list(cls, data: Sequence) -> Action:
        """保存した形（[席, "d", 牌ID] など）から作る。形がおかしければ ValueError"""
        if not isinstance(data, (list, tuple)) or not 2 <= len(data) <= 3 or not isinstance(data[1], str):
            raise ValueError(f"行動の形がおかしい: {data!r}")
        seat, move = data[0], Move(data[1])           # 知らない文字なら ValueError
        if not _is_int(seat) or not 0 <= seat < NUM_PLAYERS:
            raise ValueError(f"席の番号がおかしい: {seat!r}")
        tile = data[2] if len(data) > 2 else None
        if (move in (Move.DISCARD, Move.RIICHI)) != (tile is not None):
            raise ValueError(f"行動の形がおかしい: {list(data)!r}")
        if tile is not None and (not _is_int(tile) or not 0 <= tile < NUM_TILES):
            raise ValueError(f"牌の番号がおかしい: {tile!r}")
        return cls(seat, move, tile)


def discard(seat: int, tile: int) -> Action:
    return Action(seat, Move.DISCARD, tile)


def riichi(seat: int, tile: int) -> Action:
    return Action(seat, Move.RIICHI, tile)


def tsumo(seat: int) -> Action:
    return Action(seat, Move.TSUMO)


def ron(seat: int) -> Action:
    return Action(seat, Move.RON)


def pass_(seat: int) -> Action:
    return Action(seat, Move.PASS)


def nine(seat: int) -> Action:
    return Action(seat, Move.NINE)


# ---------------------------------------------------------------- 局の状態


class Phase(StrEnum):
    DRAW = "draw"       # 手番の人が、ツモった 14 枚から打牌などを選ぶ
    CLAIM = "claim"     # 捨て牌でロンできる人の返事（ロン／見送る）を待つ
    END = "end"         # 局が終わった


@dataclass(frozen=True)
class Discard:
    tile: int
    tsumogiri: bool = False     # ツモってきた牌を、そのまま切った
    riichi: bool = False        # リーチ宣言牌
    order: int = 0              # 局の何枚目の打牌か（0 始まり。全員の打牌を通して数える）


@dataclass(frozen=True)
class Draw:
    number: int                 # その人の何回目のツモか（1 始まり）
    tile: int
    luck: DrawReport            # このツモに補正が働いたか


@dataclass(frozen=True)
class Player:
    hand: tuple[int, ...]               # 手牌（ツモ牌を除く。理牌済み）
    drawn: int | None = None            # 自分の番でツモった牌（打牌するまで）
    river: tuple[Discard, ...] = ()     # 河（切った順）
    riichi_at: int | None = None        # リーチ宣言牌が、河の何枚目か（0 始まり）。宣言していなければ None
    riichi_paid: bool = False           # リーチが成立した（宣言牌が通り、リーチ棒を出した）
    double_riichi: bool = False         # 最初の打牌でリーチした
    ippatsu: bool = False               # 一発のチャンスが残っている（リーチのあと、次に自分が切るまで）
    missed: bool = False                # 同巡内フリテン（あがり牌を見逃してから、次に自分が切るまで）
    riichi_missed: bool = False         # リーチのあとに、あがり牌を見逃した（この局のあいだ、ずっとフリテン）
    draws: tuple[Draw, ...] = ()        # ツモの記録

    @property
    def tiles(self) -> tuple[int, ...]:
        """手牌（ツモ牌があれば、それも含める）"""
        return self.hand if self.drawn is None else (*self.hand, self.drawn)

    @property
    def in_riichi(self) -> bool:
        """リーチを宣言しているか（宣言牌がまだロンされるかどうかの間も含む）"""
        return self.riichi_at is not None

    @property
    def river_tiles(self) -> tuple[int, ...]:
        return tuple(d.tile for d in self.river)

    @property
    def river_kinds(self) -> frozenset[int]:
        return frozenset(kind_of(d.tile) for d in self.river)


class Furiten(StrEnum):
    RIVER = "river"         # 自分の河に、待ち牌がある
    MISSED = "missed"       # あがり牌を見逃した（次に自分が切るまで）
    RIICHI = "riichi"       # リーチのあとに、あがり牌を見逃した（この局のあいだ、ずっと）


FURITEN_TEXTS = {
    Furiten.RIVER: "自分の河に待ち牌があるので、フリテン（ロンできない。ツモならあがれる）",
    Furiten.MISSED: "あがり牌を見逃したので、次に自分が切るまでフリテン（同巡内フリテン）",
    Furiten.RIICHI: "リーチのあとにあがり牌を見逃したので、この局のあいだフリテン（ツモでしかあがれない）",
}


@dataclass(frozen=True)
class RonCheck:
    """ある捨て牌でロンできるか"""

    shape: bool                     # その牌で、あがりの形になる
    furiten: Furiten | None = None  # フリテンなら、その理由
    yaku: bool = False              # 役がある（形になっていても、役が無ければロンできない）

    @property
    def ok(self) -> bool:
        return self.shape and self.furiten is None and self.yaku


NO_RON = RonCheck(False)


@dataclass(frozen=True)
class Miss:
    """あがり牌が出たのに、ロンしなかった（できなかった）こと 1 回ぶん"""

    seat: int                       # あがり牌を見送った人
    from_seat: int                  # その牌を切った人
    tile: int
    check: RonCheck                 # ロンできたか（できなければ、その理由）
    passed: bool                    # ロンできたのに、自分で見送った

    @property
    def no_yaku(self) -> bool:
        """役がなくてロンできなかった（フリテンでもなかった）"""
        return not self.passed and self.check.furiten is None and not self.check.yaku


class EndKind(StrEnum):
    RON = "ron"
    TSUMO = "tsumo"
    EXHAUSTED = "exhausted"         # 流局（山が尽きた）
    NINE_TERMINALS = "nine"         # 途中流局：九種九牌
    FOUR_WINDS = "four_winds"       # 途中流局：四風連打
    FOUR_RIICHI = "four_riichi"     # 途中流局：四家立直

    @property
    def is_win(self) -> bool:
        return self in (EndKind.RON, EndKind.TSUMO)

    @property
    def is_abortive(self) -> bool:
        return self in (EndKind.NINE_TERMINALS, EndKind.FOUR_WINDS, EndKind.FOUR_RIICHI)


END_NAMES = {
    EndKind.RON: "ロン",
    EndKind.TSUMO: "ツモ",
    EndKind.EXHAUSTED: "流局",
    EndKind.NINE_TERMINALS: "九種九牌",
    EndKind.FOUR_WINDS: "四風連打",
    EndKind.FOUR_RIICHI: "四家立直",
}


@dataclass(frozen=True)
class Win:
    seat: int
    ctx: WinContext                         # あがりの状況（解説は engine.scoring.explain に渡して作る）
    judgement: Judgement                    # 判定ライブラリによる点数（点の移動は、これで決める）
    from_seat: int | None                   # ロンなら放銃した席、ツモなら None
    payments: tuple[int, int, int, int]     # このあがりでの点の移動（席ごと。受け取りは ＋）


@dataclass(frozen=True)
class HandResult:
    kind: EndKind
    wins: tuple[Win, ...] = ()                  # あがり（複数ロンなら、本場・供託をもらう人が先）
    tenpai: tuple[bool, ...] = ()               # 流局したときの、席ごとの聴牌
    nagashi: tuple[int, ...] = ()               # 流し満貫になった席
    settlement: tuple[int, int, int, int] = (0, 0, 0, 0)    # 局の終わりの点の移動（あがり・罰符・流し満貫。リーチ棒の支払いは含まない）
    scores: tuple[int, int, int, int] = (0, 0, 0, 0)        # 局の終わりの持ち点
    kyotaku: int = 0                            # 局の終わりに卓に残ったリーチ棒の本数
    renchan: bool = False                       # 親が続くか
    caller: int | None = None                   # 九種九牌を宣言した席
    bumped: tuple[int, ...] = ()                # 頭ハネで、ロンが無効になった席


@dataclass(frozen=True)
class HandStart:
    """局の始まりの状況"""

    number: int                         # 試合の何局目か（0 始まり。連荘した局・流局した局も 1 局と数える）
    rotation: int                       # それまでに親が交代した回数（0 ＝ 東 1 局、4 ＝ 南 1 局）
    dealer: int                         # 親の席
    honba: int                          # 本場
    kyotaku: int                        # 局の始めに卓に出ているリーチ棒の本数
    scores: tuple[int, int, int, int]   # 局の始めの持ち点

    @property
    def round_wind(self) -> int:
        return EAST + self.rotation // NUM_PLAYERS

    @property
    def round_number(self) -> int:
        """東 1 局の「1」"""
        return self.rotation % NUM_PLAYERS + 1

    def seat_wind(self, seat: int) -> int:
        return EAST + (seat - self.dealer) % NUM_PLAYERS


@dataclass(frozen=True)
class HandState:
    start: HandStart
    seed: str                               # この局の山のシード
    rules: Rules
    actions: tuple[Action, ...]
    wall_tiles: tuple[int, ...]             # 山の並び（補正で入れ替えたあと）
    live_drawn: int                         # ツモ山から引いた枚数
    players: tuple[Player, Player, Player, Player]
    turn: int                               # 手番の席（いまツモった人。CLAIM では、いま切った人）
    phase: Phase
    scores: tuple[int, int, int, int]       # いまの持ち点（リーチ棒を出すと 1000 減る）
    kyotaku: int                            # いま卓に出ているリーチ棒の本数
    deals: tuple[DealReport, ...]           # 席ごとの、配牌の補正の記録
    pending: tuple[int, ...] = ()           # CLAIM：返事がまだの席（ロンできる人）
    rons: tuple[int, ...] = ()              # CLAIM：ロンを宣言した席
    misses: tuple[Miss, ...] = ()           # あがり牌の見送り（役なし・フリテンでロンできなかったときも含む）
    result: HandResult | None = None

    # ------------------------------------------------------------ 読み取り

    @property
    def finished(self) -> bool:
        return self.result is not None

    @property
    def dealer(self) -> int:
        return self.start.dealer

    @property
    def round_wind(self) -> int:
        return self.start.round_wind

    def seat_wind(self, seat: int) -> int:
        return self.start.seat_wind(seat)

    @property
    def live_remaining(self) -> int:
        """ツモ山の残り枚数（カンは無いので、70 枚から引いた枚数を引くだけ。カンができたら、嶺上牌のぶんも引く）"""
        return NUM_LIVE - self.live_drawn

    @property
    def dora_indicators(self) -> tuple[int, ...]:
        """ドラ表示牌（カンは無いので、最初の 1 枚だけ）"""
        return (self.wall_tiles[DORA_START],)

    @property
    def ura_indicators(self) -> tuple[int, ...]:
        """裏ドラ表示牌（リーチしてあがったときだけ見る）"""
        return (self.wall_tiles[URA_START],)

    @property
    def last_discard(self) -> tuple[int, Discard] | None:
        """いちばん最近の打牌（席, 牌）"""
        for action in reversed(self.actions):
            if action.move in (Move.DISCARD, Move.RIICHI):
                river = self.players[action.seat].river
                return (action.seat, river[-1]) if river else None
        return None

    @property
    def discard_count(self) -> int:
        """この局で切られた牌の合計"""
        return sum(len(p.river) for p in self.players)

    def visible_to(self, seat: int) -> tuple[int, ...]:
        """その席から見えている、自分の手牌以外の牌（全員の河とドラ表示牌）。

        いまは、どの席にも同じものが見えている（鳴きができたら、副露の牌も足す）。
        """
        return (*(t for p in self.players for t in p.river_tiles), *self.dora_indicators)

    def draws_left(self, seat: int) -> int:
        """その席が、このあとツモれる回数。

        ツモは、手番の人（いまツモった人、または、いま切った人）の次の人から順に回る。
        残りが left 枚なら、k 枚目（k ＝ 1〜left）をツモるのは (手番 ＋ k) の席。
        """
        left = self.live_remaining
        offset = (seat - self.turn) % NUM_PLAYERS
        if offset == 0:
            return left // NUM_PLAYERS
        return (left - offset) // NUM_PLAYERS + 1 if left >= offset else 0

    # ------------------------------------------------------------ できる行動

    def can_tsumo(self, seat: int) -> bool:
        """いま「ツモ」であがれるか"""
        player = self.players[seat]
        if self.result is not None or self.phase is not Phase.DRAW or seat != self.turn or player.drawn is None:
            return False
        if not is_win_shape(player.tiles):
            return False
        return judge(tsumo_context(self, seat), self.rules).ok

    def riichi_tiles(self, seat: int) -> tuple[int, ...]:
        """リーチを宣言して切れる牌（切っても聴牌が残る牌）。リーチできなければ空"""
        player = self.players[seat]
        if self.result is not None or self.phase is not Phase.DRAW or seat != self.turn or player.drawn is None or player.in_riichi:
            return ()
        if self.scores[seat] < RIICHI_STICK or self.live_remaining < RIICHI_MIN_WALL:
            return ()
        counts = counts34(player.tiles)
        kinds = set()
        for kind in {kind_of(t) for t in player.tiles}:
            counts[kind] -= 1
            if shanten_of(counts) == TENPAI:
                kinds.add(kind)
            counts[kind] += 1
        return tuple(t for t in player.tiles if kind_of(t) in kinds)

    def can_nine(self, seat: int) -> bool:
        """九種九牌で流局にできるか（最初のツモで、么九牌が 9 種類以上）"""
        player = self.players[seat]
        if self.result is not None or self.phase is not Phase.DRAW or seat != self.turn or player.drawn is None:
            return False
        if not self.rules.abortive_draws or player.river:
            return False
        return nine_kinds(player.tiles) >= NINE_KINDS

    def ron_check(self, seat: int, tile: int | None = None) -> RonCheck:
        """その席が、いちばん最近の捨て牌（tile を渡せば、その牌）でロンできるか"""
        if tile is None:
            last = self.last_discard
            if last is None or last[0] == seat:
                return NO_RON
            tile = last[1].tile
        return _ron_check(self, seat, tile)

    def furiten(self, seat: int) -> Furiten | None:
        """その席がいまフリテンか（聴牌していなければ None）"""
        player = self.players[seat]
        waits = wait_kinds(player.hand)
        if not waits:
            return None
        if any(kind in player.river_kinds for kind in waits):
            return Furiten.RIVER
        if player.riichi_missed:
            return Furiten.RIICHI
        if player.missed:
            return Furiten.MISSED
        return None


def nine_kinds(tiles: Sequence[int]) -> int:
    """么九牌の種類数"""
    return len({kind_of(t) for t in tiles if is_yaochu_kind(kind_of(t))})


def _wall(hand: HandState) -> Wall:
    return Wall(list(hand.wall_tiles), live_drawn=hand.live_drawn, sealed=True)


def _with_player(hand: HandState, seat: int, player: Player) -> tuple[Player, Player, Player, Player]:
    players = list(hand.players)
    players[seat] = player
    return tuple(players)  # type: ignore[return-value]


# ---------------------------------------------------------------- あがりの状況


def _base_context(hand: HandState, seat: int, tile: int, *, is_tsumo: bool, closed: Sequence[int]) -> WinContext:
    player = hand.players[seat]
    riichi_on = player.riichi_paid
    return WinContext(
        closed_tiles=tuple(closed),
        win_tile=tile,
        is_tsumo=is_tsumo,
        seat_wind=hand.seat_wind(seat),
        round_wind=hand.round_wind,
        riichi=riichi_on,
        double_riichi=riichi_on and player.double_riichi,
        ippatsu=riichi_on and player.ippatsu,
        dora_indicators=hand.dora_indicators,
        ura_indicators=hand.ura_indicators if riichi_on else (),
        honba=hand.start.honba,
        kyotaku=hand.kyotaku,
    )


def tsumo_context(hand: HandState, seat: int) -> WinContext:
    """いまツモであがったときの状況（ハイテイ・天和・地和・一発などを含む。本場・供託は局のいまの値）"""
    player = hand.players[seat]
    assert player.drawn is not None
    ctx = _base_context(hand, seat, player.drawn, is_tsumo=True, closed=player.tiles)
    first = not player.river              # 最初のツモ（鳴きは無いので、誰にも邪魔されていない）
    return replace(
        ctx,
        haitei=hand.live_remaining == 0,
        tenhou=first and seat == hand.dealer,
        chiihou=first and seat != hand.dealer,
    )


def ron_context(hand: HandState, seat: int, tile: int) -> WinContext:
    """その牌でロンしたときの状況（河底・一発などを含む。本場・供託は局のいまの値）"""
    player = hand.players[seat]
    ctx = _base_context(hand, seat, tile, is_tsumo=False, closed=(*player.hand, tile))
    return replace(ctx, houtei=hand.live_remaining == 0)


def _ron_check(hand: HandState, seat: int, tile: int) -> RonCheck:
    player = hand.players[seat]
    if player.drawn is not None or not is_win_shape((*player.hand, tile)):
        return NO_RON
    reason = hand.furiten(seat)
    yaku = judge(ron_context(hand, seat, tile), hand.rules).ok
    return RonCheck(True, reason, yaku)


# ---------------------------------------------------------------- 局を始める


def _hand_seed(config: GameConfig, number: int) -> str:
    return f"{config.seed}:{number}"


def start_hand(config: GameConfig, start: HandStart) -> HandState:
    """配牌を配り、親が最初の 1 枚をツモった状態"""
    seed = _hand_seed(config, start.number)
    wall = Wall.from_seed(seed)
    deals: list[DealReport] = []
    # 配牌の補正：自分から先に、席の順に（補正 0 の席は、乱数も使わず山にも触れない）
    for seat in range(NUM_PLAYERS):
        order = (seat - start.dealer) % NUM_PLAYERS
        deals.append(
            improve_deal(
                wall, order, config.luck_of(seat), f"{seed}:{seat}",
                seat_wind=start.seat_wind(seat), round_wind=start.round_wind,
            )
        )
    wall.seal()
    players = tuple(
        Player(hand=tuple(sort_tiles(wall.dealt_hand((seat - start.dealer) % NUM_PLAYERS)))) for seat in range(NUM_PLAYERS)
    )
    hand = HandState(
        start=start,
        seed=seed,
        rules=config.rules,
        actions=(),
        wall_tiles=tuple(wall.tiles),
        live_drawn=0,
        players=players,  # type: ignore[arg-type]
        turn=start.dealer,
        phase=Phase.DRAW,
        scores=start.scores,
        kyotaku=start.kyotaku,
        deals=tuple(deals),
    )
    return _draw(config, hand, start.dealer)


def _draw(config: GameConfig, hand: HandState, seat: int) -> HandState:
    """seat の人が 1 枚ツモる（その前に、その席のツモの補正を試す）"""
    wall = _wall(hand)
    player = hand.players[seat]
    number = len(player.draws) + 1
    probability = draw_probability(config.luck_of(seat).draw)
    report = NO_DRAW_LUCK
    if probability > 0:           # 補正なしの席では、乱数も作らない
        visible = hand.visible_to(seat)

        def wanted() -> list[int]:
            counts = counts34(player.hand)
            return [kind for kind, _ in acceptance(counts, remaining_counts(player.hand, visible)).tiles]

        report = improve_draw(wall, probability, wanted, Rng(hand.seed, f"luck:draw:{seat}:{number}"))
    tile = wall.draw()
    player = replace(player, drawn=tile, draws=(*player.draws, Draw(number, tile, report)))
    return replace(
        hand,
        wall_tiles=tuple(wall.tiles),
        live_drawn=wall.live_drawn,
        players=_with_player(hand, seat, player),
        turn=seat,
        phase=Phase.DRAW,
        pending=(),
        rons=(),
    )


# ---------------------------------------------------------------- 行動を進める


def apply_hand(config: GameConfig, hand: HandState, action: Action) -> HandState:
    """局の中で、行動を 1 つ進める。できない行動なら GameError"""
    if hand.result is not None:
        raise GameError("この局は終わっています")
    seat, move = action.seat, action.move
    actions = (*hand.actions, action)
    if hand.phase is Phase.DRAW:
        if seat != hand.turn:
            raise GameError("手番ではありません")
        if move in (Move.DISCARD, Move.RIICHI):
            assert action.tile is not None
            return _discard(config, replace(hand, actions=actions), seat, action.tile, declare=move is Move.RIICHI)
        if move is Move.TSUMO:
            if not hand.can_tsumo(seat):
                raise GameError("ツモであがれる形ではありません")
            return _end_tsumo(config, replace(hand, actions=actions), seat)
        if move is Move.NINE:
            if not hand.can_nine(seat):
                raise GameError("九種九牌にはできません")
            return _end_abortive(replace(hand, actions=actions), EndKind.NINE_TERMINALS, caller=seat)
        raise GameError("いまはできない行動です")
    # CLAIM：ロンできる人の返事
    if seat not in hand.pending or move not in (Move.RON, Move.PASS):
        raise GameError("いまはできない行動です")
    pending = tuple(s for s in hand.pending if s != seat)
    rons = hand.rons
    players = hand.players
    misses = hand.misses
    if move is Move.RON:
        rons = (*rons, seat)
    else:
        players = _with_player(hand, seat, _missed(hand.players[seat]))
        tile = hand.players[hand.turn].river[-1].tile
        misses = (*misses, Miss(seat, hand.turn, tile, RonCheck(True, None, True), passed=True))
    hand = replace(hand, actions=actions, pending=pending, rons=rons, players=players, misses=misses)
    if pending:
        return hand
    if hand.rons:
        return _end_ron(config, hand)
    return _after_discard(config, hand)


def _missed(player: Player) -> Player:
    """あがり牌を見逃した（同巡内フリテン。リーチしていれば、この局のあいだずっとフリテン）"""
    return replace(player, missed=True, riichi_missed=player.riichi_missed or player.riichi_paid)


def _discard(config: GameConfig, hand: HandState, seat: int, tile: int, *, declare: bool) -> HandState:
    player = hand.players[seat]
    if tile not in player.tiles:
        raise GameError(f"手牌にない牌は切れません: {tile}")
    if player.in_riichi and tile != player.drawn:
        raise GameError("リーチのあとは、ツモった牌を切るだけです")
    if declare and tile not in hand.riichi_tiles(seat):
        if player.in_riichi:
            raise GameError("もうリーチしています")
        if hand.scores[seat] < RIICHI_STICK:
            raise GameError("持ち点が 1000 点より少ないので、リーチできません")
        if hand.live_remaining < RIICHI_MIN_WALL:
            raise GameError("このあと自分のツモ番が無いので、リーチできません")
        raise GameError("その牌を切ると聴牌にならないので、リーチできません")
    remaining = list(player.tiles)
    remaining.remove(tile)
    river = (*player.river, Discard(tile, tsumogiri=tile == player.drawn, riichi=declare, order=hand.discard_count))
    player = replace(
        player,
        hand=tuple(sort_tiles(remaining)),
        drawn=None,
        river=river,
        # 一発は、リーチのあと次に自分が切るまで。同巡内フリテンは、自分が切ったら解ける
        ippatsu=declare,
        missed=False,
        riichi_at=len(river) - 1 if declare else player.riichi_at,
        double_riichi=player.double_riichi or (declare and len(river) == 1),
    )
    hand = replace(hand, players=_with_player(hand, seat, player), turn=seat)
    # この牌でロンできる人を調べる。あがりの形になるのにロンできない人（役なし・フリテン）は、見逃しになる
    pending = []
    players = list(hand.players)
    misses = list(hand.misses)
    for step in range(1, NUM_PLAYERS):
        other = (seat + step) % NUM_PLAYERS
        check = _ron_check(hand, other, tile)
        if not check.shape:
            continue
        if check.ok:
            pending.append(other)
        else:
            players[other] = _missed(players[other])
            misses.append(Miss(other, seat, tile, check, passed=False))
    hand = replace(hand, players=tuple(players), misses=tuple(misses))  # type: ignore[arg-type]
    if pending:
        return replace(hand, phase=Phase.CLAIM, pending=tuple(pending), rons=())
    return _after_discard(config, hand)


def _after_discard(config: GameConfig, hand: HandState) -> HandState:
    """捨て牌が通った（誰もロンしなかった）あと：リーチの成立、途中流局、流局、次の人のツモ"""
    seat = hand.turn
    player = hand.players[seat]
    rules = config.rules
    if player.river and player.river[-1].riichi:
        scores = list(hand.scores)
        scores[seat] -= RIICHI_STICK
        hand = replace(
            hand,
            players=_with_player(hand, seat, replace(player, riichi_paid=True)),
            scores=tuple(scores),  # type: ignore[arg-type]
            kyotaku=hand.kyotaku + 1,
        )
        if rules.abortive_draws and all(p.riichi_paid for p in hand.players):
            return _end_abortive(hand, EndKind.FOUR_RIICHI)
    if rules.abortive_draws and _four_winds(hand):
        return _end_abortive(hand, EndKind.FOUR_WINDS)
    if hand.live_remaining <= 0:
        return _end_exhausted(config, hand)
    return _draw(config, hand, (seat + 1) % NUM_PLAYERS)


def _four_winds(hand: HandState) -> bool:
    """最初の 1 巡で、4 人が同じ風牌を切ったか"""
    if any(len(p.river) != 1 for p in hand.players):
        return False
    kinds = {kind_of(p.river[0].tile) for p in hand.players}
    return len(kinds) == 1 and EAST <= next(iter(kinds)) <= NORTH


# ---------------------------------------------------------------- 局の終わり


def _pay_win(hand: HandState, seat: int, ctx: WinContext, judgement: Judgement, from_seat: int | None) -> tuple[int, int, int, int]:
    pay = [0] * NUM_PLAYERS
    main = judgement.main + judgement.honba_main
    if from_seat is not None:
        pay[from_seat] -= main
        pay[seat] += main
    else:
        for other in range(NUM_PLAYERS):
            if other == seat:
                continue
            if seat == hand.dealer or other == hand.dealer:
                amount = main
            else:
                amount = judgement.additional + judgement.honba_additional
            pay[other] -= amount
            pay[seat] += amount
    pay[seat] += judgement.kyotaku_bonus
    return tuple(pay)  # type: ignore[return-value]


def _finish(hand: HandState, result: HandResult) -> HandState:
    return replace(hand, phase=Phase.END, pending=(), result=result)


def _settle(hand: HandState, settlement: Sequence[int]) -> tuple[int, int, int, int]:
    return tuple(s + d for s, d in zip(hand.scores, settlement, strict=True))  # type: ignore[return-value]


def _end_wins(config: GameConfig, hand: HandState, winners: Sequence[tuple[int, WinContext, int | None]], kind: EndKind,
              bumped: Sequence[int] = ()) -> HandState:
    wins = []
    settlement = [0] * NUM_PLAYERS
    for index, (seat, ctx, from_seat) in enumerate(winners):
        # 本場と供託は、先頭の 1 人だけがもらう（上家取り）
        ctx = replace(ctx, honba=hand.start.honba if index == 0 else 0, kyotaku=hand.kyotaku if index == 0 else 0)
        judgement = judge(ctx, config.rules)
        if not judgement.ok:              # ここに来る前に確かめてあるので、起きないはず
            raise GameError("あがりの判定に失敗しました")
        pay = _pay_win(hand, seat, ctx, judgement, from_seat)
        wins.append(Win(seat, ctx, judgement, from_seat, pay))
        settlement = [a + b for a, b in zip(settlement, pay, strict=True)]
    dealer_won = any(w.seat == hand.dealer for w in wins)
    result = HandResult(
        kind=kind,
        wins=tuple(wins),
        settlement=tuple(settlement),  # type: ignore[arg-type]
        scores=_settle(hand, settlement),
        kyotaku=0,
        renchan=dealer_won,
        bumped=tuple(bumped),
    )
    return _finish(hand, result)


def _end_tsumo(config: GameConfig, hand: HandState, seat: int) -> HandState:
    return _end_wins(config, hand, [(seat, tsumo_context(hand, seat), None)], EndKind.TSUMO)


def _end_ron(config: GameConfig, hand: HandState) -> HandState:
    seat = hand.turn
    last = hand.players[seat].river[-1]
    # 捨てた人から見て、順番が先の人から
    order = sorted(hand.rons, key=lambda s: (s - seat) % NUM_PLAYERS)
    winners = order if config.rules.multiple_ron else order[:1]
    bumped = [s for s in order if s not in winners]
    return _end_wins(
        config, hand, [(s, ron_context(hand, s, last.tile), seat) for s in winners], EndKind.RON, bumped=bumped,
    )


def _end_exhausted(config: GameConfig, hand: HandState) -> HandState:
    tenpai = tuple(bool(wait_kinds(p.hand)) for p in hand.players)
    nagashi: tuple[int, ...] = ()
    if config.rules.nagashi_mangan:
        nagashi = tuple(
            seat for seat, p in enumerate(hand.players) if p.river and all(is_yaochu_kind(kind_of(t)) for t in p.river_tiles)
        )
    settlement = [0] * NUM_PLAYERS
    if nagashi:
        # 流し満貫：満貫のツモあがりと同じ点（本場は付けない）。罰符の精算はしない
        for seat in nagashi:
            for other in range(NUM_PLAYERS):
                if other == seat:
                    continue
                amount = 4000 if seat == hand.dealer or other == hand.dealer else 2000
                settlement[other] -= amount
                settlement[seat] += amount
    else:
        count = sum(tenpai)
        if 0 < count < NUM_PLAYERS:
            for seat in range(NUM_PLAYERS):
                settlement[seat] = NOTEN_TOTAL // count if tenpai[seat] else -(NOTEN_TOTAL // (NUM_PLAYERS - count))
    result = HandResult(
        kind=EndKind.EXHAUSTED,
        tenpai=tenpai,
        nagashi=nagashi,
        settlement=tuple(settlement),  # type: ignore[arg-type]
        scores=_settle(hand, settlement),
        kyotaku=hand.kyotaku,
        renchan=tenpai[hand.dealer],
    )
    return _finish(hand, result)


def _end_abortive(hand: HandState, kind: EndKind, *, caller: int | None = None) -> HandState:
    result = HandResult(
        kind=kind,
        scores=hand.scores,
        kyotaku=hand.kyotaku,
        renchan=True,
        caller=caller,
    )
    return _finish(hand, result)


# ---------------------------------------------------------------- 試合


@dataclass(frozen=True)
class GameResult:
    scores: tuple[int, int, int, int]   # 最後の持ち点（残ったリーチ棒を 1 位に足したあと）
    ranks: tuple[int, int, int, int]    # 席ごとの順位（1〜4）
    kyotaku_to: int | None              # 残ったリーチ棒を受け取った席（残っていなければ None）
    reason: str                         # 終わった理由（下の END_REASONS の鍵）


END_REASONS = {
    "planned": "予定の局が終わった",
    "tobi": "持ち点が 0 点より少ない人が出た（飛び）",
    "agariyame": "最後の局で、親が 30000 点以上の 1 位になった（あがりやめ・聴牌やめ）",
    "sudden_death": "延長戦で、30000 点以上の人が出た",
    "extension_end": "延長戦の最後の局が終わった",
    "max_hands": f"局の数が上限（{MAX_HANDS} 局）に達した（飛びなしで、連荘が長く続いたとき）",
}


@dataclass(frozen=True)
class GameState:
    config: GameConfig
    first_dealer: int                   # 起家（最初の親）の席
    hands: tuple[HandState, ...]        # 打った局（最後が、いま打っている局か、最後に終わった局）
    result: GameResult | None = None

    @property
    def current(self) -> HandState:
        return self.hands[-1]

    @property
    def finished(self) -> bool:
        return self.result is not None

    @property
    def between_hands(self) -> bool:
        """局が終わって、まだ次の局を始めていないか（試合が終わっていれば False）"""
        return self.result is None and self.current.result is not None

    @property
    def logs(self) -> tuple[tuple[Action, ...], ...]:
        return tuple(h.actions for h in self.hands)

    def rank_order(self, scores: Sequence[int]) -> list[int]:
        """順位の順に並べた席（同点なら、起家に近い人が上）"""
        return sorted(range(NUM_PLAYERS), key=lambda s: (-scores[s], (s - self.first_dealer) % NUM_PLAYERS))

    def ranks(self, scores: Sequence[int]) -> tuple[int, int, int, int]:
        order = self.rank_order(scores)
        return tuple(order.index(s) + 1 for s in range(NUM_PLAYERS))  # type: ignore[return-value]


def start_game(config: GameConfig) -> GameState:
    """試合を始める（起家を決めて、最初の局の配牌を配る）"""
    first = Rng(config.seed, "dealer").below(NUM_PLAYERS)
    start = HandStart(number=0, rotation=0, dealer=first, honba=0, kyotaku=0, scores=(START_POINTS,) * NUM_PLAYERS)
    return GameState(config=config, first_dealer=first, hands=(start_hand(config, start),))


def apply(game: GameState, action: Action) -> GameState:
    """いまの局で、行動を 1 つ進める。局が終わったら、試合が終わったかどうかも決める"""
    if game.finished:
        raise GameError("この試合は終わっています")
    hand = apply_hand(game.config, game.current, action)
    game = replace(game, hands=(*game.hands[:-1], hand))
    if hand.result is not None:
        reason = _game_over(game)
        if reason is not None:
            game = replace(game, result=_final(game, reason))
    return game


def _game_over(game: GameState) -> str | None:
    """局が終わったときに、試合が終わるかを決める。終わるなら、その理由（END_REASONS の鍵）。

    ふつうの決まりで続くときでも、局の数が上限（MAX_HANDS）に達したら終える（飛びなしで連荘が続くと、
    いつまでも終わらないことがあるため。保存の形も、局の数を MAX_HANDS までに限っている）。
    """
    reason = _game_over_by_rules(game)
    if reason is None and len(game.hands) >= MAX_HANDS:
        return "max_hands"
    return reason


def _game_over_by_rules(game: GameState) -> str | None:
    hand = game.current
    result = hand.result
    assert result is not None
    scores = result.scores
    rules = game.config.rules
    if rules.tobi and min(scores) < 0:
        return "tobi"
    planned = game.config.length.planned
    rotation = hand.start.rotation
    top = max(scores)
    if rotation < planned - 1:
        return None
    if rotation == planned - 1:                     # 最後の局（オーラス）
        if result.renchan:
            if result.kind.is_abortive:
                return None
            dealer = hand.dealer
            if game.rank_order(scores)[0] == dealer and scores[dealer] >= GOAL_POINTS:
                return "agariyame"
            return None
        return "planned" if top >= GOAL_POINTS else None      # 誰も 30000 点に届いていなければ延長
    # 延長戦（サドンデス）
    if top >= GOAL_POINTS:
        return "sudden_death"
    if rotation >= planned + NUM_PLAYERS - 1 and not result.renchan:
        return "extension_end"
    return None


def _final(game: GameState, reason: str) -> GameResult:
    result = game.current.result
    assert result is not None
    scores = list(result.scores)
    kyotaku_to = None
    if result.kyotaku:
        kyotaku_to = game.rank_order(scores)[0]
        scores[kyotaku_to] += RIICHI_STICK * result.kyotaku
    final = tuple(scores)
    return GameResult(final, game.ranks(final), kyotaku_to, reason)  # type: ignore[arg-type]


def next_start(game: GameState) -> HandStart:
    """終わった局の次の局の始まり（連荘・本場・供託・親）"""
    hand = game.current
    result = hand.result
    if result is None:
        raise GameError("まだ局が終わっていません")
    start = hand.start
    # 本場：親があがった・流局（途中流局を含む）なら 1 つ増やす。子があがったら 0 に戻す
    honba = 0 if result.kind.is_win and not result.renchan else start.honba + 1
    return HandStart(
        number=start.number + 1,
        rotation=start.rotation + (0 if result.renchan else 1),
        dealer=start.dealer if result.renchan else (start.dealer + 1) % NUM_PLAYERS,
        honba=honba,
        kyotaku=result.kyotaku,
        scores=result.scores,
    )


def next_hand(game: GameState) -> GameState:
    """次の局を始める（局が終わっていて、試合が終わっていないとき）"""
    if game.finished:
        raise GameError("この試合は終わっています")
    if game.current.result is None:
        raise GameError("まだ局が終わっていません")
    if len(game.hands) >= MAX_HANDS:
        raise GameError("局の数が多すぎます")
    return replace(game, hands=(*game.hands, start_hand(game.config, next_start(game))))


# ---------------------------------------------------------------- 誰の返事を待っているか


def waiting_for(hand: HandState) -> int | None:
    """次に行動を決める席（局が終わっていれば None）。CLAIM では、返事がまだの人のうち、順番が先の人"""
    if hand.result is not None:
        return None
    if hand.phase is Phase.CLAIM:
        return min(hand.pending, key=lambda s: (s - hand.turn) % NUM_PLAYERS)
    return hand.turn


def auto_action(hand: HandState, seat: int) -> Action | None:
    """リーチしている人の手番は、決まった行動しかない（あがれればツモ、そうでなければツモ切り）。それ以外は None"""
    if hand.result is not None or hand.phase is not Phase.DRAW or seat != hand.turn:
        return None
    player = hand.players[seat]
    if not player.in_riichi or player.drawn is None:
        return None
    if hand.can_tsumo(seat):
        return tsumo(seat)
    return discard(seat, player.drawn)


# ---------------------------------------------------------------- 再生と保存


def replay(config: GameConfig, logs: Sequence[Sequence[Action]]) -> GameState:
    """設定と、局ごとの行動の列から、状態を作り直す"""
    game = start_game(config)
    for index, actions in enumerate(logs):
        if index > 0:
            game = next_hand(game)
        for action in actions:
            game = apply(game, action)
    return game


def to_save(game: GameState) -> dict[str, Any]:
    """ブラウザなどに残すための小さな記録（設定＋局ごとの行動の列）"""
    return {"v": SAVE_VERSION, "config": game.config.to_dict(), "logs": [[a.to_list() for a in h.actions] for h in game.hands]}


def from_save(data: dict[str, Any]) -> GameState:
    """記録から状態を作り直す。形が違う・できない行動が入っている場合は ValueError。

    記録はブラウザに置いてあるので、壊れていたり、書き換えられていたりすることがある。
    どんな中身でも、ValueError 以外の例外を出さないようにする。
    """
    if not isinstance(data, dict) or data.get("v") != SAVE_VERSION:
        raise ValueError("記録の形が違います")
    logs = data.get("logs")
    if not isinstance(logs, list) or not 1 <= len(logs) <= MAX_HANDS:
        raise ValueError("記録の形が違います（局の列）")
    if any(not isinstance(items, list) or len(items) > MAX_ACTIONS for items in logs):
        raise ValueError("記録の形が違います（行動の列）")
    try:
        config = GameConfig.from_dict(data.get("config"))
        actions = [[Action.from_list(item) for item in items] for items in logs]
        return replay(config, actions)
    except ValueError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError, ArithmeticError, AssertionError) as error:
        raise ValueError(f"記録を読めません: {error}") from error

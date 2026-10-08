"""CPU 3 人との対局：4 人で打つ局と、試合（東風戦・半荘戦）の進行。

決めごとは雀魂の段位戦に合わせ、流派で分かれるものはルールの設定（engine/rules.py）で切り替える。

局の進み方
    親から順に、ツモって 1 枚切る。切った牌に、ほかの人がロン・ポン・チー・カン（大明槓）できれば、
    その人たちの返事を待つ。優先は ロン ＞ ポン・大明槓 ＞ チー。誰も鳴かなければ、次の人がツモる。
    自分の番では、打牌のほかに、ツモあがり・リーチ・暗槓・加槓・九種九牌（途中流局）を選べる。
    チー・ポンしたら、ツモらずに 1 枚切る。カンしたら、嶺上牌（王牌の牌）をツモってから切る。
    山（ツモ山 70 枚。カン 1 回ごとに 1 枚減る）が尽きたら流局。聴牌の人が、聴牌していない人から点をもらう。

決めごと（雀魂の段位戦。出典は docs/DESIGN.md の 7 章）
    リーチ        門前（暗槓だけなら門前）で聴牌、持ち点 1000 点以上、このあとツモ番がある（ツモ山が 4 枚以上残っている）こと。
                  宣言した牌が通ったら（ロンされなかったら。鳴かれても成立する）、1000 点を卓に出す（供託）。
                  リーチのあとはツモ切りだけ。暗槓は、ツモった牌で、待ちが変わらないときだけできる（送り槓はできない）
    フリテン      自分の河に待ち牌があるとロンできない（ツモはできる）。あがり牌を見逃すと、次に自分がツモるまで
                  ロンできない（同巡内フリテン。役が無くてロンできなかった牌も、見逃しになる）。
                  リーチのあとに見逃すと、その局のあいだずっとロンできない
    鳴き          チーは上家（自分の直前の人）の捨て牌だけ。ポン・大明槓は誰の捨て牌でも。最後の捨て牌（河底牌）は鳴けない。
                  喰い替えは禁止：鳴いた直後に、鳴いた牌と同じ牌、チーした順子の反対側の牌（例：45 で 3 をチーして 6）は切れない。
                  鳴いたあとに切れる牌が残らない鳴きは、できない
    カン          1 局に 4 回まで。最後の牌（海底牌）をツモったときはできない。カンドラは、暗槓ならすぐ、
                  大明槓・加槓なら次の打牌のあと（その打牌でのロンから数える）にめくる。カン裏もある。
                  加槓の牌は、ほかの人がロンできる（槍槓）。暗槓の牌は、国士無双だけロンできる
    四槓散了      2 人以上で合わせて 4 回カンしたら、4 回目のカンのあとの打牌が通ったところで途中流局。
                  1 人で 4 回なら続ける（それ以上のカンはできない）
    責任払い      大三元・大四喜が確定する 3 種目の三元牌（4 種目の風牌）をポン・大明槓させた人は、その役満の点を払う。
                  ツモなら全額、ほかの人のロンなら放銃した人と半分ずつ。本場の点も払う
    鳴きと一発など  誰かが鳴く（暗槓を含む）と、一発は消える。それより前に鳴きがあると、ダブル立直・天和・地和・九種九牌・
                  四風連打にはならない。流し満貫は、自分の捨て牌が鳴かれていたらならない（自分が鳴くのはかまわない）
    複数ロン      2 人・3 人が同じ牌でロンしたら、全員のあがり。本場と供託は、捨てた人から見て順番が先の人だけがもらう
                  （上家取り）。ルールで「頭ハネ」（先の 1 人だけ）にもできる
    流局          聴牌の人が 1〜3 人なら、聴牌していない人から合わせて 3000 点（役がない聴牌も聴牌に数える）。
                  流し満貫（捨て牌がすべて么九牌）の人がいれば、罰符の代わりに満貫のツモと同じ点をもらう（本場は付けない）
    途中流局      九種九牌（最初のツモで么九牌が 9 種類以上。宣言したとき）、四風連打（最初の 1 巡で 4 人が同じ風牌）、
                  四家立直（4 人のリーチが成立）、四槓散了。点の動きは無く、親は続ける
    連荘          親があがったとき、流局で親が聴牌していたとき、途中流局のとき。本場が 1 つ増える
    試合の終わり  予定の局（東風戦は東 4 局、半荘戦は南 4 局）が終わったとき、誰かが 30000 点以上なら終わり。
                  いなければ延長（東風戦は南場、半荘戦は西場）に入り、誰かが 30000 点以上になった局で終わる
                  （サドンデス。延長の 4 局目が終われば、それで終わり）。
                  最後の局で、親があがるか聴牌して、30000 点以上の 1 位なら、そこで終わる（あがりやめ・聴牌やめ）。
                  誰かの持ち点が 0 点より少なくなったら終わる（飛び。0 点ちょうどは続ける）。
                  終わったときに卓に残っているリーチ棒は、1 位がもらう。同点なら、起家に近い人が上の順位

状態は「設定（シードなど）＋局ごとの行動の列」から完全に作り直せる（replay）。行動の列には CPU の行動（鳴かずに見送った
返事も）も入るので、CPU の打ち方を変えたあとでも、記録した対局はそのまま作り直せる。CPU の打ち方は engine/cpu.py にある。

ツキ補正は、席ごとに配牌とツモに働く（自分は config.luck、CPU 3 人は config.cpu_luck。CPU の初期値は 0）。
補正は、まだ誰も見ていない牌どうしの入れ替えだけ（engine/luck.py）。補正 0 の席では、乱数も引かず山にも触れない。
嶺上牌には補正を働かせない（王牌の牌なので）。
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
from engine.melds import Meld, MeldType
from engine.rng import Rng
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.judge import Judgement, judge
from engine.tiles import CHUN, EAST, HAKU, NORTH, NUM_TILES, counts34, is_red, is_yaochu_kind, kind_of, sort_tiles
from engine.wall import DORA_START, NUM_LIVE, NUM_RINSHAN, URA_START, Wall
from engine.yaku_table import YAKUMAN_HAN

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
#: 1 局にできるカンの回数（嶺上牌の枚数）
MAX_KANS = NUM_RINSHAN
#: 役満 1 倍ぶんの点（ロンで受け取る点。子・親）。責任払いの計算に使う
YAKUMAN_CHILD = 32_000
YAKUMAN_DEALER = 48_000
#: 1 本場につき、あがった人が受け取る点の合計
HONBA_TOTAL = 300
MAX_SEED = 10**12
#: 保存の形の版。1 は鳴きの無かったころ（Phase 3）の記録で、作り直すときは鳴きなしのルールで打つ
SAVE_VERSION = 2
#: 保存した記録の大きさの上限（壊れた記録で、作り直しに何分もかからないように）
MAX_HANDS = 64
MAX_ACTIONS = 800

SEAT_NAMES = ("自分", "下家", "対面", "上家")
DRAGONS = frozenset({HAKU, HAKU + 1, CHUN})
WINDS = frozenset(range(EAST, NORTH + 1))


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class GameError(ValueError):
    """できない行動（手番でない人の打牌、手牌にない牌、聴牌していないリーチ、喰い替え、など）"""


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
    RON = "n"         # ロン（捨て牌・加槓の牌であがる）
    PASS = "p"        # ロン・鳴きをしないで見送る
    NINE = "k"        # 九種九牌で流局にする
    CHI = "c"         # チー（上家の捨て牌と、手の 2 枚で順子）
    PON = "o"         # ポン（捨て牌と、手の 2 枚で刻子）
    KAN = "m"         # 大明槓（捨て牌と、手の 3 枚で槓子）
    ANKAN = "a"       # 暗槓（手の 4 枚で槓子。自分の番に）
    KAKAN = "e"       # 加槓（ポンした刻子に、手の 1 枚を足す。自分の番に）


#: 牌を 1 枚指定する行動（切る牌・カンする牌）
TILE_MOVES = frozenset({Move.DISCARD, Move.RIICHI, Move.ANKAN, Move.KAKAN})
#: 捨て牌を鳴く行動と、使う手牌の枚数
CALL_SIZES = {Move.CHI: 2, Move.PON: 2, Move.KAN: 3}
CALL_MOVES = frozenset(CALL_SIZES)
KAN_MOVES = frozenset({Move.KAN, Move.ANKAN, Move.KAKAN})
MOVE_NAMES = {
    Move.DISCARD: "打牌", Move.RIICHI: "リーチ", Move.TSUMO: "ツモ", Move.RON: "ロン", Move.PASS: "見送り",
    Move.NINE: "九種九牌", Move.CHI: "チー", Move.PON: "ポン", Move.KAN: "カン（大明槓）", Move.ANKAN: "カン（暗槓）",
    Move.KAKAN: "カン（加槓）",
}


@dataclass(frozen=True)
class Action:
    seat: int
    move: Move
    tile: int | None = None             # 切る牌（打牌とリーチ）、カンする牌（暗槓・加槓）
    tiles: tuple[int, ...] = ()         # 鳴くときに使う手牌（チー・ポンは 2 枚、大明槓は 3 枚）

    def to_list(self) -> list:
        if self.tile is not None:
            return [self.seat, self.move.value, self.tile]
        return [self.seat, self.move.value, *self.tiles]

    @classmethod
    def from_list(cls, data: Sequence) -> Action:
        """保存した形（[席, "d", 牌ID]・[席, "o", 牌ID, 牌ID] など）から作る。形がおかしければ ValueError"""
        if not isinstance(data, (list, tuple)) or not 2 <= len(data) <= 5 or not isinstance(data[1], str):
            raise ValueError(f"行動の形がおかしい: {data!r}")
        seat, move = data[0], Move(data[1])           # 知らない文字なら ValueError
        if not _is_int(seat) or not 0 <= seat < NUM_PLAYERS:
            raise ValueError(f"席の番号がおかしい: {seat!r}")
        rest = list(data[2:])
        if any(not _is_int(t) or not 0 <= t < NUM_TILES for t in rest):
            raise ValueError(f"牌の番号がおかしい: {list(data)!r}")
        if move in TILE_MOVES:
            if len(rest) != 1:
                raise ValueError(f"行動の形がおかしい: {list(data)!r}")
            return cls(seat, move, rest[0])
        if move in CALL_MOVES:
            if len(rest) != CALL_SIZES[move] or len(set(rest)) != len(rest):
                raise ValueError(f"行動の形がおかしい: {list(data)!r}")
            return cls(seat, move, None, tuple(rest))
        if rest:
            raise ValueError(f"行動の形がおかしい: {list(data)!r}")
        return cls(seat, move)


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


def chi(seat: int, a: int, b: int) -> Action:
    return Action(seat, Move.CHI, None, (a, b))


def pon(seat: int, a: int, b: int) -> Action:
    return Action(seat, Move.PON, None, (a, b))


def kan(seat: int, a: int, b: int, c: int) -> Action:
    return Action(seat, Move.KAN, None, (a, b, c))


def ankan(seat: int, tile: int) -> Action:
    return Action(seat, Move.ANKAN, tile)


def kakan(seat: int, tile: int) -> Action:
    return Action(seat, Move.KAKAN, tile)


# ---------------------------------------------------------------- 局の状態


class Phase(StrEnum):
    DRAW = "draw"       # 手番の人が打牌などを選ぶ（ツモったあと。チー・ポンしたあとは、ツモらずに切る）
    CLAIM = "claim"     # 牌（捨て牌・加槓の牌・暗槓の牌）に対する、ほかの人の返事（ロン・鳴き・見送る）を待つ
    END = "end"         # 局が終わった


@dataclass(frozen=True)
class Discard:
    tile: int
    tsumogiri: bool = False     # ツモってきた牌を、そのまま切った
    riichi: bool = False        # リーチ宣言牌
    order: int = 0              # 局の何枚目の打牌か（0 始まり。全員の打牌を通して数える）
    called_by: int | None = None    # この牌を鳴いた人（鳴かれていなければ None）


@dataclass(frozen=True)
class Draw:
    number: int                 # その人の何回目のツモか（1 始まり。嶺上牌のツモも数える）
    tile: int
    luck: DrawReport            # このツモに補正が働いたか
    rinshan: bool = False       # 嶺上牌のツモ（カンのあと）


@dataclass(frozen=True)
class Furo:
    """副露 1 組（鳴いた面子と暗槓）"""

    meld: Meld
    from_seat: int | None = None    # 鳴いた牌を切った人（暗槓は None）
    added: int | None = None        # 加槓で足した牌


@dataclass(frozen=True)
class Player:
    hand: tuple[int, ...]               # 門前の手牌（ツモ牌を除く。理牌済み。副露が n 組なら 13 − 3n 枚、鳴いた直後は 14 − 3n 枚）
    drawn: int | None = None            # 自分の番でツモった牌（打牌するまで）
    river: tuple[Discard, ...] = ()     # 河（切った順。鳴かれた牌も、印を付けて残す）
    riichi_at: int | None = None        # リーチ宣言牌が、河の何枚目か（0 始まり）。宣言していなければ None
    riichi_paid: bool = False           # リーチが成立した（宣言牌が通り、リーチ棒を出した）
    double_riichi: bool = False         # 最初の打牌でリーチした（それより前に鳴きが無かった）
    ippatsu: bool = False               # 一発のチャンスが残っている（リーチのあと、次に自分が切るまで。誰かが鳴くと消える）
    missed: bool = False                # 同巡内フリテン（あがり牌を見逃してから、次に自分がツモるまで）
    riichi_missed: bool = False         # リーチのあとに、あがり牌を見逃した（この局のあいだ、ずっとフリテン）
    draws: tuple[Draw, ...] = ()        # ツモの記録
    furo: tuple[Furo, ...] = ()         # 副露（鳴いた順）
    rinshan: bool = False               # いまのツモ牌は嶺上牌（カンのあと）
    pao: int | None = None              # 責任払いの相手（大三元・大四喜を確定させる牌を鳴かせた人）
    pao_yaku: str | None = None         # 責任払いの役（daisangen ／ daisuushii）

    @property
    def tiles(self) -> tuple[int, ...]:
        """門前の手牌（ツモ牌があれば、それも含める）"""
        return self.hand if self.drawn is None else (*self.hand, self.drawn)

    @property
    def melds(self) -> tuple[Meld, ...]:
        return tuple(f.meld for f in self.furo)

    @property
    def menzen(self) -> bool:
        """門前か（暗槓だけなら門前のまま）"""
        return not any(f.meld.is_open for f in self.furo)

    @property
    def kans(self) -> int:
        return sum(1 for f in self.furo if f.meld.is_kan)

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

    @property
    def meld_tiles(self) -> tuple[int, ...]:
        return tuple(t for f in self.furo for t in f.meld.tiles)


class Furiten(StrEnum):
    RIVER = "river"         # 自分の河に、待ち牌がある
    MISSED = "missed"       # あがり牌を見逃した（次に自分がツモるまで）
    RIICHI = "riichi"       # リーチのあとに、あがり牌を見逃した（この局のあいだ、ずっと）


FURITEN_TEXTS = {
    Furiten.RIVER: "自分の河に待ち牌があるので、フリテン（ロンできない。ツモならあがれる）",
    Furiten.MISSED: "あがり牌を見逃したので、次に自分がツモるまでフリテン（同巡内フリテン）",
    Furiten.RIICHI: "リーチのあとにあがり牌を見逃したので、この局のあいだフリテン（ツモでしかあがれない）",
}


@dataclass(frozen=True)
class RonCheck:
    """ある牌でロンできるか"""

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
    from_seat: int                  # その牌を出した人（捨てた人・加槓した人）
    tile: int
    check: RonCheck                 # ロンできたか（できなければ、その理由）
    passed: bool                    # ロンできたのに、自分で見送った（鳴きを選んだときも）
    chankan: bool = False           # 加槓・暗槓の牌だった（槍槓）
    order: int = 0                  # いつのことか：その捨て牌が局の何枚目の打牌か（加槓・暗槓の牌なら、それまでに切られた枚数）

    @property
    def no_yaku(self) -> bool:
        """役がなくてロンできなかった（フリテンでもなかった）"""
        return not self.passed and self.check.furiten is None and not self.check.yaku


class ClaimKind(StrEnum):
    DISCARD = "discard"     # 捨て牌
    KAKAN = "kakan"         # 加槓の牌（槍槓でロンできる）
    ANKAN = "ankan"         # 暗槓の牌（国士無双だけロンできる）


@dataclass(frozen=True)
class Claim:
    """返事を待っている牌と、それに返事ができる人"""

    kind: ClaimKind
    seat: int                       # その牌を出した人（捨てた人・カンした人）
    tile: int
    ron: tuple[int, ...] = ()       # その牌でロンできる人
    pon: tuple[int, ...] = ()       # ポン・大明槓できる人
    chi: tuple[int, ...] = ()       # チーできる人


class EndKind(StrEnum):
    RON = "ron"
    TSUMO = "tsumo"
    EXHAUSTED = "exhausted"         # 流局（山が尽きた）
    NINE_TERMINALS = "nine"         # 途中流局：九種九牌
    FOUR_WINDS = "four_winds"       # 途中流局：四風連打
    FOUR_RIICHI = "four_riichi"     # 途中流局：四家立直
    FOUR_KANS = "four_kans"         # 途中流局：四槓散了

    @property
    def is_win(self) -> bool:
        return self in (EndKind.RON, EndKind.TSUMO)

    @property
    def is_abortive(self) -> bool:
        return self in (EndKind.NINE_TERMINALS, EndKind.FOUR_WINDS, EndKind.FOUR_RIICHI, EndKind.FOUR_KANS)


END_NAMES = {
    EndKind.RON: "ロン",
    EndKind.TSUMO: "ツモ",
    EndKind.EXHAUSTED: "流局",
    EndKind.NINE_TERMINALS: "九種九牌",
    EndKind.FOUR_WINDS: "四風連打",
    EndKind.FOUR_RIICHI: "四家立直",
    EndKind.FOUR_KANS: "四槓散了",
}


@dataclass(frozen=True)
class Win:
    seat: int
    ctx: WinContext                         # あがりの状況（解説は engine.scoring.explain に渡して作る）
    judgement: Judgement                    # 判定ライブラリによる点数（点の移動は、これで決める）
    from_seat: int | None                   # ロンなら放銃した席、ツモなら None
    payments: tuple[int, int, int, int]     # このあがりでの点の移動（席ごと。受け取りは ＋）
    pao: int | None = None                  # 責任払いをした席（なければ None）
    pao_yaku: str | None = None


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
    turn: int                               # 手番の席（いまツモった人・鳴いた人。CLAIM では、いま牌を出した人）
    phase: Phase
    scores: tuple[int, int, int, int]       # いまの持ち点（リーチ棒を出すと 1000 減る）
    kyotaku: int                            # いま卓に出ているリーチ棒の本数
    deals: tuple[DealReport, ...]           # 席ごとの、配牌の補正の記録
    pending: tuple[int, ...] = ()           # CLAIM：返事がまだの席（返事をもらう順。ロンできる人 → ポン・カン → チー）
    rons: tuple[int, ...] = ()              # CLAIM：ロンを宣言した席
    misses: tuple[Miss, ...] = ()           # あがり牌の見送り（役なし・フリテンでロンできなかったときも含む）
    result: HandResult | None = None
    rinshan_drawn: int = 0                  # 嶺上牌を引いた枚数（＝成立したカンの回数）
    dora_revealed: int = 1                  # めくったドラ表示牌の枚数（最初の 1 枚＋カンドラ）
    dora_pending: int = 0                   # 大明槓・加槓のカンドラで、まだめくっていない枚数（次の打牌のあとにめくる）
    interrupted: bool = False               # この局で鳴き（暗槓を含む）があった（一発・ダブル立直・天和・地和などが消える）
    claim: Claim | None = None              # CLAIM：返事を待っている牌
    call: Action | None = None              # CLAIM：宣言されたチー・ポン・大明槓（ロンが無ければ、これを行う）
    forbidden: tuple[int, ...] = ()         # DRAW：鳴いた直後の打牌で切れない種類（喰い替え）

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
        """ツモ山の残り枚数（カン 1 回ごとに、ツモ山の最後の 1 枚が王牌に回るので、1 枚ずつ減る）"""
        return NUM_LIVE - self.live_drawn - self.rinshan_drawn

    @property
    def dora_indicators(self) -> tuple[int, ...]:
        """めくってあるドラ表示牌（最初の 1 枚と、カンドラ）"""
        return self.wall_tiles[DORA_START:DORA_START + self.dora_revealed]

    @property
    def ura_indicators(self) -> tuple[int, ...]:
        """裏ドラ表示牌（めくってあるドラ表示牌と同じ枚数。リーチしてあがったときだけ見る）"""
        return self.wall_tiles[URA_START:URA_START + self.dora_revealed]

    @property
    def kan_seats(self) -> frozenset[int]:
        """カンをした席"""
        return frozenset(seat for seat, p in enumerate(self.players) if p.kans)

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
        """その席から見えている、自分の門前の手牌以外の牌（全員の河・全員の副露・ドラ表示牌）。

        いまは、どの席にも同じものが見えている。鳴かれた捨て牌は、鳴いた人の副露として 1 回だけ数える。
        """
        rivers = (d.tile for p in self.players for d in p.river if d.called_by is None)
        return (*rivers, *(t for p in self.players for t in p.meld_tiles), *self.dora_indicators)

    def draws_left(self, seat: int) -> int:
        """その席が、このあとツモれる回数（鳴きで順番が飛ばなければ）。

        ツモは、手番の人（いまツモった人、または、いま切った人）の次の人から順に回る。
        残りが left 枚なら、k 枚目（k ＝ 1〜left）をツモるのは (手番 ＋ k) の席。
        """
        left = self.live_remaining
        offset = (seat - self.turn) % NUM_PLAYERS
        if offset == 0:
            return left // NUM_PLAYERS
        return (left - offset) // NUM_PLAYERS + 1 if left >= offset else 0

    # ------------------------------------------------------------ できる行動

    def _my_turn(self, seat: int) -> bool:
        """seat の人が、ツモった牌を持って行動を選ぶところか（チー・ポンの直後は含めない）"""
        return self.result is None and self.phase is Phase.DRAW and seat == self.turn and self.players[seat].drawn is not None

    def can_tsumo(self, seat: int) -> bool:
        """いま「ツモ」であがれるか"""
        if not self._my_turn(seat):
            return False
        if not is_win_shape(self.players[seat].tiles):
            return False
        return judge(tsumo_context(self, seat), self.rules).ok

    def riichi_tiles(self, seat: int) -> tuple[int, ...]:
        """リーチを宣言して切れる牌（切っても聴牌が残る牌）。リーチできなければ空"""
        player = self.players[seat]
        if not self._my_turn(seat) or player.in_riichi or not player.menzen:
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
        """九種九牌で流局にできるか（最初のツモで、么九牌が 9 種類以上。それより前に鳴きが無いこと）"""
        player = self.players[seat]
        if not self._my_turn(seat) or not self.rules.abortive_draws or player.river or self.interrupted or player.rinshan:
            return False
        return nine_kinds(player.tiles) >= NINE_KINDS

    def can_kan(self) -> bool:
        """いまカンできる状況か（ルールで鳴きあり・4 回未満・最後の牌をツモったのでない）"""
        return self.rules.calls and self.rinshan_drawn < MAX_KANS and self.live_remaining > 0

    def ankan_tiles(self, seat: int) -> tuple[int, ...]:
        """暗槓できる牌（種類ごとに 1 枚）。リーチのあとは、ツモった牌で、待ちが変わらないときだけ"""
        if not self._my_turn(seat) or not self.can_kan():
            return ()
        player = self.players[seat]
        counts = counts34(player.tiles)
        kinds = [k for k in range(len(counts)) if counts[k] == 4]
        if player.in_riichi:
            kinds = [k for k in kinds if _riichi_kan_ok(player, k)]
        return tuple(next(t for t in player.tiles if kind_of(t) == k) for k in kinds)

    def kakan_tiles(self, seat: int) -> tuple[int, ...]:
        """加槓できる牌（ポンした刻子と同じ種類の、手の中の牌）"""
        if not self._my_turn(seat) or not self.can_kan():
            return ()
        player = self.players[seat]
        pons = {f.meld.first_kind for f in player.furo if f.meld.type is MeldType.PON}
        return tuple(t for t in player.tiles if kind_of(t) in pons)

    def call_actions(self, seat: int) -> tuple[Action, ...]:
        """CLAIM で、その席が選べる返事（ロン・チー・ポン・大明槓。見送るは含めない）。鳴きに使う牌は、赤 5 を先に使う"""
        claim = self.claim
        if self.result is not None or self.phase is not Phase.CLAIM or claim is None or seat not in self.pending:
            return ()
        found: list[Action] = []
        if seat in claim.ron:
            found.append(ron(seat))
        if claim.kind is ClaimKind.DISCARD:
            player = self.players[seat]
            if seat in claim.pon:
                found.extend(_pon_actions(self, player, seat, claim.tile))
            if seat in claim.chi:
                found.extend(_chi_actions(self, player, seat, claim.tile))
        return tuple(found)

    def ron_check(self, seat: int, tile: int | None = None) -> RonCheck:
        """その席が、いま返事を待っている牌（無ければ、いちばん最近の捨て牌。tile を渡せば、その牌）でロンできるか"""
        kind = ClaimKind.DISCARD
        if tile is None:
            if self.claim is not None and self.phase is Phase.CLAIM:
                if self.claim.seat == seat:
                    return NO_RON
                tile, kind = self.claim.tile, self.claim.kind
            else:
                last = self.last_discard
                if last is None or last[0] == seat:
                    return NO_RON
                tile = last[1].tile
        return _ron_check(self, seat, tile, kind)

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


def _riichi_kan_ok(player: Player, kind: int) -> bool:
    """リーチのあとの暗槓：ツモった牌でのカン（送り槓でない）で、カンしても待ちの種類が変わらないか"""
    if player.drawn is None or kind_of(player.drawn) != kind:
        return False
    before = set(wait_kinds(player.hand))
    after = set(wait_kinds([t for t in player.hand if kind_of(t) != kind]))
    return bool(before) and before == after


def kuikae_kinds(move: Move, called: int, used: Sequence[int]) -> frozenset[int]:
    """鳴いた直後に切れない種類（喰い替え）。鳴いた牌と同じ種類と、チーした順子の反対側の牌（スジ）。

    例：45萬で 3萬をチー → 3萬と 6萬。56萬で 7萬をチー → 7萬と 4萬。35萬で 4萬をチー（嵌張）→ 4萬だけ。
    """
    kind = kind_of(called)
    forbidden = {kind}
    if move is Move.CHI:
        low, high = sorted(kind_of(t) for t in used)
        if kind < low and (high + 1) % 9 != 0:          # 下側を鳴いた：反対側は、もう 1 つ上
            forbidden.add(high + 1)
        elif kind > high and low % 9 != 0:              # 上側を鳴いた：反対側は、もう 1 つ下
            forbidden.add(low - 1)
    return frozenset(forbidden)


def _leaves_discard(hand: Sequence[int], used: Sequence[int], forbidden: frozenset[int]) -> bool:
    """鳴いたあとに、喰い替えにならずに切れる牌が残るか"""
    rest = list(hand)
    for tile in used:
        rest.remove(tile)
    return any(kind_of(t) not in forbidden for t in rest)


def _choose(tiles: Sequence[int], kind: int, count: int, aka: bool) -> tuple[int, ...] | None:
    """手牌から、その種類を count 枚選ぶ（赤 5 を先に。鳴いた面子に入れておけば、うっかり切ることがない）"""
    same = sorted((t for t in tiles if kind_of(t) == kind), key=lambda t: (not is_red(t, aka=aka), t))
    return tuple(same[:count]) if len(same) >= count else None


def _pon_actions(hand: HandState, player: Player, seat: int, tile: int) -> list[Action]:
    kind = kind_of(tile)
    aka = hand.rules.aka_dora
    found = []
    two = _choose(player.hand, kind, 2, aka)
    if two is not None and _leaves_discard(player.hand, two, kuikae_kinds(Move.PON, tile, two)):
        found.append(pon(seat, *two))
    three = _choose(player.hand, kind, 3, aka)
    if three is not None and hand.rinshan_drawn < MAX_KANS:
        found.append(kan(seat, *three))
    return found


def chi_shapes(kind: int) -> list[tuple[int, int]]:
    """その種類をチーできる、手の 2 枚の種類の組（下側・嵌張・上側）"""
    if kind >= 27:
        return []
    number = kind % 9
    shapes = []
    if number >= 2:
        shapes.append((kind - 2, kind - 1))
    if 1 <= number <= 7:
        shapes.append((kind - 1, kind + 1))
    if number <= 6:
        shapes.append((kind + 1, kind + 2))
    return shapes


def _chi_actions(hand: HandState, player: Player, seat: int, tile: int) -> list[Action]:
    aka = hand.rules.aka_dora
    found = []
    for first, second in chi_shapes(kind_of(tile)):
        a = _choose(player.hand, first, 1, aka)
        b = _choose(player.hand, second, 1, aka)
        if a is None or b is None:
            continue
        used = (a[0], b[0])
        if _leaves_discard(player.hand, used, kuikae_kinds(Move.CHI, tile, used)):
            found.append(chi(seat, *used))
    return found


def _wall(hand: HandState) -> Wall:
    return Wall(list(hand.wall_tiles), live_drawn=hand.live_drawn, rinshan_drawn=hand.rinshan_drawn,
                dora_revealed=hand.dora_revealed, sealed=True)


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
        melds=player.melds,
        riichi=riichi_on,
        double_riichi=riichi_on and player.double_riichi,
        ippatsu=riichi_on and player.ippatsu,
        dora_indicators=hand.dora_indicators,
        ura_indicators=hand.ura_indicators if riichi_on else (),
        honba=hand.start.honba,
        kyotaku=hand.kyotaku,
    )


def tsumo_context(hand: HandState, seat: int) -> WinContext:
    """いまツモであがったときの状況（ハイテイ・嶺上開花・天和・地和・一発などを含む。本場・供託は局のいまの値）"""
    player = hand.players[seat]
    assert player.drawn is not None
    ctx = _base_context(hand, seat, player.drawn, is_tsumo=True, closed=player.tiles)
    # 最初のツモ：まだ切っていない、それまでに誰も鳴いていない、嶺上牌でない
    first = not player.river and not hand.interrupted and not player.rinshan
    return replace(
        ctx,
        rinshan=player.rinshan,
        haitei=hand.live_remaining == 0 and not player.rinshan,
        tenhou=first and seat == hand.dealer,
        chiihou=first and seat != hand.dealer,
    )


def ron_context(hand: HandState, seat: int, tile: int, *, chankan: bool = False) -> WinContext:
    """その牌でロンしたときの状況（河底・槍槓・一発などを含む。本場・供託は局のいまの値）"""
    player = hand.players[seat]
    ctx = _base_context(hand, seat, tile, is_tsumo=False, closed=(*player.hand, tile))
    return replace(ctx, houtei=hand.live_remaining == 0 and not chankan, chankan=chankan)


def _is_kokushi(judgement: Judgement) -> bool:
    return any(y.key in ("kokushi", "kokushi_13") for y in judgement.yaku)


def _ron_check(hand: HandState, seat: int, tile: int, kind: ClaimKind = ClaimKind.DISCARD) -> RonCheck:
    player = hand.players[seat]
    if player.drawn is not None or not is_win_shape((*player.hand, tile)):
        return NO_RON
    judgement = judge(ron_context(hand, seat, tile, chankan=kind is not ClaimKind.DISCARD), hand.rules)
    if kind is ClaimKind.ANKAN and not (judgement.ok and _is_kokushi(judgement)):
        return NO_RON                   # 暗槓の牌でロンできるのは、国士無双だけ
    return RonCheck(True, hand.furiten(seat), judgement.ok)


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


def _turn_state(hand: HandState, seat: int, player: Player, **changes: Any) -> HandState:
    """seat の人の手番にする（返事待ちの印は消す）"""
    return replace(
        hand, players=_with_player(hand, seat, player), turn=seat, phase=Phase.DRAW, pending=(), rons=(),
        claim=None, call=None, **changes,
    )


def _draw(config: GameConfig, hand: HandState, seat: int) -> HandState:
    """seat の人が 1 枚ツモる（その前に、その席のツモの補正を試す）。同巡内フリテンは、ここで解ける"""
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
    player = replace(player, drawn=tile, rinshan=False, missed=False, draws=(*player.draws, Draw(number, tile, report)))
    return _turn_state(hand, seat, player, wall_tiles=tuple(wall.tiles), live_drawn=wall.live_drawn, forbidden=())


def _draw_rinshan(hand: HandState, seat: int) -> HandState:
    """カンのあと、嶺上牌をツモる（ツモ山の最後の 1 枚が王牌に回る）"""
    wall = _wall(hand)
    tile = wall.draw_rinshan()
    player = hand.players[seat]
    number = len(player.draws) + 1
    player = replace(
        player, drawn=tile, rinshan=True, missed=False,
        draws=(*player.draws, Draw(number, tile, NO_DRAW_LUCK, rinshan=True)),
    )
    return _turn_state(hand, seat, player, rinshan_drawn=wall.rinshan_drawn, forbidden=())


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
        player = hand.players[seat]
        if move in (Move.DISCARD, Move.RIICHI):
            assert action.tile is not None
            return _discard(config, replace(hand, actions=actions), seat, action.tile, declare=move is Move.RIICHI)
        if player.drawn is None:
            raise GameError("鳴いた直後は、1 枚切るだけです")
        if move is Move.TSUMO:
            if not hand.can_tsumo(seat):
                raise GameError("ツモであがれる形ではありません")
            return _end_tsumo(config, replace(hand, actions=actions), seat)
        if move is Move.NINE:
            if not hand.can_nine(seat):
                raise GameError("九種九牌にはできません")
            return _end_abortive(replace(hand, actions=actions), EndKind.NINE_TERMINALS, caller=seat)
        if move is Move.ANKAN:
            assert action.tile is not None
            if kind_of(action.tile) not in {kind_of(t) for t in hand.ankan_tiles(seat)} or action.tile not in player.tiles:
                raise GameError("その牌は暗槓できません")
            return _declare_ankan(config, replace(hand, actions=actions), seat, kind_of(action.tile))
        if move is Move.KAKAN:
            assert action.tile is not None
            if action.tile not in hand.kakan_tiles(seat):
                raise GameError("その牌は加槓できません")
            return _declare_kakan(config, replace(hand, actions=actions), seat, action.tile)
        raise GameError("いまはできない行動です")
    return _respond(config, replace(hand, actions=actions), action)


def _missed(player: Player) -> Player:
    """あがり牌を見逃した（同巡内フリテン。リーチしていれば、この局のあいだずっとフリテン）"""
    return replace(player, missed=True, riichi_missed=player.riichi_missed or player.riichi_paid)


def _respond(config: GameConfig, hand: HandState, action: Action) -> HandState:
    """CLAIM：返事を 1 つ受け取る。全員の返事がそろったら、ロン → 鳴き → 見送り の順に決める"""
    claim = hand.claim
    seat, move = action.seat, action.move
    if claim is None or seat not in hand.pending:
        raise GameError("いまはできない行動です")
    if move is Move.RON:
        if seat not in claim.ron:
            raise GameError("この牌ではロンできません")
    elif move in CALL_MOVES:
        if not _valid_call(hand, action):
            raise GameError("その鳴きはできません")
    elif move is not Move.PASS:
        raise GameError("いまはできない行動です")

    players, misses = hand.players, hand.misses
    if seat in claim.ron and move is not Move.RON:
        # ロンできたのに、見送った（鳴きを選んだときも同じ）。同巡内フリテン（リーチ中なら、この局のあいだずっと）
        players = _with_player(hand, seat, _missed(hand.players[seat]))
        check = RonCheck(True, None, True)
        misses = (*misses, Miss(seat, claim.seat, claim.tile, check, passed=True, chankan=claim.kind is not ClaimKind.DISCARD,
                                order=_miss_order(hand, claim.kind)))
    pending = tuple(s for s in hand.pending if s != seat)
    rons, call = hand.rons, hand.call
    if move is Move.RON:
        rons = (*rons, seat)
    elif move in CALL_MOVES and (call is None or call.move is Move.CHI):
        call = action
    # 優先の低い返事は、もう聞かない（ロンが出たら、ロンできる人だけ。ポン・カンが出たら、チーだけの人は聞かない）
    if rons:
        pending = tuple(s for s in pending if s in claim.ron)
    elif call is not None and call.move is not Move.CHI:
        pending = tuple(s for s in pending if s in claim.ron or s in claim.pon)
    hand = replace(hand, players=players, misses=misses, pending=pending, rons=rons, call=call)
    if pending:
        return hand
    if hand.rons:
        return _end_ron(config, hand)
    if claim.kind is ClaimKind.DISCARD:
        if hand.call is not None:
            return _execute_call(config, hand, hand.call)
        return _after_discard(config, hand)
    return _finish_kan(hand)


def _valid_call(hand: HandState, action: Action) -> bool:
    """チー・ポン・大明槓の返事が、決まりに合っているか（使う牌の種類・枚数、喰い替えで切れる牌が残るか）"""
    claim = hand.claim
    assert claim is not None
    seat, move, used = action.seat, action.move, action.tiles
    if claim.kind is not ClaimKind.DISCARD or len(used) != CALL_SIZES[move] or len(set(used)) != len(used):
        return False
    player = hand.players[seat]
    if any(t not in player.hand for t in used):
        return False
    kind = kind_of(claim.tile)
    kinds = sorted(kind_of(t) for t in used)
    if move is Move.CHI:
        if seat not in claim.chi or tuple(kinds) not in chi_shapes(kind):
            return False
    else:
        if seat not in claim.pon or any(k != kind for k in kinds):
            return False
        if move is Move.KAN:
            return hand.rinshan_drawn < MAX_KANS
    return _leaves_discard(player.hand, used, kuikae_kinds(move, claim.tile, used))


def _discard(config: GameConfig, hand: HandState, seat: int, tile: int, *, declare: bool) -> HandState:
    player = hand.players[seat]
    if tile not in player.tiles:
        raise GameError(f"手牌にない牌は切れません: {tile}")
    if len(player.tiles) % 3 != 2:
        raise GameError("いまは切れません")
    if player.in_riichi and tile != player.drawn:
        raise GameError("リーチのあとは、ツモった牌を切るだけです")
    if kind_of(tile) in hand.forbidden:
        raise GameError("鳴いた直後に、その牌は切れません（喰い替え）")
    if declare and tile not in hand.riichi_tiles(seat):
        if player.in_riichi:
            raise GameError("もうリーチしています")
        if not player.menzen:
            raise GameError("鳴いた手では、リーチできません")
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
        rinshan=False,
        river=river,
        # 一発は、リーチのあと次に自分が切るまで
        ippatsu=declare,
        riichi_at=len(river) - 1 if declare else player.riichi_at,
        double_riichi=player.double_riichi or (declare and len(river) == 1 and not hand.interrupted),
    )
    hand = replace(hand, players=_with_player(hand, seat, player), turn=seat, forbidden=())
    if hand.dora_pending:
        # 大明槓・加槓のカンドラは、打牌のあとにめくる（この打牌でのロンから数える）
        hand = replace(hand, dora_revealed=hand.dora_revealed + hand.dora_pending, dora_pending=0)
    return _open_claim(config, hand, ClaimKind.DISCARD, seat, tile)


def _four_kans_next(hand: HandState) -> bool:
    """この打牌が通ったら四槓散了か（2 人以上で 4 回カンしたあとの打牌）"""
    return hand.rules.abortive_draws and hand.rinshan_drawn >= MAX_KANS and len(hand.kan_seats) >= 2


def _open_claim(config: GameConfig, hand: HandState, kind: ClaimKind, seat: int, tile: int) -> HandState:
    """出た牌に返事ができる人を調べる。あがりの形になるのにロンできない人（役なし・フリテン）は、見逃しになる"""
    players = list(hand.players)
    misses = list(hand.misses)
    can_ron, can_pon, can_chi = [], [], []
    # 鳴けるのは捨て牌だけ。最後の捨て牌（河底牌）と、四槓散了になる打牌は、ロンだけ
    calls = kind is ClaimKind.DISCARD and hand.rules.calls and hand.live_remaining > 0 and not _four_kans_next(hand)
    for step in range(1, NUM_PLAYERS):
        other = (seat + step) % NUM_PLAYERS
        check = _ron_check(hand, other, tile, kind)
        if check.ok:
            can_ron.append(other)
        elif check.shape:
            players[other] = _missed(players[other])
            misses.append(Miss(other, seat, tile, check, passed=False, chankan=kind is not ClaimKind.DISCARD, order=_miss_order(hand, kind)))
        player = hand.players[other]
        if not calls or player.in_riichi:
            continue
        if _pon_actions(hand, player, other, tile):
            can_pon.append(other)
        if step == 1 and _chi_actions(hand, player, other, tile):
            can_chi.append(other)
    claim = Claim(kind, seat, tile, tuple(can_ron), tuple(can_pon), tuple(can_chi))
    hand = replace(hand, players=tuple(players), misses=tuple(misses), claim=claim, turn=seat)  # type: ignore[arg-type]
    asked = {*can_ron, *can_pon, *can_chi}
    if not asked:
        if kind is ClaimKind.DISCARD:
            return _after_discard(config, hand)
        return _finish_kan(hand)

    def order(s: int) -> tuple[int, int]:
        rank = 0 if s in can_ron else (1 if s in can_pon else 2)
        return (rank, (s - seat) % NUM_PLAYERS)

    return replace(hand, phase=Phase.CLAIM, pending=tuple(sorted(asked, key=order)), rons=(), call=None)


def _miss_order(hand: HandState, kind: ClaimKind) -> int:
    """見逃しの順番（捨て牌なら、その牌が局の何枚目の打牌か。加槓・暗槓の牌なら、それまでに切られた枚数）"""
    return hand.discard_count - 1 if kind is ClaimKind.DISCARD else hand.discard_count


def _establish_riichi(hand: HandState, seat: int) -> HandState:
    """リーチ宣言牌が通った（ロンされなかった）：リーチが成立して、リーチ棒を出す"""
    player = hand.players[seat]
    if not player.river or not player.river[-1].riichi or player.riichi_paid:
        return hand
    scores = list(hand.scores)
    scores[seat] -= RIICHI_STICK
    return replace(
        hand,
        players=_with_player(hand, seat, replace(player, riichi_paid=True)),
        scores=tuple(scores),  # type: ignore[arg-type]
        kyotaku=hand.kyotaku + 1,
    )


def _after_discard(config: GameConfig, hand: HandState) -> HandState:
    """捨て牌が通った（誰もロンも鳴きもしなかった）あと：リーチの成立、途中流局、流局、次の人のツモ"""
    seat = hand.turn
    rules = config.rules
    paid = hand.players[seat].riichi_paid
    hand = _establish_riichi(hand, seat)
    if not paid and hand.players[seat].riichi_paid and rules.abortive_draws and all(p.riichi_paid for p in hand.players):
        return _end_abortive(hand, EndKind.FOUR_RIICHI)
    if rules.abortive_draws and _four_winds(hand):
        return _end_abortive(hand, EndKind.FOUR_WINDS)
    if _four_kans_next(hand):
        return _end_abortive(hand, EndKind.FOUR_KANS)
    if hand.live_remaining <= 0:
        return _end_exhausted(config, hand)
    return _draw(config, hand, (seat + 1) % NUM_PLAYERS)


def _four_winds(hand: HandState) -> bool:
    """最初の 1 巡で、4 人が同じ風牌を切ったか（それまでに鳴きが無いこと）"""
    if hand.interrupted or any(len(p.river) != 1 for p in hand.players):
        return False
    kinds = {kind_of(p.river[0].tile) for p in hand.players}
    return len(kinds) == 1 and EAST <= next(iter(kinds)) <= NORTH


def _no_ippatsu(players: Sequence[Player]) -> tuple[Player, ...]:
    """誰かが鳴いた（暗槓を含む）：全員の一発のチャンスが消える"""
    return tuple(replace(p, ippatsu=False) if p.ippatsu else p for p in players)


def _execute_call(config: GameConfig, hand: HandState, action: Action) -> HandState:
    """チー・ポン・大明槓を行う（ロンが無かったとき）"""
    claim = hand.claim
    assert claim is not None
    caller, discarder, tile, move = action.seat, claim.seat, claim.tile, action.move
    hand = _establish_riichi(hand, discarder)          # 宣言牌が鳴かれても、リーチは成立する
    players = list(hand.players)
    thrower = players[discarder]
    players[discarder] = replace(thrower, river=(*thrower.river[:-1], replace(thrower.river[-1], called_by=caller)))
    player = players[caller]
    rest = list(player.hand)
    for used in action.tiles:
        rest.remove(used)
    meld_type = {Move.CHI: MeldType.CHI, Move.PON: MeldType.PON, Move.KAN: MeldType.MINKAN}[move]
    meld = Meld(meld_type, (*action.tiles, tile), tile)
    player = replace(player, hand=tuple(sort_tiles(rest)), furo=(*player.furo, Furo(meld, discarder)))
    if move is not Move.CHI and player.pao is None:
        player = _with_pao(player, kind_of(tile), discarder)
    players[caller] = player
    hand = replace(hand, players=_no_ippatsu(players), interrupted=True)  # type: ignore[arg-type]
    if move is Move.KAN:
        # 大明槓：カンドラは次の打牌のあとにめくる。嶺上牌をツモってから切る
        return _draw_rinshan(replace(hand, dora_pending=hand.dora_pending + 1), caller)
    return _turn_state(hand, caller, hand.players[caller], forbidden=tuple(sorted(kuikae_kinds(move, tile, action.tiles))))


def _with_pao(player: Player, kind: int, discarder: int) -> Player:
    """3 種目の三元牌（4 種目の風牌）を鳴いて、大三元（大四喜）が確定したら、牌を出した人が責任払いになる"""
    sets = {f.meld.first_kind for f in player.furo if f.meld.type is not MeldType.CHI}
    if kind in DRAGONS and DRAGONS <= sets:
        return replace(player, pao=discarder, pao_yaku="daisangen")
    if kind in WINDS and WINDS <= sets:
        return replace(player, pao=discarder, pao_yaku="daisuushii")
    return player


def _reveal_pending(hand: HandState) -> HandState:
    """まだめくっていない明槓のカンドラを、次のカンの前にめくる"""
    if not hand.dora_pending:
        return hand
    return replace(hand, dora_revealed=hand.dora_revealed + hand.dora_pending, dora_pending=0)


def _declare_ankan(config: GameConfig, hand: HandState, seat: int, kind: int) -> HandState:
    """暗槓：4 枚をさらし、カンドラをすぐめくる。国士無双の人だけ、この牌でロンできる（槍槓）"""
    hand = _reveal_pending(hand)
    player = hand.players[seat]
    quad = tuple(t for t in player.tiles if kind_of(t) == kind)
    rest = [t for t in player.tiles if kind_of(t) != kind]
    player = replace(player, hand=tuple(sort_tiles(rest)), drawn=None, rinshan=False, furo=(*player.furo, Furo(Meld(MeldType.ANKAN, quad))))
    hand = replace(hand, players=_with_player(hand, seat, player), dora_revealed=hand.dora_revealed + 1)
    return _open_claim(config, hand, ClaimKind.ANKAN, seat, quad[-1])


def _declare_kakan(config: GameConfig, hand: HandState, seat: int, tile: int) -> HandState:
    """加槓：ポンした刻子に 1 枚足すと宣言する。この牌でロンできる人がいれば、先に聞く（槍槓）"""
    hand = _reveal_pending(hand)
    player = hand.players[seat]
    rest = list(player.tiles)
    rest.remove(tile)
    player = replace(player, hand=tuple(sort_tiles(rest)), drawn=None, rinshan=False)
    hand = replace(hand, players=_with_player(hand, seat, player))
    return _open_claim(config, hand, ClaimKind.KAKAN, seat, tile)


def _finish_kan(hand: HandState) -> HandState:
    """暗槓・加槓が成立した（槍槓が無かった）：一発が消え、嶺上牌をツモる。加槓のカンドラは次の打牌のあと"""
    claim = hand.claim
    assert claim is not None
    seat = claim.seat
    pending_dora = hand.dora_pending
    if claim.kind is ClaimKind.KAKAN:
        player = hand.players[seat]
        furo = list(player.furo)
        index = next(i for i, f in enumerate(furo) if f.meld.type is MeldType.PON and f.meld.first_kind == kind_of(claim.tile))
        old = furo[index]
        furo[index] = Furo(Meld(MeldType.KAKAN, (*old.meld.tiles, claim.tile), old.meld.called_tile), old.from_seat, claim.tile)
        hand = replace(hand, players=_with_player(hand, seat, replace(player, furo=tuple(furo))))
        pending_dora += 1
    hand = replace(hand, players=_no_ippatsu(hand.players), interrupted=True, dora_pending=pending_dora)  # type: ignore[arg-type]
    return _draw_rinshan(hand, seat)


# ---------------------------------------------------------------- 局の終わり


def _pao_units(judgement: Judgement, pao_yaku: str | None) -> int:
    """責任払いの役満が、役満の何倍ぶんか（その役が付いていなければ 0）"""
    if pao_yaku is None:
        return 0
    return sum(y.han for y in judgement.yaku if y.key == pao_yaku) // YAKUMAN_HAN


def _pay_win(hand: HandState, seat: int, ctx: WinContext, judgement: Judgement, from_seat: int | None) -> tuple[tuple[int, int, int, int], int | None]:
    """あがりの点の移動（席ごと）と、責任払いをした席"""
    player = hand.players[seat]
    units = _pao_units(judgement, player.pao_yaku) if player.pao is not None else 0
    if units:
        return _pay_with_pao(hand, seat, ctx, judgement, from_seat, player.pao, units), player.pao  # type: ignore[arg-type]
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
    return tuple(pay), None  # type: ignore[return-value]


def _pay_with_pao(hand: HandState, seat: int, ctx: WinContext, judgement: Judgement, from_seat: int | None, pao: int, units: int) -> tuple[int, int, int, int]:
    """責任払い：責任払いの役満の分は、ツモなら責任者が全額、ほかの人のロンなら放銃者と責任者が半分ずつ。本場の点は責任者。
    ほかに重なった役満の分は、ふつうのあがりと同じに払う（複合した分の扱いはルールによって異なる。docs/DESIGN.md）"""
    dealer = seat == hand.dealer
    unit = YAKUMAN_DEALER if dealer else YAKUMAN_CHILD
    rest = judgement.yakuman_times - units
    pay = [0] * NUM_PLAYERS
    pay[pao] -= HONBA_TOTAL * ctx.honba
    if from_seat is None:
        pay[pao] -= units * unit
        for other in range(NUM_PLAYERS):
            if other != seat:
                pay[other] -= rest * (unit // 3 if dealer else (unit // 2 if other == hand.dealer else unit // 4))
    elif from_seat == pao:
        pay[pao] -= (units + rest) * unit
    else:
        pay[from_seat] -= units * unit // 2 + rest * unit
        pay[pao] -= units * unit // 2
    pay[seat] = -sum(pay) + judgement.kyotaku_bonus
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
        pay, pao = _pay_win(hand, seat, ctx, judgement, from_seat)
        wins.append(Win(seat, ctx, judgement, from_seat, pay, pao, hand.players[seat].pao_yaku if pao is not None else None))
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
    claim = hand.claim
    assert claim is not None
    seat = claim.seat
    # 捨てた人（カンした人）から見て、順番が先の人から
    order = sorted(hand.rons, key=lambda s: (s - seat) % NUM_PLAYERS)
    winners = order if config.rules.multiple_ron else order[:1]
    bumped = [s for s in order if s not in winners]
    chankan = claim.kind is not ClaimKind.DISCARD
    return _end_wins(
        config, hand, [(s, ron_context(hand, s, claim.tile, chankan=chankan), seat) for s in winners], EndKind.RON, bumped=bumped,
    )


def _end_exhausted(config: GameConfig, hand: HandState) -> HandState:
    tenpai = tuple(bool(wait_kinds(p.hand)) for p in hand.players)
    nagashi: tuple[int, ...] = ()
    if config.rules.nagashi_mangan:
        # 捨て牌がすべて么九牌で、1 枚も鳴かれていない（自分が鳴いたかどうかは問わない）
        nagashi = tuple(
            seat for seat, p in enumerate(hand.players)
            if p.river and all(is_yaochu_kind(kind_of(d.tile)) and d.called_by is None for d in p.river)
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
    """次に行動を決める席（局が終わっていれば None）。CLAIM では、返事がまだの人のうち、先に聞く人
    （ロンできる人 → ポン・カンできる人 → チーだけの人。同じなら、牌を出した人から見て順番が先の人）"""
    if hand.result is not None:
        return None
    if hand.phase is Phase.CLAIM:
        return hand.pending[0]
    return hand.turn


def auto_action(hand: HandState, seat: int) -> Action | None:
    """リーチしている人の手番は、決まった行動しかない（ツモ切り）。それ以外（あがれる・暗槓できる）は None。

    あがれるときは、ツモを宣言するかどうかを本人が決める（自分の画面では「ツモ」を押す）。
    """
    if hand.result is not None or hand.phase is not Phase.DRAW or seat != hand.turn:
        return None
    player = hand.players[seat]
    if not player.in_riichi or player.drawn is None:
        return None
    if hand.can_tsumo(seat):
        return tsumo(seat)
    if hand.ankan_tiles(seat):
        return None
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
    版 1 の記録（鳴きの無かったころ）は、鳴きなしのルールで作り直す（そのとき打った対局と同じになる）。
    """
    if not isinstance(data, dict) or data.get("v") not in (1, SAVE_VERSION):
        raise ValueError("記録の形が違います")
    logs = data.get("logs")
    if not isinstance(logs, list) or not 1 <= len(logs) <= MAX_HANDS:
        raise ValueError("記録の形が違います（局の列）")
    if any(not isinstance(items, list) or len(items) > MAX_ACTIONS for items in logs):
        raise ValueError("記録の形が違います（行動の列）")
    try:
        config = GameConfig.from_dict(data.get("config"))
        if data.get("v") == 1:
            config = replace(config, rules=replace(config.rules, calls=False))
        actions = [[Action.from_list(item) for item in items] for items in logs]
        return replay(config, actions)
    except ValueError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError, ArithmeticError, AssertionError) as error:
        raise ValueError(f"記録を読めません: {error}") from error

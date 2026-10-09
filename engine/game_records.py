"""CPU との対局の成績の記録と集計。

成績は、条件（自分のツキ補正・CPU のツキ補正・CPU の強さ・対局の長さ・打つ前のヒントを見たか）とセットで残す。
条件が違う対局を混ぜると意味がなくなるので、集計は条件ごとに分ける。
「実力」と呼ぶのは、補正 0（自分も CPU も）で、打つ前のヒントも見ずに打った対局だけ。

    record_of(game, tally, ...)    終わった対局 1 つぶんの記録を作る
    summarize(records)             条件ごとに集計する（実力が先頭）
    graduation(records)            卒業の目安（補正 0・CPU ふつう・ヒントなしの東風戦）の進み具合
    dump_record / load_history     ブラウザや JSON に残すための変換（壊れたデータは読み飛ばす）
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from engine.game import HUMAN, CpuLevel, EndKind, Furiten, GameState, Length, Miss
from engine.rules import DEFAULT_RULES

HISTORY_VERSION = 1
#: 残す対局数の上限（古いものから捨てる）
MAX_RECORDS = 300
#: 卒業の目安（docs/DESIGN.md の 9 章）。補正 0・CPU ふつう・ヒントなしの東風戦で数える
GOAL_GAMES = 30
GOAL_RANK = 2.5
GOAL_DEAL_IN = 0.15
#: 見落とし・役なしの鳴きは、直近この数の対局で 0 回
GOAL_MISS_GAMES = 10


@dataclass(frozen=True)
class Tally:
    """1 対局のあいだに数える、自分の打牌と鳴きの評価"""

    decisions: int = 0          # 自分で選んだ打牌の回数
    followed: int = 0           # そのうち、コーチのおすすめと同じ牌を切った回数
    defense: int = 0            # リーチを受けていて、オリるべき局面での打牌の回数
    safe: int = 0               # そのうち、いちばん安全な牌を切れた回数
    calls: int = 0              # 自分が鳴いた回数（チー・ポン・大明槓）
    bad_calls: int = 0          # そのうち、役なしの鳴き（鳴いたあとの手に役が見えない）
    #: 自分で選んだ打牌のうち、コーチの評価がいちばん良かった回数（Phase 5。おまかせ補正で使う）。
    #: オリるべき局面では、いちばん安全な牌を切れたとき。ほかは、おすすめと同じ速さの牌を切れたとき（同じ速さの牌が
    #: いくつかあれば、どれでもよい）。鳴いた手で、役が見えなくなる牌・役まで遠回りになる牌を切ったときは数えない
    good: int = 0

    def add(self, other: Tally) -> Tally:
        return Tally(
            self.decisions + other.decisions, self.followed + other.followed, self.defense + other.defense, self.safe + other.safe,
            self.calls + other.calls, self.bad_calls + other.bad_calls, self.good + other.good,
        )

    @property
    def good_rate(self) -> float | None:
        return self.good / self.decisions if self.decisions else None

    def to_dict(self) -> dict[str, int]:
        return {"n": self.decisions, "f": self.followed, "d": self.defense, "s": self.safe, "c": self.calls, "b": self.bad_calls,
                "g": self.good}

    @classmethod
    def from_dict(cls, data: object) -> Tally:
        """形がおかしければ、0 から数え直す（記録の一部なので、読めないだけで止めない）。鳴きの数が無い記録（鳴きの無かったころ）は 0。

        良い打牌の数（g）が無い記録（Phase 4 までの記録）は、おすすめと同じ牌を切った回数で代える
        （おすすめどおりの打牌は、良い打牌に入る。少なめに数えることになるが、0 にするよりずっと近い）。
        """
        if not isinstance(data, dict):
            return cls()
        values = []
        for name in ("n", "f", "d", "s", "c", "b", "g"):
            value = data.get(name, data.get("f", 0) if name == "g" else 0)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10_000:
                return cls()
            values.append(value)
        decisions, followed, defense, safe, calls, bad_calls, good = values
        if followed > decisions or safe > defense or defense > decisions or bad_calls > calls or good > decisions:
            return cls()
        return cls(decisions, followed, defense, safe, calls, bad_calls, good)


@dataclass(frozen=True)
class GameRecord:
    time: int                   # 終わった時刻（UNIX 秒）
    seed: int                   # 対局の番号
    length: str                 # east（東風戦）／ south（半荘戦）
    deal: int                   # 自分の配牌の良さ（0〜100）
    draw: int                   # 自分のツモの良さ（0〜100）
    cpu_deal: int               # CPU の配牌の良さ
    cpu_draw: int               # CPU のツモの良さ
    cpu_level: str              # normal ／ weak
    hinted: bool                # 打つ前のヒント（おすすめ）を 1 回でも見たか
    rank: int                   # 順位（1〜4）
    score: int                  # 最後の持ち点
    hands: int                  # 打った局数
    wins: int = 0               # あがった局数
    deal_ins: int = 0           # 放銃した局数（自分の捨て牌でロンされた）
    riichi: int = 0             # リーチした局数
    win_points: int = 0         # あがりで受け取った点の合計（本場・供託を含む）
    deal_in_points: int = 0     # 放銃で払った点の合計
    misses: int = 0             # 役なし・フリテンで、ロンできなかった回数（見落とし）
    tally: Tally = field(default_factory=Tally)
    rules: tuple[tuple[str, object], ...] = ()     # 初期値と違うルール（名前, 値）

    @property
    def plain(self) -> bool:
        """補正 0（自分も CPU も）で、ヒントも見ずに打った対局か（実力）"""
        return self.deal == self.draw == self.cpu_deal == self.cpu_draw == 0 and not self.hinted

    @property
    def key(self) -> tuple:
        """集計の条件（初期値と違うルールも含める。鳴きなしの対局と、鳴きありの対局を混ぜない）"""
        return (self.length, self.cpu_level, self.deal, self.draw, self.cpu_deal, self.cpu_draw, self.hinted, self.rules)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "t": self.time, "seed": self.seed, "len": self.length, "deal": self.deal, "draw": self.draw,
            "cdeal": self.cpu_deal, "cdraw": self.cpu_draw, "cpu": self.cpu_level, "hinted": self.hinted,
            "rank": self.rank, "score": self.score, "hands": self.hands, "wins": self.wins, "dealin": self.deal_ins,
            "riichi": self.riichi, "wpts": self.win_points, "dpts": self.deal_in_points, "miss": self.misses,
            "tally": self.tally.to_dict(),
        }
        if self.rules:
            data["rules"] = dict(self.rules)
        data["naki"] = 1            # 鳴きのある対局を打てるようになってから（Phase 4 から）の記録の印
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameRecord:
        """形がおかしければ ValueError"""
        if not isinstance(data, dict):
            raise ValueError("記録の形が違います")

        def number(name: str, low: int, high: int, default: int | None = None) -> int:
            value = data.get(name, default)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"記録の値がおかしい: {name}={value!r}")
            return value

        hinted = data.get("hinted", False)
        if not isinstance(hinted, bool):
            raise ValueError("記録の値がおかしい: hinted")
        length, level = data.get("len"), data.get("cpu")
        if length not in {item.value for item in Length} or level not in {item.value for item in CpuLevel}:
            raise ValueError("記録の値がおかしい: len / cpu")
        hands = number("hands", 1, 200)
        rules = data.get("rules", {})
        known = DEFAULT_RULES.to_dict()
        if not isinstance(rules, dict):
            raise ValueError("記録の値がおかしい: rules")
        # 知らないルールや、おかしな値は捨てる（画面に出すのは、知っている項目の違いだけ）
        kept_rules = {name: value for name, value in rules.items() if name in known and type(value) is type(known[name])}
        if data.get("naki") != 1:
            # 鳴きの無かったころ（Phase 3）の記録：鳴きなしのルールで打った対局として数える（卒業の目安には入れない）
            kept_rules["calls"] = False
        kept = tuple(sorted((name, value) for name, value in kept_rules.items() if known[name] != value))
        return cls(
            time=number("t", 0, 10**11),
            seed=number("seed", 0, 10**12),
            length=length,
            deal=number("deal", 0, 100),
            draw=number("draw", 0, 100),
            cpu_deal=number("cdeal", 0, 100, 0),
            cpu_draw=number("cdraw", 0, 100, 0),
            cpu_level=level,
            hinted=hinted,
            rank=number("rank", 1, 4),
            score=number("score", -10**8, 10**8),            # 飛びなしで連荘が続くと、100 万点を超えることもある
            hands=hands,
            wins=number("wins", 0, hands, 0),
            deal_ins=number("dealin", 0, hands, 0),
            riichi=number("riichi", 0, hands, 0),
            win_points=number("wpts", 0, 10**8, 0),
            deal_in_points=number("dpts", 0, 10**8, 0),
            misses=number("miss", 0, 10_000, 0),
            tally=Tally.from_dict(data.get("tally")),
            rules=kept,
        )


def is_oversight(miss: Miss) -> bool:
    """自分のあがり牌が出たのにロンできなかったことのうち、「見落とし」に数えるもの（卒業の目安に使う）。

    数えるのは、役が無かったときと、自分の捨て牌にあがり牌があったとき（捨て牌のフリテン）。
    自分で「見送る」を選んだときと、そのあとの同巡内フリテン・リーチ後のフリテンは、自分で選んだ結果なので数えない。
    """
    if miss.seat != HUMAN or miss.passed:
        return False
    return miss.check.furiten not in (Furiten.MISSED, Furiten.RIICHI)


def record_of(game: GameState, tally: Tally, *, time: int, hinted: bool) -> GameRecord:
    """終わった対局の記録を作る"""
    result = game.result
    if result is None:
        raise ValueError("まだ終わっていない対局は記録できません")
    config = game.config
    wins = deal_ins = riichi = win_points = deal_in_points = misses = 0
    for hand in game.hands:
        hand_result = hand.result
        if hand_result is None:
            continue
        me = hand.players[HUMAN]
        riichi += int(me.riichi_paid)
        if any(w.seat == HUMAN for w in hand_result.wins):
            wins += 1
            win_points += sum(w.payments[HUMAN] for w in hand_result.wins if w.seat == HUMAN)
        if hand_result.kind is EndKind.RON and any(w.from_seat == HUMAN for w in hand_result.wins):
            deal_ins += 1
            deal_in_points += -sum(w.payments[HUMAN] for w in hand_result.wins if w.from_seat == HUMAN)
        misses += sum(1 for miss in hand.misses if is_oversight(miss))
    default = DEFAULT_RULES.to_dict()
    rules = tuple(sorted((name, value) for name, value in config.rules.to_dict().items() if default.get(name) != value))
    return GameRecord(
        time=int(time),
        seed=config.seed,
        length=config.length.value,
        deal=config.luck.deal,
        draw=config.luck.draw,
        cpu_deal=config.cpu_luck.deal,
        cpu_draw=config.cpu_luck.draw,
        cpu_level=config.cpu_level.value,
        hinted=hinted,
        rank=result.ranks[HUMAN],
        score=result.scores[HUMAN],
        hands=len(game.hands),
        wins=wins,
        deal_ins=deal_ins,
        riichi=riichi,
        win_points=win_points,
        deal_in_points=deal_in_points,
        misses=misses,
        tally=tally,
        rules=rules,
    )


# ---------------------------------------------------------------- 集計


@dataclass(frozen=True)
class Summary:
    """同じ条件で打った対局の集計"""

    length: str
    cpu_level: str
    deal: int
    draw: int
    cpu_deal: int
    cpu_draw: int
    hinted: bool
    games: int
    ranks: tuple[int, int, int, int]        # 1 位〜4 位の回数
    hands: int
    wins: int
    deal_ins: int
    riichi: int
    win_points: int
    deal_in_points: int
    misses: int
    score_total: int
    tally: Tally
    rules: tuple[tuple[str, object], ...] = ()     # 初期値と違うルール（名前, 値）

    @property
    def plain(self) -> bool:
        return self.deal == self.draw == self.cpu_deal == self.cpu_draw == 0 and not self.hinted

    @property
    def average_rank(self) -> float:
        return sum((index + 1) * count for index, count in enumerate(self.ranks)) / self.games if self.games else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.hands if self.hands else 0.0

    @property
    def deal_in_rate(self) -> float:
        return self.deal_ins / self.hands if self.hands else 0.0

    @property
    def average_score(self) -> float:
        return self.score_total / self.games if self.games else 0.0

    @property
    def follow_rate(self) -> float | None:
        """コーチのおすすめと同じ牌を切った割合（ヒントを見た対局では、なぞれば 100% になるので出さない）"""
        return self.tally.followed / self.tally.decisions if self.tally.decisions and not self.hinted else None


def _summary(key: tuple, items: Sequence[GameRecord]) -> Summary:
    length, level, deal, draw, cpu_deal, cpu_draw, hinted, rules = key
    ranks = [0, 0, 0, 0]
    tally = Tally()
    for record in items:
        ranks[record.rank - 1] += 1
        tally = tally.add(record.tally)
    return Summary(
        length=length, cpu_level=level, deal=deal, draw=draw, cpu_deal=cpu_deal, cpu_draw=cpu_draw, hinted=hinted,
        games=len(items),
        ranks=tuple(ranks),  # type: ignore[arg-type]
        hands=sum(r.hands for r in items),
        wins=sum(r.wins for r in items),
        deal_ins=sum(r.deal_ins for r in items),
        riichi=sum(r.riichi for r in items),
        win_points=sum(r.win_points for r in items),
        deal_in_points=sum(r.deal_in_points for r in items),
        misses=sum(r.misses for r in items),
        score_total=sum(r.score for r in items),
        tally=tally,
        rules=rules,
    )


def summarize(records: Iterable[GameRecord]) -> list[Summary]:
    """条件ごとに集計する。実力（補正 0・ヒントなし）を先に、あとは補正の弱い順"""
    groups: dict[tuple, list[GameRecord]] = {}
    for record in records:
        groups.setdefault(record.key, []).append(record)
    result = [_summary(key, items) for key, items in groups.items()]
    result.sort(key=lambda s: (not s.plain, bool(s.rules), s.length != Length.EAST.value, s.cpu_level != CpuLevel.NORMAL.value,
                               s.deal + s.draw, s.cpu_deal + s.cpu_draw, s.hinted, s.deal, s.draw, repr(s.rules)))
    return result


@dataclass(frozen=True)
class Graduation:
    """卒業の目安の進み具合（補正 0・CPU ふつう・ヒントなし・初期のルール（鳴きあり）の東風戦の、直近の対局）"""

    games: int                  # 数えた対局数（多くても GOAL_GAMES）
    average_rank: float | None
    deal_in_rate: float | None
    recent_misses: int          # 直近 GOAL_MISS_GAMES 戦の、見落としの回数
    recent_bad_calls: int = 0   # 直近 GOAL_MISS_GAMES 戦の、役なしの鳴きの回数
    recent_calls: int = 0       # 直近 GOAL_MISS_GAMES 戦の、鳴いた回数
    hands: int = 0              # 数えた対局の、局の数の合計（放銃率の分母）
    deal_ins: int = 0           # そのうち、自分が放銃した局の数

    @property
    def enough(self) -> bool:
        return self.games >= GOAL_GAMES

    @property
    def rank_ok(self) -> bool:
        return self.average_rank is not None and self.average_rank <= GOAL_RANK

    @property
    def deal_in_ok(self) -> bool:
        return self.deal_in_rate is not None and self.deal_in_rate <= GOAL_DEAL_IN

    @property
    def misses_ok(self) -> bool:
        return self.games >= GOAL_MISS_GAMES and self.recent_misses == 0

    @property
    def calls_ok(self) -> bool:
        """役なしの鳴きをしない（直近 GOAL_MISS_GAMES 戦で 0 回）"""
        return self.games >= GOAL_MISS_GAMES and self.recent_bad_calls == 0

    @property
    def passed(self) -> bool:
        return self.enough and self.rank_ok and self.deal_in_ok and self.misses_ok and self.calls_ok


def graduation(records: Sequence[GameRecord]) -> Graduation:
    eligible = [
        r for r in records
        if r.plain and r.length == Length.EAST.value and r.cpu_level == CpuLevel.NORMAL.value and not r.rules
    ][-GOAL_GAMES:]
    if not eligible:
        return Graduation(0, None, None, 0)
    hands = sum(r.hands for r in eligible)
    deal_ins = sum(r.deal_ins for r in eligible)
    recent = eligible[-GOAL_MISS_GAMES:]
    return Graduation(
        games=len(eligible),
        average_rank=sum(r.rank for r in eligible) / len(eligible),
        deal_in_rate=deal_ins / hands if hands else None,
        recent_misses=sum(r.misses for r in recent),
        recent_bad_calls=sum(r.tally.bad_calls for r in recent),
        recent_calls=sum(r.tally.calls for r in recent),
        hands=hands,
        deal_ins=deal_ins,
    )


# ---------------------------------------------------------------- 保存


def add_record(records: Sequence[GameRecord], record: GameRecord) -> list[GameRecord]:
    return [*records, record][-MAX_RECORDS:]


def dump_record(record: GameRecord) -> str:
    return json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))


def dump_history(records: Sequence[GameRecord]) -> str:
    return json.dumps({"v": HISTORY_VERSION, "games": [r.to_dict() for r in records]}, ensure_ascii=False, separators=(",", ":"))


def load_history(text: str | None) -> list[GameRecord]:
    """保存した文字列から記録を読む。全体が壊れていれば空、壊れた 1 件はその 1 件だけ読み飛ばす"""
    if not text:
        return []
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return []
    return records_from(data)


def records_from(data: object) -> list[GameRecord]:
    """記録の配列（または版の番号つきの形）から読む"""
    if isinstance(data, dict):
        if data.get("v") != HISTORY_VERSION:
            return []
        data = data.get("games")
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        try:
            records.append(GameRecord.from_dict(item))
        except ValueError:
            continue
    return records[-MAX_RECORDS:]


def rules_text(rules: Mapping[str, object] | Sequence[tuple[str, object]]) -> str:
    """初期値と違うルールの短い書き方（成績の表に添える）"""
    names = {
        "nagashi_mangan": ("流し満貫あり", "流し満貫なし"),
        "abortive_draws": ("途中流局あり", "途中流局なし"),
        "multiple_ron": ("複数ロン", "頭ハネ"),
        "tobi": ("飛びあり", "飛びなし"),
        "aka_dora": ("赤ドラあり", "赤ドラなし"),
        "kuitan": ("喰いタンあり", "喰いタンなし"),
        "kiriage_mangan": ("切り上げ満貫あり", "切り上げ満貫なし"),
        "double_yakuman": ("ダブル役満あり", "ダブル役満なし"),
        "kazoe_yakuman": ("数え役満あり", "数え役満なし"),
        "calls": ("鳴きあり", "鳴きなし"),
    }
    items = dict(rules)
    words = []
    for name, value in items.items():
        if name in names and isinstance(value, bool):
            words.append(names[name][0 if value else 1])
        elif name == "double_wind_pair_fu":
            words.append(f"連風牌の雀頭 {value} 符")
    return "・".join(words)

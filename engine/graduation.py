"""卒業判定：仕様の 9 章「卒業条件」の 6 つを、記録からまとめて判定する（Phase 5）。

    1 役          役の翻数・成立・不成立・役の判定 のドリル（どれも直近 20 問で 80% 以上）
    2 点数        点数早見のドリル（直近 20 問で 90% 以上）・符の計算のドリル（直近 20 問で 80% 以上）・
                  あがったときの点数の申告（直近 20 回で 90% 以上）
    3 鳴きとフリテン  あがれる？のドリル（直近 20 問で 80% 以上）・
                  CPU 戦の役なしの鳴きと、役なし・フリテンの見落とし（直近 10 戦で、どちらも 0 回）
    4 守り        危険牌のドリル（直近 20 問で 80% 以上）・CPU 戦の放銃率（30 戦で 15% 以下）
    5 発声と作法  発声と作法のドリル（直近 20 問で 80% 以上）
    6 対局の成績  CPU 戦 30 回の平均順位 2.5 以下

CPU 戦の条件は、補正 0（自分も CPU も）・CPU ふつう・打つ前のヒントなし・初期のルール（鳴きあり）の東風戦の、
直近 30 回で見る（engine.game_records.graduation。数え方は Phase 3・4 と同じ）。
ドリルは、種類ごとの直近の答え（engine.srs.Deck.recent）で見る。前に間違えていても、いま答えられれば良い。
「即答で申告」の速さは測らない（答えの正しさだけを見る）。画面にも、そう書く。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from engine.drills import KINDS
from engine.game_records import GOAL_DEAL_IN, GOAL_GAMES, GOAL_MISS_GAMES, GOAL_RANK, GameRecord, graduation
from engine.srs import Deck

#: ドリルで見る、直近の答えの数
RECENT = 20
DRILL_GOAL = 80             # 直近の正答率の目標（%）
TABLE_GOAL = 90             # 点数早見
DECLARE_GOAL = 90           # あがったときの点数の申告（docs/DESIGN.md の 9 章で決めた 90%）
#: 点数の申告の記録の名前（ui.progress_store.DECLARE と同じ）
DECLARE = "declare"

#: 練習する場所（画面で、ページへのリンクにする）
WHERE_DRILL, WHERE_GAME, WHERE_PLAY = "drill", "game", "play"


@dataclass(frozen=True)
class Check:
    """条件の中の、1 つの目標"""

    name: str           # 何を見るか（例：「役の翻数」のドリル）
    goal: str           # 目標（例：直近 20 問で 80% 以上）
    status: str         # いまの値（例：直近 20 問で 17 問正解（85%））
    passed: bool
    ready: bool         # 判定できるだけの記録があるか
    where: str          # 練習する場所（WHERE_…）
    kind: str = ""      # ドリルの種類（where が drill のとき）


@dataclass(frozen=True)
class Condition:
    key: str
    title: str          # 仕様の 9 章の文
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def done(self) -> int:
        return sum(1 for check in self.checks if check.passed)


@dataclass(frozen=True)
class Report:
    conditions: tuple[Condition, ...]

    @property
    def passed(self) -> bool:
        return all(condition.passed for condition in self.conditions)

    @property
    def done(self) -> int:
        """満たした条件の数"""
        return sum(1 for condition in self.conditions if condition.passed)


def _half_up(value: Decimal, digits: int) -> str:
    """四捨五入して書く（ui.practice_view.rounded と同じ。書式の指定に任せると、偶数への丸めで 1 つずれることがある）"""
    return f"{value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)}"


def _percent(right: int, total: int) -> str:
    return f"{_half_up(Decimal(right * 100) / total, 0)}%" if total else "—"


def drill_check(decks: Mapping[str, Deck], kind: str, goal: int, *, name: str | None = None, unit: str = "問") -> Check:
    """ドリル（か、点数の申告）の直近 RECENT 問の正答率"""
    deck = decks.get(kind) or Deck()
    right, total = deck.recent_accuracy(RECENT)
    label = name or (f"「{KINDS[kind].name}」のドリル" if kind in KINDS else "あがったときの点数の申告")
    target = f"直近 {RECENT} {unit}で {goal}% 以上"
    where = WHERE_PLAY if kind == DECLARE else WHERE_DRILL
    if total < RECENT:
        status = f"いままでに {total} {unit}。判定は {RECENT} {unit}たまってから" if total else ("まだ申告していない" if kind == DECLARE else "まだ答えていない")
        return Check(label, target, status, False, False, where, kind)
    passed = right * 100 >= goal * total
    return Check(label, target, f"直近 {total} {unit}で {right} {unit}正解（{_percent(right, total)}）", passed, True, where, kind)


def report(decks: Mapping[str, Deck], games: Sequence[GameRecord]) -> Report:
    """いまの記録で、卒業条件を判定する"""
    grad = graduation(games)
    few = grad.games < GOAL_MISS_GAMES
    counted = f"対象の対局は {grad.games} 戦。判定は {GOAL_MISS_GAMES} 戦たまってから" if grad.games else "対象の対局が、まだ無い"
    calls = Check(
        "CPU 戦の、役なしの鳴き", f"直近 {GOAL_MISS_GAMES} 戦で 0 回",
        counted if few else f"直近 {GOAL_MISS_GAMES} 戦で {grad.recent_bad_calls} 回（鳴いた {grad.recent_calls} 回のうち）",
        grad.calls_ok, not few, WHERE_GAME,
    )
    misses = Check(
        "CPU 戦の、役なし・フリテンの見落とし", f"直近 {GOAL_MISS_GAMES} 戦で 0 回",
        counted if few else f"直近 {GOAL_MISS_GAMES} 戦で {grad.recent_misses} 回",
        grad.misses_ok, not few, WHERE_GAME,
    )
    short = not grad.enough
    deal_in = "—" if not grad.hands else f"{_half_up(Decimal(grad.deal_ins * 100) / grad.hands, 1)}%（{grad.hands} 局で {grad.deal_ins} 回）"
    deal_ins = Check(
        "CPU 戦の放銃率", f"{GOAL_GAMES} 戦で {round(GOAL_DEAL_IN * 100)}% 以下",
        (f"いまは {grad.games} 戦で {deal_in}。判定は {GOAL_GAMES} 戦たまってから" if grad.games else "対象の対局が、まだ無い") if short
        else f"直近 {GOAL_GAMES} 戦で {deal_in}",
        grad.enough and grad.deal_in_ok, not short, WHERE_GAME,
    )
    rank = "—" if grad.average_rank is None else _half_up(Decimal(str(grad.average_rank)), 2)
    ranks = Check(
        "CPU 戦の平均順位", f"{GOAL_GAMES} 戦で {GOAL_RANK} 以下",
        (f"いまは {grad.games} 戦で {rank}。判定は {GOAL_GAMES} 戦たまってから" if grad.games else "対象の対局が、まだ無い") if short
        else f"直近 {GOAL_GAMES} 戦で {rank}",
        grad.enough and grad.rank_ok, not short, WHERE_GAME,
    )
    return Report((
        Condition("yaku", "主要な役を定義込みで説明でき、手牌を見て役と翻数を言える。", (
            drill_check(decks, "han", DRILL_GOAL),
            drill_check(decks, "valid", DRILL_GOAL),
            drill_check(decks, "yaku", DRILL_GOAL),
        )),
        Condition("points", "子・親の頻出点数を即答で申告でき、簡単な符計算ができる（このアプリでは、答えの正しさで判定する。速さは測らない）。", (
            drill_check(decks, "table", TABLE_GOAL),
            drill_check(decks, "fu", DRILL_GOAL),
            drill_check(decks, DECLARE, DECLARE_GOAL, name="あがったときの点数の申告（一人練習・CPU 戦）", unit="回"),
        )),
        # 仕様の文は「和了れなくなる」。和了（ホーラ）とルビが付いて読み違えやすいので、ひらがなで書く
        Condition("calls", "役なしの鳴きで、あがれなくなるミスをしない。フリテンを理解している。", (
            drill_check(decks, "win", DRILL_GOAL),
            calls,
            misses,
        )),
        Condition("defense", "リーチに対して安全な牌を選んでオリられる。", (
            drill_check(decks, "danger", DRILL_GOAL),
            deal_ins,
        )),
        Condition("manners", "発声（ポン・チー・カン・ロン・ツモ・リーチ）と基本マナーを知っている。", (
            drill_check(decks, "manners", DRILL_GOAL),
        )),
        Condition("record", f"補正 0 で CPU（ふつう）相手に東風戦を {GOAL_GAMES} 戦打ち、平均順位 {GOAL_RANK} 以下になる。", (
            ranks,
        )),
    ))

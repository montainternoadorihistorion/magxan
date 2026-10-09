"""おまかせ補正：成績に合わせて、ツキ補正を段階的に自動で下げる（仕様の 4 章「おまかせモード」。成績が落ちたら、1 段階戻す）。

段階は 強（75）→ 中（50）→ 弱（25）→ なし（0）。おまかせを始めたときは、いまの補正にいちばん近い段階から。
新しい局（一人練習）・新しい対局（CPU 戦）を始めるときに、次の 2 つを見て、1 段階ずつ動かす。

    打牌    前に段階を変えて（おまかせを始めて）からの、打つ前のヒントを見ずに打った局のうち、直近のもの
            （一人練習は 10 局まで。役指定練習の局は除く。CPU 戦は 3 対局まで）の、コーチの評価がいちばん良かった打牌の割合
              一人練習：いちばん速い打牌（おすすめと同じ速さ。同じ速さの牌が いくつかあれば、どれでもよい）
              CPU 戦  ：オリるべき局面では、いちばん安全な牌。ほかは、おすすめと同じ速さの牌（engine.game_records.Tally.good）
    ドリル  すべての種類の、直近の答えの正答率（種類ごとに直近 10 問まで。合わせて 20 問以上あるときだけ見る）

    どちらも 80% 以上 → 1 段階下げる（補正を弱くする）
    どれかが 60% 未満 → 1 段階戻す（補正を強くする）
    そのあいだ        → そのまま

段階を変えたあと（おまかせを始めたあと）、ヒントなしの局が一人練習で 5 局（CPU 戦は 2 対局）たまるまでは、判断しない
（変えたばかりの強さで、何局か打ってもらうため。行ったり来たりしないように、基準にもあいだを空けてある）。
ヒントを見ながら打った局は数えない（おすすめをなぞれば、評価は良くなるので）。いまの段階の補正で打った局だけを数える
（おまかせを入れたときに打っていた局は、前の補正のままなので数えない）。

基準の目安（CPU 戦の自分の席に、決まった打ち方の打ち手を座らせた計測。東風戦 40 回・補正 25）：
向聴数だけを見て、受け入れの広さを見ずに切り、オリない打ち手（CPU の「弱い」）は 53%（対局ごとに 40〜65%）。
いつも いちばん速い牌のどれかを切り、オリない打ち手は 91%（対局ごとに 79〜100%）。docs/DESIGN.md の 5 章「おまかせ補正」。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from engine.game_records import GameRecord
from engine.luck import PRESETS
from engine.records import HandRecord
from engine.srs import Deck

#: おまかせで使う段階（強い順）
LEVELS = (75, 50, 25, 0)
LEVEL_NAMES = {level: name for name, level in PRESETS}
DOWN_AT = 0.8           # これ以上なら、補正を下げる
UP_BELOW = 0.6          # これより下なら、補正を戻す
MIN_HANDS = 5           # 判断に要る、ヒントなしの局の数（一人練習）
RECENT_HANDS = 10       # 判断に使う、直近の局の数（一人練習）
MIN_GAMES = 2           # 同じく、対局の数（CPU 戦）
RECENT_GAMES = 3
MIN_DRILLS = 20         # ドリルの正答率を見るのに要る、答えの数
DRILL_RECENT = 10       # 種類ごとに見る、直近の答えの数


@dataclass(frozen=True)
class Rate:
    right: int
    total: int

    @property
    def value(self) -> float:
        return self.right / self.total if self.total else 0.0

    @property
    def percent(self) -> int:
        """百分率（切り捨て。79.9% を「80%」と書くと、「80% 以上で下げる」と食い違って見えるため）"""
        return self.right * 100 // self.total if self.total else 0


@dataclass(frozen=True)
class Play:
    """判断に使う、打牌の評価"""

    rate: Rate          # 直近の局（対局）の、良い打牌の割合
    count: int          # 段階を変えてからの、ヒントなしの局（対局）の数
    used: int           # そのうち、rate に入れた数（直近のもの）


@dataclass(frozen=True)
class AutoDecision:
    level: int                  # 次に使う段階
    before: int                 # 判断する前の段階
    play: Play
    drill: Rate | None          # ドリルの正答率（答えが足りなければ None）
    waiting: int                # 判断まで、あと何局（何対局）。判断したなら 0

    @property
    def changed(self) -> int:
        """動いた向き（−1 ＝ 下げた・＋1 ＝ 戻した・0 ＝ そのまま）"""
        return (self.level < self.before) * -1 + (self.level > self.before)

    @property
    def judged(self) -> bool:
        return self.waiting == 0


def level_name(level: int) -> str:
    return LEVEL_NAMES.get(level, str(level))


def start_level(deal: int, draw: int) -> int:
    """おまかせを始めるときの段階：いまの補正（配牌とツモの平均）にいちばん近い段階。同じ近さなら、強いほう"""
    mean = (deal + draw) / 2
    return min(LEVELS, key=lambda level: (abs(level - mean), -level))


def current_level(deal: int, draw: int) -> int:
    """おまかせの、いまの段階（設定が段階どおりでなければ、いちばん近い段階）"""
    return deal if deal == draw and deal in LEVELS else start_level(deal, draw)


def _step(level: int, move: int) -> int:
    index = LEVELS.index(level)
    return LEVELS[max(0, min(len(LEVELS) - 1, index + move))]


def drill_rate(decks: Mapping[str, Deck], kinds: Iterable[str]) -> Rate | None:
    """ドリルの直近の正答率（種類ごとに直近 DRILL_RECENT 問まで）。答えが MIN_DRILLS 問に足りなければ None"""
    right = total = 0
    for kind in kinds:
        deck = decks.get(kind)
        if deck is None:
            continue
        r, n = deck.recent_accuracy(DRILL_RECENT)
        right, total = right + r, total + n
    return Rate(right, total) if total >= MIN_DRILLS else None


def practice_play(records: Iterable[HandRecord], since: int, level: int) -> Play:
    """一人練習：段階を変えてからの、いまの段階の補正で、ヒントなしで打った局（役指定練習の局は除く）の、直近 RECENT_HANDS 局の評価"""
    used = [r for r in records if r.time > since and not r.hinted and not r.target and r.decisions > 0 and r.deal == r.draw == level]
    recent = used[-RECENT_HANDS:]
    return Play(Rate(sum(r.best for r in recent), sum(r.decisions for r in recent)), len(used), len(recent))


def game_play(records: Iterable[GameRecord], since: int, level: int) -> Play:
    """CPU 戦：段階を変えてからの、いまの段階の補正で、ヒントなしで打った対局の、直近 RECENT_GAMES 対局の評価"""
    used = [r for r in records if r.time > since and not r.hinted and r.tally.decisions > 0 and r.deal == r.draw == level]
    recent = used[-RECENT_GAMES:]
    return Play(Rate(sum(r.tally.good for r in recent), sum(r.tally.decisions for r in recent)), len(used), len(recent))


def decide(level: int, play: Play, need: int, drill: Rate | None) -> AutoDecision:
    """次の段階を決める。need は、判断に要る局（対局）の数"""
    level = level if level in LEVELS else LEVELS[0]
    if play.count < need:
        return AutoDecision(level, level, play, drill, need - play.count)
    rates = [play.rate, *([drill] if drill is not None else [])]
    if all(rate.value >= DOWN_AT for rate in rates):
        return AutoDecision(_step(level, 1), level, play, drill, 0)
    if any(rate.value < UP_BELOW for rate in rates):
        return AutoDecision(_step(level, -1), level, play, drill, 0)
    return AutoDecision(level, level, play, drill, 0)


def reason(decision: AutoDecision, *, unit: str, counter: str, ahead: bool = False) -> str:
    """判断の理由を、ひとことで。unit は「局」「対局」、counter は数える言葉（「局」「回」）。
    ahead なら、これからの見込みとして書く（「次の局を始めるとき、…下げます」）"""
    if not decision.judged:
        return f"ヒントを見ずに打った{unit}が、あと {decision.waiting} {counter}たまったら判断します。"
    play, drill = decision.play, decision.drill
    figures = f"打牌の評価 {play.rate.percent}%（直近 {play.used} {unit}）"
    if drill is not None:
        figures += f"・ドリルの正答率 {drill.percent}%（直近 {drill.total} 問）"
    both = "どちらも " if drill is not None else ""
    before, after = level_name(decision.before), level_name(decision.level)
    down, up = round(DOWN_AT * 100), round(UP_BELOW * 100)
    named = [("打牌の評価", play.rate), *([("ドリルの正答率", drill)] if drill is not None else [])]
    low = "と".join(name for name, rate in named if rate.value < UP_BELOW)
    when = f"次の{unit}を始めるとき、" if ahead else ""
    if decision.changed < 0:
        return f"{figures}。{both}{down}% 以上なので、{when}補正を「{before}」から「{after}」に{'下げます' if ahead else '下げました'}。"
    if decision.changed > 0:
        return f"{figures}。{low}が {up}% より低いので、{when}補正を「{before}」から「{after}」に{'上げます' if ahead else '上げました'}。"
    if all(rate.value >= DOWN_AT for _, rate in named):
        return f"{figures}。{both}{down}% 以上です。補正は、もう「{after}」です。"
    if low:
        return f"{figures}。{low}が {up}% より低いですが、補正は、いちばん強い段階の「{after}」のままです。"
    return f"{figures}。補正は「{after}」のままです（{both}{down}% 以上で下げ、{up}% より低いものがあれば上げます）。"


# ---------------------------------------------------------------- 前回の変更の控え（設定に残す。文字と数だけ）

MAX_COUNT = 1_000_000
MAX_TIME = 10**11


def decision_data(decision: AutoDecision, time: int) -> dict[str, int]:
    """段階を変えた判断の控え（画面で「前回の変更」を、開き直しても出せるように）"""
    play = decision.play
    data = {"from": decision.before, "to": decision.level, "pr": play.rate.right, "pn": play.rate.total, "pu": play.used, "t": int(time)}
    if decision.drill is not None:
        data.update(dr=decision.drill.right, dn=decision.drill.total)
    return data


def _count(data: dict, name: str, top: int = MAX_COUNT) -> int | None:
    value = data.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= top else None


def decision_from_data(data: object) -> tuple[AutoDecision, int] | None:
    """控えから、判断と時刻を作り直す。形がおかしければ None（ブラウザに残っているので、壊れていることがある）"""
    if not isinstance(data, dict) or data.get("from") not in LEVELS or data.get("to") not in LEVELS or data["from"] == data["to"]:
        return None
    if isinstance(data["from"], bool) or isinstance(data["to"], bool):
        return None
    right, total, used = (_count(data, name) for name in ("pr", "pn", "pu"))
    time = _count(data, "t", MAX_TIME)
    if right is None or total is None or used is None or time is None or right > total:
        return None
    drill = None
    if "dr" in data or "dn" in data:
        dr, dn = _count(data, "dr"), _count(data, "dn")
        if dr is None or dn is None or dr > dn:
            return None
        drill = Rate(dr, dn)
    return AutoDecision(data["to"], data["from"], Play(Rate(right, total), used, used), drill, 0), time

"""ドリル：短い問題をくり返して、読み・役・待ち・符・点数の数え方を覚える。

    item, why = next_item("table", deck, now, pick=乱数)     次に出す問題（復習の時刻になった問題が先）
    q = question("table", item)                               問題（選択肢・正解・解説）
    graded = grade(q, {"3900"})                               採点
    deck = deck.review(item, graded.correct, now, keep=KINDS["table"].finite)

問題の種類
    決まった数の問題がある種類（finite）   読み・翻数・成立/不成立・点数早見。すべての問題を、間隔反復で追う
    その場で作る種類                       役の判定・あがれる？・待ち・符・点数計算・何切る。番号から作る。
                                           同じ番号なら、いつでも同じ問題。間違えた問題だけを覚えておいて、あとでもう一度出す

正解は、どれも点数計算・向聴数・牌効率のエンジンが決める（ここで答えを書かない）。
選択肢の「はずれ」も、エンジンの計算結果から選ぶ（例：1 翻ずれた点数、となりの牌）。
ルールは初期設定（engine.rules.DEFAULT_RULES）。役図鑑の例を使う問題だけは、その例に書いてあるルール。
"""
from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import cache, lru_cache

from engine import practice
from engine.analysis.shanten import shanten_text
from engine.analysis.waits import wait_kinds
from engine.coach import Analysis, Position, Verdict, analyze, judge_discard
from engine.content import TRAP_RESULTS, YakuPage, glossary, yaku_pages
from engine.luck import LuckSettings
from engine.melds import Meld, MeldType
from engine.rng import Rng
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import ContextError, WinContext
from engine.scoring.decompose import BlockType, Form
from engine.scoring.explain import Explanation, Status, explain
from engine.scoring.judge import Level
from engine.scoring.layout import block_tiles
from engine.scoring.points import PointsResult, calculate_points
from engine.scoring.random_hand import random_win
from engine.scoring.texts import kind_text, wait_text
from engine.srs import MAX_BOX, Deck
from engine.tiles import NUM_KINDS, RED_FIVE_IDS, counts34, is_yaochu_kind, kind_of, sort_tiles
from engine.yaku_table import YAKU

#: その場で作る問題の番号の上限
MAX_NUMBER = 999_999_999
#: 「定着した」と数える箱（間隔をあけて 2 回以上、続けて正解した問題）
LEARNED_BOX = 3
WIND_NAMES = {27: "東", 28: "南", 29: "西", 30: "北"}


# ---------------------------------------------------------------- 種類


@dataclass(frozen=True)
class DrillKind:
    key: str
    name: str           # 画面に出す名前
    short: str          # 何を練習するか
    finite: bool        # 決まった数の問題がある種類か
    group: str          # GROUPS の鍵


GROUPS: dict[str, str] = {
    "word": "言葉を覚える",
    "yaku": "役を覚える",
    "count": "数える",
    "play": "打つ",
}

_KINDS = (
    DrillKind("reading", "用語の読み", "麻雀の言葉と役の名前を、正しく読む", True, "word"),
    DrillKind("han", "役の翻数", "役ごとの翻数と、鳴いたときにどうなるか", True, "yaku"),
    DrillKind("valid", "成立・不成立", "手を見て、その役が付くかどうかを見分ける", True, "yaku"),
    DrillKind("yaku", "役の判定", "あがった手に付く役を、すべて挙げる", False, "yaku"),
    DrillKind("win", "あがれる？", "ロン・ツモと言ってよい手かを見分ける（役なし・形ちがい・フリテン）", False, "yaku"),
    DrillKind("wait", "待ち", "聴牌した手の待ち牌を、すべて見つける", False, "count"),
    DrillKind("fu", "符の計算", "あがった手の符を数える", False, "count"),
    DrillKind("table", "点数早見", "符と翻から、点数をすぐ言えるようにする", True, "count"),
    DrillKind("score", "点数計算", "あがった手の点数を、役から順に数える", False, "count"),
    DrillKind("discard", "何切る", "いちばん速く聴牌に近づく打牌を選ぶ（牌効率）", False, "play"),
)
#: ドリルの種類（画面に並べる順）
KINDS: dict[str, DrillKind] = {kind.key: kind for kind in _KINDS}


# ---------------------------------------------------------------- 問題


@dataclass(frozen=True)
class Choice:
    key: str            # 採点に使う鍵
    label: str          # 画面に出す文字
    why: str = ""       # 答えたあとに出す、ひとことの説明（この選択肢が何にあたるか）
    tile: int | None = None     # 牌の種類（待ちのドリルで、牌の絵を出すため）


@dataclass(frozen=True)
class Question:
    kind: str
    item: str                               # 問題の鍵（間隔反復の記録に使う）
    prompt: str                             # 問題文
    choices: tuple[Choice, ...] = ()        # 選択肢（何切るでは空。手牌から 1 枚選ぶ）
    correct: frozenset[str] = frozenset()   # 正解の鍵（いくつも選ぶ問題では、過不足なく選んで正解）
    multi: bool = False                     # いくつも選ぶ問題か
    note: str = ""                          # 問題文の下に出す補足（答え方など）
    answer: tuple[str, ...] = ()            # 解説（答えたあとに出す文章）
    ctx: WinContext | None = None           # 見せる手（あがりの状況）
    rules: Rules = DEFAULT_RULES            # その手を数えるルール
    rule_notes: tuple[str, ...] = ()        # 初期設定と違うルール（例：喰いタンなし）
    hand: tuple[int, ...] = ()              # 見せる手（13 枚。待ちのドリル）
    river: tuple[int, ...] | None = None    # 自分の河（見せない問題は None）
    position: Position | None = None        # 何切るの局面
    page: str = ""                          # 関係する役図鑑のページ
    term: str = ""                          # 関係する用語（辞典の見出し語）

    def choice(self, key: str) -> Choice:
        return next(c for c in self.choices if c.key == key)


@dataclass(frozen=True)
class Graded:
    correct: bool
    picked: frozenset[str]
    missed: tuple[Choice, ...]      # 選ばなかった正解
    extra: tuple[Choice, ...]       # 選んだが、正解でないもの


def grade(question: Question, picked: Iterable[str]) -> Graded:
    """選んだ答えを採点する。いくつも選ぶ問題は、過不足なく選んだときだけ正解"""
    chosen = frozenset(picked)
    known = {c.key for c in question.choices}
    if not chosen <= known:
        raise ValueError(f"選択肢に無い答えです: {sorted(chosen - known)}")
    if not question.multi and len(chosen) != 1:
        raise ValueError("答えは 1 つだけ選びます")
    missed = tuple(c for c in question.choices if c.key in question.correct and c.key not in chosen)
    extra = tuple(c for c in question.choices if c.key in chosen and c.key not in question.correct)
    return Graded(not missed and not extra, chosen, missed, extra)


def grade_discard(question: Question, tile: int) -> tuple[bool, Verdict, Analysis]:
    """何切る：切った牌を採点する。→（正解か, 評価, 局面の分析）"""
    if question.position is None:
        raise ValueError("何切るの問題ではありません")
    analysis = analyze(question.position)
    verdict = judge_discard(analysis, tile)
    return verdict.is_best, verdict, analysis


# ---------------------------------------------------------------- 小さな道具


def _number(item: str) -> int:
    """その場で作る問題の鍵（数字）を読む"""
    if not isinstance(item, str) or not (item.isascii() and item.isdigit()) or len(item) > len(str(MAX_NUMBER)):
        raise ValueError(f"問題の番号が読めません: {item!r}")
    return int(item)


def _weighted(rng: Rng, items: Sequence[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in items)
    point = rng.random() * total
    for item, weight in items:
        point -= weight
        if point < 0:
            return item
    return items[-1][0]


def _free_tile(kind: int, used: Collection[int]) -> int | None:
    """その種類の牌のうち、まだ使っていない 1 枚（赤でないほうを優先）"""
    ids = [kind * 4 + i for i in range(4) if kind * 4 + i not in used]
    plain = [t for t in ids if t not in RED_FIVE_IDS]
    return (plain or ids or [None])[0]


def _fmt(value: int) -> str:
    return f"{value:,}"


def _shuffled(rng: Rng, items: Sequence[str]) -> list[str]:
    result = list(items)
    rng.shuffle(result)
    return result


_RULE_TEXTS: tuple[tuple[str, dict], ...] = (
    ("aka_dora", {True: "赤ドラあり", False: "赤ドラなし"}),
    ("kuitan", {True: "喰いタンあり", False: "喰いタンなし"}),
    ("kiriage_mangan", {True: "切り上げ満貫あり", False: "切り上げ満貫なし"}),
    ("double_wind_pair_fu", {2: "連風牌の雀頭は 2 符", 4: "連風牌の雀頭は 4 符"}),
    ("double_yakuman", {True: "ダブル役満あり", False: "ダブル役満なし"}),
    ("kazoe_yakuman", {True: "数え役満あり", False: "数え役満なし（三倍満まで）"}),
)


def rule_notes(rules: Rules) -> tuple[str, ...]:
    """初期設定と違うルールを、短い言葉にする（同じなら空）"""
    return tuple(
        texts[getattr(rules, name)] for name, texts in _RULE_TEXTS if getattr(rules, name) != getattr(DEFAULT_RULES, name)
    )


def _plain(ctx: WinContext) -> WinContext:
    """本場と供託を 0 にする（点数の問題を、手そのものの点だけにするため）"""
    return replace(ctx, honba=0, kyotaku=0)


# ---------------------------------------------------------------- 点数の書き方


def _points(han: int, fu: int, *, dealer: bool, tsumo: bool, times: int = 0, rules: Rules = DEFAULT_RULES) -> PointsResult:
    return calculate_points(han, fu, yakuman_times=times, is_dealer=dealer, is_tsumo=tsumo, honba=0, kyotaku=0, rules=rules)


def pay_text(points: PointsResult, *, tsumo: bool, dealer: bool) -> str:
    """支払いの書き方。ロン「3,900 点」／子のツモ「1,000・2,000 点」（子・親の順）／親のツモ「2,000 点オール」"""
    pays = points.payments
    if not tsumo:
        return f"{_fmt(pays[0].points)} 点"
    if dealer:
        return f"{_fmt(pays[0].points)} 点オール"
    return f"{_fmt(pays[1].points)}・{_fmt(pays[0].points)} 点"


def _pay_label(points: PointsResult, *, tsumo: bool, dealer: bool) -> str:
    text = pay_text(points, tsumo=tsumo, dealer=dealer)
    return f"{text}（{points.level_name}）" if points.level_name else text


def _who(dealer: bool) -> str:
    return "親" if dealer else "子"


def _how(tsumo: bool) -> str:
    return "ツモ" if tsumo else "ロン"


def combo_exists(fu: int, han: int, tsumo: bool) -> bool:
    """その符と翻の組み合わせが、実際にあるか。

    20 符は平和のツモだけ（2 翻以上）。25 符は七対子だけ（ロンは 2 翻以上、ツモは 3 翻以上）。
    """
    if fu == 20:
        return tsumo and han >= 2
    if fu == 25:
        return han >= (3 if tsumo else 2)
    return han >= 1


_LADDER_FU = (20, 25, 30, 40, 50, 60, 70)
#: 満貫以上の区分（鍵, 代表の翻数, 役満の倍数）
LEVELS = (("mangan", 5, 0), ("haneman", 6, 0), ("baiman", 8, 0), ("sanbaiman", 11, 0), ("yakuman", 13, 1))


@lru_cache(maxsize=8)
def _ladder(dealer: bool, tsumo: bool) -> tuple[tuple[int, str, str], ...]:
    """よく出る点数の一覧：（受け取る合計, 表示, その点になる符と翻）。合計の小さい順"""
    found: dict[str, tuple[int, list[str]]] = {}

    def add(points: PointsResult, how: str) -> None:
        label = pay_text(points, tsumo=tsumo, dealer=dealer)
        entry = found.setdefault(label, (points.total, []))
        if how not in entry[1]:
            entry[1].append(how)

    for fu in _LADDER_FU:
        for han in (1, 2, 3, 4):
            if combo_exists(fu, han, tsumo):
                points = _points(han, fu, dealer=dealer, tsumo=tsumo)
                if points.level is Level.NONE:
                    add(points, f"{fu} 符 {han} 翻")
    for _, han, times in LEVELS:
        points = _points(han, 30, dealer=dealer, tsumo=tsumo, times=times)
        add(points, points.level_name)
    double = _points(26, 30, dealer=dealer, tsumo=tsumo, times=2)
    add(double, double.level_name)
    rows = sorted((total, label, "・".join(hows[:2])) for label, (total, hows) in found.items())
    return tuple(rows)


def _near_points(label: str, total: int, *, dealer: bool, tsumo: bool, rng: Rng, count: int = 3) -> list[tuple[int, str, str]]:
    """正解に近い点数を、はずれの選択肢として選ぶ（一覧の上で、正解のすぐ上下にあるもの）"""
    rows = [row for row in _ladder(dealer, tsumo) if row[1] != label]
    below = [row for row in rows if row[0] <= total][::-1]
    above = [row for row in rows if row[0] > total]
    near: list[tuple[int, str, str]] = []
    for index in range(len(rows)):          # 正解に近い順（すぐ下、すぐ上、その次…）
        near += below[index:index + 1] + above[index:index + 1]
    near = near[: count + 1]                # いちばん近い 4 つを候補にして、そこから選ぶ
    rng.shuffle(near)
    picked = near[:count]
    for row in rows:                        # 足りなければ、残りから
        if len(picked) >= count:
            break
        if row not in picked:
            picked.append(row)
    return picked


# ---------------------------------------------------------------- 点数早見


_SEATS = {"c": False, "p": True}        # 子・親
_HOWS = {"r": False, "t": True}         # ロン・ツモ
_LEVEL_KEYS = {key: (han, times) for key, han, times in LEVELS}
_LEVEL_HANS = (5, 6, 7, 8, 9, 10, 11, 12, 13)


@cache
def _table_items() -> tuple[str, ...]:
    items = []
    situations = [seat + how for how in _HOWS for seat in _SEATS]       # 子ロン・親ロン・子ツモ・親ツモ
    for situation in situations:
        items += [f"{situation}:{fu}:{han}" for fu in (30, 40) for han in (1, 2, 3, 4)]
    for situation in situations:
        items += [f"{situation}:{key}" for key, _, _ in LEVELS]
    items += [f"lv:{han}" for han in _LEVEL_HANS]
    for situation in situations:        # 特別な符：平和のツモ（20 符）と七対子（25 符）
        items += [f"{situation}:{fu}:{han}" for fu in (20, 25) for han in (2, 3, 4) if combo_exists(fu, han, _HOWS[situation[1]])]
    return tuple(items)


def table_row(fu: int, *, dealer: bool, tsumo: bool) -> tuple[tuple[int, str], ...]:
    """早見表の 1 行：その符の、1〜4 翻の点数（実際にある組み合わせだけ）"""
    return tuple(
        (han, _pay_label(_points(han, fu, dealer=dealer, tsumo=tsumo), tsumo=tsumo, dealer=dealer))
        for han in (1, 2, 3, 4)
        if combo_exists(fu, han, tsumo)
    )


def level_row(*, dealer: bool, tsumo: bool) -> tuple[tuple[str, str], ...]:
    """早見表の、満貫以上の行：（呼び名, 点数）"""
    rows = []
    for _, han, times in LEVELS:
        points = _points(han, 30, dealer=dealer, tsumo=tsumo, times=times)
        rows.append((points.level_name, pay_text(points, tsumo=tsumo, dealer=dealer)))
    return tuple(rows)


def _table_question(item: str) -> Question:
    if item not in _table_items():
        raise ValueError(f"点数早見に無い問題です: {item!r}")
    rng = Rng(item, "drill:table")
    parts = item.split(":")
    if parts[0] == "lv":
        han = int(parts[1])
        names = [_points(value, 30, dealer=False, tsumo=False).level_name for value in (5, 6, 8, 11, 13)]
        correct = _points(han, 30, dealer=False, tsumo=False).level_name
        answer = ["5 翻 ＝ 満貫、6〜7 翻 ＝ 跳満、8〜10 翻 ＝ 倍満、11〜12 翻 ＝ 三倍満、13 翻以上 ＝ 数え役満。満貫から上は、符を数えなくてよい。"]
        if han >= 13:
            answer.append("13 翻以上を数え役満にするか、三倍満までとするかは、ルールによって異なる。")
        return Question(
            "table", item, f"{han} 翻のあがりを、何と呼ぶ？",
            tuple(Choice(name, name) for name in names), frozenset({correct}), answer=tuple(answer),
        )

    dealer, tsumo = _SEATS[parts[0][0]], _HOWS[parts[0][1]]
    situation = f"{_who(dealer)}の{_how(tsumo)}"
    note = "ツモの点は「子が払う点・親が払う点」の順。" if tsumo and not dealer else ("「オール」は、子 3 人が同じ点を払うこと。" if tsumo else "")
    if len(parts) == 2:         # 満貫以上
        han, times = _LEVEL_KEYS[parts[1]]
        points = _points(han, 30, dealer=dealer, tsumo=tsumo, times=times)
        label = pay_text(points, tsumo=tsumo, dealer=dealer)
        rows = [(name, text) for name, text in level_row(dealer=dealer, tsumo=tsumo)]
        others = [(name, text) for name, text in rows if text != label]
        other_seat = _points(han, 30, dealer=not dealer, tsumo=tsumo, times=times)
        swapped = pay_text(other_seat, tsumo=tsumo, dealer=not dealer)
        rng.shuffle(others)
        picks = others[:3]
        choices = [Choice(label, label, points.level_name)] + [Choice(text, text, name) for name, text in picks]
        # ロンの問題には、親と子を取りちがえた点も混ぜる（ツモは書き方が違うので、混ぜると見ただけで分かってしまう）
        if not tsumo and swapped not in {c.key for c in choices} and rng.chance(0.5):
            choices[-1] = Choice(swapped, swapped, f"{_who(not dealer)}の{points.level_name}")
        choices.sort(key=lambda c: _amount_key(c.key))
        answer = (
            f"{situation}の{points.level_name}は、{label}。",
            f"{situation}：" + " ／ ".join(f"{name} {text}" for name, text in rows),
            "親の点は、子の 1.5 倍。" if not tsumo else "ツモは、ロンの点を 3 人で分けて払う（親は子の 2 倍）。",
        )
        return Question("table", item, f"{situation}：{points.level_name}は何点？", tuple(choices), frozenset({label}), note=note, answer=answer)

    fu, han = int(parts[1]), int(parts[2])
    points = _points(han, fu, dealer=dealer, tsumo=tsumo)
    label = pay_text(points, tsumo=tsumo, dealer=dealer)

    def entry(f: int, h: int, seat: bool) -> tuple[str, str, int] | None:
        if not (1 <= h <= 5) or not combo_exists(f, h, tsumo):
            return None
        other = _points(h, f, dealer=seat, tsumo=tsumo)
        text = pay_text(other, tsumo=tsumo, dealer=seat)
        why = f"{f} 符 {h} 翻" if other.level is Level.NONE else other.level_name
        if seat != dealer:
            why = f"{_who(seat)}の{' ' if why[0].isdigit() else ''}{why}"
        return (text, why, other.total)

    other_fu = {20: 30, 25: 30, 30: 40, 40: 30}[fu]
    wanted = [(fu, han - 1, dealer), (fu, han + 1, dealer), (other_fu, han, dealer), (other_fu, han - 1, dealer), (other_fu, han + 1, dealer)]
    if not tsumo:       # ロンの問題には、親と子を取りちがえた点も混ぜる（ツモは書き方が違うので、見ただけで分かってしまう）
        wanted.insert(3, (fu, han, not dealer))
    pool: list[tuple[str, str, int]] = []
    for f, h, seat in wanted:
        made = entry(f, h, seat)
        if made is not None and made[0] != label and made[0] not in {p[0] for p in pool}:
            pool.append(made)
    first, rest = pool[:4], pool[4:]            # 近いもの（1 翻ちがい・符ちがい・親子ちがい）を先に使う
    rng.shuffle(first)
    picks = (first + rest)[:3]
    mine = f"{fu} 符 {han} 翻" + (f"（{points.level_name}）" if points.level_name else "")
    choices = [Choice(label, label, mine)] + [Choice(text, text, why) for text, why, _ in picks]
    totals = {label: points.total, **{text: total for text, _, total in picks}}
    choices.sort(key=lambda c: (totals[c.key], c.key))
    row = table_row(fu, dealer=dealer, tsumo=tsumo)
    answer = [points.formula, f"{fu} 符・{situation}：" + " ／ ".join(f"{h} 翻 {text}" for h, text in row)]
    if fu == 20:
        answer.append("20 符になるのは、平和をツモであがったときだけ。")
    if fu == 25:
        answer.append("25 符は、七対子の符（七対子は、いつも 25 符で、切り上げない）。")
    if (han, fu) == (4, 30):
        mangan = pay_text(_points(5, 30, dealer=dealer, tsumo=tsumo), tsumo=tsumo, dealer=dealer)
        answer.append(f"30 符 4 翻（と 60 符 3 翻）を、満貫に切り上げるルールもある（切り上げ満貫）。そのルールでは、{mangan}になる。")
    return Question(
        "table", item, f"{situation}：{fu} 符 {han} 翻は何点？", tuple(choices), frozenset({label}), note=note, answer=tuple(answer),
    )


def _amount_key(text: str) -> tuple[int, str]:
    """点数の文字（「1,000・2,000 点」など）を、小さい順に並べるための鍵"""
    digits = "".join(ch if ch.isdigit() else " " for ch in text.replace(",", "")).split()
    return (int(digits[-1]) if digits else 0, text)


# ---------------------------------------------------------------- 点数計算・符の計算・役の判定


def _score_question(item: str) -> Question:
    number = _number(item)
    ctx = _plain(random_win(f"score:{number}", "any"))
    result = explain(ctx)
    best = result.best
    assert best is not None and best.points is not None
    points = best.points
    dealer, tsumo = ctx.is_dealer, ctx.is_tsumo
    label = pay_text(points, tsumo=tsumo, dealer=dealer)
    rng = Rng(item, "drill:score")
    others = _near_points(label, points.total, dealer=dealer, tsumo=tsumo, rng=rng)
    if best.is_yakuman:
        why = points.level_name
    elif points.level is Level.NONE:
        why = f"{points.fu} 符 {points.han} 翻"
    else:
        why = f"{points.han} 翻（{points.level_name}）"
    rows = sorted([(points.total, label, why), *others])
    names = "・".join(y.name for y in best.evaluation.yaku)
    dora = f"・ドラ {best.dora_han}" if best.dora_han else ""
    answer = [f"{names}{dora} で {why}。{_who(dealer)}の{_how(tsumo)}なので、{pay_text(points, tsumo=tsumo, dealer=dealer)}。"]
    answer.append(points.formula)
    return Question(
        "score", item, "この手は何点？",
        tuple(Choice(text, text, how) for _, text, how in rows), frozenset({label}),
        note="役 → ドラ → 符 → 点数 の順に数える。本場と供託は無いものとする。" + ("ツモの点は「子が払う点・親が払う点」の順。" if tsumo and not dealer else ""),
        answer=tuple(answer), ctx=ctx,
    )


_FU_VALUES = (20, 30, 40, 50, 60, 70, 80, 90, 100, 110)


def _fu_question(item: str) -> Question:
    number = _number(item)
    rng = Rng(item, "drill:fu")
    source = "fu" if rng.chance(0.7) else "any"         # 符の足し算が要る手を多めに。20 符・30 符の手も混ぜる
    for attempt in range(60):
        ctx = _plain(random_win(f"fu:{number}:{attempt}", source))
        result = explain(ctx)
        best = result.best
        if best is not None and not best.is_yakuman and best.interp.form is not Form.KOKUSHI:
            break
    else:       # 60 回続けて役満になることは、まず無い
        raise RuntimeError(f"符の問題を作れませんでした: {item!r}")
    fu = best.fu.fu
    if fu == 25:
        values = [20, 25, 30, 40]
    else:
        near = sorted((v for v in _FU_VALUES if v != fu), key=lambda v: (abs(v - fu), v))[:3]
        values = [fu, *near]
        if rng.chance(0.25):                             # 七対子でない手にも、ときどき 25 符を混ぜる
            values[-1] = 25
    lines = [f"{line.label} {line.fu} 符" for line in best.fu.lines if line.fu or line.label == "副底"]
    if best.interp.form is Form.CHIITOI:
        answer = [best.fu.note]
    else:
        raw = best.fu.raw_total
        total = f"合計 {raw} 符"
        if fu != raw:
            total += f" → 例外で {fu} 符" if raw == 20 else f" → 切り上げて {fu} 符"
        answer = ["、".join(lines) + f"。{total}。"]
        if best.fu.note:
            answer.append(best.fu.note)
    return Question(
        "fu", item, "この手は何符？",
        tuple(Choice(str(v), f"{v} 符") for v in sorted(values)), frozenset({str(fu)}),
        note="副底 20 符に足していき、最後に 10 符単位に切り上げる（切り上げたあとの符を答える）。",
        answer=tuple(answer), ctx=ctx,
    )


#: 役の判定で、はずれの選択肢に使う役（よく出る役）
_COMMON_YAKU = (
    "riichi", "menzen_tsumo", "pinfu", "tanyao", "iipeikou", "yakuhai_seat", "yakuhai_round", "sanshoku", "ittsu",
    "chanta", "toitoi", "sanankou", "chiitoitsu", "honitsu",
)
_YAKU_ORDER = {key: index for index, key in enumerate(YAKU)}


def _yaku_label(key: str, ctx: WinContext) -> str:
    if key == "yakuhai_seat":
        return f"自風牌（{WIND_NAMES[ctx.seat_wind]}）"
    if key == "yakuhai_round":
        return f"場風牌（{WIND_NAMES[ctx.round_wind]}）"
    return YAKU[key].name


def _yaku_why(result: Explanation, key: str) -> tuple[bool, str]:
    """その役が数えられるか、条件は満たしているか、ひとことの理由"""
    check = result.yaku_check(key)
    if check is None:
        return (False, "")
    if check.ok:
        note = f"（{check.note}）" if check.note else ""
        han = "役満" if check.is_yakuman else f"{check.han} 翻"
        return (True, f"{han}{note}")
    if check.note:          # 別の読み方なら成立する役：条件の 1 つを挙げるより、そのことを言うほうが正しい
        return (False, check.note)
    failed = next((c for c in check.checks if not c.ok), None)
    if failed is None:
        return (False, "")
    return (False, f"「{failed.text}」を満たさない" + (f"（{failed.detail}）" if failed.detail else ""))


def _yaku_question(item: str) -> Question:
    number = _number(item)
    ctx = _plain(random_win(f"yaku:{number}", "any"))
    result = explain(ctx)
    best = result.best
    assert best is not None
    correct = [y.key for y in best.evaluation.yaku]
    rng = Rng(item, "drill:yaku")
    # 選択肢は 6 つ以上。はずれも必ず 2 つ以上入れる（全部選べば正解、にならないように）
    wanted = max(6, len(correct) + 2)
    pool = [y.key for y in best.near] + _shuffled(rng, _COMMON_YAKU)
    keys = list(correct)
    for key in pool:
        if len(keys) >= wanted:
            break
        if key in keys:
            continue
        ok, _ = _yaku_why(result, key)
        if ok:              # 条件は満たしているが、上位の役や役満のために数えない役は、選択肢に入れない（まぎらわしいだけ）
            continue
        keys.append(key)
    keys.sort(key=_YAKU_ORDER.__getitem__)
    choices = tuple(Choice(key, _yaku_label(key, ctx), _yaku_why(result, key)[1]) for key in keys)
    names = "・".join(_yaku_label(key, ctx) for key in correct)
    total = "役満" if best.is_yakuman else f"{best.evaluation.han} 翻"
    answer = [f"付く役は、{names}（役の合計 {total}）。"]
    if best.dora_han:
        answer.append(f"ドラが {best.dora_han} 枚あるが、ドラは役ではない（翻は増えるが、ドラだけではあがれない）。")
    return Question(
        "yaku", item, "この手に付く役を、すべて選ぶ", choices, frozenset(correct), multi=True,
        note="ドラは役ではないので、数えない。", answer=tuple(answer), ctx=ctx,
    )


# ---------------------------------------------------------------- 成立・不成立（役図鑑の例から）


#: あがったときの状況で決まる役のページ（手の形だけでは決まらないので、成立・不成立の問題にしない）
SITUATION_PAGES = frozenset(
    {"riichi", "ippatsu", "menzen_tsumo", "rinshan", "chankan", "haitei", "houtei", "double_riichi", "tenhou", "chiihou", "nagashi_mangan"}
)
VALID_YES, VALID_NO = "yes", "no"


@cache
def _valid_items() -> dict[str, tuple[YakuPage, int, bool]]:
    """問題の鍵 →（ページ, 例の番号, 成立例か）"""
    items: dict[str, tuple[YakuPage, int, bool]] = {}
    for page in yaku_pages():
        if page.key in SITUATION_PAGES or not page.yaku:
            continue
        for index in range(len(page.examples)):
            items[f"{page.key}:e{index}"] = (page, index, True)
        for index, trap in enumerate(page.traps):
            if trap.expect == "no_call":        # 手の形ではなく、場面の決まりであがれない例（絵だけでは分からない）
                continue
            result = explain(trap.hand.context(), trap.hand.rules)
            checks = [result.yaku_check(key) for key in page.yaku]
            if any(check is not None and check.ok for check in checks):
                continue                        # 条件は満たしているが、上位の役として数える例（「付かない」と言い切れない）
            items[f"{page.key}:t{index}"] = (page, index, False)
    return items


def _valid_question(item: str) -> Question:
    found = _valid_items().get(item)
    if found is None:
        raise ValueError(f"成立・不成立に無い問題です: {item!r}")
    page, index, is_example = found
    if is_example:
        hand = page.examples[index]
        answer = [f"{page.name}が付く。"]
        if hand.note:
            answer.append(hand.note)
    else:
        trap = page.traps[index]
        hand = trap.hand
        answer = [f"{page.name}は付かない。{trap.why}", f"この手は：{TRAP_RESULTS[trap.expect]}。"]
    return Question(
        "valid", item, f"この手に「{page.name}」は付く？",
        (Choice(VALID_YES, "付く"), Choice(VALID_NO, "付かない")), frozenset({VALID_YES if is_example else VALID_NO}),
        answer=tuple(answer), ctx=hand.context(), rules=hand.rules, rule_notes=rule_notes(hand.rules), page=page.key,
    )


# ---------------------------------------------------------------- あがれる？


WIN_YES, WIN_NO_YAKU, WIN_NO_SHAPE, WIN_FURITEN = "win", "no_yaku", "no_shape", "furiten"
_WIN_CHOICES = (
    Choice(WIN_YES, "あがれる"),
    Choice(WIN_NO_YAKU, "役がないので、あがれない"),
    Choice(WIN_NO_SHAPE, "あがりの形になっていない"),
    Choice(WIN_FURITEN, "フリテンなので、ロンできない"),
)
_WIN_WEIGHTS = ((WIN_YES, 34), (WIN_NO_YAKU, 30), (WIN_FURITEN, 20), (WIN_NO_SHAPE, 16))


def _waits_of(ctx: WinContext) -> tuple[int, ...]:
    """あがり牌を除いた手（聴牌形）の待ち"""
    hand = list(ctx.closed_tiles)
    hand.remove(ctx.win_tile)
    return wait_kinds(hand)


def furiten_kinds(ctx: WinContext, river: Sequence[int]) -> tuple[int, ...]:
    """自分の河にある待ち牌（種類）。1 つでもあればフリテン"""
    waits = set(_waits_of(ctx))
    return tuple(sorted({kind_of(t) for t in river} & waits))


def win_class(ctx: WinContext, river: Sequence[int], rules: Rules = DEFAULT_RULES) -> str:
    """その牌であがりを宣言できるか（WIN_YES / WIN_NO_YAKU / WIN_NO_SHAPE / WIN_FURITEN）"""
    status = explain(ctx, rules).status
    if status is Status.NOT_WINNING:
        return WIN_NO_SHAPE
    if status is Status.NO_YAKU:
        return WIN_NO_YAKU
    if not ctx.is_tsumo and furiten_kinds(ctx, river):
        return WIN_FURITEN
    return WIN_YES


def _bare(ctx: WinContext, *, tsumo: bool, riichi: bool = False) -> WinContext:
    """同じ手で、状況の役（一発・嶺上開花など）を外したもの"""
    return WinContext(
        closed_tiles=ctx.closed_tiles, win_tile=ctx.win_tile, is_tsumo=tsumo, seat_wind=ctx.seat_wind, round_wind=ctx.round_wind,
        melds=ctx.melds, riichi=riichi and ctx.is_menzen, dora_indicators=ctx.dora_indicators,
    )


def _opened(ctx: WinContext, rng: Rng, *, tsumo: bool) -> WinContext | None:
    """門前の面子を 1〜2 組、鳴いた面子（チー・ポン）に変えたもの。変えられる面子が無ければ None"""
    result = explain(_bare(ctx, tsumo=True))            # 門前のツモなら必ず役がある（読み方を 1 つ得るため）
    if not result.candidates:
        return None
    interp = result.candidates[0].interp
    if interp.form is not Form.REGULAR:
        return None
    groups = block_tiles(interp, ctx)
    free = [
        index for index, block in enumerate(interp.blocks)
        if block.type in (BlockType.SHUNTSU, BlockType.KOUTSU) and not block.open and index != interp.win_index
    ]
    if not free:
        return None
    rng.shuffle(free)
    count = 1 if len(free) == 1 or rng.chance(0.6) else 2
    melds = list(ctx.melds)
    closed = list(ctx.closed_tiles)
    for index in free[:count]:
        tiles = groups[index]
        kind = MeldType.CHI if interp.blocks[index].type is BlockType.SHUNTSU else MeldType.PON
        melds.append(Meld(kind, tuple(tiles)))
        for tile in tiles:
            closed.remove(tile)
    return WinContext(
        closed_tiles=tuple(closed), win_tile=ctx.win_tile, is_tsumo=tsumo, seat_wind=ctx.seat_wind, round_wind=ctx.round_wind,
        melds=tuple(melds), dora_indicators=ctx.dora_indicators,
    )


def _broken(ctx: WinContext, rng: Rng) -> WinContext | None:
    """あがり牌を、待ちのとなりの牌に取りかえたもの（あがりの形にならない）"""
    hand = list(ctx.closed_tiles)
    hand.remove(ctx.win_tile)
    waits = set(wait_kinds(hand))
    used = {*ctx.all_tiles, *ctx.dora_indicators}
    near: list[int] = []
    for wait in sorted(waits):
        if wait >= 27:
            near += [k for k in range(27, NUM_KINDS) if k not in waits]
            continue
        for step in (-2, -1, 1, 2):
            kind = wait + step
            if 0 <= kind < 27 and kind // 9 == wait // 9 and kind not in waits:
                near.append(kind)
    kinds = [k for k in dict.fromkeys(near) if _free_tile(k, used) is not None]
    if not kinds:
        return None
    tile = _free_tile(rng.choice(kinds), used)
    assert tile is not None
    return WinContext(
        closed_tiles=(*hand, tile), win_tile=tile, is_tsumo=ctx.is_tsumo, seat_wind=ctx.seat_wind, round_wind=ctx.round_wind,
        melds=ctx.melds, riichi=ctx.riichi, dora_indicators=ctx.dora_indicators,
    )


def _river(ctx: WinContext, rng: Rng, *, furiten: bool) -> tuple[int, ...] | None:
    """自分の河を作る（6〜12 枚）。待ち牌は入れない。furiten のときだけ、待ち牌を 1 枚まぜる"""
    used = {*ctx.all_tiles, *ctx.dora_indicators}
    waits = set(_waits_of(ctx))
    # 字牌と端の牌を多めにする（実際の河に近づける）
    pool = [k for k in range(NUM_KINDS) if k not in waits for _ in range(3 if is_yaochu_kind(k) else 1)]
    river: list[int] = []
    size = 6 + rng.below(7)
    for _ in range(size * 6):
        if len(river) >= size:
            break
        tile = _free_tile(rng.choice(pool), used)
        if tile is not None:
            used.add(tile)
            river.append(tile)
    if furiten:
        kinds = [k for k in sorted(waits) if _free_tile(k, used) is not None]
        others = [k for k in kinds if k != ctx.win_kind]
        if not kinds:
            return None
        # あがり牌とは別の待ち牌が河にある形（見落としやすい）を多めにする
        kind = rng.choice(others) if others and rng.chance(0.6) else rng.choice(kinds)
        tile = _free_tile(kind, used)
        assert tile is not None
        river.insert(rng.below(len(river) + 1), tile)
    return tuple(river)


def _win_attempt(rng: Rng, wanted: str, token: str) -> tuple[WinContext, tuple[int, ...]] | None:
    """問題の候補を 1 つ作る →（あがりの状況, 自分の河）。作れなければ None"""
    base = random_win(token, rng.choice(("menzen", "menzen", "any", "open")))
    try:
        if wanted == WIN_NO_YAKU:
            if base.is_menzen and rng.chance(0.5):
                ctx = _bare(base, tsumo=False)
            else:
                ctx = _opened(base, rng, tsumo=rng.chance(0.4))
            return None if ctx is None else _with_river(ctx, rng, furiten=False)
        if wanted == WIN_FURITEN:
            ctx = _bare(base, tsumo=False, riichi=rng.chance(0.5)) if rng.chance(0.7) else _opened(base, rng, tsumo=False)
            return None if ctx is None else _with_river(ctx, rng, furiten=True)
        if wanted == WIN_NO_SHAPE:
            start = _bare(base, tsumo=rng.chance(0.3), riichi=rng.chance(0.4)) if rng.chance(0.7) else _opened(base, rng, tsumo=rng.chance(0.3))
            if start is None:
                return None
            ctx = _broken(start, rng)
            return None if ctx is None else _with_river(ctx, rng, furiten=False)
        # あがれる手：いろいろな形を混ぜる
        variant = _weighted(rng, (("tsumo", 30), ("open", 25), ("ron", 20), ("furiten_tsumo", 15), ("riichi", 10)))
        if variant == "tsumo":
            return _with_river(_bare(base, tsumo=True), rng, furiten=False)
        if variant == "open":
            ctx = _opened(base, rng, tsumo=rng.chance(0.4))
            return None if ctx is None else _with_river(ctx, rng, furiten=False)
        if variant == "ron":
            return _with_river(_bare(base, tsumo=False), rng, furiten=False)
        if variant == "furiten_tsumo":
            return _with_river(_bare(base, tsumo=True, riichi=rng.chance(0.5)), rng, furiten=True)
        return _with_river(_bare(base, tsumo=False, riichi=True), rng, furiten=False)
    except ContextError:
        return None


def _with_river(ctx: WinContext, rng: Rng, *, furiten: bool) -> tuple[WinContext, tuple[int, ...]] | None:
    river = _river(ctx, rng, furiten=furiten)
    return None if river is None else (ctx, river)


def _win_question(item: str) -> Question:
    number = _number(item)
    rng = Rng(item, "drill:win")
    wanted = _weighted(rng, _WIN_WEIGHTS)
    for attempt in range(400):
        made = _win_attempt(rng, wanted, f"win:{number}:{attempt}")
        if made is not None and win_class(*made) == wanted:
            ctx, river = made
            break
    else:
        raise RuntimeError(f"「あがれる？」の問題を作れませんでした: {item!r}")
    result = explain(ctx)
    call = _how(ctx.is_tsumo)
    waits = _waits_of(ctx) if wanted != WIN_NO_SHAPE else ()
    in_river = furiten_kinds(ctx, river)
    names = "・".join(kind_text(k) for k in in_river)
    answer: list[str] = []
    if wanted == WIN_YES:
        best = result.best
        assert best is not None
        answer.append(f"あがれる。役は、{'・'.join(y.name for y in best.evaluation.yaku)}。申告は「{result.declaration}」")
        if in_river:
            answer.append(f"自分の河に待ち牌の {names} があるのでフリテンだが、フリテンでも、ツモならあがれる（できないのはロンだけ）。")
    elif wanted == WIN_NO_YAKU:
        answer.append("あがりの形にはなっているが、役が 1 つも無いので、あがれない。")
        answer += list(result.advice)
    elif wanted == WIN_NO_SHAPE:
        hand = list(ctx.closed_tiles)
        hand.remove(ctx.win_tile)
        real = "・".join(kind_text(k) for k in wait_kinds(hand))
        answer.append(f"{kind_text(ctx.win_kind)} では、あがりの形（4 面子 1 雀頭）にならない。この手の待ちは、{real}。")
        answer.append("あがりの形でないのに「ロン」「ツモ」と言って手を倒すと、チョンボ（反則）になる。発声の前に、待ちをもう一度確かめる。")
    else:
        all_waits = "・".join(kind_text(k) for k in waits)
        answer.append(f"自分の河に、待ち牌の {names} がある（フリテン）。この手の待ちは {all_waits}。")
        answer.append("フリテンのときは、どの待ち牌でもロンできない（河にある牌とは別の待ち牌でも、できない）。ツモならあがれる。")
        answer.append("フリテンには、ほかに「同じ巡のうちに見逃した牌がある」「リーチのあとに見逃した」ときもある。")
    return Question(
        "win", item, f"この牌で「{call}」と言える？", _WIN_CHOICES, frozenset({wanted}),
        note="手牌・あがり牌・自分の河を見て判断する。", answer=tuple(answer), ctx=ctx, river=river,
    )


# ---------------------------------------------------------------- 待ち


def _wait_reason(hand: Sequence[int], kind: int, ctx: WinContext) -> str:
    """その牌が来たときの、待ちの形（例：45萬 で 3萬・6萬 を待つ両面待ち）"""
    tile = _free_tile(kind, set(hand))
    if tile is None:
        return ""
    try:
        made = WinContext(
            closed_tiles=(*hand, tile), win_tile=tile, is_tsumo=True, seat_wind=ctx.seat_wind, round_wind=ctx.round_wind, riichi=True,
        )
    except ContextError:
        return ""
    result = explain(made)
    if not result.candidates:
        return ""
    return wait_text(result.candidates[0].interp, kind)


def _wait_question(item: str) -> Question:
    number = _number(item)
    rng = Rng(item, "drill:wait")
    for attempt in range(200):
        ctx = random_win(f"wait:{number}:{attempt}", "menzen")
        if ctx.melds:
            continue
        hand = list(ctx.closed_tiles)
        hand.remove(ctx.win_tile)
        counts = counts34(hand)
        waits = wait_kinds(hand)
        if 1 <= len(waits) <= 5 and all(counts[k] < 4 for k in waits):
            break
    else:
        raise RuntimeError(f"待ちの問題を作れませんでした: {item!r}")
    hand = sort_tiles(hand)

    def distance(kind: int) -> int:
        return min((abs(kind - w) for w in waits if w < 27 and kind < 27 and w // 9 == kind // 9), default=9)

    pool: set[int] = set()
    for kind in range(NUM_KINDS):
        if kind in waits or counts[kind] >= 4:
            continue
        near_hand = counts[kind] > 0 or (kind < 27 and any(0 <= o < 27 and o // 9 == kind // 9 and counts[o] for o in (kind - 1, kind + 1)))
        if distance(kind) <= 3 or near_hand:
            pool.add(kind)
    order = [int(k) for k in _shuffled(rng, [str(k) for k in sorted(pool)])]
    beside = [k for k in order if distance(k) <= 2]                 # 待ち牌のとなり
    elsewhere = [k for k in order if distance(k) > 2]               # 手牌のほかの部分のそば
    mixed: list[int] = []
    for index in range(len(order)):                                 # 2 つを交互に混ぜる
        mixed += beside[index:index + 1] + elsewhere[index:index + 1]
    wanted = max(6, min(9, len(waits) + 4))
    kinds = sorted([*waits, *mixed[: wanted - len(waits)]])
    choices = tuple(
        Choice(str(k), kind_text(k), _wait_reason(hand, k, ctx) if k in waits else "", tile=k) for k in kinds
    )
    names = "・".join(kind_text(k) for k in waits)
    answer = (f"待ちは、{names}（{len(waits)} 種）。",)
    return Question(
        "wait", item, "この手の待ち牌を、すべて選ぶ", choices, frozenset(str(k) for k in waits), multi=True,
        note="あと 1 枚であがりの形になる牌を、すべて。役があるかどうかは問わない。", answer=answer, hand=tuple(hand),
    )


# ---------------------------------------------------------------- 何切る


def _discard_question(item: str) -> Question:
    number = _number(item)
    rng = Rng(item, "drill:discard")
    for attempt in range(60):
        config = practice.PracticeConfig(seed=number * 100 + attempt, luck=LuckSettings(50, 0))
        state = practice.start(config)
        usable = True
        for _ in range(rng.below(7)):           # 0〜6 巡、おすすめどおりに進めた局面にする
            if state.finished or state.can_tsumo:
                usable = False
                break
            pick = analyze(practice.position_of(state)).pick
            state = practice.apply(state, practice.discard(pick.tile))
        if not usable or state.finished or state.can_tsumo:
            continue
        position = replace(practice.position_of(state), can_riichi=False)       # リーチするかどうかは、ここでは問わない
        analysis = analyze(position)
        if analysis.can_win or analysis.last_discard or len(analysis.best) == len(analysis.candidates):
            continue                            # どれを切っても同じ局面は、問題にならない
        if any(candidate.dora for candidate in analysis.best):
            continue                            # ドラを切るのが正解になる局面は、出さない（速さだけの問題で、打点を捨てる癖を付けないため）
        break
    else:
        raise RuntimeError(f"何切るの問題を作れませんでした: {item!r}")
    pick = analysis.pick
    width = "待ち" if pick.shanten == 0 else "受け入れ"
    answer = [f"いちばん速いのは、{kind_text(pick.kind)}切り（{shanten_text(pick.shanten)}・{width} {pick.kinds} 種 {pick.total} 枚）。"]
    same = [kind_text(c.kind) for c in analysis.best if not c.is_pick]
    if same:
        answer.append(f"{'・'.join(same)}切りも、同じ速さ。")
    return Question(
        "discard", item, "何を切る？", (), frozenset(str(c.kind) for c in analysis.best),
        note="速さ（向聴数と、受け入れの枚数）だけで比べる。役や打点、守りは考えない。", answer=tuple(answer),
        river=tuple(state.discards), position=position,
    )


# ---------------------------------------------------------------- 役の翻数


def han_label(page: YakuPage) -> str:
    """役の翻数の書き方（例：2 翻（鳴くと 1 翻）、1 翻（門前限定）、役満（鳴いても成立））"""
    info = YAKU[page.yaku[0]]
    if info.yakuman:
        return "役満（門前限定）" if info.closed_only else "役満（鳴いても成立）"
    if info.closed_only:
        return f"{info.han_closed} 翻（門前限定）"
    if info.kuisagari:
        return f"{info.han_closed} 翻（鳴くと {info.han_open} 翻）"
    return f"{info.han_closed} 翻（鳴いても同じ）"


def _han_rank(label: str) -> tuple[int, int]:
    han = 13 if label.startswith("役満") else int(label.split(" ")[0])
    mode = 0 if "門前限定" in label else (1 if "鳴くと" in label else 2)
    return (han, mode)


@cache
def _han_items() -> dict[str, YakuPage]:
    return {f"h:{page.key}": page for page in yaku_pages() if page.yaku}


def _han_question(item: str) -> Question:
    page = _han_items().get(item)
    if page is None:
        raise ValueError(f"役の翻数に無い問題です: {item!r}")
    label = han_label(page)
    labels = sorted({han_label(p) for p in _han_items().values()}, key=_han_rank)
    han = _han_rank(label)[0]
    rng = Rng(item, "drill:han")
    others = _shuffled(rng, [text for text in labels if text != label])
    # 近いもの（翻数が同じで鳴いたときの扱いが違う／扱いが同じで翻数が 1 つ違う）を先に

    def gap(text: str) -> int:
        other = _han_rank(text)[0]
        return 3 if (other == 13) != (han == 13) else abs(other - han)       # 役満とふつうの役は、遠いものとして扱う

    others.sort(key=gap)        # 翻数が同じで、鳴いたときの扱いだけが違うものを先に
    picks = others[:3]
    choices = tuple(Choice(text, text) for text in sorted([label, *picks], key=_han_rank))
    answer = [f"{page.name}は、{label}。", page.short]
    doubles = [YAKU[key].name for key in page.yaku if YAKU[key].yakuman == 2]
    if doubles:
        answer.append(f"{'・'.join(doubles)}をダブル役満（役満 2 つぶん）にするかどうかは、ルールによって異なる。")
    if page.key == "tanyao":
        answer.append("鳴いた断么九（喰いタン）を認めないルールもある（ルールによって異なる）。")
    return Question(
        "han", item, f"「{page.name}」は何翻？", choices, frozenset({label}),
        note="門前限定は、鳴くと付かない役。「鳴くと 1 翻」などは、鳴くと翻が下がる役（喰い下がり）。",
        answer=tuple(answer), page=page.key,
    )


# ---------------------------------------------------------------- 用語の読み


#: ふだんの言葉と同じ読みなので、読みの問題にしない用語
_PLAIN_TERMS = frozenset({"山", "親", "子", "局", "筋", "壁", "腰", "基本点", "点棒", "強打", "発声", "三味線", "現物", "高目"})


def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or ch == "々"


@cache
def _reading_items() -> dict[str, tuple[str, str, str, str]]:
    """問題の鍵 →（言葉, 読み, まとまり, 意味）"""
    items: dict[str, tuple[str, str, str, str]] = {}
    for term in glossary().terms:
        if term.term in _PLAIN_TERMS or not all(_is_kanji(ch) for ch in term.term):
            continue                            # かなの入った言葉は、読みで迷わない
        items[f"t:{term.term}"] = (term.term, term.reading, term.category, term.meaning)
    for page in yaku_pages():
        if any(_is_kanji(ch) for ch in page.name):
            items[f"y:{page.key}"] = (page.name, page.reading.replace(" ", ""), "yaku", page.short)
    return items


def _first_sentence(text: str) -> str:
    head = text.split("。")[0]
    return head + "。" if head else text


def _reading_question(item: str) -> Question:
    items = _reading_items()
    if item not in items:
        raise ValueError(f"用語の読みに無い問題です: {item!r}")
    word, reading, group, meaning = items[item]
    rng = Rng(item, "drill:reading")
    used = {reading}
    picks: list[tuple[str, str]] = []
    others = _shuffled(rng, [key for key in items if key != item])
    # 同じまとまりの言葉（まぎらわしい）を先に、その中では読みの長さが近いものを先に
    others.sort(key=lambda key: (items[key][2] != group, min(2, abs(len(items[key][1]) - len(reading)) // 2)))
    for key in others:
        other_word, other_reading = items[key][0], items[key][1]
        if other_reading in used:
            continue
        used.add(other_reading)
        picks.append((other_reading, f"「{other_word}」の読み"))
        if len(picks) >= 3:
            break
    choices = [Choice(reading, reading), *(Choice(text, text, why) for text, why in picks)]
    rng.shuffle(choices)
    answer = (f"{word}（{reading}）：{_first_sentence(meaning)}",)
    return Question(
        "reading", item, f"「{word}」の読みは？", tuple(choices), frozenset({reading}), answer=answer,
        page=item[2:] if item.startswith("y:") else "", term=word if item.startswith("t:") else "",
    )


# ---------------------------------------------------------------- 入口


_FINITE = {
    "table": lambda: _table_items(),
    "valid": lambda: tuple(_valid_items()),
    "han": lambda: tuple(_han_items()),
    "reading": lambda: tuple(_reading_items()),
}
_MAKERS = {
    "table": _table_question,
    "score": _score_question,
    "fu": _fu_question,
    "yaku": _yaku_question,
    "valid": _valid_question,
    "win": _win_question,
    "wait": _wait_question,
    "discard": _discard_question,
    "han": _han_question,
    "reading": _reading_question,
}


def items_of(kind: str) -> tuple[str, ...]:
    """決まった数の問題がある種類の、すべての問題の鍵（その場で作る種類は空）"""
    if kind not in KINDS:
        raise ValueError(f"ドリルの種類は {list(KINDS)} のどれかです: {kind!r}")
    maker = _FINITE.get(kind)
    return maker() if maker is not None else ()


def is_item(kind: str, item: object) -> bool:
    """その種類の問題の鍵として正しいか（保存してあった記録には、いまは無い問題の鍵が残っていることがある）"""
    if kind not in KINDS or not isinstance(item, str):
        return False
    if KINDS[kind].finite:
        return item in items_of(kind)
    return item.isascii() and item.isdigit() and len(item) <= len(str(MAX_NUMBER))


def new_item(kind: str, pick: int) -> str:
    """その場で作る種類の、新しい問題の鍵（pick は乱数）"""
    if kind not in KINDS or KINDS[kind].finite:
        raise ValueError(f"その場で作る種類ではありません: {kind!r}")
    return str(pick % (MAX_NUMBER + 1))


@lru_cache(maxsize=512)
def question(kind: str, item: str) -> Question:
    """問題を作る。同じ種類・同じ鍵なら、いつでも同じ問題。知らない鍵なら ValueError"""
    if kind not in _MAKERS:
        raise ValueError(f"ドリルの種類は {list(KINDS)} のどれかです: {kind!r}")
    return _MAKERS[kind](item)


REVIEW, NEW, DONE = "review", "new", "done"


def next_item(kind: str, deck: Deck, now: int, *, pick: int, skip: Collection[str] = ()) -> tuple[str | None, str]:
    """次に出す問題 →（鍵, 理由）。

    復習の時刻になった問題（REVIEW）が先。無ければ、まだ出していない問題・新しく作る問題（NEW）。
    決まった数の問題をすべて出し終えていて、復習の時刻になった問題も無ければ（None, DONE）。
    """
    for item in deck.due(now, skip):
        if is_item(kind, item):
            return (item, REVIEW)
    if not KINDS[kind].finite:
        return (new_item(kind, pick), NEW)
    unseen = [item for item in items_of(kind) if item not in deck.cards and item not in skip]
    if unseen:
        return (Rng(pick, f"drill:{kind}:new").choice(unseen), NEW)
    return (None, DONE)


def early_item(kind: str, deck: Deck, skip: Collection[str] = ()) -> str | None:
    """先取りで復習する問題：次に出す時刻がいちばん近いもの（覚えていない問題から）"""
    cards = [(card.box, card.due, item) for item, card in deck.cards.items() if item not in skip and is_item(kind, item)]
    return min(cards)[2] if cards else None


@dataclass(frozen=True)
class DrillProgress:
    answered: int               # 答えた回数
    right: int                  # 正解した回数
    due: int                    # 復習の時刻になっている問題の数
    waiting: int                # 復習待ち（まだ時刻になっていない）の問題の数
    total: int | None           # 問題の数（その場で作る種類は None）
    seen: int = 0               # 1 回以上出した問題の数（決まった数の問題がある種類だけ）
    learned: int = 0            # 定着した問題の数（同上）
    next_due: int | None = None # 次の復習の時刻（復習待ちが無ければ None）

    @property
    def accuracy(self) -> float | None:
        return self.right / self.answered if self.answered else None


def progress_of(kind: str, deck: Deck, now: int) -> DrillProgress:
    """ドリル 1 種類の進み具合"""
    cards = {item: card for item, card in deck.cards.items() if is_item(kind, item)}
    due = sum(1 for card in cards.values() if card.due <= now)
    later = [card.due for card in cards.values() if card.due > now and card.box < MAX_BOX]
    finite = KINDS[kind].finite
    return DrillProgress(
        answered=deck.answered,
        right=deck.right,
        due=due,
        waiting=len(later),
        total=len(items_of(kind)) if finite else None,
        seen=len(cards) if finite else 0,
        learned=sum(1 for card in cards.values() if card.box >= LEARNED_BOX) if finite else 0,
        next_due=min(later) if later else None,
    )

"""エンジンの計算結果を、AI に渡す「事実」の文と、よくある質問（テンプレートの答えつき）にする。

AI には、ここで作った文だけを渡す（自分で計算・判定させない）。返ってきた文は、同じ文と照らし合わせる（check.py）。
だから、ここに書く数・牌・役の名前は、すべてエンジンの値そのもの。文の形は、人が読んでも分かるようにする。

よくある質問（Suggestion）の答えは、同じ事実の文をつないだもの。AI のキーが無いときは、これをそのまま見せる
（仕様の「キーが無くても、テンプレート解説で全機能が動くこと」）。キーがあれば、AI がこれを分かりやすく言い直す。

    win_facts(explanation)                 あがった手（役・符・点数の式・支払い・申告）
    turn_facts(hand, seat, advice)         対局で自分が切る番（手牌・河・向聴数・候補・おすすめ・守備・リーチの比べ方）
    call_facts(hand, seat, advice)         対局で鳴ける牌が出たとき（見送る・鳴き方ごとの見込み）
    practice_facts(state, analysis)        一人練習で切る番
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from engine.analysis.ukeire import draw_chance
from engine.call_coach import CallAdvice, CallDecision, CallOption, YakuStatus, call_name
from engine.coach import Analysis, Candidate, Position, Verdict
from engine.content import table_guide
from engine.defense import LEVEL_NAMES, SHAPE_NAMES, TileDanger, summary
from engine.game import SEAT_NAMES, HandState, Player
from engine.game_coach import RiichiView, Stance, TurnAdvice, TurnDecision
from engine.melds import Meld, MeldType
from engine.practice import Decision as PracticeDecision
from engine.practice import PracticeState
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.decompose import Form
from engine.scoring.dora import dora_kind_of
from engine.scoring.explain import Explanation, Status
from engine.scoring.points import calculate_points
from engine.scoring.texts import kind_text, kinds_text, wait_text
from engine.scoring.yaku_eval import YakuResult
from engine.target_coach import TargetAdvice, block_text
from engine.tiles import EAST, is_red, kind_of, sort_tiles
from engine.yaku_table import YAKUMAN_HAN

WIND_NAMES = {27: "東", 28: "南", 29: "西", 30: "北"}
#: 受け入れの牌を 1 種類ずつ書くのは、この種類数まで（多いと読みにくく、AI が全部を数え上げてしまう）
DETAIL_KINDS = 10
#: 打牌の候補を書く数
CANDIDATES = 6
#: 牌の種類の数（おすすめの有効牌は、種類が多くてもすべて書く）
ALL_KINDS = 34
STANCE_WORDS = {Stance.FREE: "自由に打つ（リーチを受けていない）", Stance.PUSH: "押す（聴牌を保ってあがりを目指す）", Stance.FOLD: "オリる（守る）"}
STATUS_WORDS = {
    YakuStatus.SECURED: "役が確定",
    YakuStatus.ON_PATH: "役の見込みあり（遠回りせずに作れる）",
    YakuStatus.RIICHI: "門前なので、聴牌すればリーチで役が付く",
    YakuStatus.DETOUR: "役まで遠回り",
    YakuStatus.NONE: "役が見えない（このままでは、あがれない）",
}
MELD_WORDS = {MeldType.CHI: "チー", MeldType.PON: "ポン", MeldType.ANKAN: "暗槓", MeldType.MINKAN: "大明槓", MeldType.KAKAN: "加槓"}


@dataclass(frozen=True)
class Suggestion:
    """よくある質問 1 つと、エンジンの事実をつないだ答え（テンプレート）"""

    key: str                        # 質問の種類（例：why）
    question: str                   # ボタンに出す質問（例：なぜ白を切るの？）
    answer: tuple[str, ...]         # テンプレートの答え（1 行ずつ）

    @property
    def text(self) -> str:
        return "\n".join(self.answer)


#: どの局面にも付ける、一般的な決まりの見出し（ここに出てくる数は、その局面の値ではない）
GENERAL_SECTIONS = frozenset({"このアプリのルール", "基本", "点数の決まり"})


@dataclass(frozen=True)
class Facts:
    """AI に渡す事実（見出しと、その下の文）と、よくある質問"""

    context: str                                            # win・turn・call・practice
    title: str                                              # 何の局面か（例：あがりの解説）
    sections: tuple[tuple[str, tuple[str, ...]], ...]       # （見出し, 文）
    suggestions: tuple[Suggestion, ...] = ()
    rules: Rules = DEFAULT_RULES

    @property
    def text(self) -> str:
        lines = [f"# {self.title}"]
        for head, body in self.sections:
            lines.append(f"【{head}】")
            lines.extend(body)
        return "\n".join(lines)

    @property
    def point_text(self) -> str:
        """その局面だけの事実の文（一般的な決まりの見出しを除く）。照らし合わせで、単位の無い数を「点」と認めるのは、ここに出てくる数だけ"""
        return "\n".join(line for head, body in self.sections if head not in GENERAL_SECTIONS for line in body)

    @property
    def key(self) -> str:
        """同じ事実かどうかを見分ける鍵（同じ質問の答えを、何度も呼ばずに使い回すため）"""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def suggestion(self, key: str) -> Suggestion | None:
        return next((s for s in self.suggestions if s.key == key), None)


def _on(flag: bool) -> str:
    return "あり" if flag else "なし"


def _basics(rules: Rules) -> tuple[str, ...]:
    """どの局面にも付ける、基本の決まり（数を含む一般的な説明を、AI が使えるようにする）"""
    red = "（このアプリでは、5萬・5筒・5索 のうち 1 枚ずつが赤 5 で、赤 5 は 1 枚ごとに 1 翻のドラになる）" if rules.aka_dora else ""
    return (
        f"牌は 34 種類で、同じ牌が 4 枚ずつ、全部で 136 枚ある{red}。",
        "手牌は 13 枚で、ツモると 14 枚になる。鳴いた面子は 3 枚（カンは 4 枚）。",
        "あがりの形は、4 面子 1 雀頭。例外は 2 つ：七対子（7 種類の対子）と、国士無双（13 種類の么九牌を 1 枚ずつと、そのうち 1 種類をもう 1 枚）。",
        "役が 1 つ以上ないと、あがれない（ドラだけでは、あがれない）。",
        "リーチは、門前（暗槓だけなら門前のまま）で聴牌していて、このあと自分のツモが残っているときに宣言できる"
        "（対局では、持ち点が 1,000 点以上あり、山が 4 枚以上残っていることも条件。このアプリは雀魂に合わせた条件で、ルールによって異なる）。"
        "宣言した牌でロンされなければ、1,000 点（リーチ棒）を卓に出す。",
        "向聴数は、聴牌まであと何枚の有効牌が要るか（1 向聴なら、あと 1 枚で聴牌）。聴牌は、あと 1 枚であがれる形。",
        "有効牌は、引くと向聴数が進む牌（聴牌なら、あがり牌）。受け入れ枚数は、有効牌のうち見えていない枚数の合計。",
    )


def _rule_lines(rules: Rules, *, game: bool) -> tuple[str, ...]:
    """このアプリで使っているルール（ルールによって異なるところ）"""
    lines = [
        f"赤ドラ：{_on(rules.aka_dora)}。喰いタン（鳴いた断么九）：{_on(rules.kuitan)}。切り上げ満貫：{_on(rules.kiriage_mangan)}。",
        f"連風牌（場風と自風が同じ風牌）の雀頭：{rules.double_wind_pair_fu} 符。数え役満：{_on(rules.kazoe_yakuman)}。ダブル役満：{_on(rules.double_yakuman)}。",
    ]
    if game:
        lines.append(
            f"鳴き：{_on(rules.calls)}。2 人以上が同じ牌でロンしたとき：{'全員のあがり' if rules.multiple_ron else '頭ハネ'}。"
            f"途中流局：{_on(rules.abortive_draws)}。流し満貫：{_on(rules.nagashi_mangan)}。飛び：{_on(rules.tobi)}。"
        )
    lines.append("どれも、ルールによって異なる（このアプリの設定は、雀魂の段位戦が初期値）。")
    return tuple(lines)


def _facts(
    context: str, title: str, sections: Iterable[tuple[str, Sequence[str]]], rules: Rules,
    suggestions: Iterable[Suggestion] = (), *, game: bool = False,
) -> Facts:
    kept = tuple((head, tuple(body)) for head, body in sections if body)
    tail = (("このアプリのルール", _rule_lines(rules, game=game)), ("基本", _basics(rules)))
    found = tuple(s for s in suggestions if s.answer)
    return Facts(context, title, (*kept, *tail), found, rules)


def _tile(tile: int, aka: bool = True) -> str:
    return ("赤" if is_red(tile, aka=aka) else "") + kind_text(kind_of(tile))


#: 字牌の読み（質問のボタンに添える。「中」を「なか」と読まないように）
HONOR_READINGS = {27: "トン", 28: "ナン", 29: "シャー", 30: "ペー", 31: "ハク", 32: "ハツ", 33: "チュン"}


def _spoken(tile: int, aka: bool = True) -> str:
    """質問のボタンに出す牌の名前（字牌は、読みを添える。例：中（チュン））"""
    reading = HONOR_READINGS.get(kind_of(tile))
    return _tile(tile, aka) + (f"（{reading}）" if reading else "")


def _tiles(tiles: Iterable[int], aka: bool = True) -> str:
    return "・".join(_tile(t, aka) for t in sort_tiles(tiles))


def _count(kinds: Iterable[tuple[int, int]]) -> str:
    return "・".join(f"{kind_text(kind)}（残り {count} 枚）" for kind, count in kinds)


def _stage(shanten: int) -> str:
    return "聴牌" if shanten == 0 else ("あがりの形" if shanten < 0 else f"{shanten} 向聴")


def _round(hand: HandState) -> str:
    start = hand.start
    return f"{WIND_NAMES[start.round_wind]}{start.round_number}局 {start.honba} 本場"


def _name(seat: int, viewer: int) -> str:
    """席の呼び方（見ている人から見て：自分・下家・対面・上家）"""
    return SEAT_NAMES[(seat - viewer) % 4]


def _meld_list(melds: Iterable[Meld], aka: bool = True) -> str:
    """副露の書き方（例：ポン 888萬・チー 678筒（赤5を含む））"""
    items = []
    for meld in melds:
        red = "（赤5を含む）" if any(is_red(t, aka=aka) for t in meld.tiles) else ""
        items.append(f"{MELD_WORDS[meld.type]} {kinds_text(sorted(kind_of(t) for t in meld.tiles))}{red}")
    return "・".join(items)


def _melds(player: Player, aka: bool = True) -> str:
    return _meld_list(player.melds, aka)


def _meld_lines(melds: Sequence[Meld], aka: bool = True, *, mine: bool = True) -> list[str]:
    """副露（チー・ポン・明槓）と暗槓を分けて書く。暗槓は鳴きではないので、暗槓だけなら門前のまま（リーチもできる）"""
    open_melds = [m for m in melds if m.type is not MeldType.ANKAN]
    closed = [m for m in melds if m.type is MeldType.ANKAN]
    lines = []
    if open_melds:
        lines.append(f"副露：{_meld_list(open_melds, aka)}" + ("（鳴いているので、リーチはできない）。" if mine else "。"))
    if closed:
        lines.append(f"暗槓：{_meld_list(closed, aka)}（暗槓は鳴きではない" + ("。ほかに鳴いていなければ門前のままで、リーチもできる）。" if mine else "）。"))
    return lines


def _acceptance(live: Sequence[tuple[int, int]], limit: int = DETAIL_KINDS) -> str:
    """有効牌の書き方（種類が多いときは書かない）"""
    if not live or len(live) > limit:
        return ""
    return f"（{_count(live)}）"


def _candidate_line(candidate: Candidate, *, limit: int = DETAIL_KINDS) -> str:
    """打牌の候補 1 つ（例：白切り：聴牌・待ち 2 種 3 枚（東（残り 1 枚）・南（残り 2 枚））"""
    width = "待ち" if candidate.shanten == 0 else "受け入れ"
    text = f"{kind_text(candidate.kind)}切り：{_stage(candidate.shanten)}・{width} {candidate.kinds} 種 {candidate.total} 枚"
    if candidate.total == 0:
        return text + ("（待ち牌が 1 枚も残っていない）" if candidate.shanten == 0 else "（有効牌が 1 枚も残っていない）")
    return text + _acceptance(candidate.option.acceptance.live, limit)


def _bullets(lines: Iterable[str]) -> list[str]:
    return [f"・{line}" for line in lines]


def _chance_line(total: int, unseen: int) -> str:
    chance = round(draw_chance(total, unseen) * 100)
    return f"次のツモで有効牌を引く確率は {chance}%（有効牌 {total} 枚 ÷ 見えていない牌 {unseen} 枚。補正なしの麻雀での値）。"


# ---------------------------------------------------------------- あがり


def _yaku_han(item: YakuResult) -> str:
    if item.is_yakuman:
        return "役満" if item.han == YAKUMAN_HAN else f"役満 × {item.han // YAKUMAN_HAN}"
    return f"{item.han} 翻"


def _say_lines() -> list[str]:
    """申告のしかた（「卓で打つとき」のページと同じ内容）"""
    section = next((s for s in table_guide().sections if s.key == "win"), None)
    if section is None:
        return []
    return [section.summary, *(line for line in (*section.steps, *section.points) if "言う" in line)]


#: 満貫以上の呼び名と、その代表の翻数・役満の倍数
LEVEL_EXAMPLES = (("満貫", 5, 0), ("跳満", 6, 0), ("倍満", 8, 0), ("三倍満", 11, 0), ("役満", 13, 1))


def level_table(rules: Rules) -> str:
    """満貫以上のロンの点（子／親）。エンジンで計算する"""
    parts = []
    for name, han, times in LEVEL_EXAMPLES:
        child, dealer = (
            calculate_points(han, 30, yakuman_times=times, is_dealer=dealer, is_tsumo=False, honba=0, kyotaku=0, rules=rules).total
            for dealer in (False, True)
        )
        parts.append(f"{name} {child:,} 点／{dealer:,} 点")
    return "満貫以上のロンの点（子／親）：" + "・".join(parts) + "。"


def win_summary(explanation: Explanation, *, total: bool = True) -> str:
    """あがりを 1 行で（例：立直・平和・断么九。30 符 3 翻。受け取る点の合計 3,900 点）。あがれなければ空。total が偽なら、点の合計を書かない"""
    best = explanation.best
    if best is None or best.points is None:
        return ""
    names = [item.name for item in best.evaluation.yaku]
    if best.dora_han:
        names.extend(explanation.dora_words)
    points = best.points
    size = (points.level_name if best.is_yakuman else f"{best.fu.fu} 符 {points.han} 翻" + (f"（{points.level_name}）" if points.level_name else ""))
    return f"{'・'.join(names)}。{size}。" + (f"受け取る点の合計 {points.total:,} 点。" if total else "")


def win_facts(explanation: Explanation, *, who: str = "", extra: Sequence[str] = ()) -> Facts:
    """あがった手の事実（役・符・点数の式・支払い・申告）。

    who は、あがった人の呼び方（例：自分、下家。点数計算ラボでは空）。extra は、対局での補足（放銃した人・責任払いなど）。
    """
    ctx = explanation.ctx
    rules = explanation.rules
    aka = rules.aka_dora
    how = "ツモ" if ctx.is_tsumo else ("槍槓" if ctx.chankan else "ロン")
    title = f"あがりの解説（{who + 'の' if who else ''}{how}）"
    closed = [t for t in ctx.closed_tiles if t != ctx.win_tile]
    situation = [
        f"{'ツモ' if ctx.is_tsumo else 'ロン'}であがった。あがり牌は {_tile(ctx.win_tile, aka)}。",
        f"あがった人は{'親' if ctx.is_dealer else '子'}（自風は {WIND_NAMES[ctx.seat_wind]}、場風は {WIND_NAMES[ctx.round_wind]}）。",
        f"門前の手牌（あがり牌を除く）：{_tiles(closed, aka)}。",
        *_meld_lines(ctx.melds, aka, mine=False),
    ]
    if not any(m.type is not MeldType.ANKAN for m in ctx.melds):
        situation.append("鳴いていない（門前）。")
    flags = [name for flag, name in (
        (ctx.riichi and not ctx.double_riichi, "リーチしていた"), (ctx.double_riichi, "ダブル立直していた"), (ctx.ippatsu, "一発"),
        (ctx.rinshan, "嶺上牌でのツモ"), (ctx.chankan, "槍槓（ほかの人がカンした牌でのロン）"), (ctx.haitei, "最後のツモ牌"), (ctx.houtei, "最後の捨て牌"),
        (ctx.tenhou, "親の配牌のままのあがり"), (ctx.chiihou, "子の最初のツモでのあがり"),
    ) if flag]
    if flags:
        situation.append("場面：" + "・".join(flags) + "。")
    if ctx.dora_indicators:
        situation.append("ドラ表示牌：" + "・".join(f"{_tile(t, aka)}（ドラは {kind_text(dora_kind_of(kind_of(t)))}）" for t in ctx.dora_indicators) + "。")
    if ctx.ura_indicators:
        situation.append("裏ドラ表示牌：" + "・".join(f"{_tile(t, aka)}（裏ドラは {kind_text(dora_kind_of(kind_of(t)))}）" for t in ctx.ura_indicators) + "。")
    if ctx.honba or ctx.kyotaku:
        situation.append(f"本場は {ctx.honba} 本場、供託のリーチ棒は {ctx.kyotaku} 本。")
    situation.extend(extra)
    best = explanation.best
    if best is None or best.points is None:
        reason = "役がないので、あがれない。" if explanation.status is Status.NO_YAKU else "あがりの形になっていない。"
        result = [reason, *explanation.advice]
        why = Suggestion("why", "なぜあがれないの？", tuple(result))
        return _facts("win", title, [("あがり", situation), ("結果", result)], rules, [why])
    interp = best.interp
    shape = []
    if interp.form is Form.CHIITOI:
        shape.append("対子：" + "・".join(b.text() for b in interp.blocks) + "。")
    elif interp.form is Form.REGULAR:
        pair = interp.pair
        shape.append("面子：" + "・".join(b.text() for b in interp.mentsu) + "。" + (f"雀頭：{pair.text()}。" if pair is not None else ""))
    shape.append(f"待ち：{wait_text(interp, kind_of(ctx.win_tile))}。")
    if explanation.has_alternatives:
        shape.append(f"読み方は {len(explanation.candidates)} 通りある。点数がいちばん高い読み方を採る（高点法）。")
    points = best.points
    evaluation = best.evaluation
    yaku = [f"{item.name} {_yaku_han(item)}" + (f"（{item.note}）" if item.note else "") for item in evaluation.yaku]
    if best.is_yakuman:
        times = evaluation.yakuman_times
        yaku.append(f"合計：{points.level_name}" + (f"（役満 {times} つぶん）" if times > 1 else ""))
        if evaluation.ignored:
            yaku.append(f"役満が成立したので、ほかの役（{'・'.join(item.name for item in evaluation.ignored)}）とドラは数えない。")
    else:
        if best.dora_han:
            yaku.append("・".join(explanation.dora_words) + f"（ドラは合わせて {best.dora_han} 翻）")
        yaku.append(f"合計 {points.han} 翻" + (f"（{points.level_name}）" if points.level_name else ""))
    checks = []
    for item in evaluation.yaku:
        met = [c.text + (f"（{c.detail}）" if c.detail else "") for c in item.checks if c.ok]
        if met:
            checks.append(f"{item.name}の条件：" + "／".join(met))
    if best.is_yakuman:
        fu = ["役満は、符に関係なく点数が決まる。符は数えなくてよい。"]
    else:
        fu = [f"{line.label} {line.fu} 符" + (f"（{line.detail}）" if line.detail else "") for line in best.fu.lines]
        fu.append(f"合計 {best.fu.raw_total} 符 → {best.fu.fu} 符" + ("（10 符単位に切り上げ）" if best.fu.raw_total != best.fu.fu else ""))
        if best.fu.note:
            fu.append(best.fu.note)
    calc = [points.formula, *points.steps]
    pay = [(f"{p.payer} {p.count} 人が、1 人 {p.points:,} 点ずつ払う" if p.count > 1 else f"{p.payer}が {p.points:,} 点を払う")
           + (f"（うち本場 {p.honba:,} 点）" if p.honba else "") + "。"
           for p in points.payments]
    if points.kyotaku_bonus:
        pay.append(f"供託のリーチ棒 {points.kyotaku_bonus:,} 点も受け取る。")
    pay.append(f"あがった人が受け取る点の合計：{points.total:,} 点。")
    rule_text = [
        "基本点 ＝ 符 × 2 の（翻 ＋ 2）乗。2,000 を超えたら満貫（基本点 2,000）で打ち止め。",
        "5 翻は満貫、6〜7 翻は跳満（基本点 3,000）、8〜10 翻は倍満（4,000）、11〜12 翻は三倍満（6,000）、13 翻以上は数え役満（8,000。ルールによっては三倍満まで）。",
        "子のロンは基本点 × 4、親のロンは基本点 × 6 を、100 点単位に切り上げる。",
        "ツモは、子があがると親が基本点 × 2・子が基本点 × 1 ずつ、親があがると子が基本点 × 2 ずつ払う（それぞれ 100 点単位に切り上げ）。",
        "本場は 1 本場につき、ロンは 300 点、ツモは 1 人 100 点ずつ上乗せ（このアプリの設定。ルールによって異なる）。"
        "供託のリーチ棒は 1 本 1,000 点で、あがった人がもらう（このアプリでは、2 人以上がロンしたとき、本場と供託は、放銃した人から見て近い人だけがもらう）。",
        level_table(rules),
    ]
    near = [f"{item.name}：{item.hint}" for item in best.near if item.hint]
    notes = list(explanation.rule_notes)
    sections = [
        ("あがり", situation),
        ("手の読み方", shape),
        ("役と翻", yaku),
        ("役の条件（この手で満たしたもの）", checks),
        ("符", fu),
        ("点数の式", calc),
        ("点数の決まり", rule_text),
        ("支払い", pay),
        ("卓での申告", [explanation.declaration]),
        ("惜しかった役", near),
        ("ルールによって異なること", notes),
    ]
    # 点数の答え：式（基本点 → 支払い）と、受け取る点の合計。支払いが式と同じ（本場・供託の無いロン）なら、くり返さない
    extras = ctx.is_tsumo or points.kyotaku_bonus or any(p.honba for p in points.payments)
    points_answer = (win_summary(explanation, total=False), *points.steps, *(pay if extras else pay[-1:]))
    suggestions = [
        Suggestion("points", "なぜこの点数になるの？", points_answer),
        Suggestion("yaku", "どんな役が付いたの？", (*yaku, *checks)),
    ]
    if not best.is_yakuman:
        suggestions.append(Suggestion("fu", "符はどう数えるの？", tuple(fu)))
    suggestions.append(Suggestion("say", "卓ではどう申告するの？", (f"この手の申告：{explanation.declaration}", *_say_lines(), *pay)))
    if near:
        suggestions.append(Suggestion("near", "ほかに付きそうだった役は？", tuple(near)))
    if notes:
        suggestions.append(Suggestion("rules", "ルールで変わるところは？", tuple(notes)))
    return _facts("win", title, sections, rules, suggestions)


# ---------------------------------------------------------------- 対局：自分が切る番


def _situation(hand: HandState, seat: int, *, my_turn: bool) -> list[str]:
    aka = hand.rules.aka_dora
    player = hand.players[seat]
    wind = hand.seat_wind(seat)
    dora = "・".join(f"{_tile(t, aka)}（ドラは {kind_text(dora_kind_of(kind_of(t)))}）" for t in hand.dora_indicators)
    return [
        f"{_round(hand)}。供託のリーチ棒 {hand.kyotaku} 本。山の残り {hand.live_remaining} 枚。",
        f"自分は {WIND_NAMES[wind]}家（{'親' if wind == EAST else '子'}）。場風は {WIND_NAMES[hand.round_wind]}。",
        f"ドラ表示牌：{dora}。",
        "持ち点：" + "・".join(f"{_name((seat + i) % 4, seat)} {hand.scores[(seat + i) % 4]:,} 点" for i in range(4)) + "。",
        f"自分の番は {len(player.river) + 1} 巡目（ここまでに {len(player.river)} 枚切った）。" if my_turn
        else f"自分はここまでに {len(player.river)} 枚切った。",
    ]


def _rivers(hand: HandState, seat: int) -> list[str]:
    aka = hand.rules.aka_dora
    lines = []
    for i in range(4):
        other = (seat + i) % 4
        player = hand.players[other]
        name = _name(other, seat)
        tiles = []
        for discard in player.river:
            mark = "（リーチ宣言牌）" if discard.riichi else ("（鳴かれた）" if discard.called_by is not None else "")
            tiles.append(_tile(discard.tile, aka) + mark)
        state = "（リーチしている）" if player.riichi_paid else ""
        melds = "".join(f"。{line.rstrip('。')}" for line in _meld_lines(player.melds, aka, mine=False)) if other != seat else ""
        lines.append(f"{name}{state}の河：{'・'.join(tiles) if tiles else 'なし'}{melds}。")
    return lines


def _riichi_lines(view: RiichiView) -> list[str]:
    lines = [f"{kind_text(kind_of(view.tile))}を切ると聴牌。{view.advice}"]
    for wait in view.waits:
        parts = [f"待ち {kind_text(wait.kind)}（残り {wait.remaining} 枚" + (f"・{wait.shape}" if wait.shape else "") + "）"]
        for label, value in (("ダマでロン", wait.dama_ron), ("ダマでツモ", wait.dama_tsumo), ("リーチしてロン", wait.riichi_ron), ("リーチしてツモ", wait.riichi_tsumo)):
            if value is not None:
                parts.append(f"{label} {value:,} 点")
            elif label.startswith("ダマ"):
                parts.append(f"{label}は役なし")
        lines.append("・".join(parts) + "（裏ドラ・一発・本場・供託は入れない）。")
    return lines


def _decision_lines(decision: TurnDecision) -> list[str]:
    tile = decision.action.tile
    assert tile is not None
    lines = [f"前の打牌：{kind_text(kind_of(tile))}切り。評価：{decision.verdict.label}。{decision.verdict.text}"]
    if not decision.followed:
        lines.append(f"そのときのおすすめは {kind_text(kind_of(decision.advice.pick))}切りだった。")
    if decision.safety is not None:
        lines.append(decision.safety.text)
    lines.extend(decision.notes)
    return lines


def _danger_text(row: TileDanger) -> str:
    """危険度と根拠（例：とても危険・無スジ（当たりうる待ち：両面・嵌張））"""
    worst = row.worst
    shapes = f"（当たりうる待ち：{'・'.join(SHAPE_NAMES[s] for s in worst.shapes)}）" if worst.shapes else ""
    return f"{LEVEL_NAMES[row.level]}・{summary(worst)}{shapes}" + ("（ドラ）" if row.dora else "")


def _danger_line(row: TileDanger, forbidden: Iterable[int] = ()) -> str:
    locked = "（いまは喰い替えで切れない）" if row.kind in set(forbidden) else ""
    return f"{kind_text(row.kind)}：{_danger_text(row)}{locked}"


DANGER_NOTE = "危険度は、現物・スジ・壁・字牌の見えている枚数から決めた目安（安全・ほぼ安全・比較的安全・やや危険・危険・とても危険）。"
#: 速さの比べ方（候補の一覧に添える。受け入れ枚数の多い候補が、向聴数で負けていることがあるため）
SPEED_RULE = "速さは、まず切ったあとの向聴数で比べる（小さいほど聴牌に近い）。向聴数が同じときに、受け入れ枚数で比べる（多いほど有効牌を引きやすい）。"


def turn_facts(
    hand: HandState, seat: int, advice: TurnAdvice, *, last: TurnDecision | None = None, win: Explanation | None = None,
) -> Facts:
    """対局で、自分が切る番の事実。win は、いまのツモ牌であがれるときの解説（ツモあがりの見込み）"""
    rules = hand.rules
    aka = rules.aka_dora
    player = hand.players[seat]
    analysis = advice.analysis
    pick_name = _tile(advice.pick, aka)
    mine = [f"手牌：{_tiles(player.hand, aka)}" + (f"。ツモ牌 {_tile(player.drawn, aka)}" if player.drawn is not None else "。鳴いた直後なので、ツモらずに 1 枚切る") + "。"]
    mine.extend(_meld_lines(player.melds, aka))
    if hand.forbidden:
        mine.append("鳴いた直後なので、" + "・".join(kind_text(k) for k in hand.forbidden) + "は切れない（喰い替えの禁止）。")
    if player.in_riichi:
        mine.append("自分はリーチしている（あがり牌と、待ちが変わらない暗槓のほかは、ツモ切りする。リーチ後の暗槓の条件は、ルールによって異なる）。")
    can_win = []
    if win is not None and win.best is not None and win.best.points is not None:
        can_win.append(f"いまのツモ牌で、ツモあがりできる：{win_summary(win)}")
    shanten = [f"いまの向聴数：{_stage(analysis.shanten)}。"]
    shown = analysis.candidates[:CANDIDATES]
    candidates = [_candidate_line(c) for c in shown]
    chosen = analysis.candidate(kind_of(advice.pick))
    more = []          # おすすめの補足（速さの比べ方）
    if chosen is not None and all(c.kind != chosen.kind for c in shown):
        more.append(f"おすすめの {_candidate_line(chosen)}。")
    if analysis.pick.kind != kind_of(advice.pick):
        more.append(f"速さだけで選ぶなら {_candidate_line(analysis.pick)}。")
    equal = advice.equal_tiles
    if equal:
        more.append("おすすめと同じ速さの牌：" + "・".join(_tile(t, aka) for t in equal) + "。")
    pick = [f"押し引き：{STANCE_WORDS[advice.stance]}。", f"コーチのおすすめ：{pick_name}切り。理由：{advice.reason}", *more]
    if advice.stance is not Stance.FOLD and chosen is not None and chosen.total > 0 and analysis.position.draws_left > 0:
        pick.append("おすすめを切ったあと、" + _chance_line(chosen.total, analysis.position.unseen))
    defense = []
    if advice.threats:
        who = "・".join(_name(t.seat, seat) for t in advice.threats)
        defense.append(f"リーチしている人：{who}。")
        defense.extend(_danger_line(row, hand.forbidden) for row in advice.table)
        defense.append(DANGER_NOTE)
    riichi = []
    for view in advice.tenpai_views:
        riichi.extend(_riichi_lines(view))
    yaku = [f"{h.name}：" + ("この役で聴牌している" if h.distance == 0 else f"この役で聴牌するまで あと {h.distance} 枚")
            + (f"（この役に使わない牌：{'・'.join(kind_text(k) for k in h.spare)}）" if h.spare else "") for h in advice.yaku]
    outlooks = []
    for kind, outlook in sorted(advice.open_outlooks.items()):
        names = "・".join(c.name for c in (*outlook.secured, *outlook.path_yaku)[:2])
        outlooks.append(f"{kind_text(kind)}を切ると：{STATUS_WORDS[outlook.status]}" + (f"（{names}）" if names else "") + f"・{_stage(outlook.shanten)}")
    previous = _decision_lines(last) if last is not None else []
    sections = [
        ("局面", _situation(hand, seat, my_turn=True)),
        ("自分の手", mine),
        ("あがれる", can_win),
        ("河と鳴き", _rivers(hand, seat)),
        ("向聴数", shanten),
        (f"打牌の候補（速さの順に {len(shown)} つ：切ったあとの向聴数と、有効牌の残り枚数）", candidates),
        ("おすすめ", pick),
        ("守備（リーチを受けている）", defense),
        ("聴牌にとれるとき（リーチとダマ）", riichi),
        ("役の候補", yaku),
        ("鳴いた手：切り方ごとの役の見込み", outlooks),
        ("前の打牌の評価", previous),
    ]
    # よくある質問
    why = [advice.reason]
    if advice.stance is Stance.FOLD:
        row = next((r for r in advice.table if r.kind == kind_of(advice.pick)), None)
        if row is not None:
            why.append(f"{pick_name}の危険度：{_danger_text(row)}。")
        why.append(DANGER_NOTE)
    else:
        why.append("候補を比べると：")
        why.extend(_bullets(candidates[:3]))
        why.append(SPEED_RULE)
        why.extend(more)
    suggestions = [Suggestion("why", f"なぜ{_spoken(advice.pick, aka)}を切るの？", tuple(why))]
    if can_win:
        suggestions.insert(0, Suggestion("win", "いま、あがれるの？", (*can_win, "「ツモ」を押すと、あがれる。")))
    if len(shown) > 1 and advice.stance is not Stance.FOLD:
        suggestions.append(Suggestion("compare", "ほかの牌を切るとどうなる？", ("切る牌ごとの、切ったあとの形（速さの順）：", *_bullets(candidates), SPEED_RULE)))
    if defense:
        safe = sorted(advice.table, key=lambda r: r.level)[:5]
        suggestions.append(Suggestion("danger", "どの牌が安全？", (
            f"リーチしている人：{'・'.join(_name(t.seat, seat) for t in advice.threats)}。手牌の牌の危険度（安全な順）：",
            *_bullets(_danger_line(r, hand.forbidden) for r in safe), DANGER_NOTE,
        )))
    if advice.riichi is not None:
        view = advice.riichi
        question = "リーチしたほうがいい？" if view.can_riichi else "この聴牌で、あがれる？"
        suggestions.append(Suggestion("riichi", question, tuple(_riichi_lines(view))))
    if yaku:
        suggestions.append(Suggestion("yaku", "この手で狙える役は？", (*yaku, *outlooks)))
    elif outlooks:
        suggestions.append(Suggestion("yaku", "鳴いた手で、役はどうなる？", tuple(outlooks)))
    if previous:
        suggestions.append(Suggestion("last", "さっきの打牌はどうだった？", tuple(previous)))
    return _facts("turn", "対局：自分が切る番", sections, rules, suggestions, game=True)


# ---------------------------------------------------------------- 対局：鳴ける牌が出た


def _option_line(option: CallOption, aka: bool) -> str:
    outlook = option.outlook
    names = "・".join(c.name for c in (*outlook.secured, *outlook.path_yaku)[:2])
    head = "見送る" if option.action is None else call_name(option.action)
    after = "" if option.discard is None else f"（鳴いたら {_tile(option.discard, aka)} 切り）"
    width = "待ち" if outlook.shanten == 0 else "受け入れ"
    return (
        f"{head}{after}：{STATUS_WORDS[outlook.status]}" + (f"（{names}）" if names else "")
        + f"・打点の目安 {outlook.han} 翻・{_stage(outlook.shanten)}・{width} {outlook.total} 枚"
        + (f"（速さだけなら {_stage(option.fastest)}）" if option.fastest is not None and option.fastest < outlook.shanten else "")
    )


HAN_NOTE = "打点の目安は、確定した役＋リーチ（門前のとき）＋いまの形で付く役のうち一番高いもの＋ドラ（役どうしが同時に付くかは見ない、おおまかな目安）。"


def call_facts(hand: HandState, seat: int, advice: CallAdvice) -> Facts:
    """対局で、鳴ける牌が出たときの事実"""
    rules = hand.rules
    aka = rules.aka_dora
    player = hand.players[seat]
    who = _name(advice.from_seat, seat)
    tile = _tile(advice.tile, aka)
    mine = [f"手牌：{_tiles(player.hand, aka)}。"]
    if player.melds:
        mine.append(f"副露：{_melds(player, aka)}。")
    claim = [f"{who}が切った {tile} を鳴ける。"]
    for option in advice.calls:
        if option.action is not None and option.action.tiles:
            kinds = sorted([*(kind_of(t) for t in option.action.tiles), kind_of(advice.tile)])
            claim.append(f"{call_name(option.action)}：{kinds_text(kinds)} の面子になる。")
    if advice.threatened:
        claim.append("誰かのリーチを受けている（宣言牌そのものを鳴くときも、リーチを受けているものとして扱う）。")
    options = [_option_line(advice.stay, aka), *(_option_line(o, aka) for o in advice.calls)]
    recommend = "見送る" if advice.recommend is None else call_name(advice.recommend)
    pick = [f"コーチのおすすめ：{recommend}。理由：{advice.reason}", HAN_NOTE]
    sections = [
        ("局面", _situation(hand, seat, my_turn=False)),
        ("自分の手", mine),
        ("河と鳴き", _rivers(hand, seat)),
        ("鳴ける牌", claim),
        ("見送る・鳴き方ごとの見込み（役・打点の目安・速さ）", options),
        ("おすすめ", pick),
    ]
    suggestions = [
        Suggestion("why", "鳴いたほうがいい？", (f"おすすめ：{recommend}。{advice.reason}", "比べると：", *_bullets(options))),
        Suggestion("yaku", "鳴いたら、役は残る？", (
            "鳴くと門前でなくなるので、リーチ・門前清自摸和・平和などの門前の役は付かなくなる。鳴いても付く役が要る。",
            *_bullets(options), HAN_NOTE,
        )),
    ]
    return _facts("call", "対局：鳴ける牌が出た", sections, rules, suggestions, game=True)


# ---------------------------------------------------------------- 答え合わせ（さっきの打牌）


def _position_lines(position: Position) -> list[str]:
    """コーチが見た局面（自分から見えている情報）"""
    aka = position.rules.aka_dora
    closed = [t for t in position.tiles if t != position.drawn]
    dora = "・".join(f"{_tile(t, aka)}（ドラは {kind_text(dora_kind_of(kind_of(t)))}）" for t in position.dora_indicators)
    lines = [
        f"自風は {WIND_NAMES[position.seat_wind]}、場風は {WIND_NAMES[position.round_wind]}。" + (f"ドラ表示牌：{dora}。" if dora else ""),
        f"切る前の手牌：{_tiles(closed, aka)}" + (f"。ツモ牌 {_tile(position.drawn, aka)}" if position.drawn is not None else "。鳴いた直後") + "。",
    ]
    if position.melds:
        lines.append(f"副露：{_meld_list(position.melds, aka)}。")
    lines.append(f"このあと自分がツモれる回数：{position.draws_left} 回。")
    return lines


def review_facts(
    analysis: Analysis, verdict: Verdict, tile: int, *, title: str, context: str,
    advice: TurnAdvice | None = None, safety: str = "", notes: Sequence[str] = (), game: bool = False,
) -> Facts:
    """さっきの打牌（切った牌 tile）の答え合わせの事実。advice は対局のコーチのおすすめ（一人練習では None）"""
    position = analysis.position
    rules = position.rules
    aka = rules.aka_dora
    name = _tile(tile, aka)
    shown = analysis.candidates[:CANDIDATES]
    candidates = [_candidate_line(c) for c in shown]
    chosen = verdict.chosen
    if all(c.kind != chosen.kind for c in shown):
        candidates.append(f"（切った牌）{_candidate_line(chosen)}")
    played = [f"切った牌：{name}" + ("（リーチを宣言）" if verdict.riichi else "") + f"。評価：{verdict.label}。{verdict.text}", *verdict.reasons]
    if advice is not None:
        pick_tile = advice.pick
        coach = [f"押し引き：{STANCE_WORDS[advice.stance]}。", f"コーチのおすすめ：{_tile(pick_tile, aka)}切り。理由：{advice.reason}"]
    else:
        pick_tile = verdict.pick.tile
        coach = [f"コーチのおすすめ（速さ）：{_candidate_line(verdict.pick)}。"]
    defense = []
    if advice is not None and advice.threats:
        defense.append("リーチしている人がいた。手牌の牌の危険度：")
        defense.extend(_danger_line(row, position.forbidden) for row in advice.table)
        defense.append(DANGER_NOTE)
    if safety:
        defense.append(f"切った牌の安全度：{safety}")
    sections = [
        ("局面（切る前）", _position_lines(position)),
        ("向聴数", [f"切る前の向聴数：{_stage(analysis.shanten)}。"]),
        (f"打牌の候補（速さの順に {len(shown)} つ：切ったあとの向聴数と、有効牌の残り枚数）", candidates),
        ("おすすめ", coach),
        ("自分の打牌の評価", played),
        ("守備", defense),
        ("注意", list(notes)),
    ]
    folding = advice is not None and advice.stance is Stance.FOLD
    # オリる局面では、速さより安全度が先（コーチは、安全な牌をすすめていた）
    how = [*([safety] if safety else []), *played, *notes] if folding else [*played, *([safety] if safety else []), *notes]
    suggestions = [Suggestion("how", "さっきの打牌はどうだった？", tuple(how))]
    question = f"{_spoken(pick_tile, aka)}を切っていたら、どうなった？"
    if folding and advice is not None and kind_of(pick_tile) != kind_of(tile):
        rows = {row.kind: row for row in advice.table}
        better = [coach[-1]]
        for kind, label in ((kind_of(pick_tile), "おすすめの "), (kind_of(tile), "切った ")):
            if kind in rows:
                better.append(f"{label}{kind_text(kind)}：{_danger_text(rows[kind])}。")
        better.append(DANGER_NOTE)
        suggestions.append(Suggestion("better", question, tuple(better)))
    elif kind_of(pick_tile) != kind_of(tile) and not verdict.is_best:
        better = [*coach[-1:], "比べると：", *_bullets([_candidate_line(verdict.pick), _candidate_line(chosen)])]
        if verdict.gained:
            better.append(f"おすすめなら増える有効牌：{_count(verdict.gained)}。")
        if verdict.lost:
            better.append(f"切った牌のほうにだけある有効牌：{_count(verdict.lost)}。")
        suggestions.append(Suggestion("better", question, tuple(better)))
    if defense:
        safe = sorted(advice.table, key=lambda r: r.level)[:5] if advice is not None else []
        if safe:
            suggestions.append(Suggestion("danger", "どの牌が安全だった？", (
                "手牌の牌の危険度（安全な順）：", *_bullets(_danger_line(r) for r in safe), *([f"切った牌の安全度：{safety}"] if safety else []), DANGER_NOTE,
            )))
    return _facts(context, title, sections, rules, suggestions, game=game)


def turn_review_facts(decision: TurnDecision) -> Facts:
    """対局：さっきの自分の打牌の答え合わせ"""
    tile = decision.action.tile
    assert tile is not None
    return review_facts(
        decision.advice.analysis, decision.verdict, tile, title=f"対局：さっきの打牌（{decision.number} 回目のツモのあと）の答え合わせ",
        context="review", advice=decision.advice, safety=decision.safety.text if decision.safety else "", notes=decision.notes, game=True,
    )


def call_review_facts(decision: CallDecision, rules: Rules) -> Facts:
    """対局：さっきの鳴ける牌への返事（見送る・鳴く）の答え合わせ"""
    advice = decision.advice
    aka = rules.aka_dora
    who = _name(advice.from_seat, advice.seat)
    claim = [f"{who}が切った {_tile(advice.tile, aka)} を鳴けた。"]
    if advice.threatened:
        claim.append("誰かのリーチを受けていた。")
    options = [_option_line(advice.stay, aka), *(_option_line(o, aka) for o in advice.calls)]
    recommend = "見送る" if advice.recommend is None else call_name(advice.recommend)
    coach = [f"コーチのおすすめ：{recommend}。理由：{advice.reason}", HAN_NOTE]
    reply = "見送った" if not decision.called else f"{call_name(decision.action)}をした"
    played = [f"自分の返事：{reply}。評価：{decision.label}。{decision.text}"]
    sections = [
        ("鳴ける牌", claim),
        ("見送る・鳴き方ごとの見込み（役・打点の目安・速さ）", options),
        ("おすすめ", coach),
        ("自分の返事の評価", played),
    ]
    suggestions = [
        Suggestion("how", "さっきの鳴きの判断はどうだった？", (*played, *coach[:1])),
        Suggestion("yaku", "鳴いたら、役は残った？", ("比べると：", *_bullets(options), HAN_NOTE)),
    ]
    return _facts("review", f"対局：さっきの鳴きの判断（{decision.number} 巡目）の答え合わせ", sections, rules, suggestions, game=True)


# ---------------------------------------------------------------- 一人練習


def _target_lines(target: TargetAdvice, aka: bool) -> list[str]:
    name = target.name
    lines = [f"狙う役：{name}（役指定練習）。"]
    if target.won:
        lines.append(f"いまの 14 枚で、{name}の形であがっている。")
        return lines
    if not target.possible or target.pick is None:
        lines.append(f"{name}は、この局ではもう作れない（必要な牌が見えている）。あとは速さで選ぶ。")
        return lines
    pick = target.pick
    goal = f"{name}の聴牌" if pick.distance == 0 else f"{name}まで あと {pick.missing} 枚"
    lines.append(f"役を狙うおすすめ：{_tile(pick.tile, aka)}切り。切ったあと、{goal}。近づく牌 {pick.kinds} 種 {pick.total} 枚{_acceptance(pick.closer)}。")
    blocks = [block_text(b) + (f"（足りない牌：{kinds_text(b.need)}）" if b.need else "") for b in target.plan.blocks]
    if blocks:
        lines.append("めざす形：" + "・".join(blocks) + "。")
    if target.differs_from_speed:
        lines.append(f"速さだけで選ぶなら {kind_text(target.speed_kind)}切り（役を狙うおすすめとは違う）。")
    return lines


def _speed_lead(analysis: Analysis, aka: bool) -> str:
    """速さで選んだおすすめの、ひとことの理由（例：白切りが、いちばん速い（3 向聴・受け入れ 16 種 51 枚））"""
    pick = analysis.pick
    if pick.total == 0:
        return "どれを切っても、有効牌は残っていない。"
    width = "待ち" if pick.shanten == 0 else "受け入れ"
    lead = f"{_tile(pick.tile, aka)}切りが、いちばん速い（{_stage(pick.shanten)}・{width} {pick.kinds} 種 {pick.total} 枚）。"
    same = [kind_text(c.kind) for c in analysis.best if c.kind != pick.kind]
    return lead + (f"同じ速さの牌：{'・'.join(same)}。" if same else "")


def _wait_result(result: Explanation | None) -> str:
    if result is None:
        return "—"
    summary_line = win_summary(result)
    return summary_line or "役なし（あがれない）"


def practice_facts(
    state: PracticeState, analysis: Analysis, *, target: TargetAdvice | None = None, win: Explanation | None = None,
) -> Facts:
    """一人練習で切る番の事実。target は役指定練習のおすすめ、win は、いまのツモ牌であがれるときの解説"""
    rules = state.config.rules
    aka = rules.aka_dora
    dora = "・".join(kind_text(k) for k in analysis.position.dora_kinds)
    situation = [
        f"一人練習（相手なし。放銃の心配はない）。自分のツモは {len(state.draws)} 回目（最大 18 回）。",
        f"自風は {WIND_NAMES[state.seat_wind]}、場風は {WIND_NAMES[state.config.round_wind]}。ドラ：{dora or 'なし'}。",
        f"河：{'・'.join(_tile(t, aka) for t in state.discards) or 'なし'}。",
    ]
    mine = [f"手牌：{_tiles(state.hand, aka)}" + (f"。ツモ牌 {_tile(state.drawn, aka)}" if state.drawn is not None else "") + "。"]
    if state.riichi_index is not None:
        mine.append("リーチしている（あがり牌のほかは、ツモ切りする）。")
    can_win = []
    if win is not None and win.best is not None and win.best.points is not None:
        can_win.append(f"いまのツモ牌で、ツモあがりできる：{win_summary(win)}")
    shown = analysis.candidates[:CANDIDATES]
    candidates = [_candidate_line(c) for c in shown]
    pick_name = _tile(analysis.pick.tile, aka)
    pick = [f"コーチのおすすめ（速さ）：{_candidate_line(analysis.pick, limit=ALL_KINDS)}。",
            "おすすめは、速さだけで決めている。" + SPEED_RULE + "受け入れも同じなら、ドラを残し、使いにくい牌から切る。"]
    if analysis.pick.total > 0 and analysis.position.draws_left > 0:
        pick.append("おすすめを切ったあと、" + _chance_line(analysis.pick.total, analysis.position.unseen))
    waits = []
    if analysis.waits:
        waits.append(f"{pick_name}を切ると聴牌。ツモであがったときの点（裏ドラ・一発は入れない）：")
        for wait in analysis.waits:
            waits.append(f"待ち {kind_text(wait.kind)}（残り {wait.remaining} 枚）：リーチしない → {_wait_result(wait.plain)}／リーチする → {_wait_result(wait.riichi)}")
        waits.append("一人練習には相手がいないので、放銃の心配がない。聴牌したら、リーチしたほうが得。")
    aims = _target_lines(target, aka) if target is not None else []
    sections = [
        ("局面", situation),
        ("自分の手", mine),
        ("あがれる", can_win),
        ("向聴数", [f"いまの向聴数：{_stage(analysis.shanten)}。"]),
        (f"打牌の候補（速さの順に {len(shown)} つ：切ったあとの向聴数と、有効牌の残り枚数）", candidates),
        ("おすすめ", pick),
        ("聴牌したときの待ちと点", waits),
        ("狙う役", aims),
    ]
    suggestions = []
    if can_win:
        suggestions.append(Suggestion("win", "いま、あがれるの？", (*can_win, "「ツモ」を押すと、あがれる。")))
    if target is not None and target.pick is not None and not target.won and target.possible:
        # 役指定練習：役を狙うおすすめの理由
        suggestions.append(Suggestion("why", f"なぜ{_spoken(target.pick.tile, aka)}を切るの？", tuple(aims[1:])))
    else:
        why_lines = [_speed_lead(analysis, aka), pick[1], "候補を比べると：", *_bullets(candidates[:3])]
        suggestions.append(Suggestion("why", f"なぜ{_spoken(analysis.pick.tile, aka)}を切るの？", tuple(why_lines)))
    live = analysis.pick.option.acceptance.live
    if live:
        suggestions.append(Suggestion("next", "次に何を引けばいい？", (
            f"{pick_name}を切ったあとの有効牌は {analysis.pick.kinds} 種 {analysis.pick.total} 枚：",
            _count(live) + "。", *pick[2:],
        )))
    if len(shown) > 1:
        suggestions.append(Suggestion("compare", "ほかの牌を切るとどうなる？", ("切る牌ごとの、切ったあとの形（速さの順）：", *_bullets(candidates), SPEED_RULE)))
    if waits:
        suggestions.append(Suggestion("riichi", "リーチしたほうがいい？", tuple(waits)))
    return _facts("practice", "一人練習：切る番", sections, rules, suggestions)


def practice_review_facts(decision: PracticeDecision) -> Facts:
    """一人練習：さっきの自分の打牌の答え合わせ（役指定練習なら、狙う役から見た評価も）"""
    tile = decision.action.tile
    assert tile is not None
    notes: list[str] = []
    if decision.target is not None and decision.target_advice is not None:
        notes.append(f"狙う役（{decision.target_advice.name}）から見た評価：{decision.target.label}。{decision.target.text}")
        notes.extend(decision.target.reasons)
    return review_facts(
        decision.analysis, decision.verdict, tile, title=f"一人練習：さっきの打牌（{decision.turn} 回目のツモのあと）の答え合わせ",
        context="review", notes=notes,
    )

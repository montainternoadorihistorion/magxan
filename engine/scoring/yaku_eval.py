"""役の判定（自前）。

役ごとに「成立条件」を分けて確かめ、どの条件をどの牌で満たしたかを残す。
最終的な役と翻数は、judge（mahjong ライブラリ）の結果と一致することをテストで確かめる。

役満が 1 つでも成立したら、通常の役とドラは数えない（役満だけを数える）。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from engine.rules import Rules
from engine.scoring.context import WinContext
from engine.scoring.decompose import Block, BlockType, Form, Interpretation, WaitType
from engine.scoring.fu import FuResult
from engine.scoring.texts import SUIT_NAMES, join, kind_text, wait_text
from engine.tiles import (
    CHUN,
    EAST,
    HAKU,
    HATSU,
    NORTH,
    counts34,
    is_honor_kind,
    is_terminal_kind,
    is_yaochu_kind,
    kind_of,
    name_of_kind,
    number_of_kind,
    suit_of_kind,
)
from engine.yaku_table import YAKU, YAKUMAN_HAN, han_of

DRAGONS = (HAKU, HATSU, CHUN)
WINDS = tuple(range(EAST, NORTH + 1))
GREEN_KINDS = frozenset({19, 20, 21, 23, 25, HATSU})   # 2・3・4・6・8 索と發


@dataclass(frozen=True)
class Check:
    """役の成立条件 1 つ"""

    text: str          # 条件（定義の一部）
    ok: bool
    detail: str = ""   # この手での根拠。満たしていないときは、何が足りないか


@dataclass(frozen=True)
class YakuResult:
    key: str
    name: str
    reading: str
    han: int                    # この手での翻数（成立していない役では、成立したときの翻数）
    ok: bool
    checks: tuple[Check, ...]
    note: str = ""              # 喰い下がりなどの補足
    hint: str = ""              # 惜しくも不成立のとき、何があれば成立したか

    @property
    def is_yakuman(self) -> bool:
        return YAKU[self.key].yakuman > 0


@dataclass(frozen=True)
class Evaluation:
    yaku: tuple[YakuResult, ...]       # 数える役（役満があるときは役満だけ）
    ignored: tuple[YakuResult, ...]    # 役満があるために数えない通常の役
    han: int                           # 役の翻数の合計（ドラは含まない）
    yakuman_times: int                 # 役満の倍数の合計


class _Hand:
    """判定に使う手牌の事実をまとめたもの"""

    def __init__(self, interp: Interpretation, ctx: WinContext, rules: Rules, fu: FuResult) -> None:
        self.interp = interp
        self.ctx = ctx
        self.rules = rules
        self.fu = fu
        self.is_open = not ctx.is_menzen
        self.blocks = interp.blocks
        self.mentsu = interp.mentsu
        self.pair = interp.pair
        self.shuntsu = [b for b in self.mentsu if b.type is BlockType.SHUNTSU]
        self.sets = [b for b in self.mentsu if b.is_set]
        self.kinds = [kind_of(t) for t in ctx.all_tiles]
        self.counts = counts34(ctx.all_tiles)
        self.suits = sorted({suit_of_kind(k) for k in self.kinds if not is_honor_kind(k)})
        self.honor_kinds = sorted({k for k in self.kinds if is_honor_kind(k)})
        self.kans = [m for m in ctx.melds if m.is_kan]

    def result(self, key: str, checks: list[Check], note: str = "", hint: str = "") -> YakuResult:
        info = YAKU[key]
        han = han_of(key, is_open=self.is_open, double_yakuman=self.rules.double_yakuman)
        ok = all(c.ok for c in checks)
        if ok and info.kuisagari and self.is_open and not note:
            note = f"鳴いているので {info.han_closed} 翻 → {info.han_open} 翻（喰い下がり）"
        return YakuResult(key, info.name, info.reading, han, ok, tuple(checks), note, hint)


def _texts(blocks: list[Block] | tuple[Block, ...]) -> str:
    return join(b.text() for b in blocks)


def _menzen_check(h: _Hand) -> Check:
    return Check("門前である（鳴いていない）", not h.is_open, "鳴いていない" if not h.is_open else "鳴いている")


# ---------------------------------------------------------------- 状況で決まる役


def _situational(h: _Hand) -> list[YakuResult]:
    ctx = h.ctx
    found: list[YakuResult] = []
    if ctx.double_riichi:
        found.append(h.result("double_riichi", [Check("最初の自分の番で（誰も鳴かないうちに）リーチを宣言した", True, "ダブル立直を宣言")]))
    elif ctx.riichi:
        found.append(h.result("riichi", [Check("門前で聴牌して、リーチを宣言した", True, "リーチを宣言")]))
    if ctx.ippatsu:
        found.append(h.result("ippatsu", [Check("リーチのあと 1 巡以内に、誰も鳴かないうちに和了した", True, "リーチ後 1 巡以内の和了")]))
    if ctx.is_tsumo and not h.is_open:
        found.append(h.result("menzen_tsumo", [_menzen_check(h), Check("ツモで和了した", True, "自分で引いた牌で和了")]))
    if ctx.rinshan:
        found.append(h.result("rinshan", [Check("カンをして引いた嶺上牌でツモ和了した", True, "嶺上牌で和了")]))
    if ctx.chankan:
        found.append(h.result("chankan", [Check("他家が加槓しようとした牌でロン和了した", True, "加槓の牌でロン")]))
    if ctx.haitei:
        found.append(h.result("haitei", [Check("山の最後の牌でツモ和了した", True, "最後のツモ牌で和了")]))
    if ctx.houtei:
        found.append(h.result("houtei", [Check("最後に捨てられた牌でロン和了した", True, "最後の捨て牌でロン")]))
    if ctx.tenhou:
        found.append(h.result("tenhou", [Check("親が配牌の 14 枚で和了していた", True, "配牌で和了")]))
    if ctx.chiihou:
        found.append(h.result("chiihou", [Check("子が、誰も鳴かないうちの最初のツモで和了した", True, "第一ツモで和了")]))
    return found


# ---------------------------------------------------------------- 形で決まる役（個別）


def pinfu(h: _Hand) -> YakuResult:
    pair = h.pair
    assert pair is not None
    pair_line = next(line for line in h.fu.lines if line.label == "雀頭")
    non_shuntsu = [b for b in h.mentsu if b.type is not BlockType.SHUNTSU]
    wait = wait_text(h.interp, h.ctx.win_kind)
    checks = [
        _menzen_check(h),
        Check(
            "4 つの面子がすべて順子",
            not non_shuntsu,
            _texts(h.mentsu) if not non_shuntsu else f"順子でない面子がある（{_texts(non_shuntsu)}）",
        ),
        Check("雀頭が役牌でない", pair_line.fu == 0, pair_line.detail),
        Check("待ちが両面待ち", h.interp.wait is WaitType.RYANMEN, wait),
    ]
    return h.result("pinfu", checks)


def tanyao(h: _Hand) -> YakuResult:
    yaochu = sorted({k for k in h.kinds if is_yaochu_kind(k)})
    checks = [
        Check(
            "手牌がすべて中張牌（2〜8 の数牌）",
            not yaochu,
            "么九牌（1・9・字牌）が 1 枚もない" if not yaochu else f"么九牌がある（{join(kind_text(k) for k in yaochu)}）",
        )
    ]
    if h.is_open:
        checks.append(Check("鳴いている場合は、喰いタンありのルール", h.rules.kuitan, "喰いタンあり" if h.rules.kuitan else "喰いタンなしのルール"))
    return h.result("tanyao", checks)


def _peikou_pairs(h: _Hand) -> list[Block]:
    """同じ順子の組（2 つで 1 組）を返す"""
    count = Counter(b.first for b in h.shuntsu)
    pairs: list[Block] = []
    for first, n in sorted(count.items()):
        pairs.extend([Block(first, BlockType.SHUNTSU)] * (n // 2))
    return pairs


def iipeikou(h: _Hand) -> YakuResult:
    pairs = _peikou_pairs(h)
    detail = f"{pairs[0].text()} が 2 組" if pairs else "同じ順子の組がない"
    return h.result("iipeikou", [_menzen_check(h), Check("同じ色・同じ数字の順子が 2 組ある", len(pairs) >= 1, detail)])


def ryanpeikou(h: _Hand) -> YakuResult:
    pairs = _peikou_pairs(h)
    detail = join(f"{p.text()} が 2 組" for p in pairs) if pairs else "同じ順子の組がない"
    return h.result("ryanpeikou", [_menzen_check(h), Check("「同じ順子 2 組」が 2 つある（4 面子すべて）", len(pairs) >= 2, detail)])


def _yakuhai(h: _Hand, key: str, kind: int, role: str) -> YakuResult:
    block = next((b for b in h.sets if b.first == kind), None)
    name = name_of_kind(kind)
    detail = f"{block.text()} がある" if block else f"{name}の刻子がない"
    result = h.result(key, [Check(f"{role}（{name}）の刻子か槓子がある", block is not None, detail)])
    if key in ("yakuhai_seat", "yakuhai_round"):
        return YakuResult(result.key, f"{result.name}（{name}）", result.reading, result.han, result.ok, result.checks, result.note)
    return result


def yakuhai_all(h: _Hand) -> list[YakuResult]:
    ctx = h.ctx
    return [
        _yakuhai(h, "yakuhai_haku", HAKU, "三元牌"),
        _yakuhai(h, "yakuhai_hatsu", HATSU, "三元牌"),
        _yakuhai(h, "yakuhai_chun", CHUN, "三元牌"),
        _yakuhai(h, "yakuhai_seat", ctx.seat_wind, "自風牌"),
        _yakuhai(h, "yakuhai_round", ctx.round_wind, "場風牌"),
    ]


def sanshoku(h: _Hand) -> YakuResult:
    by_number: dict[int, dict[str, Block]] = {}
    for b in h.shuntsu:
        by_number.setdefault(number_of_kind(b.first), {})[b.suit] = b
    best = max(by_number.values(), key=len, default={})
    ok = len(best) == 3
    hint = ""
    if ok:
        detail = _texts([best["m"], best["p"], best["s"]])
    elif len(best) == 2:
        number = number_of_kind(next(iter(best.values())).first)
        missing = next(s for s in "mps" if s not in best)
        need = Block({"m": 0, "p": 9, "s": 18}[missing] + number - 1, BlockType.SHUNTSU)
        detail = f"{_texts(list(best.values()))} はあるが、{SUIT_NAMES[missing]}の同じ順子がない"
        hint = f"{need.text()} の順子があれば成立"
    else:
        detail = "3 色にそろった同じ数字の順子がない"
    return h.result("sanshoku", [Check("萬子・筒子・索子のそれぞれに、同じ数字の順子がある", ok, detail)], hint=hint)


def ittsu(h: _Hand) -> YakuResult:
    best: list[Block] = []
    best_suit = ""
    for suit in "mps":
        got = [b for b in h.shuntsu if b.suit == suit and number_of_kind(b.first) in (1, 4, 7)]
        distinct = list({b.first: b for b in got}.values())
        if len(distinct) > len(best):
            best, best_suit = sorted(distinct), suit
    ok = len(best) == 3
    hint = ""
    if ok:
        detail = _texts(best)
    elif len(best) == 2:
        have = {number_of_kind(b.first) for b in best}
        missing_number = next(n for n in (1, 4, 7) if n not in have)
        need = Block({"m": 0, "p": 9, "s": 18}[best_suit] + missing_number - 1, BlockType.SHUNTSU)
        detail = f"{_texts(best)} はあるが、{need.text()} がない"
        hint = f"{need.text()} の順子があれば成立"
    else:
        detail = "同じ色の 123・456・789 がそろっていない"
    return h.result("ittsu", [Check("同じ色で 123・456・789 の順子がそろっている", ok, detail)], hint=hint)


def chanta(h: _Hand) -> YakuResult:
    without = [b for b in h.blocks if not b.has_yaochu]
    has_honor = any(b.is_honor for b in h.blocks)
    hint = f"{without[0].text()} が么九牌を含む形なら成立" if len(without) == 1 and h.shuntsu and has_honor else ""
    checks = [
        Check(
            "4 面子と雀頭のすべてに么九牌（1・9・字牌）が含まれる",
            not without,
            _texts(h.blocks) if not without else f"么九牌を含まないものがある（{_texts(without)}）",
        ),
        Check("順子が 1 つ以上ある", bool(h.shuntsu), _texts(h.shuntsu) if h.shuntsu else "順子がない（すべて刻子なら混老頭）"),
        Check("字牌が含まれる", has_honor, "字牌あり" if has_honor else "字牌がない（すべて数牌なら純全帯么九）"),
    ]
    return h.result("chanta", checks, hint=hint)


def junchan(h: _Hand) -> YakuResult:
    without = [b for b in h.blocks if not b.has_terminal]
    hint = f"{without[0].text()} が 1 か 9 を含む形なら成立" if len(without) == 1 and h.shuntsu else ""
    checks = [
        Check(
            "4 面子と雀頭のすべてに老頭牌（数牌の 1・9）が含まれる",
            not without,
            _texts(h.blocks) if not without else f"1・9 を含まないものがある（{_texts(without)}）",
        ),
        Check("順子が 1 つ以上ある", bool(h.shuntsu), _texts(h.shuntsu) if h.shuntsu else "順子がない（すべて刻子なら清老頭）"),
    ]
    return h.result("junchan", checks, hint=hint)


def toitoi(h: _Hand) -> YakuResult:
    hint = f"{h.shuntsu[0].text()} が刻子なら成立" if len(h.shuntsu) == 1 else ""
    detail = _texts(h.sets) if not h.shuntsu else f"順子がある（{_texts(h.shuntsu)}）"
    return h.result("toitoi", [Check("4 つの面子がすべて刻子か槓子", not h.shuntsu, detail)], hint=hint)


def _concealed_sets(h: _Hand) -> list[Block]:
    return [b for b in h.sets if b.is_concealed_set]


def sanankou(h: _Hand) -> YakuResult:
    concealed = _concealed_sets(h)
    ron_made = [b for b in h.sets if b.ron_completed]
    hint = ""
    if len(concealed) == 3:
        detail = _texts(concealed)
    else:
        detail = f"暗刻は {len(concealed)} つ" + (f"（{_texts(concealed)}）" if concealed else "")
        if len(concealed) == 2 and ron_made:
            detail += f"。{ron_made[0].text()} はロンで完成したので明刻として数える"
            hint = "ツモで和了していれば成立"
    return h.result("sanankou", [Check("暗刻（暗槓を含む）がちょうど 3 つある", len(concealed) == 3, detail)], hint=hint)


def sanshoku_doukou(h: _Hand) -> YakuResult:
    by_number: dict[int, dict[str, Block]] = {}
    for b in h.sets:
        if not b.is_honor:
            by_number.setdefault(number_of_kind(b.first), {})[b.suit] = b
    best = max(by_number.values(), key=len, default={})
    ok = len(best) == 3
    detail = _texts([best["m"], best["p"], best["s"]]) if ok else "3 色にそろった同じ数字の刻子がない"
    return h.result("sanshoku_doukou", [Check("萬子・筒子・索子のそれぞれに、同じ数字の刻子（槓子）がある", ok, detail)])


def sankantsu(h: _Hand) -> YakuResult:
    kans = [b for b in h.mentsu if b.type is BlockType.KANTSU]
    detail = _texts(kans) if kans else "槓子がない"
    return h.result("sankantsu", [Check("槓子がちょうど 3 つある（暗槓・明槓のどちらでもよい）", len(h.kans) == 3, detail)])


def shousangen(h: _Hand) -> YakuResult:
    dragon_sets = [b for b in h.sets if b.first in DRAGONS]
    pair_is_dragon = h.pair is not None and h.pair.first in DRAGONS
    ok = len(dragon_sets) == 2 and pair_is_dragon
    detail = f"刻子 {_texts(dragon_sets) or 'なし'}、雀頭 {h.pair.text() if h.pair else 'なし'}"
    return h.result("shousangen", [Check("三元牌（白・發・中）の 2 種類が刻子、残り 1 種類が雀頭", ok, detail)])


def honroutou(h: _Hand) -> YakuResult:
    others = sorted({k for k in h.kinds if not is_yaochu_kind(k)})
    detail = "すべて 1・9・字牌" if not others else f"中張牌がある（{join(kind_text(k) for k in others)}）"
    return h.result("honroutou", [Check("手牌がすべて么九牌（1・9・字牌）", not others, detail)])


def honitsu(h: _Hand) -> YakuResult:
    one_suit = len(h.suits) == 1
    has_honor = bool(h.honor_kinds)
    suits = join(SUIT_NAMES[s] for s in h.suits) or "なし"
    checks = [
        Check("数牌が 1 色だけ", one_suit, f"数牌は{suits}"),
        Check("字牌が含まれる", has_honor, "字牌あり" if has_honor else "字牌がない（数牌 1 色だけなら清一色）"),
    ]
    hint = ""
    if not one_suit and len(h.suits) == 2 and has_honor and h.interp.form is Form.REGULAR:
        main = Counter(b.suit for b in h.blocks if not b.is_honor).most_common(1)[0][0]
        off = [b for b in h.blocks if not b.is_honor and b.suit != main]
        if len(off) == 1:
            hint = f"{off[0].text()} が{SUIT_NAMES[main]}か字牌なら成立"
    return h.result("honitsu", checks, hint=hint)


def chinitsu(h: _Hand) -> YakuResult:
    ok = len(h.suits) == 1 and not h.honor_kinds
    if ok:
        detail = f"すべて{SUIT_NAMES[h.suits[0]]}"
    elif h.honor_kinds:
        detail = f"字牌がある（{join(name_of_kind(k) for k in h.honor_kinds)}）"
    else:
        detail = f"数牌が {len(h.suits)} 色ある"
    return h.result("chinitsu", [Check("手牌がすべて同じ色の数牌（字牌なし）", ok, detail)])


def chiitoitsu(h: _Hand) -> YakuResult:
    return h.result(
        "chiitoitsu",
        [_menzen_check(h), Check("対子が 7 組（すべて別の牌。同じ牌 4 枚は 2 組に数えない）", True, _texts(h.blocks))],
    )


# ---------------------------------------------------------------- 役満


def _yakuman_regular(h: _Hand) -> list[YakuResult]:
    found: list[YakuResult] = []
    ctx = h.ctx
    concealed = _concealed_sets(h)

    if len(concealed) == 4:
        if h.interp.wait is WaitType.TANKI:
            found.append(
                h.result(
                    "suuankou_tanki",
                    [
                        Check("暗刻（暗槓を含む）が 4 つある", True, _texts(concealed)),
                        Check("雀頭の単騎待ちで和了した", True, wait_text(h.interp, ctx.win_kind)),
                    ],
                )
            )
        else:
            found.append(h.result("suuankou", [Check("暗刻（暗槓を含む）が 4 つある（双碰待ちはツモ和了に限る）", True, _texts(concealed))]))

    dragon_sets = [b for b in h.sets if b.first in DRAGONS]
    if len(dragon_sets) == 3:
        found.append(h.result("daisangen", [Check("白・發・中のすべてが刻子か槓子", True, _texts(dragon_sets))]))

    wind_sets = [b for b in h.sets if b.first in WINDS]
    if len(wind_sets) == 4:
        found.append(h.result("daisuushii", [Check("東・南・西・北のすべてが刻子か槓子", True, _texts(wind_sets))]))
    elif len(wind_sets) == 3 and h.pair is not None and h.pair.first in WINDS:
        found.append(
            h.result("shousuushii", [Check("風牌の 3 種類が刻子、残り 1 種類が雀頭", True, f"刻子 {_texts(wind_sets)}、雀頭 {h.pair.text()}")])
        )

    if not h.shuntsu and all(is_terminal_kind(k) for k in h.kinds):
        found.append(h.result("chinroutou", [Check("手牌がすべて老頭牌（数牌の 1・9）", True, _texts(h.blocks))]))

    if len(h.kans) == 4:
        found.append(h.result("suukantsu", [Check("槓子が 4 つある", True, _texts([b for b in h.mentsu if b.type is BlockType.KANTSU]))]))

    if not ctx.melds and len(h.suits) == 1 and not h.honor_kinds:
        base = {"m": 0, "p": 9, "s": 18}[h.suits[0]]
        numbers = h.counts[base:base + 9]
        extra = [n - need for n, need in zip(numbers, (3, 1, 1, 1, 1, 1, 1, 1, 3), strict=True)]
        if all(e >= 0 for e in extra) and sum(extra) == 1:
            shape = Check("門前で、同じ色の 1112345678999 ＋ 同じ色の 1 枚", True, f"{SUIT_NAMES[h.suits[0]]}の九蓮宝燈形")
            if extra[ctx.win_kind - base] == 1:
                found.append(h.result("junsei_chuuren", [shape, Check("1112345678999 の 13 枚で、9 種類どれでもあがれる待ちだった", True, "9 面待ち")]))
            else:
                found.append(h.result("chuuren", [shape]))
    return found


def _yakuman_any_form(h: _Hand) -> list[YakuResult]:
    """通常形でも七対子形でも成立する役満"""
    found: list[YakuResult] = []
    if all(is_honor_kind(k) for k in h.kinds):
        found.append(h.result("tsuuiisou", [Check("手牌がすべて字牌", True, _texts(h.blocks))]))
    if all(k in GREEN_KINDS for k in h.kinds):
        found.append(h.result("ryuuiisou", [Check("手牌が 2・3・4・6・8 索と發だけ", True, _texts(h.blocks))]))
    return found


# ---------------------------------------------------------------- まとめ


def _regular_yaku(h: _Hand) -> list[YakuResult]:
    found: list[YakuResult] = []
    candidates = [pinfu(h), tanyao(h)]
    peikou = ryanpeikou(h)
    candidates.append(peikou if peikou.ok else iipeikou(h))
    candidates.extend(yakuhai_all(h))
    candidates.extend([sanshoku(h), ittsu(h), junchan(h)])
    found.extend(c for c in candidates if c.ok)
    if not any(c.key == "junchan" for c in found):
        result = chanta(h)
        if result.ok:
            found.append(result)
    for result in (toitoi(h), sanankou(h), sanshoku_doukou(h), sankantsu(h), shousangen(h)):
        if result.ok:
            found.append(result)
    if not h.shuntsu:
        result = honroutou(h)
        if result.ok:
            found.append(result)
    clean = chinitsu(h)
    if clean.ok:
        found.append(clean)
    else:
        mixed = honitsu(h)
        if mixed.ok:
            found.append(mixed)
    return found


def _chiitoi_yaku(h: _Hand) -> list[YakuResult]:
    found = [chiitoitsu(h)]
    for result in (tanyao(h), honroutou(h)):
        if result.ok:
            found.append(result)
    clean = chinitsu(h)
    if clean.ok:
        found.append(clean)
    else:
        mixed = honitsu(h)
        if mixed.ok:
            found.append(mixed)
    return found


def _kokushi_yaku(h: _Hand) -> list[YakuResult]:
    shape = Check("13 種類の么九牌（1・9・字牌）が 1 枚ずつ＋そのどれか 1 枚", True, "国士無双形")
    if h.interp.wait is WaitType.KOKUSHI_13:
        return [h.result("kokushi_13", [shape, Check("13 種類が 1 枚ずつそろった形で、13 種類どれでもあがれる待ちだった", True, "十三面待ち")])]
    return [h.result("kokushi", [shape])]


def evaluate(interp: Interpretation, ctx: WinContext, rules: Rules, fu: FuResult) -> Evaluation:
    """この読み方で成立する役をすべて求める"""
    h = _Hand(interp, ctx, rules, fu)
    found = _situational(h)
    if interp.form is Form.KOKUSHI:
        found.extend(_kokushi_yaku(h))
    elif interp.form is Form.CHIITOI:
        found.extend(_chiitoi_yaku(h))
        found.extend(_yakuman_any_form(h))
    else:
        found.extend(_regular_yaku(h))
        found.extend(_yakuman_regular(h))
        found.extend(_yakuman_any_form(h))

    yakuman = [y for y in found if y.is_yakuman]
    if yakuman:
        times = sum(y.han for y in yakuman) // YAKUMAN_HAN
        ignored = tuple(y for y in found if not y.is_yakuman)
        return Evaluation(tuple(yakuman), ignored, sum(y.han for y in yakuman), times)
    return Evaluation(tuple(found), (), sum(y.han for y in found), 0)


MAX_NEAR_MISSES = 4


def near_misses(interp: Interpretation, ctx: WinContext, rules: Rules, fu: FuResult, achieved: set[str]) -> tuple[YakuResult, ...]:
    """惜しくも成立しなかった役を返す（多くても MAX_NEAR_MISSES 個）。

    「惜しい」とするのは次のどれか。
      * 条件が 1 つだけ足りない（平和の待ち・雀頭、門前限定の役を鳴いた、喰いタンなしのルール）
      * 面子か雀頭が 1 つ違えば成立した（断么九・三色同順・一気通貫・対々和・混一色・混全帯么九・純全帯么九）
      * ロンでなくツモなら成立した（三暗刻・四暗刻）
      * 雀頭の役牌があと 1 枚で刻子だった
    """
    if interp.form is not Form.REGULAR:
        return ()
    h = _Hand(interp, ctx, rules, fu)
    results: list[YakuResult] = []

    def failed_checks(result: YakuResult) -> list[Check]:
        return [c for c in result.checks if not c.ok]

    # 平和: 面子はすべて順子で、あと 1 つの条件だけが足りないとき
    if "pinfu" not in achieved and not h.sets:
        result = pinfu(h)
        failed = failed_checks(result)
        if len(failed) == 1:
            results.append(_with_hint(result, f"「{failed[0].text}」を満たしていれば成立"))

    # 一盃口: 同じ順子は 2 組あるのに、鳴いているとき
    if "iipeikou" not in achieved and "ryanpeikou" not in achieved and h.is_open and _peikou_pairs(h):
        results.append(_with_hint(iipeikou(h), "門前（鳴いていない手）なら成立"))

    # 断么九
    if "tanyao" not in achieved:
        result = tanyao(h)
        blocks_with_yaochu = [b for b in h.blocks if b.has_yaochu]
        if not result.checks[0].ok and len(blocks_with_yaochu) == 1 and (not h.is_open or rules.kuitan):
            results.append(_with_hint(result, f"{blocks_with_yaochu[0].text()} が 2〜8 だけの形なら成立"))
        elif result.checks[0].ok and not result.ok:
            results.append(_with_hint(result, "喰いタンありのルールなら成立"))

    # 面子が 1 つ違えば成立した役（判定のときに hint を付けてある）
    for result in (sanshoku(h), ittsu(h), toitoi(h), honitsu(h)):
        if result.key not in achieved and not result.ok and result.hint:
            results.append(result)
    if "junchan" not in achieved and "chanta" not in achieved:
        for result in (junchan(h), chanta(h)):
            if not result.ok and result.hint:
                results.append(result)
                break

    # ロンでなくツモなら成立した役
    concealed = _concealed_sets(h)
    ron_made = [b for b in h.sets if b.ron_completed]
    if "sanankou" not in achieved:
        result = sanankou(h)
        if not result.ok and result.hint:
            results.append(result)
    if not h.is_open and len(concealed) == 3 and ron_made and "suuankou" not in achieved and "suuankou_tanki" not in achieved:
        check = Check(
            "暗刻（暗槓を含む）が 4 つある（双碰待ちはツモ和了に限る）",
            False,
            f"{ron_made[0].text()} はロンで完成したので明刻として数える",
        )
        results.append(h.result("suuankou", [check], hint="ツモで和了していれば成立（役満）"))

    # 雀頭の役牌があと 1 枚で刻子だった
    pair = h.pair
    if pair is not None:
        for result in yakuhai_all(h):
            if result.ok or result.key in achieved:
                continue
            kind = {
                "yakuhai_haku": HAKU,
                "yakuhai_hatsu": HATSU,
                "yakuhai_chun": CHUN,
                "yakuhai_seat": ctx.seat_wind,
                "yakuhai_round": ctx.round_wind,
            }[result.key]
            if pair.first == kind:
                results.append(_with_hint(result, f"雀頭の{name_of_kind(kind)}があと 1 枚あって刻子なら成立"))

    return tuple(results[:MAX_NEAR_MISSES])


def _with_hint(result: YakuResult, hint: str) -> YakuResult:
    return YakuResult(result.key, result.name, result.reading, result.han, result.ok, result.checks, result.note, hint)

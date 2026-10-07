"""符の計算（自前）。内訳を 1 行ずつ作る。

符は「和了の形の細かい点数」。副底 20 符に、和了り方・待ち・雀頭・面子の符を足し、10 符単位に切り上げる。

    副底                                 20 符（必ず付く）
    門前でロン                           +10 符
    ツモ                                 +2 符（平和のツモには付けない）
    待ちが嵌張・辺張・単騎               +2 符（両面・双碰は 0 符）
    雀頭が役牌                           +2 符（連風牌はルールにより 2 符または 4 符）
    面子  順子 0 符
          刻子  明刻 2 符 ／ 暗刻 4 符   么九牌（1・9・字牌）なら 2 倍
          槓子  明槓 8 符 ／ 暗槓 16 符  么九牌なら 2 倍

例外
    七対子          25 符で固定（切り上げない）
    平和のツモ      20 符（ツモの 2 符を付けない）
    鳴いた平和形    鳴いた手で足す符が何も無いとき。ロンは合計 20 符のままになるが、30 符として計算する
                    （ツモなら、ツモの 2 符が付いて 22 符 → 30 符）
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.rules import Rules
from engine.scoring.context import WinContext
from engine.scoring.decompose import WAIT_NAMES, Block, BlockType, Form, Interpretation, WaitType
from engine.scoring.texts import kind_text
from engine.tiles import HAKU, is_yaochu_kind

FUTEI = 20
MENZEN_RON = 10
TSUMO = 2
WAIT_FU = {
    WaitType.RYANMEN: 0,
    WaitType.SHANPON: 0,
    WaitType.KANCHAN: 2,
    WaitType.PENCHAN: 2,
    WaitType.TANKI: 2,
}
CHIITOI_FU = 25
OPEN_PINFU_FU = 30


@dataclass(frozen=True)
class FuLine:
    label: str        # 何の符か
    fu: int
    detail: str = ""  # この手での具体的な内容


@dataclass(frozen=True)
class FuResult:
    lines: tuple[FuLine, ...]
    raw_total: int        # 切り上げる前の合計
    fu: int               # 10 符単位に切り上げたあと（七対子は 25）
    note: str = ""        # 例外の説明（七対子、平和ツモ、鳴いた平和形）
    is_pinfu_shape: bool = False   # 門前で、足す符が何も無い形（＝平和の形）


def round_up_fu(raw_total: int) -> int:
    """符の合計を 10 符単位に切り上げる（32 → 40、30 → 30）"""
    return (raw_total + 9) // 10 * 10


def set_fu(block: Block) -> int:
    """刻子・槓子の符"""
    if not block.is_set:
        return 0
    value = 8 if block.type is BlockType.KANTSU else 2
    if block.is_concealed_set:
        value *= 2
    if is_yaochu_kind(block.first):
        value *= 2
    return value


def set_label(block: Block) -> str:
    """刻子・槓子の呼び名（明刻・暗刻・明槓・暗槓 と、中張牌・么九牌）"""
    kind = "槓" if block.type is BlockType.KANTSU else "刻"
    side = "暗" if block.is_concealed_set else "明"
    tile = "么九牌" if is_yaochu_kind(block.first) else "中張牌"
    return f"{side}{kind}（{tile}）"


def pair_fu(pair_kind: int, ctx: WinContext, rules: Rules) -> tuple[int, str]:
    """雀頭の符と、その理由"""
    name = kind_text(pair_kind)
    if pair_kind >= HAKU:
        return 2, f"{name}は三元牌（役牌）"
    is_seat = pair_kind == ctx.seat_wind
    is_round = pair_kind == ctx.round_wind
    if is_seat and is_round:
        return rules.double_wind_pair_fu, f"{name}は連風牌（場風と自風の両方。このルールでは {rules.double_wind_pair_fu} 符）"
    if is_seat:
        return 2, f"{name}は自風牌（役牌）"
    if is_round:
        return 2, f"{name}は場風牌（役牌）"
    return 0, f"{name}は役牌ではない"


def calculate_fu(interp: Interpretation, ctx: WinContext, rules: Rules) -> FuResult:
    """この読み方での符と、その内訳"""
    if interp.form is Form.CHIITOI:
        line = FuLine("七対子", CHIITOI_FU, "七対子は 25 符で固定")
        return FuResult((line,), CHIITOI_FU, CHIITOI_FU, "七対子は例外で、内訳を足し上げず 25 符で固定（切り上げもしない）。")
    if interp.form is Form.KOKUSHI:
        return FuResult((), 0, 0, "国士無双は役満なので、符は数えない。")

    is_open = not ctx.is_menzen
    win_block = interp.win_block
    assert win_block is not None

    wait_fu = WAIT_FU[interp.wait]
    wait_line = FuLine(f"待ち：{WAIT_NAMES[interp.wait]}", wait_fu, f"{win_block.text()} が完成")

    pair = interp.pair
    assert pair is not None
    pair_value, pair_reason = pair_fu(pair.first, ctx, rules)
    pair_line = FuLine("雀頭", pair_value, f"{pair.text()}：{pair_reason}")

    mentsu_lines = []
    for block in interp.mentsu:
        if block.is_set:
            detail = block.text()
            if block.ron_completed:
                detail += "（ロンで完成したので明刻として数える）"
            mentsu_lines.append(FuLine(set_label(block), set_fu(block), detail))
        else:
            mentsu_lines.append(FuLine("順子", 0, block.text()))

    other = wait_fu + pair_value + sum(line.fu for line in mentsu_lines)
    is_pinfu_shape = other == 0 and not is_open

    lines = [FuLine("副底", FUTEI, "どの和了にも必ず付く")]
    note = ""
    if not is_open and not ctx.is_tsumo:
        lines.append(FuLine("門前ロン", MENZEN_RON, "鳴かずにロンで和了した"))
    if ctx.is_tsumo:
        if is_pinfu_shape:
            lines.append(FuLine("ツモ", 0, "平和のツモには付けない"))
            note = "平和のツモ和了は例外で、ツモの 2 符を付けず 20 符で計算する。"
        else:
            lines.append(FuLine("ツモ", TSUMO, "ツモで和了した"))
    lines.extend([wait_line, pair_line, *mentsu_lines])

    raw_total = sum(line.fu for line in lines)
    fu = round_up_fu(raw_total)
    if is_open and raw_total == FUTEI:
        fu = OPEN_PINFU_FU
        note = (
            "鳴いた手で、待ち・雀頭・面子の符がどれも 0 の形（鳴いた平和形）をロンで和了すると、合計は 20 符のままになる。"
            "このときは例外として 30 符で計算する（20 符 1 翻の手は作らない）。"
        )
    return FuResult(tuple(lines), raw_total, fu, note, is_pinfu_shape)

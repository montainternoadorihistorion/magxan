"""点数の計算（自前）。途中の式を 1 行ずつ残す。

    基本点 ＝ 符 × 2^(翻＋2)             ただし 2000 を超えたら満貫（2000）で打ち止め
    5 翻            満貫   基本点 2000
    6〜7 翻         跳満   基本点 3000
    8〜10 翻        倍満   基本点 4000
    11〜12 翻       三倍満 基本点 6000
    13 翻以上       数え役満 基本点 8000（ルールによっては三倍満まで）
    役満            基本点 8000 × 倍数

    支払い（100 点単位に切り上げ）
      ロン   子の和了: 放銃者が 基本点 × 4      親の和了: 放銃者が 基本点 × 6
      ツモ   子の和了: 親が 基本点 × 2、子 2 人が 基本点 × 1 ずつ
             親の和了: 子 3 人が 基本点 × 2 ずつ
    本場   1 本場につき、ロンは放銃者が ＋300、ツモは各自が ＋100
    供託   場に出ているリーチ棒（1 本 1000 点）は和了者がもらう
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.rules import Rules
from engine.scoring.judge import Level, level_of
from engine.yaku_table import YAKUMAN_HAN

LEVEL_NAMES = {
    Level.NONE: "",
    Level.MANGAN: "満貫",
    Level.HANEMAN: "跳満",
    Level.BAIMAN: "倍満",
    Level.SANBAIMAN: "三倍満",
    Level.KAZOE_YAKUMAN: "数え役満",
    Level.YAKUMAN: "役満",
}
LEVEL_BASE = {
    Level.MANGAN: 2000,
    Level.HANEMAN: 3000,
    Level.BAIMAN: 4000,
    Level.SANBAIMAN: 6000,
    Level.KAZOE_YAKUMAN: 8000,
}
YAKUMAN_BASE = 8000
_TIMES_NAMES = {1: "役満", 2: "ダブル役満", 3: "トリプル役満"}


@dataclass(frozen=True)
class Payment:
    payer: str      # 誰が払うか（放銃者／親／子 1 人あたり）
    count: int      # その立場の人数
    points: int     # 1 人が払う点（本場ぶんを含む）
    honba: int      # そのうち本場ぶん


@dataclass(frozen=True)
class PointsResult:
    han: int
    fu: int
    level: Level
    yakuman_times: int
    level_name: str                # 満貫・跳満…・役満（満貫未満は空）
    base: int                      # 基本点
    formula: str                   # 計算を 1 行にまとめた式（例: 30 符 3 翻・子のロン：30 × 2⁵ ＝ … → 3,900 点）
    steps: tuple[str, ...]         # 計算の途中の式（文章）
    payments: tuple[Payment, ...]
    main: int                      # judge と同じ意味（本場を含まない）
    additional: int
    honba_main: int
    honba_additional: int
    kyotaku_bonus: int
    total: int                     # 和了者が受け取る合計
    declaration: str               # 卓での申告の言い方


def ceil100(value: int) -> int:
    return (value + 99) // 100 * 100


def _fmt(value: int) -> str:
    return f"{value:,}"


def _superscript(number: int) -> str:
    return str(number).translate(str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"))


def _amount(before: int, after: int) -> str:
    """100 点単位への切り上げを含めた金額の書き方（例: 3,840 → 切り上げて 3,900 点 ／ 8,000 点）"""
    if before == after:
        return f"{_fmt(after)} 点"
    return f"{_fmt(before)} → 切り上げて {_fmt(after)} 点"


def calculate_points(
    han: int,
    fu: int,
    *,
    yakuman_times: int,
    is_dealer: bool,
    is_tsumo: bool,
    honba: int,
    kyotaku: int,
    rules: Rules,
) -> PointsResult:
    """翻と符から、基本点・支払い・申告の言い方までを求める"""
    level = level_of(han, fu, yakuman_times, rules)
    steps: list[str] = []
    who = "親" if is_dealer else "子"
    how = "ツモ" if is_tsumo else "ロン"

    # ---- 基本点
    if level is Level.YAKUMAN:
        base = YAKUMAN_BASE * yakuman_times
        level_name = _TIMES_NAMES.get(yakuman_times, f"{yakuman_times} 倍役満")
        if yakuman_times == 1:
            steps.append(f"役満なので、翻や符によらず基本点は {_fmt(YAKUMAN_BASE)}。")
            head = f"役満・{who}の{how}：基本点 {_fmt(base)}"
        else:
            steps.append(f"役満 {yakuman_times} つぶんなので、基本点は {_fmt(YAKUMAN_BASE)} × {yakuman_times} ＝ {_fmt(base)}。")
            head = f"{level_name}・{who}の{how}：基本点 {_fmt(YAKUMAN_BASE)} × {yakuman_times} ＝ {_fmt(base)}"
    else:
        level_name = LEVEL_NAMES[level]
        raw = fu * 2 ** (han + 2)
        power = f"{fu} × 2{_superscript(han + 2)} ＝ {fu} × {_fmt(2 ** (han + 2))} ＝ {_fmt(raw)}"
        if level is Level.NONE:
            base = raw
            steps.append(f"基本点 ＝ 符 × 2^(翻＋2) ＝ {power}")
            head = f"{fu} 符 {han} 翻・{who}の{how}：{power}"
        elif level is Level.MANGAN and han < 5:
            base = LEVEL_BASE[level]
            if raw > 2000:
                steps.append(f"基本点 ＝ 符 × 2^(翻＋2) ＝ {power}。2,000 を超えるので満貫（基本点 2,000）で打ち止め。")
                head = f"{fu} 符 {han} 翻・{who}の{how}：{power} → 2,000 を超えるので満貫（基本点 2,000）"
            else:
                steps.append(
                    f"基本点 ＝ 符 × 2^(翻＋2) ＝ {power}。"
                    f"{fu} 符 {han} 翻は、切り上げ満貫のルールにより満貫（基本点 2,000）として扱う。"
                )
                head = f"{fu} 符 {han} 翻・{who}の{how}：{power} → 切り上げ満貫（基本点 2,000）"
        else:
            base = LEVEL_BASE[level]
            reason = {
                Level.MANGAN: "5 翻は満貫",
                Level.HANEMAN: f"{han} 翻は跳満（6〜7 翻）",
                Level.BAIMAN: f"{han} 翻は倍満（8〜10 翻）",
                Level.SANBAIMAN: f"{han} 翻は三倍満（11〜12 翻）" if han < YAKUMAN_HAN else f"{han} 翻（13 翻以上）だが、このルールでは三倍満まで",
                Level.KAZOE_YAKUMAN: f"{han} 翻は数え役満（13 翻以上）",
            }[level]
            steps.append(f"{reason}。符によらず基本点は {_fmt(base)}。")
            head = f"{han} 翻・{who}の{how}：{level_name}（基本点 {_fmt(base)}）"

    # ---- 支払い
    if is_tsumo:
        if is_dealer:
            each = ceil100(base * 2)
            main = additional = each
            steps.append(f"親のツモ：子 3 人が 基本点 × 2 ずつ払う。{_fmt(base)} × 2 ＝ {_amount(base * 2, each)}ずつ。")
            tail = f"子 3 人が × 2 ＝ {_amount(base * 2, each)}ずつ"
        else:
            main = ceil100(base * 2)
            additional = ceil100(base)
            steps.append(
                f"子のツモ：親が 基本点 × 2、子 2 人が 基本点 × 1 ずつ払う。"
                f"親は {_fmt(base)} × 2 ＝ {_amount(base * 2, main)}、子は {_fmt(base)} × 1 ＝ {_amount(base, additional)}ずつ。"
            )
            tail = f"親が × 2 ＝ {_amount(base * 2, main)}、子 2 人が × 1 ＝ {_amount(base, additional)}ずつ"
        honba_main = honba_additional = 100 * honba
    else:
        multiplier = 6 if is_dealer else 4
        main = ceil100(base * multiplier)
        additional = 0
        steps.append(
            f"{who}のロン：放銃者が 基本点 × {multiplier} を払う。{_fmt(base)} × {multiplier} ＝ {_amount(base * multiplier, main)}。"
        )
        tail = f"× {multiplier} ＝ {_amount(base * multiplier, main)}"
        honba_main = 300 * honba
        honba_additional = 0
    formula = f"{head} → {tail}"

    if honba:
        if is_tsumo:
            steps.append(f"{honba} 本場：各自の支払いに {_fmt(100 * honba)} 点ずつ上乗せ。")
        else:
            steps.append(f"{honba} 本場：放銃者の支払いに {_fmt(300 * honba)} 点を上乗せ。")
    kyotaku_bonus = 1000 * kyotaku
    if kyotaku:
        steps.append(f"供託のリーチ棒 {kyotaku} 本（{_fmt(kyotaku_bonus)} 点）も和了者が受け取る。")

    # ---- 誰がいくら
    if not is_tsumo:
        payments = (Payment("放銃者", 1, main + honba_main, honba_main),)
        received = main + honba_main
    elif is_dealer:
        payments = (Payment("子", 3, main + honba_main, honba_main),)
        received = 3 * (main + honba_main)
    else:
        payments = (
            Payment("親", 1, main + honba_main, honba_main),
            Payment("子", 2, additional + honba_additional, honba_additional),
        )
        received = (main + honba_main) + 2 * (additional + honba_additional)
    total = received + kyotaku_bonus

    return PointsResult(
        han=han,
        fu=fu,
        level=level,
        yakuman_times=yakuman_times,
        level_name=level_name,
        base=base,
        formula=formula,
        steps=tuple(steps),
        payments=payments,
        main=main,
        additional=additional,
        honba_main=honba_main,
        honba_additional=honba_additional,
        kyotaku_bonus=kyotaku_bonus,
        total=total,
        declaration=_declaration(level_name, main, additional, honba_main, honba_additional, is_tsumo=is_tsumo, is_dealer=is_dealer),
    )


def _declaration(
    level_name: str, main: int, additional: int, honba_main: int, honba_additional: int, *, is_tsumo: bool, is_dealer: bool
) -> str:
    """卓での申告の言い方。本場があるときは「〜は〜」の形で、上乗せ後の点も言う"""

    def phrase(first: int, second: int) -> str:
        if not is_tsumo or is_dealer:
            return f"{first}"
        return f"{second}・{first}"   # 子のツモは「子の支払い・親の支払い」の順に言う

    text = phrase(main, additional)
    if honba_main:
        text += "は" + phrase(main + honba_main, additional + honba_additional)
    if is_tsumo and is_dealer:
        text += "オール"              # 親のツモは「2000 オール」「2000 は 2100 オール」
    return f"{level_name}、{text}" if level_name else text

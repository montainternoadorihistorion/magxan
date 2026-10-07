"""点数計算のテスト（手で計算した期待値との照合）。

期待値はすべて、ルールから手で計算したもの（ライブラリの出力を写したものではない）。
各行について、判定ライブラリ（judge）と自前の計算（explain）の両方が期待値どおりであることを確かめる。

    基本点 ＝ 符 × 2^(翻＋2)
    子のロン ＝ 基本点 × 4、親のロン ＝ 基本点 × 6（100 点単位に切り上げ）
    子のツモ ＝ 親が 基本点 × 2、子が 基本点 × 1 ずつ。親のツモ ＝ 子が 基本点 × 2 ずつ

牌の書き方: m 萬子 / p 筒子 / s 索子 / z 字牌（1 東 2 南 3 西 4 北 5 白 6 發 7 中）/ 0 赤5
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.explain import Status, explain
from engine.scoring.judge import JudgeError, Level, judge
from engine.scoring.notation import make_context
from engine.tiles import EAST, SOUTH, WEST

CHILD = {"seat_wind": SOUTH, "round_wind": EAST}     # 東場の南家（子）
DEALER = {"seat_wind": EAST, "round_wind": EAST}     # 東場の東家（親）


@dataclass(frozen=True)
class Case:
    name: str
    hand: str
    win: str
    han: int
    fu: int
    main: int                      # ロン: 放銃者の支払い ／ ツモ: 親の支払い（親のツモは子 1 人の支払い）
    additional: int = 0            # ツモで子 1 人が払う点
    yaku: tuple[str, ...] = ()     # 成立する役（空なら確かめない）
    level: Level = Level.NONE
    rules: Rules = DEFAULT_RULES
    kw: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.name


def case(name, hand, win, han, fu, main, additional=0, yaku=(), level=Level.NONE, rules=DEFAULT_RULES, **kw) -> Case:
    for key, value in CHILD.items():
        kw.setdefault(key, value)
    return Case(name, hand, win, han, fu, main, additional, tuple(yaku), level, rules, kw)


RIICHI = {"riichi": True}
TSUMO = {"is_tsumo": True}

CASES = [
    # ---- 平和ツモ: 20 符。2 翻 20 符 → 基本点 20 × 16 ＝ 320
    case("平和ツモ（子）", "123456m234p67s55s", "8s", 2, 20, 700, 400, ["menzen_tsumo", "pinfu"], **TSUMO),
    case("平和ツモ（親）", "123456m234p67s55s", "8s", 2, 20, 700, 700, ["menzen_tsumo", "pinfu"], **TSUMO, **DEALER),
    # ---- リーチ平和ロン: 30 符。2 翻 30 符 → 基本点 480
    case("リーチ平和ロン（子）", "123456m234p67s55s", "8s", 2, 30, 2000, yaku=["riichi", "pinfu"], **RIICHI),
    case("リーチ平和ロン（親）", "123456m234p67s55s", "8s", 2, 30, 2900, yaku=["riichi", "pinfu"], **RIICHI, **DEALER),
    # ---- 七対子: 25 符固定。2 翻 → 基本点 400、ツモで 3 翻 → 基本点 800
    case("七対子ロン（子）", "1133m5577p2299s1z", "1z", 2, 25, 1600, yaku=["chiitoitsu"]),
    case("七対子ロン（親）", "1133m5577p2299s1z", "1z", 2, 25, 2400, yaku=["chiitoitsu"], **DEALER),
    case("七対子ツモ（子）", "1133m5577p2299s1z", "1z", 3, 25, 1600, 800, ["chiitoitsu", "menzen_tsumo"], **TSUMO),
    case("七対子ツモ（親）", "1133m5577p2299s1z", "1z", 3, 25, 1600, 1600, ["chiitoitsu", "menzen_tsumo"], **TSUMO, **DEALER),
    # ---- 喰いタン: 副底 20 ＋ 明刻（中張牌）2 ＝ 22 → 30 符。1 翻 30 符 → 基本点 240
    case("喰いタン ロン（子）", "234m55p34s", "5s", 1, 30, 1000, yaku=["tanyao"], melds=["pon 888m", "chi 678p"]),
    case("喰いタン ロン（親）", "234m55p34s", "5s", 1, 30, 1500, yaku=["tanyao"], melds=["pon 888m", "chi 678p"], **DEALER),
    # ---- 鳴いた平和形: ロンは 20 符のままなので 30 符にする。ツモは 20 ＋ 2 ＝ 22 → 30 符
    case("鳴いた平和形 ロン", "234m55p34s", "5s", 1, 30, 1000, yaku=["tanyao"], melds=["chi 678p", "chi 345m"]),
    case("鳴いた平和形 ツモ", "234m55p34s", "5s", 1, 30, 500, 300, ["tanyao"], melds=["chi 678p", "chi 345m"], **TSUMO),
    # ---- 待ちの符（リーチのみ 1 翻）: 嵌張・辺張・単騎は ＋2 で 32 → 40 符。基本点 320
    case("嵌張待ち", "123m456p789s13s44z", "2s", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    case("辺張待ち（12 で 3）", "123m456p789s12s44z", "3s", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    case("辺張待ち（89 で 7）", "123m456p123s89s44z", "7s", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    case("単騎待ち", "123m456p789s123s4z", "4z", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    case("両面待ち（平和が付く）", "123m456p789s23s44z", "4s", 2, 30, 2000, yaku=["riichi", "pinfu"], **RIICHI),
    # 双碰: ロンで完成した刻子は明刻。中張牌 2 符 → 32 → 40 符、么九牌 4 符 → 34 → 40 符
    case("双碰待ち ロン（中張牌）", "123m456p789s22s44z", "2s", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    case("双碰待ち ロン（字牌）", "123m456p789s22s44z", "4z", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    # 双碰をツモ: 暗刻のまま。20 ＋ 2 ＋ 4 ＝ 26 → 30 符。2 翻 30 符 → 基本点 480
    case("双碰待ち ツモ", "123m456p789s22s44z", "2s", 2, 30, 1000, 500, ["riichi", "menzen_tsumo"], **RIICHI, **TSUMO),
    # ---- 暗刻・明刻
    case("暗刻（中張牌）ツモ", "222m456p789s23s99p", "4s", 2, 30, 1000, 500, ["riichi", "menzen_tsumo"], **RIICHI, **TSUMO),
    # 30 ＋ 暗刻（么九牌）8 ＝ 38 → 40 符
    case("暗刻（么九牌）ロン", "111m456p789s23s99p", "4s", 1, 40, 1300, yaku=["riichi"], **RIICHI),
    # 20 ＋ 明刻（么九牌）4 ＝ 24 → 30 符
    case("明刻（役牌）ロン", "123m456p23s99p", "4s", 1, 30, 1000, yaku=["yakuhai_haku"], melds=["pon 555z"]),
    # ---- 槓子
    # 20 ＋ 10 ＋ 暗槓（么九牌）32 ＝ 62 → 70 符。2 翻 70 符 → 基本点 1120 → 4480 → 4500
    case("暗槓（么九牌）", "123m456p78s22p", "9s", 2, 70, 4500, yaku=["riichi", "yakuhai_round"], melds=["ankan 1111z"], **RIICHI),
    # 20 ＋ ツモ 2 ＋ 明槓（中張牌）8 ＝ 30 符。嶺上開花 1 翻
    case("明槓＋嶺上開花", "123m567p34s66s", "5s", 1, 30, 500, 300, ["rinshan"], melds=["minkan 8888p"], rinshan=True, **TSUMO),
    # 20 ＋ 加槓（么九牌の明槓）16 ＝ 36 → 40 符
    case("加槓（役牌）", "123m456p78s22p", "9s", 1, 40, 1300, yaku=["yakuhai_chun"], melds=["kakan 7777z"]),
    # 20 ＋ 10 ＋ 暗槓（中張牌）16 ＋ 暗刻（白）8 ＝ 54 → 60 符。3 翻 60 符 → 基本点 1920 → 7680 → 7700
    case("3 翻 60 符", "234m67s99m555z", "8s", 3, 60, 7700, yaku=["riichi", "ippatsu", "yakuhai_haku"], melds=["ankan 8888p"], ippatsu=True, **RIICHI),
    case(
        "3 翻 60 符（切り上げ満貫）", "234m67s99m555z", "8s", 3, 60, 8000,
        level=Level.MANGAN, rules=Rules(kiriage_mangan=True), melds=["ankan 8888p"], ippatsu=True, **RIICHI,
    ),
    # ---- 4 翻 30 符 → 基本点 1920。子 7680 → 7700、親 11520 → 11600
    case("4 翻 30 符（子）", "223344m567p67s55p", "8s", 4, 30, 7700, yaku=["riichi", "pinfu", "tanyao", "iipeikou"], **RIICHI),
    case("4 翻 30 符（親）", "223344m567p67s55p", "8s", 4, 30, 11600, **RIICHI, **DEALER),
    case("4 翻 30 符（切り上げ満貫・子）", "223344m567p67s55p", "8s", 4, 30, 8000, level=Level.MANGAN, rules=Rules(kiriage_mangan=True), **RIICHI),
    case(
        "4 翻 30 符（切り上げ満貫・親）", "223344m567p67s55p", "8s", 4, 30, 12000,
        level=Level.MANGAN, rules=Rules(kiriage_mangan=True), **RIICHI, **DEALER,
    ),
    # ---- 満貫・跳満・倍満・三倍満・数え役満
    case(
        "満貫 5 翻 ツモ（子）", "223344m567p67s55p", "8s", 5, 20, 4000, 2000,
        ["riichi", "menzen_tsumo", "pinfu", "tanyao", "iipeikou"], Level.MANGAN, **RIICHI, **TSUMO,
    ),
    case("満貫 5 翻 ツモ（親）", "223344m567p67s55p", "8s", 5, 20, 4000, 4000, level=Level.MANGAN, **RIICHI, **TSUMO, **DEALER),
    case("跳満 6 翻 ツモ（子）", "223344m567p67s55p", "8s", 6, 20, 6000, 3000, level=Level.HANEMAN, ippatsu=True, **RIICHI, **TSUMO),
    case("跳満 6 翻 ツモ（親）", "223344m567p67s55p", "8s", 6, 20, 6000, 6000, level=Level.HANEMAN, ippatsu=True, **RIICHI, **TSUMO, **DEALER),
    # 清一色 6 ＋ 一気通貫 2 ＋ 平和 1 ＝ 9 翻
    case("倍満 9 翻 ロン（子）", "1234567892355m", "4m", 9, 30, 16000, yaku=["chinitsu", "ittsu", "pinfu"], level=Level.BAIMAN),
    case("倍満 9 翻 ロン（親）", "1234567892355m", "4m", 9, 30, 24000, level=Level.BAIMAN, **DEALER),
    case("三倍満 11 翻 ツモ（子）", "1234567892355m", "4m", 11, 20, 12000, 6000, level=Level.SANBAIMAN, **RIICHI, **TSUMO),
    case("三倍満 11 翻 ロン（子）", "1234567892355m", "4m", 11, 30, 24000, level=Level.SANBAIMAN, ippatsu=True, **RIICHI),
    case("三倍満 11 翻 ロン（親）", "1234567892355m", "4m", 11, 30, 36000, level=Level.SANBAIMAN, ippatsu=True, **RIICHI, **DEALER),
    case(
        "数え役満 13 翻 ツモ（子）", "1234567892355m", "4m", 13, 20, 16000, 8000,
        level=Level.KAZOE_YAKUMAN, ippatsu=True, haitei=True, **RIICHI, **TSUMO,
    ),
    case(
        "数え役満なしのルールでは三倍満", "1234567892355m", "4m", 13, 20, 12000, 6000,
        level=Level.SANBAIMAN, rules=Rules(kazoe_yakuman=False), ippatsu=True, haitei=True, **RIICHI, **TSUMO,
    ),
    # 4 翻 40 符 → 基本点 2560 → 満貫で打ち止め
    case("満貫（4 翻 40 符）", "223344m556677p8s", "8s", 4, 40, 8000, yaku=["tanyao", "ryanpeikou"], level=Level.MANGAN),
    # ---- 役満
    case("役満 ロン（子）", "119m19p19s123456z", "7z", 13, 0, 32000, yaku=["kokushi"], level=Level.YAKUMAN),
    case("役満 ロン（親）", "119m19p19s123456z", "7z", 13, 0, 48000, yaku=["kokushi"], level=Level.YAKUMAN, **DEALER),
    case("役満 ツモ（子）", "119m19p19s123456z", "7z", 13, 0, 16000, 8000, ["kokushi"], Level.YAKUMAN, **TSUMO),
    case("役満 ツモ（親）", "119m19p19s123456z", "7z", 13, 0, 16000, 16000, ["kokushi"], Level.YAKUMAN, **TSUMO, **DEALER),
    case("ダブル役満（国士無双十三面待ち）", "19m19p19s1234567z", "1m", 26, 0, 64000, yaku=["kokushi_13"], level=Level.YAKUMAN),
    case(
        "ダブル役満なしのルール", "19m19p19s1234567z", "1m", 13, 0, 32000,
        yaku=["kokushi_13"], level=Level.YAKUMAN, rules=Rules(double_yakuman=False),
    ),
    # ---- 高点法: 同じ 14 枚でも、点数が高くなる読み方を採る
    # 123萬 × 3 と読む: リーチ 1 ＋ 平和 1 ＋ 一盃口 1 ＋ 純全帯么九 3 ＝ 6 翻 30 符（刻子 3 つと読むと 3 翻 50 符で 6400）
    case("高点法（順子で読む）", "111222333m78p99s", "9p", 6, 30, 12000, yaku=["riichi", "pinfu", "iipeikou", "junchan"], level=Level.HANEMAN, **RIICHI),
    # 刻子 3 つと読む: 断么九 1 ＋ 三暗刻 2 ＝ 3 翻、30 ＋ 4 × 3 ＝ 42 → 50 符（順子で読むと 3 翻 30 符で 3900）
    case("高点法（刻子で読む）", "222333444m67p88s", "5p", 3, 50, 6400, yaku=["tanyao", "sanankou"]),
    # ツモなら 門前清自摸和 1 ＋ 断么九 1 ＋ 三暗刻 2 ＝ 4 翻、20 ＋ 2 ＋ 12 ＝ 34 → 40 符 → 満貫
    case("高点法（刻子で読む・ツモ）", "222333444m67p88s", "5p", 4, 40, 4000, 2000, ["menzen_tsumo", "tanyao", "sanankou"], Level.MANGAN, **TSUMO),
    # 待ちの取り方: 12＋3 の辺張（リーチのみ 40 符 1300）より、45＋3 の両面（リーチ・平和 30 符 2000）が高い
    case("高点法（待ちを両面に取る）", "12345m456p789s44z", "3m", 2, 30, 2000, yaku=["riichi", "pinfu"], **RIICHI),
    # 待ちの取り方: 4566 の 6。両面と読むと 20 ＋ 2 ＋ 8 ＝ 30 符、単騎と読むと 32 → 40 符
    case("高点法（待ちを単騎に取る）", "4566m123p789s111z", "6m", 2, 40, 1300, 700, ["menzen_tsumo", "yakuhai_round"], **TSUMO),
    # ---- 連風牌の雀頭: 30 ＋ 暗刻 8 ＋ 雀頭 4 ＝ 42 → 50 符。雀頭 2 符のルールなら 40 → 40 符
    case("連風牌の雀頭 4 符", "111m456p789s23s11z", "4s", 1, 50, 2400, yaku=["riichi"], **RIICHI, **DEALER),
    case("連風牌の雀頭 2 符", "111m456p789s23s11z", "4s", 1, 40, 2000, yaku=["riichi"], rules=Rules(double_wind_pair_fu=2), **RIICHI, **DEALER),
    # 自風だけ（南場の東家）なら、どちらのルールでも 2 符 → 40 符
    case("自風の雀頭は 2 符", "111m456p789s23s11z", "4s", 1, 40, 2000, **RIICHI, seat_wind=EAST, round_wind=SOUTH),
    # ---- 喰い下がり
    case("三色同順（門前 2 翻）", "234m234p23s789m44z", "4s", 3, 30, 3900, yaku=["sanshoku", "pinfu"]),
    case("三色同順（鳴いて 1 翻）", "234m23s789m44z", "4s", 1, 30, 1000, yaku=["sanshoku"], melds=["chi 234p"]),
    case("一気通貫（門前 2 翻）", "123456789m23s44z", "4s", 3, 30, 3900, yaku=["ittsu", "pinfu"]),
    case("一気通貫（鳴いて 1 翻）", "123456m23s44z", "4s", 1, 30, 1000, yaku=["ittsu"], melds=["chi 789m"]),
]


@pytest.mark.parametrize("c", CASES, ids=str)
def test_score(c: Case):
    ctx = make_context(c.hand, c.win, **c.kw)

    verdict = judge(ctx, c.rules)
    assert verdict.ok, verdict.error
    assert (verdict.han, verdict.fu) == (c.han, c.fu)
    assert (verdict.main, verdict.additional) == (c.main, c.additional)
    assert verdict.level is c.level
    if c.yaku:
        assert sorted(y.key for y in verdict.yaku) == sorted(c.yaku)

    result = explain(ctx, c.rules)
    assert result.status is Status.WIN
    assert result.consistent, result.mismatches
    best = result.best
    assert best is not None and best.points is not None
    assert (best.han, best.fu.fu) == (c.han, c.fu)
    assert (best.points.main, best.points.additional) == (c.main, c.additional)
    assert best.points.level is c.level
    if c.yaku:
        assert sorted(y.key for y in best.evaluation.yaku) == sorted(c.yaku)


# ---------------------------------------------------------------- 役ごとの成立例

YAKU_CASES = [
    # (名前, 手牌, 和了牌, 成立する役, 状況)
    ("立直・一発", "123m456p789s23s44z", "4s", ["riichi", "ippatsu", "pinfu"], {"riichi": True, "ippatsu": True}),
    ("ダブル立直", "123m456p789s13s44z", "2s", ["double_riichi"], {"riichi": True, "double_riichi": True}),
    ("門前清自摸和", "123m456p789s13s44z", "2s", ["menzen_tsumo"], {"is_tsumo": True}),
    ("海底摸月", "123m456p789s13s44z", "2s", ["menzen_tsumo", "haitei"], {"is_tsumo": True, "haitei": True}),
    ("河底撈魚", "123m456p789s13s44z", "2s", ["houtei"], {"houtei": True}),
    ("槍槓", "123m456p789s13s44z", "2s", ["chankan"], {"chankan": True}),
    ("嶺上開花", "123m456p13s44z", "2s", ["rinshan", "menzen_tsumo"], {"is_tsumo": True, "rinshan": True, "melds": ["ankan 9999s"]}),
    ("大三元", "23m55p", "1m", ["daisangen"], {"melds": ["pon 555z", "pon 666z", "pon 777z"]}),
    ("役牌 發", "123m456p23s99p", "4s", ["yakuhai_hatsu"], {"melds": ["pon 666z"]}),
    ("自風牌", "123m456p23s99p", "4s", ["yakuhai_seat"], {"melds": ["pon 222z"]}),
    ("場風牌", "123m456p23s99p", "4s", ["yakuhai_round"], {"melds": ["pon 111z"]}),
    ("連風牌（自風＋場風）", "123m456p23s99p", "4s", ["yakuhai_seat", "yakuhai_round"], {"melds": ["pon 111z"], "seat_wind": EAST}),
    ("三色同刻", "222s456m9p", "9p", ["sanshoku_doukou"], {"melds": ["pon 222m", "pon 222p"]}),
    ("対々和", "666s88s99m", "9m", ["toitoi"], {"melds": ["pon 222m", "pon 444p"]}),
    ("三暗刻", "222m444p666s78s99m", "9s", ["sanankou"], {}),
    ("混全帯么九", "123m789p12s99m111z", "3s", ["chanta", "yakuhai_round"], {}),
    ("純全帯么九", "123789m123p78s99p", "9s", ["junchan", "pinfu"], {}),
    ("三槓子", "45m99s", "6m", ["sankantsu"], {"melds": ["ankan 1111m", "minkan 2222p", "kakan 3333s"]}),
    ("小三元", "234m45p77z", "6p", ["shousangen", "yakuhai_haku", "yakuhai_hatsu"], {"melds": ["pon 555z", "pon 666z"]}),
    ("混老頭", "111s99m44z", "4z", ["honroutou", "toitoi"], {"melds": ["pon 111m", "pon 999p"]}),
    ("二盃口", "223344m556677p8s", "8s", ["ryanpeikou", "tanyao"], {}),
    ("混一色（門前）", "123345678m33z44z", "4z", ["honitsu"], {}),
    ("清一色（鳴き）", "345m678m5m", "5m", ["chinitsu"], {"melds": ["chi 123m", "pon 999m"]}),
    ("七対子＋断么九", "2244m3366p5577s8s", "8s", ["chiitoitsu", "tanyao"], {}),
    ("七対子＋混老頭", "1199m1199p11s11z7z", "7z", ["chiitoitsu", "honroutou"], {}),
    ("天和", "123m456p789s13s44z", "2s", ["tenhou"], {"is_tsumo": True, "tenhou": True, "seat_wind": EAST}),
    ("地和", "123m456p789s13s44z", "2s", ["chiihou"], {"is_tsumo": True, "chiihou": True}),
    ("四暗刻", "222m444p666s77s88m", "7s", ["suuankou"], {"is_tsumo": True}),
    ("四暗刻単騎", "111m333p555s777s2z", "2z", ["suuankou_tanki"], {}),
    ("字一色", "111222333z55z66z", "6z", ["tsuuiisou"], {}),
    ("小四喜", "111222333z4z567m", "4z", ["shousuushii"], {}),
    ("大四喜", "44z55m", "4z", ["daisuushii"], {"melds": ["pon 111z", "pon 222z", "pon 333z"]}),
    ("緑一色", "223344s666s888s6z", "6z", ["ryuuiisou"], {}),
    ("清老頭", "999p1s", "1s", ["chinroutou"], {"melds": ["pon 111m", "pon 999m", "pon 111p"]}),
    ("九蓮宝燈", "1112345678899m", "9m", ["chuuren"], {}),
    ("純正九蓮宝燈", "1112345678999m", "5m", ["junsei_chuuren"], {}),
    ("四槓子", "5z", "5z", ["suukantsu"], {"melds": ["ankan 1111m", "minkan 2222p", "kakan 3333s", "ankan 4444z"]}),
    ("大三元＋字一色（役満の複合）", "11z22z", "1z", ["daisangen", "tsuuiisou"], {"melds": ["pon 555z", "pon 666z", "pon 777z"]}),
]


@pytest.mark.parametrize(("name", "hand", "win", "yaku", "kw"), YAKU_CASES, ids=[c[0] for c in YAKU_CASES])
def test_yaku_examples(name, hand, win, yaku, kw):
    kw = {**CHILD, **kw}
    ctx = make_context(hand, win, **kw)
    verdict = judge(ctx)
    assert verdict.ok, verdict.error
    assert sorted(y.key for y in verdict.yaku) == sorted(yaku)
    result = explain(ctx)
    assert result.consistent, result.mismatches
    assert sorted(y.key for y in result.best.evaluation.yaku) == sorted(yaku)


def test_every_yaku_has_an_example():
    """役の表にあるすべての役が、上の例のどこかで成立している"""
    from engine.yaku_table import YAKU

    covered = {key for c in CASES for key in c.yaku} | {key for c in YAKU_CASES for key in c[3]}
    assert set(YAKU) - covered == set()


# ---------------------------------------------------------------- 和了れない形


def test_no_yaku_is_reported():
    # 門前でロン、リーチなし。雀頭の東が場風なので平和にもならない → 役なし
    ctx = make_context("123m456p789s23s11z", "4s", **CHILD)
    assert judge(ctx).error is JudgeError.NO_YAKU
    result = explain(ctx)
    assert result.status is Status.NO_YAKU and result.consistent
    assert result.best is None
    assert result.candidates and not result.candidates[0].has_yaku


def test_dora_alone_is_not_a_yaku():
    # ドラが 3 枚あっても、役がなければ和了れない
    ctx = make_context("123m456p789s23s11z", "4s", dora="9m3p6s", **CHILD)
    assert judge(ctx).error is JudgeError.NO_YAKU
    assert explain(ctx).status is Status.NO_YAKU


def test_kuitan_off_makes_open_tanyao_no_yaku():
    ctx = make_context("234m55p34s", "5s", melds=["pon 888m", "chi 678p"], **CHILD)
    assert judge(ctx, Rules(kuitan=False)).error is JudgeError.NO_YAKU
    result = explain(ctx, Rules(kuitan=False))
    assert result.status is Status.NO_YAKU and result.consistent


def test_not_winning_shape_is_reported():
    ctx = make_context("123m456p789s23s19p", "4s", **CHILD)
    assert judge(ctx).error is JudgeError.NOT_WINNING
    result = explain(ctx)
    assert result.status is Status.NOT_WINNING and result.consistent
    assert result.candidates == ()


# ---------------------------------------------------------------- 本場・供託・ドラ


def test_honba_and_kyotaku_on_ron():
    # リーチ・平和・断么九 ＝ 3 翻 30 符 ＝ 3900。2 本場で ＋600、供託 1 本で ＋1000
    ctx = make_context("234567m234p67s55s", "8s", riichi=True, honba=2, kyotaku=1, **CHILD)
    verdict = judge(ctx)
    assert (verdict.han, verdict.fu, verdict.main) == (3, 30, 3900)
    assert (verdict.honba_main, verdict.kyotaku_bonus, verdict.total) == (600, 1000, 5500)
    points = explain(ctx).best.points
    assert (points.main, points.honba_main, points.kyotaku_bonus, points.total) == (3900, 600, 1000, 5500)
    assert points.declaration == "3900は4500"
    assert [(p.payer, p.count, p.points) for p in points.payments] == [("放銃者", 1, 4500)]


def test_honba_on_tsumo():
    # リーチ・ツモ・平和・断么九 ＝ 4 翻 20 符 → 基本点 1280。親 2600、子 1300。1 本場で各 ＋100
    ctx = make_context("234567m234p67s55s", "8s", riichi=True, is_tsumo=True, honba=1, **CHILD)
    verdict = judge(ctx)
    assert (verdict.han, verdict.fu, verdict.main, verdict.additional) == (4, 20, 2600, 1300)
    assert (verdict.honba_main, verdict.honba_additional, verdict.total) == (100, 100, 5500)
    points = explain(ctx).best.points
    assert points.declaration == "1300・2600は1400・2700"
    assert [(p.payer, p.count, p.points) for p in points.payments] == [("親", 1, 2700), ("子", 2, 1400)]
    assert points.total == 5500


def test_dora_aka_and_ura():
    # ドラ表示牌 4萬 → ドラは 5萬。手牌に 5萬 が 2 枚（うち 1 枚は赤）→ ドラ 2 ＋ 赤 1
    # 裏ドラ表示牌 北 → 裏ドラは 東。手牌に東は無い → 0
    ctx = make_context("0m345567p234678s", "5m", dora="4m", ura="4z", riichi=True, **CHILD)
    verdict = judge(ctx)
    assert (verdict.dora, verdict.aka_dora, verdict.ura_dora) == (2, 1, 0)
    result = explain(ctx)
    assert result.consistent
    assert (result.dora.dora, result.dora.aka, result.dora.ura) == (2, 1, 0)
    assert result.best.dora_han == 3


def test_ura_dora_needs_riichi():
    hand, win = "234m567p234s67s88s", "5s"
    with_riichi = make_context(hand, win, dora="1z", ura="7s", riichi=True, **CHILD)
    assert judge(with_riichi).ura_dora == 2          # 裏ドラ表示牌 7索 → 8索 が 2 枚
    assert explain(with_riichi).dora.ura == 2
    without = make_context(hand, win, dora="1z", ura="7s", is_tsumo=True, **CHILD)
    assert judge(without).ura_dora == 0              # リーチしていなければ裏ドラは無い
    assert explain(without).dora.ura == 0


def test_aka_dora_off():
    # 赤ドラなしのルールでは、牌ID 16（萬子の 5 の 1 枚目）もふつうの 5萬
    ctx = make_context("340m567p234s67s88s", "5s", riichi=True, **CHILD)
    assert judge(ctx, Rules(aka_dora=True)).aka_dora == 1
    assert judge(ctx, Rules(aka_dora=False)).aka_dora == 0
    assert explain(ctx, Rules(aka_dora=False)).dora.aka == 0


def test_yakuman_ignores_dora_and_other_yaku():
    ctx = make_context("222m444p666s77s88m", "7s", is_tsumo=True, riichi=True, dora="1m6s", **CHILD)
    verdict = judge(ctx)
    assert [y.key for y in verdict.yaku] == ["suuankou"]
    assert (verdict.dora, verdict.yakuman_times, verdict.main, verdict.additional) == (0, 1, 16000, 8000)
    result = explain(ctx)
    assert result.consistent
    assert result.best.dora_han == 0
    assert {y.key for y in result.best.evaluation.ignored} >= {"riichi", "menzen_tsumo", "tanyao", "toitoi"}


# ---------------------------------------------------------------- 判定ライブラリの癖への対処


def test_double_yakuman_setting_does_not_leak_between_calls():
    ctx = make_context("19m19p19s1234567z", "1m", **CHILD)
    assert judge(ctx, Rules(double_yakuman=False)).main == 32000
    assert judge(ctx, Rules(double_yakuman=True)).main == 64000
    assert judge(ctx, Rules(double_yakuman=False)).main == 32000


def test_dora_count_does_not_leak_between_calls():
    with_dora = make_context("123456m234p67s55s", "8s", dora="4s", riichi=True, **CHILD)
    without = make_context("123456m234p67s55s", "8s", riichi=True, **CHILD)
    first = judge(with_dora)
    second = judge(without)
    assert (first.dora, first.han) == (2, 4)
    assert (second.dora, second.han) == (0, 2)


def test_yakuman_beats_counted_han_reading():
    """四暗刻（役満）の読み方が、ドラの多い 15 翻の読み方より優先される。

    333萬 333444555筒 44索 を 3萬 でツモ。刻子 4 つと読めば四暗刻。
    345筒 × 3 と読むと ダブル立直 2 ＋ 一発 1 ＋ ツモ 1 ＋ 断么九 1 ＋ 一盃口 1 ＋ ドラ 9 ＝ 15 翻。
    ライブラリは翻数の大きい読み方を選ぶので、そのままだと数え役満（なしのルールでは三倍満）になる。
    """
    ctx = make_context(
        "33m333444555p44s", "3m",
        dora="2m2p2p", is_tsumo=True, riichi=True, double_riichi=True, ippatsu=True, seat_wind=WEST,
    )
    for rules in (Rules(), Rules(kazoe_yakuman=False)):
        verdict = judge(ctx, rules)
        assert [y.key for y in verdict.yaku] == ["suuankou"]
        assert (verdict.yakuman_times, verdict.main, verdict.additional) == (1, 16000, 8000)
        result = explain(ctx, rules)
        assert result.consistent, result.mismatches
        assert [y.key for y in result.best.evaluation.yaku] == ["suuankou"]
        other = result.candidates[1]
        assert other.han >= 13 and not other.is_yakuman

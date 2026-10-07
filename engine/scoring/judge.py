"""判定ライブラリ（mahjong）への窓口。

和了の成否・役・符・点数の「正解」は、ここを通して mahjong ライブラリに決めてもらう。
ライブラリを呼ぶのはこのファイルだけにして、癖への対処を 1 か所にまとめる。

  * 設定オブジェクト（HandConfig）は呼ぶたびに新しく作る。使い回すと、前の結果に入っている
    ドラの翻数が後の計算で書き換わるため。結果はすぐに自前の不変データへ写し取る。
  * 連風牌の雀頭はライブラリでは常に 4 符。「2 符」のルールのときは、返ってきた符の内訳を直して
    点数を計算し直す（字牌の対子はどの分解でも雀頭になるので、高点法の選び方は変わらない）。
  * ライブラリは手牌の読み方を「翻 → 符」の大きい順で選ぶ。役満は 13 翻として数えるので、
    ドラが多くて 14 翻以上になる別の読み方（数え役満・三倍満）があると、そちらを選んでしまう。
    例: 333萬 333444555筒 44索 のツモ（四暗刻）を、345筒 × 3 の一盃口＋ドラ 8 の 14 翻と読む。
    13 翻以上で役満でない結果が返ったときは、ドラと偶然役を外してもう一度判定し、
    役満の読み方があればそちらを採る（役満は数え役満より高いか同点で、名前も役満が優先される）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.hand_calculating.scores import ScoresCalculator
from mahjong.meld import Meld as LibraryMeld

from engine.melds import Meld, MeldType
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.yaku_table import (
    LIBRARY_AKA_DORA_ID,
    LIBRARY_DORA_ID,
    LIBRARY_ID_TO_KEY,
    LIBRARY_URA_DORA_ID,
    YAKUMAN_HAN,
)


class Level(StrEnum):
    """点数の区分"""

    NONE = "none"                    # 満貫未満
    MANGAN = "mangan"                # 満貫
    HANEMAN = "haneman"              # 跳満
    BAIMAN = "baiman"                # 倍満
    SANBAIMAN = "sanbaiman"          # 三倍満
    KAZOE_YAKUMAN = "kazoe_yakuman"  # 数え役満
    YAKUMAN = "yakuman"              # 役満（何倍かは yakuman_times）


class JudgeError(StrEnum):
    NOT_WINNING = "not_winning"   # 和了の形になっていない
    NO_YAKU = "no_yaku"           # 形はできているが役がない
    INVALID = "invalid"           # 状況の指定がおかしい


@dataclass(frozen=True)
class JudgedYaku:
    key: str     # engine.yaku_table.YAKU の名前
    han: int     # この手での翻数（鳴いていれば喰い下がり後。役満は 13 × 倍数）


@dataclass(frozen=True)
class Judgement:
    """ライブラリによる判定結果"""

    error: JudgeError | None = None
    han: int = 0                      # 役とドラを合わせた翻数
    fu: int = 0
    yaku: tuple[JudgedYaku, ...] = ()
    dora: int = 0
    aka_dora: int = 0
    ura_dora: int = 0
    fu_details: tuple[tuple[str, int], ...] = ()   # ライブラリの符の内訳（理由の名前、符）
    level: Level = Level.NONE
    yakuman_times: int = 0            # 役満の倍数（役満でなければ 0）
    is_open: bool = False
    #: ロンなら放銃者が払う点。ツモなら親が払う点（親のツモなら子 1 人が払う点）。本場ぶんは含まない
    main: int = 0
    #: ツモで子 1 人が払う点（ロンなら 0）。本場ぶんは含まない
    additional: int = 0
    honba_main: int = 0               # main に上乗せされる本場ぶん
    honba_additional: int = 0         # additional に上乗せされる本場ぶん
    kyotaku_bonus: int = 0            # 供託のリーチ棒ぶん
    total: int = 0                    # 和了者が受け取る合計

    @property
    def ok(self) -> bool:
        return self.error is None


_ERRORS = {
    HandCalculator.ERR_HAND_NOT_WINNING: JudgeError.NOT_WINNING,
    HandCalculator.ERR_NO_YAKU: JudgeError.NO_YAKU,
}

_DOUBLE_WIND_PAIR = "double_valued_pair"
_SINGLE_WIND_PAIR = "valued_pair"


def _library_meld(meld: Meld) -> LibraryMeld:
    if meld.type is MeldType.CHI:
        return LibraryMeld(meld_type=LibraryMeld.CHI, tiles=meld.tiles, opened=True)
    if meld.type is MeldType.PON:
        return LibraryMeld(meld_type=LibraryMeld.PON, tiles=meld.tiles, opened=True)
    if meld.type is MeldType.KAKAN:
        return LibraryMeld(meld_type=LibraryMeld.SHOUMINKAN, tiles=meld.tiles, opened=True)
    return LibraryMeld(meld_type=LibraryMeld.KAN, tiles=meld.tiles, opened=meld.type is MeldType.MINKAN)


def _library_config(ctx: WinContext, rules: Rules, *, yakuman_only: bool = False) -> HandConfig:
    """ライブラリに渡す設定。yakuman_only なら、役満の成否に関係しないもの（ドラと偶然役）を外す"""
    plain = not yakuman_only
    options = OptionalRules(
        has_open_tanyao=rules.kuitan,
        has_aka_dora=rules.aka_dora and plain,
        has_double_yakuman=rules.double_yakuman,
        kazoe_limit=HandConfig.KAZOE_LIMITED if rules.kazoe_yakuman else HandConfig.KAZOE_SANBAIMAN,
        kiriage=rules.kiriage_mangan,
    )
    return HandConfig(
        is_tsumo=ctx.is_tsumo,
        is_riichi=ctx.riichi and plain,
        is_ippatsu=ctx.ippatsu and plain,
        is_rinshan=ctx.rinshan and plain,
        is_chankan=ctx.chankan and plain,
        is_haitei=ctx.haitei and plain,
        is_houtei=ctx.houtei and plain,
        is_daburu_riichi=ctx.double_riichi and plain,
        is_tenhou=ctx.tenhou,
        is_chiihou=ctx.chiihou,
        player_wind=ctx.seat_wind,
        round_wind=ctx.round_wind,
        kyoutaku_number=ctx.kyotaku,
        tsumi_number=ctx.honba,
        options=options,
    )


def level_of(han: int, fu: int, yakuman_times: int, rules: Rules) -> Level:
    """翻・符から点数の区分を決める（表示用。点数そのものはライブラリの値を使う）"""
    if yakuman_times:
        return Level.YAKUMAN
    if han >= YAKUMAN_HAN:
        return Level.KAZOE_YAKUMAN if rules.kazoe_yakuman else Level.SANBAIMAN
    if han >= 11:
        return Level.SANBAIMAN
    if han >= 8:
        return Level.BAIMAN
    if han >= 6:
        return Level.HANEMAN
    if han == 5:
        return Level.MANGAN
    if fu * 2 ** (han + 2) > 2000:
        return Level.MANGAN
    if rules.kiriage_mangan and (han, fu) in ((4, 30), (3, 60)):
        return Level.MANGAN
    return Level.NONE


def judge(ctx: WinContext, rules: Rules = DEFAULT_RULES) -> Judgement:
    """和了の状況をライブラリに渡し、役・符・点数を受け取る"""
    result = _judge_once(ctx, rules, yakuman_only=False)
    if result.ok and not result.yakuman_times and result.han >= YAKUMAN_HAN:
        # 13 翻以上の「役満でない読み方」が選ばれた。役満の読み方が隠れていないか確かめる
        yakuman = _judge_once(ctx, rules, yakuman_only=True)
        if yakuman.ok and yakuman.yakuman_times:
            return yakuman
    return result


def _judge_once(ctx: WinContext, rules: Rules, *, yakuman_only: bool) -> Judgement:
    config = _library_config(ctx, rules, yakuman_only=yakuman_only)
    response = HandCalculator.estimate_hand_value(
        list(ctx.all_tiles),
        ctx.win_tile,
        melds=[_library_meld(m) for m in ctx.melds],
        dora_indicators=[] if yakuman_only else list(ctx.dora_indicators),
        ura_dora_indicators=[] if yakuman_only else list(ctx.ura_indicators),
        config=config,
    )
    if response.error:
        return Judgement(error=_ERRORS.get(response.error, JudgeError.INVALID))

    is_open = response.is_open_hand
    yaku: list[JudgedYaku] = []
    dora = aka = ura = 0
    yakuman_times = 0
    for item in response.yaku:   # ここで値を写し取る（ライブラリ側のオブジェクトは後で書き換わり得る）
        han = item.han_open if is_open and item.han_open else item.han_closed
        if item.yaku_id == LIBRARY_DORA_ID:
            dora = han
        elif item.yaku_id == LIBRARY_AKA_DORA_ID:
            aka = han
        elif item.yaku_id == LIBRARY_URA_DORA_ID:
            ura = han
        else:
            yaku.append(JudgedYaku(LIBRARY_ID_TO_KEY[item.yaku_id], han))
            if item.is_yakuman:
                yakuman_times += han // YAKUMAN_HAN

    han_total = int(response.han)
    fu = int(response.fu)
    fu_details = tuple((d["reason"], int(d["fu"])) for d in (response.fu_details or []))
    cost = dict(response.cost)

    if rules.double_wind_pair_fu == 2 and any(reason == _DOUBLE_WIND_PAIR for reason, _ in fu_details):
        fu_details = tuple(
            (_SINGLE_WIND_PAIR, 2) if reason == _DOUBLE_WIND_PAIR else (reason, value) for reason, value in fu_details
        )
        fu = (sum(value for _, value in fu_details) + 9) // 10 * 10
        cost = dict(ScoresCalculator.calculate_scores(han_total, fu, config, yakuman_times > 0))

    return Judgement(
        han=han_total,
        fu=fu,
        yaku=tuple(yaku),
        dora=dora,
        aka_dora=aka,
        ura_dora=ura,
        fu_details=fu_details,
        level=level_of(han_total, fu, yakuman_times, rules),
        yakuman_times=yakuman_times,
        is_open=is_open,
        main=int(cost["main"]),
        additional=int(cost["additional"]),
        honba_main=int(cost["main_bonus"]),
        honba_additional=int(cost["additional_bonus"]),
        kyotaku_bonus=int(cost["kyoutaku_bonus"]),
        total=int(cost["total"]),
    )

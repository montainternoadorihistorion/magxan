"""役の一覧（名前・読み・翻数）。

翻数は判定ライブラリ（mahjong）の値と一致することをテストで確かめる。
役満は「何倍の役満か」を yakuman に持つ（1 = 役満、2 = ダブル役満）。翻数として数えるときは 13 × 倍数。
"""
from __future__ import annotations

from dataclasses import dataclass

YAKUMAN_HAN = 13


@dataclass(frozen=True)
class YakuInfo:
    key: str            # プログラム内で役を指す名前
    name: str           # 日本語の役名
    reading: str        # 読み（カタカナ）
    han_closed: int     # 門前での翻数
    han_open: int       # 鳴いたときの翻数（0 = 門前限定）
    yakuman: int = 0    # 役満の倍数（0 = 通常の役）
    library_id: int | None = None   # mahjong ライブラリでの役の番号（照合用）
    spoken: str = ""    # 卓で役を数え上げるときの言い方（例: タンヤオ、ホンイツ）。風牌の役は風の名前で言う

    @property
    def closed_only(self) -> bool:
        return self.han_open == 0

    @property
    def kuisagari(self) -> bool:
        """喰い下がり（鳴くと 1 翻下がる）か"""
        return 0 < self.han_open < self.han_closed


def _yaku(key: str, name: str, reading: str, closed: int, opened: int, library_id: int | None, spoken: str = "") -> YakuInfo:
    return YakuInfo(key, name, reading, closed, opened, 0, library_id, spoken or reading)


def _yakuman(key: str, name: str, reading: str, times: int, opened: bool, library_id: int) -> YakuInfo:
    han = YAKUMAN_HAN * times
    return YakuInfo(key, name, reading, han, han if opened else 0, times, library_id, reading.replace(" ", ""))


_ALL = [
    # ---- 1 翻
    _yaku("riichi", "立直", "リーチ", 1, 0, 1),
    _yaku("ippatsu", "一発", "イッパツ", 1, 0, 3),
    _yaku("menzen_tsumo", "門前清自摸和", "メンゼンチンツモホー", 1, 0, 0, "ツモ"),
    _yaku("pinfu", "平和", "ピンフ", 1, 0, 12),
    _yaku("tanyao", "断么九", "タンヤオチュー", 1, 1, 13, "タンヤオ"),
    _yaku("iipeikou", "一盃口", "イーペーコー", 1, 0, 14),
    _yaku("yakuhai_haku", "役牌 白", "ヤクハイ ハク", 1, 1, 15, "ハク"),
    _yaku("yakuhai_hatsu", "役牌 發", "ヤクハイ ハツ", 1, 1, 16, "ハツ"),
    _yaku("yakuhai_chun", "役牌 中", "ヤクハイ チュン", 1, 1, 17, "チュン"),
    _yaku("yakuhai_seat", "自風牌", "ジカゼハイ", 1, 1, None, "自風"),     # ライブラリでは風ごとに別の番号（18〜21）
    _yaku("yakuhai_round", "場風牌", "バカゼハイ", 1, 1, None, "場風"),    # 同上（22〜25）
    _yaku("rinshan", "嶺上開花", "リンシャンカイホー", 1, 1, 5, "リンシャン"),
    _yaku("chankan", "槍槓", "チャンカン", 1, 1, 4, "チャンカン"),
    _yaku("haitei", "海底摸月", "ハイテイモーユエ", 1, 1, 6, "ハイテイ"),
    _yaku("houtei", "河底撈魚", "ホウテイラオユイ", 1, 1, 7, "ホウテイ"),
    # ---- 2 翻
    _yaku("double_riichi", "ダブル立直", "ダブルリーチ", 2, 0, 8),
    _yaku("chiitoitsu", "七対子", "チートイツ", 2, 0, 34),
    _yaku("toitoi", "対々和", "トイトイホー", 2, 2, 30, "トイトイ"),
    _yaku("sanankou", "三暗刻", "サンアンコー", 2, 2, 31),
    _yaku("sanshoku", "三色同順", "サンショクドウジュン", 2, 1, 26, "サンショク"),
    _yaku("sanshoku_doukou", "三色同刻", "サンショクドウコー", 2, 2, 33),
    _yaku("ittsu", "一気通貫", "イッキツウカン", 2, 1, 27, "イッツー"),
    _yaku("chanta", "混全帯么九", "ホンチャンタイヤオチュー", 2, 1, 28, "チャンタ"),
    _yaku("sankantsu", "三槓子", "サンカンツ", 2, 2, 32),
    _yaku("shousangen", "小三元", "ショウサンゲン", 2, 2, 35),
    _yaku("honroutou", "混老頭", "ホンロートー", 2, 2, 29),
    # ---- 3 翻
    _yaku("ryanpeikou", "二盃口", "リャンペーコー", 3, 0, 38),
    _yaku("honitsu", "混一色", "ホンイーソー", 3, 2, 36, "ホンイツ"),
    _yaku("junchan", "純全帯么九", "ジュンチャンタイヤオチュー", 3, 2, 37, "ジュンチャン"),
    # ---- 6 翻
    _yaku("chinitsu", "清一色", "チンイーソー", 6, 5, 39, "チンイツ"),
    # ---- 役満
    _yakuman("tenhou", "天和", "テンホー", 1, False, 115),
    _yakuman("chiihou", "地和", "チーホー", 1, False, 116),
    _yakuman("kokushi", "国士無双", "コクシムソウ", 1, False, 100),
    _yakuman("kokushi_13", "国士無双十三面待ち", "コクシムソウ ジュウサンメンマチ", 2, False, 112),
    _yakuman("suuankou", "四暗刻", "スーアンコー", 1, False, 102),
    _yakuman("suuankou_tanki", "四暗刻単騎", "スーアンコー タンキ", 2, False, 113),
    _yakuman("daisangen", "大三元", "ダイサンゲン", 1, True, 103),
    _yakuman("tsuuiisou", "字一色", "ツーイーソー", 1, True, 107),
    _yakuman("shousuushii", "小四喜", "ショウスーシー", 1, True, 104),
    _yakuman("daisuushii", "大四喜", "ダイスーシー", 2, True, 111),
    _yakuman("ryuuiisou", "緑一色", "リューイーソー", 1, True, 105),
    _yakuman("chinroutou", "清老頭", "チンロートー", 1, True, 108),
    _yakuman("chuuren", "九蓮宝燈", "チューレンポートー", 1, False, 101),
    _yakuman("junsei_chuuren", "純正九蓮宝燈", "ジュンセイ チューレンポートー", 2, False, 114),
    _yakuman("suukantsu", "四槓子", "スーカンツ", 1, True, 106),
]

YAKU: dict[str, YakuInfo] = {info.key: info for info in _ALL}

#: ルールで「ダブル役満なし」のとき、1 倍として数える役
DOUBLE_YAKUMAN_KEYS = frozenset(key for key, info in YAKU.items() if info.yakuman == 2)

#: ライブラリの役番号 → こちらの役の名前
LIBRARY_ID_TO_KEY: dict[int, str] = {info.library_id: key for key, info in YAKU.items() if info.library_id is not None}
LIBRARY_ID_TO_KEY.update({18: "yakuhai_seat", 19: "yakuhai_seat", 20: "yakuhai_seat", 21: "yakuhai_seat"})
LIBRARY_ID_TO_KEY.update({22: "yakuhai_round", 23: "yakuhai_round", 24: "yakuhai_round", 25: "yakuhai_round"})

#: ライブラリが「役」として返すドラの番号
LIBRARY_DORA_ID = 120
LIBRARY_AKA_DORA_ID = 121
LIBRARY_URA_DORA_ID = 122


def han_of(key: str, *, is_open: bool, double_yakuman: bool = True) -> int:
    """その役の翻数（鳴いているかどうかで変わる）。成立しない組み合わせなら 0"""
    info = YAKU[key]
    if info.yakuman == 2 and not double_yakuman:
        return YAKUMAN_HAN if (info.han_open or not is_open) else 0
    return info.han_open if is_open else info.han_closed

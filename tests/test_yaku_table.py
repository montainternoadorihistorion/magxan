"""役の表のテスト（翻数が判定ライブラリと同じであること）"""
from __future__ import annotations

from mahjong.hand_calculating.hand_config import HandConfig

from engine.yaku_table import DOUBLE_YAKUMAN_KEYS, LIBRARY_ID_TO_KEY, YAKU, YAKUMAN_HAN, han_of


def _library_yaku():
    config = HandConfig()
    return {y.yaku_id: y for y in vars(config.yaku).values() if hasattr(y, "yaku_id")}


def test_han_matches_library():
    library = _library_yaku()
    checked = 0
    for yaku_id, key in LIBRARY_ID_TO_KEY.items():
        item = library[yaku_id]
        info = YAKU[key]
        assert (item.han_closed or 0) == info.han_closed, key
        assert (item.han_open or 0) == info.han_open, key
        assert bool(item.is_yakuman) == (info.yakuman > 0), key
        checked += 1
    assert checked == len(LIBRARY_ID_TO_KEY) >= len(YAKU)


def test_every_yaku_is_linked_to_library():
    linked = set(LIBRARY_ID_TO_KEY.values())
    assert linked == set(YAKU)


def test_names_and_readings():
    for key, info in YAKU.items():
        assert info.name and info.reading and info.spoken, key
        assert all("ァ" <= ch <= "ヿ" or ch == " " for ch in info.reading), (key, info.reading)   # 読みはカタカナ
    assert len({info.name for info in YAKU.values()}) == len(YAKU)


def test_han_of():
    assert han_of("sanshoku", is_open=False) == 2
    assert han_of("sanshoku", is_open=True) == 1           # 喰い下がり
    assert han_of("pinfu", is_open=True) == 0               # 門前限定
    assert han_of("tanyao", is_open=True) == 1
    assert han_of("chinitsu", is_open=False) == 6 and han_of("chinitsu", is_open=True) == 5
    assert han_of("daisangen", is_open=True) == YAKUMAN_HAN
    assert han_of("suuankou", is_open=True) == 0            # 門前限定の役満
    assert han_of("daisuushii", is_open=True) == 2 * YAKUMAN_HAN
    assert han_of("daisuushii", is_open=True, double_yakuman=False) == YAKUMAN_HAN
    assert han_of("suuankou_tanki", is_open=False, double_yakuman=False) == YAKUMAN_HAN
    assert han_of("suuankou_tanki", is_open=True, double_yakuman=False) == 0


def test_kuisagari_and_closed_only():
    assert YAKU["sanshoku"].kuisagari and YAKU["ittsu"].kuisagari and YAKU["chanta"].kuisagari
    assert YAKU["honitsu"].kuisagari and YAKU["junchan"].kuisagari and YAKU["chinitsu"].kuisagari
    assert not YAKU["tanyao"].kuisagari and not YAKU["toitoi"].kuisagari
    assert YAKU["riichi"].closed_only and YAKU["pinfu"].closed_only and YAKU["iipeikou"].closed_only
    assert YAKU["chiitoitsu"].closed_only and YAKU["ryanpeikou"].closed_only
    assert DOUBLE_YAKUMAN_KEYS == {"kokushi_13", "suuankou_tanki", "daisuushii", "junsei_chuuren"}

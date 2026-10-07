"""牌の表現（engine/tiles.py）のテスト"""
import pytest
from mahjong.constants import FIVE_RED_MAN, FIVE_RED_PIN, FIVE_RED_SOU
from mahjong.tile import TilesConverter

from engine import tiles as T


def test_ids_match_the_judge_library():
    """牌IDの割り当てが、判定を任せる mahjong ライブラリと同じであること"""
    assert T.RED_FIVE_IDS == {FIVE_RED_MAN, FIVE_RED_PIN, FIVE_RED_SOU}
    all_ids = list(range(T.NUM_TILES))
    assert T.counts34(all_ids) == TilesConverter.to_34_array(all_ids) == [4] * 34
    for kind in range(T.NUM_KINDS):
        code = T.code_of_kind(kind)
        expected = TilesConverter.one_line_string_to_34_array(code)
        assert expected[kind] == 1 and sum(expected) == 1


def test_kind_suit_number():
    assert [T.code_of_kind(k) for k in (0, 8, 9, 17, 18, 26, 27, 33)] == ["1m", "9m", "1p", "9p", "1s", "9s", "1z", "7z"]
    assert T.kind_of(135) == 33 and T.kind_of(0) == 0 and T.kind_of(16) == 4
    assert (T.EAST, T.SOUTH, T.WEST, T.NORTH, T.HAKU, T.HATSU, T.CHUN) == (27, 28, 29, 30, 31, 32, 33)


def test_names_are_unique_and_complete():
    names = [T.name_of_kind(k) for k in range(T.NUM_KINDS)]
    assert len(set(names)) == 34
    assert names[0] == "一萬" and names[13] == "五筒" and names[26] == "九索"
    assert names[27:] == ["東", "南", "西", "北", "白", "發", "中"]


def test_yaochu_classification():
    yaochu = [k for k in range(T.NUM_KINDS) if T.is_yaochu_kind(k)]
    assert yaochu == [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]
    assert [k for k in range(T.NUM_KINDS) if T.is_terminal_kind(k)] == [0, 8, 9, 17, 18, 26]
    assert [k for k in range(T.NUM_KINDS) if T.is_honor_kind(k)] == list(range(27, 34))


def test_red_five():
    assert T.is_red(16) and T.is_red(52) and T.is_red(88)
    assert not T.is_red(17) and not T.is_red(0)
    assert not T.is_red(16, aka=False)
    assert T.code_of(16) == "0m" and T.code_of(16, aka=False) == "5m" and T.code_of(17) == "5m"
    assert T.name_of(52) == "赤五筒" and T.name_of(52, aka=False) == "五筒" and T.name_of(53) == "五筒"


def test_parse_five_is_never_red_and_zero_is_always_red():
    """ライブラリの文字列変換では「5」の 1 枚目が赤5のIDになる。自前の変換ではそうならないこと"""
    assert T.parse_tiles("5m5p5s") == [17, 53, 89]
    assert T.parse_tiles("0m0p0s") == [16, 52, 88]
    assert T.parse_tiles("0555m") == [16, 17, 18, 19]
    assert T.parse_tiles("5055m") == [17, 16, 18, 19]
    assert T.parse_tiles("5555m", aka=False) == [16, 17, 18, 19]


def test_parse_assigns_distinct_physical_tiles():
    ids = T.parse_tiles("1111m 2222p 3333s 4444z")
    assert len(set(ids)) == 16
    assert T.counts34(ids)[0] == T.counts34(ids)[10] == T.counts34(ids)[20] == T.counts34(ids)[30] == 4


@pytest.mark.parametrize(
    "text",
    ["5555m", "00m", "11111p", "8z", "0z", "12", "m", "1x", "9", "１m", "50555s"],
)
def test_parse_rejects_impossible_hands(text):
    with pytest.raises(T.TileError):
        T.parse_tiles(text)


def test_parse_rejects_red_five_when_aka_is_off():
    with pytest.raises(T.TileError):
        T.parse_tiles("0m", aka=False)


def test_format_round_trip():
    for text in ["123m406p789s11z", "19m19p19s1234567z", "0555m", "22334455667788p", "5z"]:
        assert T.format_tiles(T.parse_tiles(text)) == text
    assert T.format_tiles([]) == ""
    assert T.format_tiles(T.parse_tiles("5m1z9s1m0p")) == "15m0p9s1z"


def test_sort_puts_red_five_first_among_fives():
    ids = T.parse_tiles("6m5m0m4m")
    assert [T.code_of(t) for t in T.sort_tiles(ids)] == ["4m", "0m", "5m", "6m"]


@pytest.mark.parametrize("bad", [-1, 136, 3.0, "1", None, True])
def test_invalid_tile_id_is_rejected(bad):
    with pytest.raises(T.TileError):
        T.kind_of(bad)

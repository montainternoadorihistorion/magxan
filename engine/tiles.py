"""牌の表現。

牌は 0〜135 の整数（「牌ID」）で表す。物理的な 136 枚それぞれに別の番号が付くので、
山を「0〜135 の並べ替え」として持てば、同じ牌が 5 枚になることも、存在しない牌が出ることも起きない。

番号の割り当ては mahjong ライブラリの 136 形式と同じにしてある（判定をそのまま任せるため）。

    種類(kind) = 牌ID // 4          0〜33 の 34 種類
        0〜 8  萬子（マンズ）の 1〜9
        9〜17  筒子（ピンズ）の 1〜9
       18〜26  索子（ソーズ）の 1〜9
       27〜33  東・南・西・北・白・發・中
    赤5        牌ID 16（萬）・52（筒）・88（索）＝ 各色の 5 の「1 枚目」

文字で書くときは「数字＋種別」の並び（mpsz 表記）を使う。
    1m〜9m  萬子 / 1p〜9p  筒子 / 1s〜9s  索子 / 1z〜7z  東南西北白發中 / 0m 0p 0s  赤5
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

NUM_TILES = 136
NUM_KINDS = 34
COPIES = 4

#: 赤5の牌ID（赤ドラありのルールで赤として扱う 3 枚）
RED_FIVE_IDS = frozenset({16, 52, 88})

SUIT_LETTERS = "mpsz"
_SUIT_START = {"m": 0, "p": 9, "s": 18, "z": 27}
_SUIT_SIZE = {"m": 9, "p": 9, "s": 9, "z": 7}

_KANJI_NUMBERS = "一二三四五六七八九"
_SUIT_KANJI = {"m": "萬", "p": "筒", "s": "索"}
_HONOR_NAMES = ("東", "南", "西", "北", "白", "發", "中")

EAST, SOUTH, WEST, NORTH, HAKU, HATSU, CHUN = range(27, 34)


class TileError(ValueError):
    """牌の指定がおかしいとき（存在しない牌、5 枚目の牌など）"""


# ---------------------------------------------------------------- 牌ID → 性質


def _check_id(tile_id: int) -> None:
    if not isinstance(tile_id, int) or isinstance(tile_id, bool) or not 0 <= tile_id < NUM_TILES:
        raise TileError(f"牌IDは 0〜135 の整数です: {tile_id!r}")


def _check_kind(kind: int) -> None:
    if not isinstance(kind, int) or isinstance(kind, bool) or not 0 <= kind < NUM_KINDS:
        raise TileError(f"牌の種類は 0〜33 の整数です: {kind!r}")


def kind_of(tile_id: int) -> int:
    """牌ID → 種類（0〜33）"""
    _check_id(tile_id)
    return tile_id // COPIES


def suit_of_kind(kind: int) -> str:
    """種類 → 種別の文字（m / p / s / z）"""
    _check_kind(kind)
    return "z" if kind >= 27 else SUIT_LETTERS[kind // 9]


def number_of_kind(kind: int) -> int:
    """種類 → その種別の中での数字（数牌は 1〜9、字牌は 1〜7）"""
    _check_kind(kind)
    return kind - 27 + 1 if kind >= 27 else kind % 9 + 1


def is_honor_kind(kind: int) -> bool:
    """字牌（東南西北白發中）か"""
    _check_kind(kind)
    return kind >= 27


def is_terminal_kind(kind: int) -> bool:
    """老頭牌（数牌の 1 と 9）か"""
    _check_kind(kind)
    return kind < 27 and kind % 9 in (0, 8)


def is_yaochu_kind(kind: int) -> bool:
    """么九牌（数牌の 1・9 と字牌）か"""
    return is_honor_kind(kind) or is_terminal_kind(kind)


def is_red(tile_id: int, *, aka: bool = True) -> bool:
    """赤5か。aka=False（赤ドラなしのルール）なら常に False"""
    _check_id(tile_id)
    return aka and tile_id in RED_FIVE_IDS


def code_of_kind(kind: int) -> str:
    """種類 → mpsz 表記（例: 4 → "5m"、27 → "1z"）"""
    return f"{number_of_kind(kind)}{suit_of_kind(kind)}"


def code_of(tile_id: int, *, aka: bool = True) -> str:
    """牌ID → mpsz 表記。赤5は "0m" のように 0 で書く"""
    kind = kind_of(tile_id)
    if is_red(tile_id, aka=aka):
        return f"0{suit_of_kind(kind)}"
    return code_of_kind(kind)


def name_of_kind(kind: int) -> str:
    """種類 → 日本語の名前（例: 4 → "五萬"、31 → "白"）"""
    _check_kind(kind)
    if kind >= 27:
        return _HONOR_NAMES[kind - 27]
    return _KANJI_NUMBERS[kind % 9] + _SUIT_KANJI[suit_of_kind(kind)]


def name_of(tile_id: int, *, aka: bool = True) -> str:
    """牌ID → 日本語の名前。赤5は "赤五萬" のように書く"""
    name = name_of_kind(kind_of(tile_id))
    return "赤" + name if is_red(tile_id, aka=aka) else name


def sort_key(tile_id: int) -> tuple[int, int]:
    """手牌を並べるときの順序。種類順。同じ種類の中では牌IDの小さい順（赤5が先頭に来る）"""
    return (kind_of(tile_id), tile_id)


def sort_tiles(tile_ids: Iterable[int]) -> list[int]:
    """理牌（リーパイ）: 手牌を見やすい順に並べる"""
    return sorted(tile_ids, key=sort_key)


def counts34(tile_ids: Iterable[int]) -> list[int]:
    """牌IDの集まり → 種類ごとの枚数（長さ 34 のリスト）"""
    counts = [0] * NUM_KINDS
    for tile_id in tile_ids:
        counts[kind_of(tile_id)] += 1
    return counts


# ---------------------------------------------------------------- 文字 → 牌ID


def parse_tiles(text: str, *, aka: bool = True, used: Iterable[int] = ()) -> list[int]:
    """mpsz 表記の文字列を牌IDのリストにする（書かれた順）。

    例: parse_tiles("123m406p11z") → 一二三萬・四筒・赤五筒・六筒・東東

    テストや役図鑑の例題で手牌を書くための入口。ここを通すことで次を保証する。
      * "5" は必ず赤でない 5、"0" は必ず赤5になる（aka=True のとき）
      * 同じ種類を 5 枚以上、赤でない 5 を 4 枚以上、赤5を 2 枚以上書いたらエラー
      * aka=False では "0" を書けない（赤ドラなしのルールに赤5は無い）

    同じ種類の牌には、空いている牌IDを小さい順に割り当てる。
    used に牌IDを渡すと、それらは「すでに使われている牌」として避ける
    （手牌・副露・ドラ表示牌を別々の文字列で書いても、同じ牌を二重に使わないようにするため）。
    """
    used = set(used)
    result: list[int] = []
    pending: list[str] = []

    for ch in text:
        if ch.isspace():
            continue
        if ch in "0123456789":
            pending.append(ch)
            continue
        if ch not in _SUIT_START:
            raise TileError(f"読めない文字があります: {ch!r}（{text!r}）")
        if not pending:
            raise TileError(f"種別 {ch!r} の前に数字がありません（{text!r}）")
        for digit in pending:
            result.append(_allocate(int(digit), ch, used, aka=aka, text=text))
        pending.clear()

    if pending:
        raise TileError(f"数字 {''.join(pending)!r} のあとに種別（m/p/s/z）がありません（{text!r}）")
    return result


def _allocate(number: int, suit: str, used: set[int], *, aka: bool, text: str) -> int:
    if number == 0:
        if suit == "z":
            raise TileError(f"字牌に 0 はありません（{text!r}）")
        if not aka:
            raise TileError(f"赤ドラなしの指定で赤5（0{suit}）が書かれています（{text!r}）")
        red_id = (_SUIT_START[suit] + 4) * COPIES
        if red_id in used:
            raise TileError(f"赤5（0{suit}）は 1 枚しかありません（{text!r}）")
        used.add(red_id)
        return red_id

    if not 1 <= number <= _SUIT_SIZE[suit]:
        raise TileError(f"{number}{suit} という牌はありません（{text!r}）")

    kind = _SUIT_START[suit] + number - 1
    for tile_id in range(kind * COPIES, kind * COPIES + COPIES):
        if tile_id in used:
            continue
        if aka and tile_id in RED_FIVE_IDS:
            continue  # "5" と書いたら赤でない 5
        used.add(tile_id)
        return tile_id

    if aka and number == 5 and suit != "z":
        raise TileError(f"赤でない 5{suit} は 3 枚までです。4 枚目は赤5なので 0{suit} と書きます（{text!r}）")
    raise TileError(f"{number}{suit} は 4 枚までです（{text!r}）")


def format_tiles(tile_ids: Sequence[int], *, aka: bool = True) -> str:
    """牌IDの集まり → mpsz 表記（理牌した順。例: "123m406p11z"）"""
    parts: list[str] = []
    current_suit = ""
    digits = ""
    for tile_id in sort_tiles(tile_ids):
        code = code_of(tile_id, aka=aka)
        if code[1] != current_suit and digits:
            parts.append(digits + current_suit)
            digits = ""
        current_suit = code[1]
        digits += code[0]
    if digits:
        parts.append(digits + current_suit)
    return "".join(parts)

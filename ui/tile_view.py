"""牌を画面に出すための変換（画像の場所、表示名、並べて見せる HTML）"""
from __future__ import annotations

from collections.abc import Iterable
from html import escape

from engine.tiles import code_of, is_red, kind_of, name_of, number_of_kind, suit_of_kind

#: 牌画像の置き場所。Streamlit の静的ファイル配信（static/ フォルダ）を使うので、アプリからの相対URLになる
TILE_IMAGE_BASE = "app/static/tiles"

_SUIT_KANJI = {"m": "萬", "p": "筒", "s": "索"}


def tile_image_url(tile_id: int, *, aka: bool = True) -> str:
    """牌画像の URL（例: app/static/tiles/5m.png、赤5は 0m.png）"""
    return f"{TILE_IMAGE_BASE}/{code_of(tile_id, aka=aka)}.png"


def tile_label(tile_id: int, *, aka: bool = True) -> str:
    """読み上げ・代替表示用の名前（例: 五萬、赤五筒、東）"""
    return name_of(tile_id, aka=aka)


def tile_short_label(tile_id: int, *, aka: bool = True) -> str:
    """文字だけで牌を表すときの短い名前（例: 5萬、赤5筒、東）"""
    kind = kind_of(tile_id)
    suit = suit_of_kind(kind)
    if suit == "z":
        return name_of(tile_id, aka=aka)
    red = "赤" if is_red(tile_id, aka=aka) else ""
    return f"{red}{number_of_kind(kind)}{_SUIT_KANJI[suit]}"


def tiles_row_html(tile_ids: Iterable[int], *, tile_width_px: int = 30, aka: bool = True, empty_text: str = "") -> str:
    """牌を横に並べた HTML（タップはできない表示専用。河や説明図に使う）。幅が足りなければ折り返す"""
    cells = []
    for tile_id in tile_ids:
        label = escape(tile_label(tile_id, aka=aka))
        cells.append(
            f'<img src="{tile_image_url(tile_id, aka=aka)}" alt="{label}" title="{label}" '
            f'width="{tile_width_px}" height="{round(tile_width_px * 4 / 3)}" '
            'style="display:block;filter:drop-shadow(0 1px 1px rgba(0,0,0,.35))">'
        )
    if not cells:
        return f'<div style="opacity:.6;font-size:14px">{escape(empty_text)}</div>'
    return '<div style="display:flex;flex-wrap:wrap;gap:3px 2px">' + "".join(cells) + "</div>"

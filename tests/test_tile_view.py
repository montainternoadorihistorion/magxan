"""牌の表示用の変換（ui/tile_view.py）のテスト"""
from engine.tiles import parse_tiles
from ui.tile_view import tile_image_url, tile_label, tile_short_label, tiles_row_html


def test_labels():
    five_man, red_pin, east = parse_tiles("5m0p1z")
    assert (tile_label(five_man), tile_short_label(five_man)) == ("五萬", "5萬")
    assert (tile_label(red_pin), tile_short_label(red_pin)) == ("赤五筒", "赤5筒")
    assert (tile_label(east), tile_short_label(east)) == ("東", "東")
    assert tile_short_label(red_pin, aka=False) == "5筒"
    assert tile_image_url(red_pin) == "app/static/tiles/0p.png"
    assert tile_image_url(red_pin, aka=False) == "app/static/tiles/5p.png"


def test_row_html_lists_every_tile_once():
    html = tiles_row_html(parse_tiles("19m0s7z"))
    assert html.count("<img ") == 4
    for name in ("1m.png", "9m.png", "0s.png", "7z.png"):
        assert name in html
    assert 'alt="赤五索"' in html


def test_row_html_empty_message_is_escaped():
    html = tiles_row_html([], empty_text="まだ<b>ありません")
    assert "<img" not in html and "&lt;b&gt;" in html

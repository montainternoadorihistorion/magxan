"""牌画像がそろっていることのテスト"""
import struct
from pathlib import Path

from engine.tiles import NUM_TILES, code_of
from ui.tile_view import TILE_IMAGE_BASE, tile_image_url

ROOT = Path(__file__).resolve().parent.parent
TILES_DIR = ROOT / "static" / "tiles"
EXPECTED = (
    {f"{n}{s}" for s in "mps" for n in range(0, 10)}
    | {f"{n}z" for n in range(1, 8)}
    | {"back"}
)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def test_all_tile_images_exist():
    assert {p.stem for p in TILES_DIR.glob("*.png")} == EXPECTED   # 34 種＋赤5 が 3 枚＋裏面 ＝ 38 枚
    assert (TILES_DIR / "LICENSE.md").is_file()


def test_tile_images_have_the_same_3_to_4_shape():
    sizes = {png_size(p) for p in TILES_DIR.glob("*.png")}
    assert len(sizes) == 1
    width, height = next(iter(sizes))
    assert width * 4 == height * 3 and width >= 150


def test_every_tile_id_maps_to_an_existing_image():
    assert TILE_IMAGE_BASE == "app/static/tiles"   # static/ フォルダは app/static/ として配信される
    for aka in (True, False):
        for tile_id in range(NUM_TILES):
            url = tile_image_url(tile_id, aka=aka)
            assert url == f"app/static/tiles/{code_of(tile_id, aka=aka)}.png"
            assert (ROOT / "static" / "tiles" / url.rsplit("/", 1)[1]).is_file()

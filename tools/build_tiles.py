"""牌画像（static/tiles/*.png）を作り直すためのスクリプト。

元データ: FluffyStuff/riichi-mahjong-tiles（CC0 1.0 / パブリックドメイン）
    https://github.com/FluffyStuff/riichi-mahjong-tiles  （確認したコミット: 26e127b, 2024-06-15）

使い方:
    git clone https://github.com/FluffyStuff/riichi-mahjong-tiles.git /path/to/src
    python tools/build_tiles.py /path/to/src

元の PNG（600x800、牌の地と絵柄が別レイヤー）を重ねて 1 枚にし、スマホ向けに縮小して保存する。
裏面は、元の鮮やかな赤を落ち着いた青緑に変える。
ファイル名は「数字＋種別」（1m〜9m, 1p〜9p, 1s〜9s, 1z〜7z）。赤5は 0m / 0p / 0s、裏面は back。
実行には Pillow が必要（アプリ本体の実行には不要）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

OUT_SIZE = (180, 240)  # 画面上は最大でも 60x80 px 程度。高精細ディスプレイ（3倍）まで滲まない大きさ
COLORS = 128           # 色数を絞ってファイルを小さくする（牌の絵柄は色数が少ない）

# 裏面の色（色相は 0〜1。0.47 ≒ 青緑）。彩度と明るさは元の赤に対する倍率
BACK_HUE = 0.47
BACK_SATURATION = 0.72
BACK_VALUE = 0.66

HONORS = ["Ton", "Nan", "Shaa", "Pei", "Haku", "Hatsu", "Chun"]  # 東南西北白發中 = 1z〜7z
SUITS = {"m": "Man", "p": "Pin", "s": "Sou"}


def source_names() -> dict[str, str]:
    """出力名 → 元ファイル名（拡張子なし）"""
    names: dict[str, str] = {}
    for suit, prefix in SUITS.items():
        for n in range(1, 10):
            names[f"{n}{suit}"] = f"{prefix}{n}"
        names[f"0{suit}"] = f"{prefix}5-Dora"
    for i, name in enumerate(HONORS, start=1):
        names[f"{i}z"] = name
    return names


def build(src_root: Path, out_dir: Path) -> list[Path]:
    export = src_root / "Export" / "Regular"
    front = Image.open(export / "Front.png").convert("RGBA")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(img: Image.Image, name: str) -> None:
        small = img.resize(OUT_SIZE, Image.LANCZOS)
        small = small.quantize(colors=COLORS, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        path = out_dir / f"{name}.png"
        small.save(path, optimize=True)
        written.append(path)

    for out_name, src_name in sorted(source_names().items()):
        face = Image.open(export / f"{src_name}.png").convert("RGBA")
        save(Image.alpha_composite(front, face), out_name)
    save(recolor(Image.open(export / "Back.png").convert("RGBA")), "back")
    return written


def recolor(img: Image.Image, hue: float = BACK_HUE, saturation: float = BACK_SATURATION, value: float = BACK_VALUE) -> Image.Image:
    """牌の裏面の色を変える（元は鮮やかな赤。牌の表と並べても目が疲れない落ち着いた青緑にする）。陰影はそのまま残す"""
    red, green, blue, alpha = img.split()
    h, s, v = Image.merge("RGB", (red, green, blue)).convert("HSV").split()
    h = h.point(lambda _: round(hue * 255))
    s = s.point(lambda x: round(x * saturation))
    v = v.point(lambda x: round(x * value))
    rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    return Image.merge("RGBA", (*rgb.split(), alpha))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    files = build(Path(sys.argv[1]), Path(__file__).resolve().parent.parent / "static" / "tiles")
    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} 枚を書き出しました（合計 {total / 1024:.0f} KB）")

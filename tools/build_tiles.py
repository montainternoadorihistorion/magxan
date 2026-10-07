"""牌画像（static/tiles/*.png）を作り直すためのスクリプト。

元データ: FluffyStuff/riichi-mahjong-tiles（CC0 1.0 / パブリックドメイン）
    https://github.com/FluffyStuff/riichi-mahjong-tiles  （確認したコミット: 26e127b, 2024-06-15）

使い方:
    git clone https://github.com/FluffyStuff/riichi-mahjong-tiles.git /path/to/src
    python tools/build_tiles.py /path/to/src

元の PNG（600x800、牌の地と絵柄が別レイヤー）を重ねて 1 枚にし、スマホ向けに縮小して保存する。
ファイル名は「数字＋種別」（1m〜9m, 1p〜9p, 1s〜9s, 1z〜7z）。赤5は 0m / 0p / 0s、裏面は back。
実行には Pillow が必要（アプリ本体の実行には不要）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

OUT_SIZE = (180, 240)  # 画面上は最大でも 60x80 px 程度。高精細ディスプレイ（3倍）まで滲まない大きさ
COLORS = 128           # 色数を絞ってファイルを小さくする（牌の絵柄は色数が少ない）

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
    save(Image.open(export / "Back.png").convert("RGBA"), "back")
    return written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    files = build(Path(sys.argv[1]), Path(__file__).resolve().parent.parent / "static" / "tiles")
    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} 枚を書き出しました（合計 {total / 1024:.0f} KB）")

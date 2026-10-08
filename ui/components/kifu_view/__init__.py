"""牌譜を 1 手ずつ見る部品（局後の振り返り）。

エンジンが作った手順（engine.kifu）を受け取り、ブラウザの中で盤面を作り直して見せる。
進む・戻るのたびにサーバーへ問い合わせないので、すぐに動く（小さい画面で何十手も進めても待たない）。
この部品は値を送り返さない（見るだけ）。
"""
from __future__ import annotations

from pathlib import Path

from engine.kifu import Kifu
from engine.tiles import NUM_TILES
from ui.components._base import registered
from ui.ruby import Rubifier
from ui.tile_view import TILE_IMAGE_BASE, tile_image_url, tile_label

_DIR = Path(__file__).parent
START_TEXT = "配牌（親が最初の 1 枚をツモったところ）。▶ で 1 手ずつ進む。「次の自分の判断 ▶」で、自分が判断したところへ飛ぶ。"


def record_data(record: Kifu) -> dict:
    """部品に送る牌譜。説明の文には、読み（ルビ）を付けた HTML も添える。
    手順は 1 つずつ（飛ばしながら）見るので、どの手順でも、その手順の文の中の初出に振る"""
    data = record.to_dict()
    for step in data["steps"]:
        rb = Rubifier()
        step["html"] = rb.html(step["text"])
        note = step.get("note")
        if note:
            note["labelHtml"] = rb.html(note["label"])
            note["textHtml"] = rb.html(note.get("text") or "")
    data["startHtml"] = Rubifier().html(START_TEXT)
    return data


def _component():
    return registered("mjdojo_kifu_view", _DIR, html="kifu_view.html", css="kifu_view.css", js="kifu_view.js")


def kifu_view(record: Kifu, *, key: str, ident: str, aka: bool = True, start_at: int = 0) -> None:
    """牌譜を表示する。ident は牌譜ごとに違う名前（別の局に切り替えたら、最初から見せるため）"""
    _component()(
        key=key,
        data={
            "ident": ident,
            "record": record_data(record),
            "images": [{"src": tile_image_url(t, aka=aka), "label": tile_label(t, aka=aka)} for t in range(NUM_TILES)],
            "back": f"{TILE_IMAGE_BASE}/back.png",
            "startAt": start_at,
        },
    )

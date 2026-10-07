"""手牌をタップして 1 枚選ぶ部品。

牌の画像そのものを押せるようにし、スマホ縦画面で 7 枚 × 2 段に並べる。
押し間違いを防ぐため「選ぶ → 確定」の 2 段階にしてある（選んだ牌をもう一度押しても確定できる）。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from ui.components._base import registered
from ui.tile_view import tile_image_url, tile_label, tile_short_label

_DIR = Path(__file__).parent


def _component():
    return registered("mjdojo_tile_hand", _DIR, html="tile_hand.html", css="tile_hand.css", js="tile_hand.js")


@dataclass(frozen=True)
class Pick:
    """確定された 1 枚と、一緒に届く計測値"""

    tile_id: int
    prev_response_ms: int | None    # ひとつ前の確定から画面更新までの時間（体感の応答時間）
    viewport_width: int | None
    viewport_height: int | None
    device_pixel_ratio: float | None
    image_errors: int               # 読み込めなかった牌画像の数


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def parse_pick(payload: object, *, rev: int, tile_ids: Sequence[int]) -> Pick | None:
    """部品から届いた値を確かめて Pick にする。

    次の場合は None（無視）:
      * 形が違う
      * rev が今の番号と違う（古い画面から届いた確定。二重送信の防止）
      * 牌IDが今の手牌に無い
    """
    if not isinstance(payload, dict) or _int(payload.get("rev")) != rev:
        return None
    tile_id = _int(payload.get("id"))
    if tile_id is None or tile_id not in tile_ids:
        return None
    return Pick(
        tile_id=tile_id,
        prev_response_ms=_int(payload.get("prevMs")),
        viewport_width=_int(payload.get("vw")),
        viewport_height=_int(payload.get("vh")),
        device_pixel_ratio=_number(payload.get("dpr")),
        image_errors=_int(payload.get("imgNg")) or 0,
    )


def tile_hand(
    tile_ids: Sequence[int],
    *,
    key: str,
    rev: int,
    on_pick: Callable[[Pick], None],
    drawn_id: int | None = None,
    enabled: bool = True,
    aka: bool = True,
    prompt: str = "牌をタップして選ぶ",
    confirm_label: str = "この牌を切る",
) -> None:
    """手牌を表示する。牌が確定されたら on_pick(Pick) を呼ぶ。

    tile_ids  並べる順の牌ID（ツモ牌を含める場合は最後に置く）
    rev       呼び出し側が行動を 1 つ処理するたびに必ず増やす番号。
              部品はこの番号が変わったことで「サーバーが応答した」と判断し、次の入力を受け付ける。
    on_pick   確定されたときの処理。Streamlit のコールバックとして、画面を描き直す前に呼ばれる。
              ここで状態を進めて rev を増やせば、1 回の再実行で新しい局面が描かれる。
    """
    tile_ids = list(tile_ids)
    memo_key = f"{key}::shown"
    # 「いま画面に出している内容」を覚えておく。確定が届いたとき、それがこの画面からのものか確かめるため
    st.session_state[memo_key] = {"rev": rev, "tile_ids": tile_ids}

    def _on_pick_change() -> None:
        shown = st.session_state.get(memo_key)
        payload = getattr(st.session_state.get(key), "pick", None)
        if not shown:
            return
        pick = parse_pick(payload, rev=shown["rev"], tile_ids=shown["tile_ids"])
        if pick is not None:
            on_pick(pick)

    _component()(
        key=key,
        data={
            "rev": rev,
            "tiles": [
                {
                    "id": tile_id,
                    "src": tile_image_url(tile_id, aka=aka),
                    "label": tile_label(tile_id, aka=aka),
                    "short": tile_short_label(tile_id, aka=aka),
                }
                for tile_id in tile_ids
            ],
            "drawnId": drawn_id,
            "enabled": enabled,
            "prompt": prompt,
            "confirmLabel": confirm_label,
        },
        on_pick_change=_on_pick_change,
    )

"""手牌をタップして 1 枚選ぶ部品。

牌の画像そのものを押せるようにし、スマホ縦画面で 7 枚 × 2 段に並べる。
押し間違いを防ぐため「選ぶ → 確定」の 2 段階にしてある（選んだ牌をもう一度押しても確定できる）。
牌を切らずにする操作（ツモあがり・ロン・見送る・九種九牌）のボタンも、確定のボタンの横に置ける
（手牌のすぐ下なので、小さい画面でも見える）。
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from ui.components._base import registered
from ui.tile_view import tile_image_url, tile_label, tile_short_label

_DIR = Path(__file__).parent
#: 操作のボタンの色：win ＝ あがり（緑）、plain ＝ 枠だけ、alert ＝ 注意（橙）
BUTTON_STYLES = ("win", "plain", "alert")


def _component():
    return registered("mjdojo_tile_hand", _DIR, html="tile_hand.html", css="tile_hand.css", js="tile_hand.js")


@dataclass(frozen=True)
class HandButton:
    """牌を切らずにする操作のボタン 1 つ"""

    key: str            # 押されたときに届く名前
    label: str          # ボタンの文字
    style: str = "win"

    def __post_init__(self) -> None:
        if self.style not in BUTTON_STYLES:
            raise ValueError(f"ボタンの色の指定が違います: {self.style!r}")


@dataclass(frozen=True)
class Pick:
    """確定された 1 枚と、一緒に届く計測値"""

    tile_id: int
    riichi: bool                    # リーチを宣言して切るか
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


def parse_action(payload: object, *, rev: int, keys: Collection[str]) -> str | None:
    """部品から届いた値が、いまの画面の操作のボタン（ツモあがりなど）を押したものなら、そのボタンの名前"""
    if not isinstance(payload, dict) or _int(payload.get("rev")) != rev:
        return None
    key = payload.get("action")
    return key if isinstance(key, str) and key in keys else None


def parse_pick(payload: object, *, rev: int, tile_ids: Sequence[int], riichi_ids: Collection[int] = ()) -> Pick | None:
    """部品から届いた値を確かめて Pick にする。

    次の場合は None（無視）:
      * 形が違う
      * rev が今の番号と違う（古い画面から届いた確定。二重送信の防止）
      * 牌IDが今の手牌に無い
      * 牌を切らずにする操作のボタンを押したもの（parse_action で調べる）
    リーチの指定は、その牌がリーチで切れる牌（riichi_ids）のときだけ受け付ける。
    """
    if not isinstance(payload, dict) or _int(payload.get("rev")) != rev or "action" in payload:
        return None
    tile_id = _int(payload.get("id"))
    if tile_id is None or tile_id not in tile_ids:
        return None
    return Pick(
        tile_id=tile_id,
        riichi=payload.get("riichi") is True and tile_id in riichi_ids,
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
    marks: Mapping[int, tuple[str, str]] | None = None,
    riichi_ids: Collection[int] = (),
    riichi_label: str = "リーチ",
    drawn_label: str = "ツモ",
    two_rows: bool = False,
    scroll_top: bool = False,
    actions: Sequence[HandButton] = (),
    on_action: Callable[[str], None] | None = None,
    discard: bool = True,
    chosen_id: int | None = None,
    chosen_label: str = "選んだ牌",
) -> None:
    """手牌を表示する。牌が確定されたら on_pick(Pick) を呼ぶ。

    tile_ids     並べる順の牌ID（ツモ牌を含める場合は最後に置く）
    rev          呼び出し側が行動を 1 つ処理するたびに必ず増やす番号。
                 部品はこの番号が変わったことで「サーバーが応答した」と判断し、次の入力を受け付ける。
    on_pick      確定されたときの処理。Streamlit のコールバックとして、画面を描き直す前に呼ばれる。
                 ここで状態を進めて rev を増やせば、1 回の再実行で新しい局面が描かれる。
    enabled      偽なら表示だけ（牌は押せず、確定のボタンと案内も出さない）
    marks        牌の左上に出す印。{牌ID: (印の文字, 読み上げ用の説明)}。例: {52: ("◎", "おすすめ")}
    riichi_ids   リーチを宣言して切れる牌ID。1 つでもあれば「リーチ」のボタンが出る
    riichi_label リーチのボタンの文字（リーチを勧めるときは「◎ リーチ」など）
    drawn_label  ツモ牌の下に出す文字
    two_rows     真なら、案内文とボタンをいつも 2 段に分ける。リーチのボタンが出る巡目と出ない巡目で、
                 確定ボタンの位置が変わらないようにする（リーチを使うページでは真にする）
    scroll_top   真なら、画面のいちばん上までスクロールを戻す（新しい局を始めた直後の 1 回だけ真にする）
    actions      確定のボタンの横に出す、牌を切らずにする操作のボタン（例：「ツモ（あがる）」「ロン」「見送る」）。
                 押すと、すぐに on_action(ボタンの名前) を呼ぶ（選ぶ → 確定 の 2 段階にはしない）
    discard      偽なら、牌を選んで切ることはできない（ロンするかどうかを決めるときなど）。案内文と操作のボタンだけを出す
    chosen_id    表示だけのとき（enabled が偽）に、選ばれた牌として枠を付ける牌ID（ドリルで、答えた牌を見せる）
    chosen_label 選ばれた牌の、読み上げ用の説明
    """
    tile_ids = list(tile_ids)
    riichi_ids = [t for t in tile_ids if t in set(riichi_ids)] if discard else []
    marks = marks or {}
    buttons = [b for b in actions if on_action is not None] if enabled else []
    memo_key = f"{key}::shown"
    # 「いま画面に出している内容」を覚えておく。確定が届いたとき、それがこの画面からのものか確かめるため
    st.session_state[memo_key] = {
        "rev": rev,
        "tile_ids": tile_ids if discard else [],
        "riichi_ids": riichi_ids,
        "actions": [b.key for b in buttons],
    }

    def _on_pick_change() -> None:
        shown = st.session_state.get(memo_key)
        payload = getattr(st.session_state.get(key), "pick", None)
        if not shown:
            return
        pressed = parse_action(payload, rev=shown["rev"], keys=shown.get("actions", ()))
        if pressed is not None:
            if on_action is not None:
                on_action(pressed)
            return
        pick = parse_pick(payload, rev=shown["rev"], tile_ids=shown["tile_ids"], riichi_ids=shown.get("riichi_ids", ()))
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
                    "mark": marks[tile_id][0] if tile_id in marks else "",
                    "markLabel": marks[tile_id][1] if tile_id in marks else "",
                }
                for tile_id in tile_ids
            ],
            "drawnId": drawn_id,
            "drawnLabel": drawn_label,
            "enabled": enabled,
            "discard": discard,
            "prompt": prompt,
            "confirmLabel": confirm_label,
            "riichiIds": riichi_ids,
            "riichiLabel": riichi_label,
            "twoRows": two_rows,
            "scrollTop": scroll_top,
            "actions": [{"key": b.key, "label": b.label, "style": b.style} for b in buttons],
            "chosenId": chosen_id if not enabled and chosen_id in tile_ids else None,
            "chosenLabel": chosen_label,
        },
        on_pick_change=_on_pick_change,
    )

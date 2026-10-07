"""ブラウザに残してある進み具合（成績・スタンプ・ドリルの記録）の読み書き。

置き場所（ブラウザ内保存の名前）
    practice.hand       打っている局
    practice.settings   一人練習の設定
    practice.history    一人練習の成績（記録の配列）
    progress.stamps     スタンプ（成立させた役）
    drill.<種類>        ドリルの記録（種類ごとに 1 つ）

画面の部品（Streamlit）には触れない。store は、ui.components.browser_store.BrowserStore と同じ形のもの。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from engine.drills import KINDS
from engine.progress import (
    Export,
    Stamp,
    build_export,
    dump_stamps,
    load_stamps,
    merge_history,
    merge_stamps,
    stamps_from_history,
)
from engine.records import HandRecord, load_history
from engine.srs import Deck, deck_from_data, dump_deck, load_deck, merge_decks

HAND_NAME = "practice.hand"
SETTINGS_NAME = "practice.settings"
HISTORY_NAME = "practice.history"
STAMPS_NAME = "progress.stamps"
DRILL_PREFIX = "drill."


class Store(Protocol):
    """ブラウザ内保存の窓口（ui.components.browser_store.BrowserStore と同じ形）"""

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def remove(self, name: str) -> None: ...
    def append(self, name: str, item: str, *, limit: int) -> None: ...


def parse_json(text: str | None) -> object:
    """JSON を読む。読めなければ None（ブラウザに残っているデータは、壊れていることがある）"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, RecursionError):        # JSON でない／入れ子が深すぎる
        return None


# ---------------------------------------------------------------- 読み書き


def read_history(store: Store) -> list[HandRecord]:
    return load_history(store.get(HISTORY_NAME))


def write_history(store: Store, records: list[HandRecord]) -> None:
    """成績を書き直す（ブラウザに残す形は、記録の配列そのもの）"""
    if not records:
        store.remove(HISTORY_NAME)
        return
    store.set(HISTORY_NAME, json.dumps([r.to_dict() for r in records], ensure_ascii=False, separators=(",", ":")))


def read_stamps(store: Store) -> dict[str, Stamp]:
    """スタンプ帳。スタンプの記録がまだ無ければ、成績から作る（スタンプができる前の版で打った局のぶん）"""
    stamps = load_stamps(store.get(STAMPS_NAME))
    if stamps is None:
        stamps = stamps_from_history(read_history(store))
    return stamps


def write_stamps(store: Store, stamps: dict[str, Stamp]) -> None:
    store.set(STAMPS_NAME, dump_stamps(stamps))


def read_deck(store: Store, kind: str) -> Deck:
    return load_deck(store.get(DRILL_PREFIX + kind))


def write_deck(store: Store, kind: str, deck: Deck) -> None:
    store.set(DRILL_PREFIX + kind, dump_deck(deck))


def read_decks(store: Store) -> dict[str, Deck]:
    return {kind: read_deck(store, kind) for kind in KINDS}


# ---------------------------------------------------------------- ファイルへの書き出し・読み込み


def export_text(store: Store, *, time: int, app_version: str) -> str:
    """いまブラウザにある進み具合を、1 つの JSON にまとめる"""
    settings = parse_json(store.get(SETTINGS_NAME))
    decks = {kind: deck for kind, deck in read_decks(store).items() if deck.answered or deck.cards}
    return build_export(
        settings=settings if isinstance(settings, dict) else None,
        history=read_history(store),
        stamps=read_stamps(store),
        drills={kind: deck.to_data() for kind, deck in decks.items()},
        time=time,
        app_version=app_version,
    )


@dataclass(frozen=True)
class Summary:
    """進み具合の大きさ（読み込みの前後で見せる）"""

    hands: int          # 成績の局数
    stamps: int         # スタンプのある役の数
    answers: int        # ドリルに答えた回数（全種類の合計）


def summary_of_store(store: Store) -> Summary:
    return Summary(len(read_history(store)), len(read_stamps(store)), sum(deck.answered for deck in read_decks(store).values()))


def summary_of_export(data: Export) -> Summary:
    decks = data.drills or {}
    stamps = data.stamps if "stamps" in data.parts else stamps_from_history(data.history)
    answers = sum(deck_from_data(decks.get(kind)).answered for kind in KINDS)
    return Summary(len(data.history), len(stamps), answers)


def apply_import(store: Store, data: Export, *, merge: bool, clean_settings: Any = None) -> Summary:
    """読み込んだファイルの中身を、ブラウザに書く。→ 書いたあとの進み具合の大きさ。

    merge が真なら、いまの記録と合わせる（同じ局は 1 つに。スタンプとドリルの回数は、多いほうを採る）。
    偽なら、ファイルの中身で置き換える（設定も置き換える。clean_settings は、設定の値を確かめる関数）。
    """
    theirs_stamps = data.stamps if "stamps" in data.parts else stamps_from_history(data.history)
    theirs_decks = {kind: deck_from_data((data.drills or {}).get(kind)) for kind in KINDS}
    if merge:
        history = merge_history(read_history(store), data.history)
        stamps = merge_stamps(read_stamps(store), theirs_stamps)
        decks = {kind: merge_decks(read_deck(store, kind), theirs_decks[kind]) for kind in KINDS}
    else:
        history = merge_history([], data.history)          # 古い順に並べ、上限に収める
        stamps = dict(theirs_stamps)
        decks = theirs_decks
        if data.settings is not None and clean_settings is not None:
            store.set(SETTINGS_NAME, json.dumps(clean_settings(data.settings)))
    write_history(store, history)
    write_stamps(store, stamps)
    for kind, deck in decks.items():
        if deck.answered or deck.cards:
            write_deck(store, kind, deck)
        else:
            store.remove(DRILL_PREFIX + kind)
    return Summary(len(history), len(stamps), sum(deck.answered for deck in decks.values()))


def clear_all(store: Store) -> None:
    """進み具合をすべて消す（打っている局と設定は残す）"""
    store.remove(HISTORY_NAME)
    store.remove(STAMPS_NAME)
    for kind in KINDS:
        store.remove(DRILL_PREFIX + kind)

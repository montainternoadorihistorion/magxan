"""ブラウザに残してある進み具合（成績・スタンプ・ドリルの記録）の読み書き。

置き場所（ブラウザ内保存の名前）
    practice.hand       打っている局
    practice.settings   一人練習の設定
    practice.history    一人練習の成績（記録の配列）
    progress.stamps     スタンプ（成立させた役）
    drill.<種類>        ドリルの記録（種類ごとに 1 つ）
    drill.declare       あがったときの点数の申告の記録（ドリルと同じ形。Phase 5）
    progress.curriculum カリキュラムの進み具合（段階ごとの確認テストの結果。Phase 5）
    game.current        CPU との対局（打っている対局）
    game.settings       CPU との対局の設定
    game.history        CPU との対局の成績（記録の配列）

画面の部品（Streamlit）には触れない。store は、ui.components.browser_store.BrowserStore と同じ形のもの。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from engine.curriculum import Progress, dump_progress, load_progress, merge_progress, progress_from_data
from engine.drills import KINDS
from engine.game_records import GameRecord, dump_record
from engine.game_records import load_history as load_games
from engine.progress import (
    Export,
    Stamp,
    build_export,
    dump_stamps,
    load_stamps,
    merge_games,
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
GAME_NAME = "game.current"
GAME_SETTINGS_NAME = "game.settings"
GAME_HISTORY_NAME = "game.history"
CURRICULUM_NAME = "progress.curriculum"
#: あがったときの点数の申告の記録（ドリルの記録と同じ形で、drill.declare に置く。書き出しでも、ドリルと一緒に扱う）
DECLARE = "declare"
DECK_KEYS = (*KINDS, DECLARE)


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


def read_games(store: Store) -> list[GameRecord]:
    """CPU との対局の成績"""
    return load_games(store.get(GAME_HISTORY_NAME))


def write_games(store: Store, records: list[GameRecord]) -> None:
    """CPU との対局の成績を書き直す（ブラウザに残す形は、記録の配列そのもの）"""
    if not records:
        store.remove(GAME_HISTORY_NAME)
        return
    store.set(GAME_HISTORY_NAME, "[" + ",".join(dump_record(r) for r in records) + "]")


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


def read_curriculum(store: Store) -> Progress:
    return load_progress(store.get(CURRICULUM_NAME))


def write_curriculum(store: Store, progress: Progress) -> None:
    if progress.steps:
        store.set(CURRICULUM_NAME, dump_progress(progress))
    else:
        store.remove(CURRICULUM_NAME)


def read_decks(store: Store) -> dict[str, Deck]:
    """ドリルの記録（種類ごと）と、点数の申告の記録（DECLARE）"""
    return {kind: read_deck(store, kind) for kind in DECK_KEYS}


def drill_answers(decks: dict[str, Deck]) -> int:
    """ドリルに答えた回数（点数の申告は数えない）"""
    return sum(deck.answered for kind, deck in decks.items() if kind in KINDS)


# ---------------------------------------------------------------- ファイルへの書き出し・読み込み


def store_signature(store: Store) -> str:
    """書き出しに入る記録（成績・スタンプ・ドリル・設定）の、いまの中身のしるし。中身が変わると、しるしも変わる"""
    names = [HISTORY_NAME, STAMPS_NAME, SETTINGS_NAME, GAME_HISTORY_NAME, GAME_SETTINGS_NAME, CURRICULUM_NAME,
             *(DRILL_PREFIX + kind for kind in DECK_KEYS)]
    digest = hashlib.sha256()
    for name in names:
        value = store.get(name)
        digest.update(name.encode() + b"\0" + (b"-" if value is None else value.encode("utf-8", "surrogatepass")) + b"\0")
    return digest.hexdigest()


def export_text(store: Store, *, time: int, app_version: str) -> str:
    """いまブラウザにある進み具合を、1 つの JSON にまとめる"""
    settings = parse_json(store.get(SETTINGS_NAME))
    game_settings = parse_json(store.get(GAME_SETTINGS_NAME))
    decks = {kind: deck for kind, deck in read_decks(store).items() if deck.answered or deck.cards}
    return build_export(
        settings=settings if isinstance(settings, dict) else None,
        history=read_history(store),
        stamps=read_stamps(store),
        drills={kind: deck.to_data() for kind, deck in decks.items()},
        time=time,
        app_version=app_version,
        games=read_games(store),
        game_settings=game_settings if isinstance(game_settings, dict) else None,
        curriculum=read_curriculum(store).to_data() if read_curriculum(store).steps else None,
    )


@dataclass(frozen=True)
class Summary:
    """進み具合の大きさ（読み込みの前後で見せる）"""

    hands: int          # 一人練習の成績の局数
    stamps: int         # スタンプのある役の数
    answers: int        # ドリルに答えた回数（全種類の合計）
    games: int = 0      # CPU との対局の成績の対局数
    declares: int = 0   # あがったときに点数を申告した回数

    def text(self) -> str:
        """画面に出す短いまとめ"""
        return (f"一人練習 {self.hands} 局・CPU との対局 {self.games} 回・スタンプ {self.stamps} 役・ドリル {self.answers} 回"
                f"・点数の申告 {self.declares} 回")


def summary_of_store(store: Store) -> Summary:
    decks = read_decks(store)
    return Summary(len(read_history(store)), len(read_stamps(store)), drill_answers(decks), len(read_games(store)), decks[DECLARE].answered)


def summary_of_export(data: Export) -> Summary:
    raw = data.drills or {}
    decks = {kind: deck_from_data(raw.get(kind)) for kind in DECK_KEYS}
    stamps = data.stamps if "stamps" in data.parts else stamps_from_history(data.history)
    return Summary(len(data.history), len(stamps), drill_answers(decks), len(data.games), decks[DECLARE].answered)


def apply_import(
    store: Store, data: Export, *, merge: bool, clean_settings: Any = None, clean_game_settings: Any = None,
) -> Summary:
    """読み込んだファイルの中身を、ブラウザに書く。→ 書いたあとの進み具合の大きさ。

    merge が真なら、いまの記録と合わせる（同じ局・同じ対局は 1 つに。スタンプとドリルの回数は、多いほうを採る）。
    偽なら、ファイルの中身で置き換える（設定も置き換える。clean_settings・clean_game_settings は、
    一人練習・CPU との対局の設定の値を確かめる関数）。CPU との対局の成績が入っていない古いファイルで置き換えると、
    CPU との対局の成績は空になる。
    """
    theirs_stamps = data.stamps if "stamps" in data.parts else stamps_from_history(data.history)
    theirs_decks = {kind: deck_from_data((data.drills or {}).get(kind)) for kind in DECK_KEYS}
    theirs_curriculum = progress_from_data(data.curriculum)
    if merge:
        history = merge_history(read_history(store), data.history)
        games = merge_games(read_games(store), data.games)
        stamps = merge_stamps(read_stamps(store), theirs_stamps)
        decks = {kind: merge_decks(read_deck(store, kind), theirs_decks[kind]) for kind in DECK_KEYS}
        curriculum = merge_progress(read_curriculum(store), theirs_curriculum)
    else:
        history = merge_history([], data.history)          # 古い順に並べ、上限に収める
        games = merge_games([], data.games)
        stamps = dict(theirs_stamps)
        decks = theirs_decks
        curriculum = theirs_curriculum
        if data.settings is not None and clean_settings is not None:
            store.set(SETTINGS_NAME, json.dumps(clean_settings(data.settings)))
        if data.game_settings is not None and clean_game_settings is not None:
            store.set(GAME_SETTINGS_NAME, json.dumps(clean_game_settings(data.game_settings)))
    write_history(store, history)
    write_games(store, games)
    write_stamps(store, stamps)
    write_curriculum(store, curriculum)
    for kind, deck in decks.items():
        if deck.answered or deck.cards:
            write_deck(store, kind, deck)
        else:
            store.remove(DRILL_PREFIX + kind)
    return Summary(len(history), len(stamps), drill_answers(decks), len(games), decks[DECLARE].answered)


def clear_all(store: Store) -> None:
    """進み具合をすべて消す（打っている局・対局と、設定は残す）"""
    store.remove(HISTORY_NAME)
    store.remove(GAME_HISTORY_NAME)
    store.remove(STAMPS_NAME)
    store.remove(CURRICULUM_NAME)
    for kind in DECK_KEYS:
        store.remove(DRILL_PREFIX + kind)

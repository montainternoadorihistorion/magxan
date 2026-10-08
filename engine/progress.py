"""進み具合の記録：スタンプ（実戦で成立させた役）と、ファイルへの書き出し・読み込み。

    スタンプ    あがった手に付いた役を、図鑑のページごとに数える（何回・最初はいつ・補正なしでは何回）
    書き出し    一人練習の設定と成績・スタンプ・ドリルの記録を、1 つの JSON にまとめる
    読み込み    書き出した JSON を確かめて、部品ごとに取り出す（壊れた部分は読み飛ばす）

記録の置き場所はブラウザの中（localStorage）なので、端末やブラウザを変えると引き継がれない。
ブラウザが消してしまうこともある。ファイルへの書き出しは、その控えと、端末の引っ越しのため。
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from engine.content import page_of_yaku, yaku_pages
from engine.game_records import HISTORY_VERSION as GAME_HISTORY_VERSION
from engine.game_records import MAX_RECORDS as MAX_GAME_RECORDS
from engine.game_records import GameRecord
from engine.records import HISTORY_VERSION, MAX_RECORDS, HandRecord
from engine.srs import is_text

APP_ID = "mjdojo"
EXPORT_KIND = "progress"
EXPORT_VERSION = 1
#: 読み込むファイルの大きさの上限（文字数）。成績 500 局＋ドリルの記録でも、この 1/10 ほど
MAX_EXPORT_CHARS = 2_000_000
_MAX_TIME = 10**11
_MAX_COUNT = 10**6


# ---------------------------------------------------------------- スタンプ


@dataclass(frozen=True)
class Stamp:
    count: int          # 成立させた回数
    first: int          # 初めて成立させた時刻（UNIX 秒）
    last: int           # いちばん最近の時刻
    plain: int = 0      # そのうち、ツキ補正なし（通常の麻雀）の局での回数

    def to_dict(self) -> dict[str, int]:
        return {"n": self.count, "first": self.first, "last": self.last, "plain": self.plain}


def stamp_keys(yaku_keys: Iterable[str]) -> list[str]:
    """あがった手の役（役の鍵）→ スタンプを押す図鑑のページ（同じページは 1 回だけ）"""
    pages = page_of_yaku()
    found: list[str] = []
    for key in yaku_keys:
        page = pages.get(key)
        if page is not None and page not in found:
            found.append(page)
    return found


def add_stamps(stamps: Mapping[str, Stamp], yaku_keys: Iterable[str], *, time: int, plain: bool) -> tuple[dict[str, Stamp], list[str]]:
    """あがった手の役にスタンプを押す。→（新しいスタンプ帳, 今回はじめて押されたページ）"""
    result = dict(stamps)
    fresh = []
    for page in stamp_keys(yaku_keys):
        old = result.get(page)
        if old is None:
            result[page] = Stamp(1, int(time), int(time), 1 if plain else 0)
            fresh.append(page)
        else:
            result[page] = Stamp(old.count + 1, old.first, max(old.last, int(time)), old.plain + (1 if plain else 0))
    return result, fresh


def stamps_from_history(records: Iterable[HandRecord]) -> dict[str, Stamp]:
    """成績の記録から、スタンプ帳を作る（スタンプの記録を持っていない、前の版のデータのため）"""
    stamps: dict[str, Stamp] = {}
    for record in sorted(records, key=lambda r: r.time):
        if record.win:
            stamps, _ = add_stamps(stamps, record.yaku, time=record.time, plain=record.deal == 0 and record.draw == 0)
    return stamps


def merge_stamps(mine: Mapping[str, Stamp], theirs: Mapping[str, Stamp]) -> dict[str, Stamp]:
    """2 つのスタンプ帳を合わせる。同じ局を二重に数えないように、回数は多いほうを採る（足さない）"""
    result = dict(mine)
    for key, other in theirs.items():
        old = result.get(key)
        if old is None:
            result[key] = other
        else:
            result[key] = Stamp(max(old.count, other.count), min(old.first, other.first), max(old.last, other.last), max(old.plain, other.plain))
    return result


@dataclass(frozen=True)
class Completion:
    done: int           # スタンプのあるページの数
    total: int          # 図鑑のページの数
    reachable: int      # そのうち、いま成立させられるページの数（一人練習で成立しうる役）

    @property
    def rate(self) -> float:
        return self.done / self.total if self.total else 0.0


def completion(stamps: Mapping[str, Stamp]) -> Completion:
    """図鑑のコンプリート率"""
    pages = yaku_pages()
    done = sum(1 for page in pages if page.key in stamps)
    return Completion(done, len(pages), sum(1 for page in pages if page.solo))


def _stamp_from(data: object) -> Stamp:
    if not isinstance(data, dict):
        raise ValueError("スタンプの形が違います")

    def number(name: str, high: int, default: int | None = None) -> int:
        value = data.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= high:
            raise ValueError(f"スタンプの値がおかしい: {name}={value!r}")
        return value

    count = number("n", _MAX_COUNT)
    first = number("first", _MAX_TIME)
    if count < 1:
        raise ValueError("スタンプの回数は 1 以上です")
    return Stamp(count, first, max(first, number("last", _MAX_TIME, first)), min(count, number("plain", _MAX_COUNT, 0)))


def stamps_to_data(stamps: Mapping[str, Stamp]) -> dict[str, dict[str, int]]:
    return {key: stamp.to_dict() for key, stamp in stamps.items()}


def stamps_from_data(data: object) -> dict[str, Stamp]:
    """保存した形からスタンプ帳を作る。知らないページや、壊れた 1 件は読み飛ばす"""
    if not isinstance(data, dict):
        return {}
    known = {page.key for page in yaku_pages()}
    stamps = {}
    for key, value in data.items():
        if key not in known:
            continue
        try:
            stamps[key] = _stamp_from(value)
        except ValueError:
            continue
    return stamps


def dump_stamps(stamps: Mapping[str, Stamp]) -> str:
    return json.dumps(stamps_to_data(stamps), ensure_ascii=False, separators=(",", ":"))


def load_stamps(text: str | None) -> dict[str, Stamp] | None:
    """ブラウザに残した文字列からスタンプ帳を読む。記録そのものが無い・読めないときは None"""
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return stamps_from_data(data) if isinstance(data, dict) else None


# ---------------------------------------------------------------- 成績の合わせ方


def merge_history(mine: Sequence[HandRecord], theirs: Sequence[HandRecord]) -> list[HandRecord]:
    """2 つの成績を合わせる。同じ局（終わった時刻・番号・狙った役が同じ）は 1 つにして、古い順に並べる"""
    seen: dict[tuple[int, int, str], HandRecord] = {}
    for record in (*mine, *theirs):
        seen.setdefault((record.time, record.seed, record.target), record)
    return sorted(seen.values(), key=lambda r: r.time)[-MAX_RECORDS:]


def merge_games(mine: Sequence[GameRecord], theirs: Sequence[GameRecord]) -> list[GameRecord]:
    """CPU との対局の成績を合わせる。同じ対局（終わった時刻と番号が同じ）は 1 つにして、古い順に並べる"""
    seen: dict[tuple[int, int], GameRecord] = {}
    for record in (*mine, *theirs):
        seen.setdefault((record.time, record.seed), record)
    return sorted(seen.values(), key=lambda r: r.time)[-MAX_GAME_RECORDS:]


# ---------------------------------------------------------------- ファイルへの書き出し・読み込み


@dataclass(frozen=True)
class Export:
    """書き出したファイルの中身"""

    exported: int                                   # 書き出した時刻（UNIX 秒）
    app_version: str
    settings: dict[str, Any] | None                 # 一人練習の設定（確かめる前の形。使う側で確かめる）
    history: list[HandRecord]
    stamps: dict[str, Stamp]
    drills: dict[str, Any] | None                   # ドリルの記録（確かめる前の形。engine.srs で確かめる）
    skipped: int = 0                                # 読み飛ばした成績の件数（壊れていた記録。CPU との対局の成績も含む）
    parts: tuple[str, ...] = field(default=())      # ファイルに入っていた部品の名前
    games: list[GameRecord] = field(default_factory=list)      # CPU との対局の成績（Phase 3 より前のファイルには無い）
    game_settings: dict[str, Any] | None = None     # CPU との対局の設定（確かめる前の形）


def build_export(
    *,
    settings: Mapping[str, Any] | None,
    history: Sequence[HandRecord],
    stamps: Mapping[str, Stamp],
    drills: Mapping[str, Any] | None,
    time: int,
    app_version: str,
    games: Sequence[GameRecord] = (),
    game_settings: Mapping[str, Any] | None = None,
) -> str:
    """進み具合を、1 つの JSON の文字列にまとめる（人が読める形に、字下げして書く）"""
    data = {
        "app": APP_ID,
        "kind": EXPORT_KIND,
        "v": EXPORT_VERSION,
        "exported": int(time),
        "app_version": app_version,
        "practice": {
            "settings": dict(settings) if settings is not None else None,
            "history": {"v": HISTORY_VERSION, "hands": [record.to_dict() for record in history]},
        },
        "stamps": stamps_to_data(stamps),
        "drills": dict(drills) if drills is not None else None,
        # CPU との対局（Phase 3 で足した。前の版のアプリは、知らない部品として読み飛ばす）
        "games": {
            "settings": dict(game_settings) if game_settings is not None else None,
            "history": {"v": GAME_HISTORY_VERSION, "games": [record.to_dict() for record in games]},
        },
    }
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if not is_text(text):
        # 書き出せない文字（片方だけのサロゲート）がどこかに残っていても、ファイルは作れるようにする（\\u の形で書く）
        text = json.dumps(data, ensure_ascii=True, indent=1)
    return text


def parse_export(text: str) -> Export:
    """書き出したファイルを読む。このアプリのファイルでなければ ValueError（理由つき）。

    中身の一部が壊れていても、読める部分は読む（壊れた成績は 1 件ずつ読み飛ばす）。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ファイルが空です。")
    if len(text) > MAX_EXPORT_CHARS:
        raise ValueError("ファイルが大きすぎます。このアプリが書き出したファイルを選んでください。")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as error:
        raise ValueError("JSON として読めませんでした。このアプリが書き出したファイルを選んでください。") from error
    if not isinstance(data, dict) or data.get("app") != APP_ID or data.get("kind") != EXPORT_KIND:
        raise ValueError("このアプリが書き出したファイルではないようです。")
    version = data.get("v")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("ファイルの版が読めません。")
    if version > EXPORT_VERSION:
        raise ValueError("このファイルは、新しい版のアプリで書き出されたものです。アプリを更新してから読み込んでください。")

    practice = data.get("practice") if isinstance(data.get("practice"), dict) else {}
    settings = practice.get("settings") if isinstance(practice.get("settings"), dict) else None
    rows = practice.get("history")
    if isinstance(rows, dict):
        rows = rows.get("hands") if rows.get("v") == HISTORY_VERSION else None
    history: list[HandRecord] = []
    skipped = 0
    for row in rows if isinstance(rows, list) else []:
        try:
            history.append(HandRecord.from_dict(row))
        except ValueError:
            skipped += 1
    block = data.get("games") if isinstance(data.get("games"), dict) else {}
    game_settings = block.get("settings") if isinstance(block.get("settings"), dict) else None
    game_rows = block.get("history")
    if isinstance(game_rows, dict):
        game_rows = game_rows.get("games") if game_rows.get("v") == GAME_HISTORY_VERSION else None
    games: list[GameRecord] = []
    for row in game_rows if isinstance(game_rows, list) else []:
        try:
            games.append(GameRecord.from_dict(row))
        except ValueError:
            skipped += 1
    exported = data.get("exported")
    if not isinstance(exported, int) or isinstance(exported, bool) or not 0 <= exported <= _MAX_TIME:
        exported = 0
    app_version = data.get("app_version")
    parts = tuple(
        name
        for name, present in (
            ("settings", settings is not None),
            ("history", isinstance(rows, list)),
            ("stamps", isinstance(data.get("stamps"), dict)),
            ("drills", isinstance(data.get("drills"), dict)),
            ("games", isinstance(game_rows, list)),
            ("game_settings", game_settings is not None),
        )
        if present
    )
    return Export(
        exported=exported,
        app_version=app_version if isinstance(app_version, str) and len(app_version) <= 40 and is_text(app_version) else "",
        settings=settings,
        history=history[-MAX_RECORDS:],
        stamps=stamps_from_data(data.get("stamps")),
        drills=data.get("drills") if isinstance(data.get("drills"), dict) else None,
        skipped=skipped,
        parts=parts,
        games=games[-MAX_GAME_RECORDS:],
        game_settings=game_settings,
    )

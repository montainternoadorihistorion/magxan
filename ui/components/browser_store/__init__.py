"""ブラウザ内保存（localStorage）を Python から読み書きする。

Streamlit Community Cloud ではサーバー側のファイルが残らず、通信が切れるとセッション（対局状態）も
消える。そこで、小さな記録を利用者のブラウザに置いておき、開き直したときに続きから再開できるようにする。

使い方（ページの中で）:

    store = BrowserStore()
    store.mount()                 # 毎回の実行で 1 度、必ず呼ぶ（ここで読み書きが行われる）
    if not store.ready:           # 開いた直後の 1 回だけ、ブラウザからの返事を待つ
        st.stop()
    text = store.get("solo")      # 無ければ None
    store.set("solo", "...")      # 文字列を保存（JSON などは呼び出し側で文字列にする）
    store.append("log", "{...}", limit=500)   # JSON の配列の末尾に 1 件足す（成績のように増えていく記録むけ）
    store.remove("solo")

保存先は端末とブラウザごとに別。消えることもあるので、大事なデータは別途 JSON で書き出せるようにする。

ブラウザに保存できないとき（保存が禁止されている、容量が足りない、利用者が待たずに始めた）は、このセッションの中だけの
置き場所に読み書きする。ページを閉じると消えるが、開いているあいだは、保存できるときと同じように動く
（成績・スタンプ・ドリルの記録がたまり、ファイルへの書き出しもできる）。available が False になるので、画面でそのことを知らせる。

やり取りの仕組み（ブラウザ側は browser_store.js）

  * 読み取り：ブラウザの中身は、セッションごとに 1 回だけ、まとめて送ってもらう（snapshot）。
    あとは Python 側の控え（known）を読む。
  * 書き込み：「何をどう書くか」を 1 件ずつの操作（set / remove / append）にして列に積み、置くたびに送る。
    ブラウザから「ここまで済ませた」という報告（ack）が来たら、列から外す。
    同じ操作が 2 回届いても結果は変わらない（ブラウザ側が番号で見分ける）ので、報告はまとめてでよい。
    報告のたびに画面の再実行が起きるので、毎回は報告させない。
  * 同じ名前への set / remove は、最後の 1 件だけ残す。だから、列が長くなるのは append がたまったときだけ。
  * 通信が長く切れてセッションが作り直されたときは、合言葉（session）が変わるので、ブラウザ側が気づいて
    中身を送り直す（ページを開いたままでも、続きから再開できる）。
"""
from __future__ import annotations

import json
import secrets
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import streamlit as st

from ui.components._base import registered

_DIR = Path(__file__).parent
STATE_VERSION = 2          # セッションに持つ状態の形。形を変えたら上げる（古い形の状態は作り直す）


def _component():
    return registered("mjdojo_browser_store", _DIR, js="browser_store.js")

DEFAULT_NAMESPACE = "mjdojo:"


def initial_state(known: dict[str, str] | None = None) -> dict[str, Any]:
    """セッションに持つ状態の最初の形。known を渡すと「ブラウザの中身はこれ」と分かっている状態になる（テスト用）"""
    return {
        "v": STATE_VERSION,
        "session": secrets.token_hex(8),     # このセッションの合言葉
        "known": None if known is None else dict(known),   # ブラウザの中身の控え。None は「まだ聞いていない」
        "ops": [],                           # まだ「届いた」と確認できていない書き込み（古い順）
        "next_id": 1,
        "error": None,                       # 保存が使えないと分かったときの理由
        "skipped": False,                    # 利用者が、返事を待たずに進むことを選んだ
        "memory": None,                      # 待たずに進んだあとの、このセッションの中だけの置き場所
        "again": False,                      # ページを開いたまま、セッションが作り直されたか（通信が長く切れたあと）
    }


class BrowserStore:
    """ブラウザ内保存の窓口。状態は st.session_state に持つので、実行のたびに作り直してよい"""

    def __init__(
        self,
        key: str = "mjdojo_store",
        namespace: str = DEFAULT_NAMESPACE,
        session: MutableMapping[str, Any] | None = None,
    ) -> None:
        self._key = key
        self._namespace = namespace
        self._state_key = f"{key}::state"
        # 通常は st.session_state。テストでは普通の dict を渡せる
        self._session: MutableMapping[str, Any] = st.session_state if session is None else session
        current = self._session.get(self._state_key)
        if not isinstance(current, dict) or current.get("v") != STATE_VERSION:
            self._session[self._state_key] = initial_state()

    @property
    def _state(self) -> dict:
        return self._session[self._state_key]

    # ------------------------------------------------------------ 読み取り

    @property
    def ready(self) -> bool:
        """ブラウザの中身を把握できているか（開いた直後の 1 回は False）"""
        return self._state["known"] is not None or self._state["skipped"]

    @property
    def available(self) -> bool:
        """ブラウザ内保存が使えるか。使えないと分かったとき、または利用者が待つのをやめたとき False"""
        return self._state["known"] is not None and self._state["error"] is None

    @property
    def error(self) -> str | None:
        return self._state["error"]

    @property
    def reconnected(self) -> bool:
        """ページを開いたまま、セッションが作り直されたか（通信が長く切れたあとや、サーバーが再起動したあと）。

        このとき、切れる直前の操作はサーバーに届いていない。画面でそのことを知らせるのに使う。
        """
        return bool(self._state.get("again"))

    def _values(self) -> dict[str, str] | None:
        """いま読み書きする置き場所。ブラウザの中身の控えか、このセッションの中だけの置き場所。まだ決まっていなければ None"""
        state = self._state
        if state["known"] is not None:
            return state["known"]
        if state["skipped"]:
            if state.get("memory") is None:
                state["memory"] = {}
            return state["memory"]
        return None

    def get(self, name: str) -> str | None:
        values = self._values()
        return None if values is None else values.get(name)

    def skip(self) -> None:
        """ブラウザからの返事を待たずに進む（ブラウザには保存せず、このセッションの中だけに置く）。

        このあと返事が届いても使わない。途中から保存を始めると、ブラウザに残っていた記録を
        「読まないまま上書き」してしまうため。
        """
        if self._state["known"] is None:
            self._state["skipped"] = True

    # ------------------------------------------------------------ 書き込み

    def _persists(self) -> bool:
        """書いた内容を、ブラウザに送るか（使えないと分かったあと・待たずに始めたあとは、送らない）"""
        state = self._state
        return state["known"] is not None and not state["error"]

    def _push(self, op: str, name: str, value: str | None = None, limit: int = 0) -> None:
        state = self._state
        if op != "append":
            # 同じ名前への古い書き込みは、もう要らない（最後の値だけが残ればよい）
            state["ops"] = [item for item in state["ops"] if item["name"] != name]
        state["ops"].append({"id": state["next_id"], "op": op, "name": name, "value": value, "limit": limit})
        state["next_id"] += 1

    def set(self, name: str, value: str) -> None:
        values = self._values()
        if values is None or values.get(name) == value:       # まだ読めていない間の書き込みは捨てる
            return
        values[name] = value
        if self._persists():
            self._push("set", name, value)

    def remove(self, name: str) -> None:
        values = self._values()
        if values is None or name not in values:
            return
        del values[name]
        if self._persists():
            self._push("remove", name)

    def append(self, name: str, item: str, *, limit: int) -> None:
        """保存されている JSON の配列の末尾に、item（JSON の文字列）を 1 件足す。limit 件を超えたら古いものから捨てる。

        ブラウザ側が「いま入っている配列」に足すので、別のタブで足した記録を消してしまうことがない。
        全体を書き直さないので、記録が増えても通信量は増えない。
        """
        values = self._values()
        if values is None:
            return
        entry = json.loads(item)                        # JSON でなければ、ここで ValueError
        try:
            items = json.loads(values.get(name) or "[]")
        except (ValueError, RecursionError):
            items = []
        if not isinstance(items, list):
            items = []
        items = [*items, entry][-limit:] if limit > 0 else [*items, entry]
        values[name] = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        if self._persists():
            self._push("append", name, item, limit)

    # ------------------------------------------------------------ ブラウザとのやり取り

    def _reply(self, name: str) -> dict | None:
        """ブラウザから届いた値（このセッション宛てのものだけ）"""
        value = getattr(self._session.get(self._key), name, None)
        if not isinstance(value, dict) or value.get("session") != self._state["session"]:
            return None     # 別のセッション（切れる前）宛ての返事は使わない
        return value

    def _on_snapshot_change(self) -> None:
        snapshot = self._reply("snapshot")
        state = self._state
        if snapshot is None or state["known"] is not None or state["skipped"]:
            return          # もう分かっている（送り直しが重なった）／待たずに始めたあとの返事は使わない
        values = snapshot.get("values")
        error = snapshot.get("error")
        state["error"] = None if error is None else str(error)
        state["again"] = snapshot.get("again") is True
        state["known"] = {k: v for k, v in values.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(values, dict) else {}

    def _on_ack_change(self) -> None:
        ack = self._reply("ack")
        if ack is None:
            return
        state = self._state
        done = ack.get("id")
        if isinstance(done, int) and not isinstance(done, bool):
            state["ops"] = [item for item in state["ops"] if item["id"] > done]
        if ack.get("error"):
            # 書けなかった（容量の上限、保存の禁止など）。以後は保存を使わない
            state["error"] = str(ack["error"])
            state["ops"] = []

    def mount(self) -> None:
        """読み書きを実行する部品を置く。set / remove / append を呼んだあと、ページの最後のほうで呼ぶ"""
        state = self._state
        _component()(
            key=self._key,
            data={
                "ns": self._namespace,
                "session": state["session"],
                "need": state["known"] is None and not state["skipped"],
                "ops": [dict(item) for item in state["ops"]],
            },
            on_snapshot_change=self._on_snapshot_change,
            on_ack_change=self._on_ack_change,
        )

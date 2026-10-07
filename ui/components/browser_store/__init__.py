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
    store.remove("solo")

保存先は端末とブラウザごとに別。消えることもあるので、大事なデータは別途 JSON で書き出せるようにする。
"""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import streamlit as st

from ui.components._base import registered

_DIR = Path(__file__).parent


def _component():
    return registered("mjdojo_browser_store", _DIR, js="browser_store.js")

DEFAULT_NAMESPACE = "mjdojo:"


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
        if self._state_key not in self._session:
            self._session[self._state_key] = {"known": None, "pending": {}, "seq": 0, "error": None, "skipped": False}

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

    def get(self, name: str) -> str | None:
        known = self._state["known"]
        return None if known is None else known.get(name)

    def skip(self) -> None:
        """ブラウザからの返事を待たずに進む（保存なしで動かす）"""
        self._state["skipped"] = True

    # ------------------------------------------------------------ 書き込み

    def set(self, name: str, value: str) -> None:
        state = self._state
        if state["known"] is None or state["error"]:
            return  # 保存が使えない／まだ読めていないときは何もしない
        if state["known"].get(name) == value:
            return
        state["known"][name] = value
        state["pending"][name] = value
        state["seq"] += 1

    def remove(self, name: str) -> None:
        state = self._state
        if state["known"] is None or state["error"] or name not in state["known"]:
            return
        del state["known"][name]
        state["pending"][name] = None
        state["seq"] += 1

    # ------------------------------------------------------------ ブラウザとのやり取り

    def _on_snapshot_change(self) -> None:
        snapshot = getattr(self._session.get(self._key), "snapshot", None)
        state = self._state
        if not isinstance(snapshot, dict) or snapshot.get("seq") != state["seq"]:
            return  # 古い問い合わせへの返事は使わない
        values = snapshot.get("values")
        state["error"] = snapshot.get("error")
        state["known"] = dict(values) if isinstance(values, dict) else {}
        state["pending"] = {}

    def mount(self) -> None:
        """読み書きを実行する部品を置く。set / remove を呼んだあと、ページの最後のほうで呼ぶ"""
        state = self._state
        _component()(
            key=self._key,
            data={
                "ns": self._namespace,
                "writes": dict(state["pending"]),
                "expected": None if state["known"] is None else dict(state["known"]),
                "seq": state["seq"],
            },
            on_snapshot_change=self._on_snapshot_change,
        )

"""ドリルの画面の状態（いまの問題・答え・この回の数）を動かす。

状態はセッション（ふつうは st.session_state）に置く。間隔反復の記録は、種類ごとにブラウザ内保存に残す。

    session = DrillSession(st.session_state, store)
    session.start("table")          # 種類を選んで始める（最初の問題が決まる）
    session.start_review()          # 復習の時刻になった問題だけを、種類をまたいで出す
    q = session.question            # いまの問題（出す問題が無ければ None）
    session.answer(["3,900 点"])    # 選択肢で答える
    session.answer_discard(牌ID)    # 何切るに答える
    session.next()                  # 次の問題へ
    session.leave()                 # 種類の一覧へ戻る

画面の部品（Streamlit）には触れない。画面なしでテストできる。
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable, MutableMapping
from typing import Any

from engine.drills import DONE, KINDS, REVIEW, Question, early_item, grade, grade_discard, next_item, question
from engine.srs import Card, Deck
from ui.progress_store import Store, read_deck, write_deck

MODE_KIND, MODE_REVIEW = "kind", "review"
EARLY = "early"
#: 続けて同じ問題を出さないために覚えておく、直前の問題の数
RECENT = 4
#: いまは無い問題（内容を入れ替えたあとに残った古い記録）に当たったとき、次を探す回数の上限
MAX_SKIPS = 20


class DrillSession:
    def __init__(
        self,
        session: MutableMapping[str, Any],
        store: Store,
        *,
        now: Callable[[], float] = time.time,
        pick: Callable[[], int] = lambda: secrets.randbelow(10**9),
    ) -> None:
        self._s = session
        self._store = store
        self._now = now
        self._pick = pick

    # ------------------------------------------------------------ 読み取り

    @property
    def kind(self) -> str | None:
        """いま出している種類（種類の一覧を出しているときは None）"""
        kind = self._s.get("dr_kind")
        return kind if kind in KINDS else None

    @property
    def item(self) -> str | None:
        return self._s.get("dr_item")

    @property
    def reason(self) -> str:
        """いまの問題を出した理由（復習・新しい問題・先取り）。出す問題が無いときは DONE"""
        return self._s.get("dr_reason", "")

    @property
    def mode(self) -> str:
        return self._s.get("dr_mode", MODE_KIND)

    @property
    def rev(self) -> int:
        """問題が変わるたびに増える番号（部品に「新しい問題になった」と伝える）"""
        return self._s.get("dr_rev", 0)

    @property
    def count(self) -> int:
        """この回に答えた数"""
        return self._s.get("dr_count", 0)

    @property
    def right(self) -> int:
        return self._s.get("dr_right", 0)

    @property
    def result(self) -> dict[str, Any] | None:
        """いまの問題に答えた結果（まだなら None）。{"picked": [...], "correct": bool} か {"tile": 牌ID, "correct": bool}"""
        return self._s.get("dr_graded")

    @property
    def answered(self) -> bool:
        return self.result is not None

    @property
    def card(self) -> Card | None:
        """答えたあとの、この問題の記録（覚えておかない問題なら None）"""
        data = self._s.get("dr_card")
        try:
            return Card.from_list(data) if data else None
        except ValueError:
            return None

    @property
    def answered_at(self) -> int:
        return self._s.get("dr_at", 0)

    @property
    def question(self) -> Question | None:
        """いまの問題。出す問題が無ければ None"""
        for _ in range(MAX_SKIPS):
            kind, item = self.kind, self.item
            if kind is None or item is None:
                return None
            try:
                return question(kind, item)
            except ValueError:      # いまは無い問題（内容を入れ替えたあとに、古い記録が残っていた）
                self._recent_add(kind, item)
                self.next()
        return None

    def deck(self, kind: str) -> Deck:
        return read_deck(self._store, kind)

    def take_review_done(self) -> bool:
        """復習をすべて終えた直後の 1 回だけ True"""
        return bool(self._s.pop("dr_review_done", False))

    # ------------------------------------------------------------ 出す問題を決める

    def _show(self, kind: str | None, item: str | None, reason: str) -> None:
        self._s["dr_kind"] = kind
        self._s["dr_item"] = item
        self._s["dr_reason"] = reason
        self._s["dr_graded"] = None
        self._s["dr_card"] = None
        self._s["dr_rev"] = self.rev + 1

    def _recent(self, kind: str) -> set[str]:
        return {item for k, item in self._s.get("dr_recent", []) if k == kind}

    def _recent_add(self, kind: str, item: str) -> None:
        self._s["dr_recent"] = [*self._s.get("dr_recent", []), (kind, item)][-RECENT:]

    def _reset(self, mode: str) -> None:
        self._s["dr_mode"] = mode
        self._s["dr_count"] = 0
        self._s["dr_right"] = 0
        self._s["dr_recent"] = []

    def start(self, kind: str) -> None:
        """種類を選んで始める"""
        if kind not in KINDS:
            raise ValueError(f"ドリルの種類は {list(KINDS)} のどれかです: {kind!r}")
        self._reset(MODE_KIND)
        self._s["dr_kind"] = kind
        self.next()

    def start_review(self) -> None:
        """復習の時刻になった問題だけを、種類をまたいで出す"""
        self._reset(MODE_REVIEW)
        self.next()

    def next(self) -> None:
        """次の問題へ進む"""
        now = int(self._now())
        if self.mode == MODE_REVIEW:
            for kind in KINDS:
                item, why = next_item(kind, self.deck(kind), now, pick=0, skip=self._recent(kind))
                if why == REVIEW:
                    self._show(kind, item, REVIEW)
                    return
            self._s["dr_review_done"] = True
            self.leave()
            return
        kind = self.kind
        if kind is None:
            return
        item, why = next_item(kind, self.deck(kind), now, pick=self._pick(), skip=self._recent(kind))
        self._show(kind, item, why)

    def early(self) -> None:
        """復習の時刻になる前の問題を、先取りで出す"""
        kind = self.kind
        if kind is None:
            return
        item = early_item(kind, self.deck(kind), self._recent(kind))
        self._show(kind, item, EARLY if item is not None else DONE)

    def leave(self) -> None:
        """種類の一覧へ戻る"""
        self._show(None, None, "")

    # ------------------------------------------------------------ 答える

    def _record(self, correct: bool) -> None:
        """答えた結果を、間隔反復の記録に入れる"""
        kind, item = self.kind, self.item
        assert kind is not None and item is not None
        now = int(self._now())
        deck = self.deck(kind).review(item, correct, now, keep=KINDS[kind].finite)
        write_deck(self._store, kind, deck)
        card = deck.cards.get(item)
        self._s["dr_card"] = card.to_list() if card is not None else None
        self._s["dr_at"] = now
        self._s["dr_count"] = self.count + 1
        self._s["dr_right"] = self.right + (1 if correct else 0)
        self._recent_add(kind, item)

    def answer(self, keys: Iterable[str]) -> bool:
        """選択肢で答える。できない操作（もう答えた、選択肢に無い答え）なら何もせず False"""
        q = None if self.answered else self.question
        if q is None or q.position is not None:
            return False
        try:
            graded = grade(q, keys)
        except ValueError:
            return False
        self._s["dr_graded"] = {"picked": sorted(graded.picked), "correct": graded.correct}
        self._record(graded.correct)
        return True

    def answer_discard(self, tile: int) -> bool:
        """何切るに答える（切る牌の牌ID）。できない操作なら何もせず False"""
        q = None if self.answered else self.question
        if q is None or q.position is None or tile not in q.position.tiles:
            return False
        correct, _, _ = grade_discard(q, tile)
        self._s["dr_graded"] = {"tile": tile, "correct": correct}
        self._record(correct)
        return True

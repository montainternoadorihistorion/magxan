"""間隔反復：間違えた問題を、間隔をあけてもう一度出す。

問題 1 つごとに「箱」の番号を持つ（ライトナー方式）。
    正解すると 1 つ上の箱へ。箱が上がるほど、次に出すまでの間隔が長くなる。
    間違えると箱 0 に戻り、すぐ（10 分後。同じ回のうちに）もう一度出る。

        箱      0       1      2      3      4       5
        間隔    10 分   1 日   3 日   7 日   16 日   35 日

    はじめて出た問題に正解したら、箱 2 から始める（もう知っている問題を、何度も出さないため）。

問題の集まり（Deck）は、ドリルの種類ごとに 1 つ。文字と数だけでできているので、そのまま JSON にして残せる。
"""
from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

DAY = 24 * 60 * 60
#: 箱ごとの、次に出すまでの間隔（秒）
INTERVALS = (10 * 60, DAY, 3 * DAY, 7 * DAY, 16 * DAY, 35 * DAY)
MAX_BOX = len(INTERVALS) - 1
#: はじめての問題に正解したときに入れる箱
FIRST_RIGHT_BOX = 2
DECK_VERSION = 1
#: 1 つの種類で覚えておく問題の数の上限（超えたら、よく覚えている問題から忘れる）
MAX_CARDS = 400
_MAX_TIME = 10**11
_MAX_COUNT = 10**6


@dataclass(frozen=True)
class Card:
    box: int        # 0 ＝ 間違えたばかり … 5 ＝ よく覚えている
    due: int        # 次に出す時刻（UNIX 秒）
    seen: int       # 出した回数
    right: int      # 正解した回数
    last: int       # 最後に答えた時刻

    def to_list(self) -> list[int]:
        return [self.box, self.due, self.seen, self.right, self.last]

    @classmethod
    def from_list(cls, data: object) -> Card:
        """保存した形から作る。形や値がおかしければ ValueError"""
        if not isinstance(data, list) or len(data) != 5 or not all(isinstance(v, int) and not isinstance(v, bool) for v in data):
            raise ValueError("問題の記録の形が違います")
        box, due, seen, right, last = data
        if not (0 <= box <= MAX_BOX and 0 <= due <= _MAX_TIME and 1 <= seen <= _MAX_COUNT and 0 <= right <= seen and 0 <= last <= _MAX_TIME):
            raise ValueError("問題の記録の値がおかしい")
        return cls(box, due, seen, right, last)


@dataclass(frozen=True)
class Deck:
    """ドリル 1 種類ぶんの記録"""

    cards: Mapping[str, Card] = field(default_factory=dict)
    answered: int = 0       # 答えた回数（忘れた問題のぶんも含む）
    right: int = 0          # 正解した回数

    @property
    def accuracy(self) -> float | None:
        """正答率（まだ 1 問も答えていなければ None）"""
        return self.right / self.answered if self.answered else None

    def due(self, now: int, skip: Collection[str] = ()) -> list[str]:
        """出す時刻になっている問題。間違えたばかりのもの（箱の小さいもの）→ 待たせているもの、の順。

        skip は、直前に出したばかりの問題（続けて同じ問題を出さないため）。
        """
        ready = [(card.box, card.due, key) for key, card in self.cards.items() if card.due <= now and key not in skip]
        return [key for _, _, key in sorted(ready)]

    def waiting(self, now: int) -> int:
        """まだ出す時刻になっていない、復習待ちの問題の数（よく覚えている箱 MAX_BOX のものは数えない）"""
        return sum(1 for card in self.cards.values() if card.due > now and card.box < MAX_BOX)

    def review(self, item: str, correct: bool, now: int, *, keep: bool = True) -> Deck:
        """1 問に答えた結果を記録する。

        keep が偽のとき（問題をその場で作る種類）は、間違えた問題だけを覚えておく。
        はじめて出て正解した問題は覚えない。覚えていた問題も、箱 FIRST_RIGHT_BOX まで戻ったら忘れる。
        """
        now = int(now)
        cards = dict(self.cards)
        old = cards.get(item)
        if not correct:
            box = 0
        elif old is None:
            box = FIRST_RIGHT_BOX
        else:
            box = min(old.box + 1, MAX_BOX)
        seen = (old.seen if old else 0) + 1
        right = (old.right if old else 0) + (1 if correct else 0)
        if not keep and correct and box >= FIRST_RIGHT_BOX:
            cards.pop(item, None)
        else:
            cards[item] = Card(box, now + INTERVALS[box], seen, right, now)
        _trim(cards, keep=item)
        return Deck(cards, self.answered + 1, self.right + (1 if correct else 0))

    def to_data(self) -> dict:
        return {
            "v": DECK_VERSION,
            "n": self.answered,
            "right": self.right,
            "cards": {key: card.to_list() for key, card in self.cards.items()},
        }


def _trim(cards: dict[str, Card], keep: str | None = None) -> None:
    """上限を超えたぶんを忘れる。よく覚えている問題（箱が大きく、次に出すのがいちばん先のもの）から。

    keep は、いま答えたばかりの問題（これは忘れない）。
    """
    extra = len(cards) - MAX_CARDS
    if extra <= 0:
        return
    order = sorted((key for key in cards if key != keep), key=lambda key: (-cards[key].box, -cards[key].due, key))
    for key in order[:extra]:
        del cards[key]


def is_text(value: str) -> bool:
    """UTF-8 で書き出せる文字列か（JSON の「\\ud83c」のような、片方だけのサロゲートが入っていないか）"""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def deck_from_data(data: object) -> Deck:
    """保存した形から作る。全体が壊れていれば空の記録、壊れた 1 件はその 1 件だけ読み飛ばす"""
    if not isinstance(data, dict) or data.get("v") != DECK_VERSION:
        return Deck()
    cards = {}
    raw = data.get("cards")
    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        if not isinstance(key, str) or len(key) > 80 or not is_text(key):
            continue
        try:
            cards[key] = Card.from_list(value)
        except ValueError:
            continue
        if len(cards) >= MAX_CARDS:
            break

    def count(name: str) -> int:
        value = data.get(name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_COUNT else 0

    answered = count("n")
    return Deck(cards, answered, min(count("right"), answered))


def dump_deck(deck: Deck) -> str:
    return json.dumps(deck.to_data(), ensure_ascii=False, separators=(",", ":"))


def load_deck(text: str | None) -> Deck:
    if not text:
        return Deck()
    try:
        return deck_from_data(json.loads(text))
    except (ValueError, RecursionError):
        return Deck()


def merge_decks(mine: Deck, theirs: Deck) -> Deck:
    """2 つの記録を合わせる。同じ問題は、あとで答えたほうの状態を採る。回数は多いほうを採る（足さない）"""
    cards = dict(mine.cards)
    for key, other in theirs.cards.items():
        old = cards.get(key)
        if old is None or other.last > old.last:
            cards[key] = other
    _trim(cards)
    answered = max(mine.answered, theirs.answered)
    return Deck(cards, answered, min(max(mine.right, theirs.right), answered))

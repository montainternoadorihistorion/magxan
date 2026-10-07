"""役図鑑・用語辞典などの内容を、data/ のファイル（YAML）から読み込む。

    yaku_pages()     役図鑑のページ（役ごとの定義・成立例・ひっかけ例・複合・コツ・由来）
    yaku_stats()     役の出やすさの統計（出典つき）
    glossary()       用語辞典の項目（読み・意味・由来）
    table_guide()    実際の卓で打つときの手順
    rule_book()      ルールによって違うところ（卓に着く前に確かめること）

内容（文章と例）はデータとして持ち、プログラムと分けてある。例として載せる手牌は、テストで点数計算に
かけて「成立例には必ずその役が付く」「ひっかけ例には付かない」ことを確かめる（tests/test_content.py）。
書き間違い（知らない項目名、型の違い）は、読み込むときにエラーにする。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.context import WinContext
from engine.scoring.notation import make_context
from engine.tiles import EAST, NORTH, SOUTH, WEST
from engine.yaku_table import YAKU

#: データの置き場所（リポジトリの data/）
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: 図鑑のまとまり（表示する順）
GROUPS: dict[str, str] = {
    "han1": "1 翻",
    "han2": "2 翻",
    "han3": "3 翻",
    "han6": "6 翻",
    "yakuman": "役満",
    "other": "そのほか",
}
#: 由来の確かさと、その意味
CERTAINTY_MEANINGS: dict[str, str] = {
    "確実": "辞書や当時の本など、系統の違う複数の資料が一致している。",
    "有力": "くわしい人の説明があり、食い違う資料は見つからなかった。ただし、裏付けは 1 つの系統だけ。",
    "諸説あり": "資料どうしで説明が食い違う。または、資料そのものが「はっきりしない」と書いている。",
    "不明": "読みと意味は確かめられたが、由来を説明する資料が見つからなかった。",
}
CERTAINTIES = tuple(CERTAINTY_MEANINGS)
#: ひっかけ例の結果（その手は実際にはどうなるか）
TRAP_RESULTS = {
    "win": "ほかの役であがれる",
    "no_yaku": "役がなく、あがれない",
    "not_winning": "あがりの形になっていない",
    "no_call": "あがりを宣言できない場面",        # 手の形ではなく、状況の決まりであがれない（暗槓へのロン、フリテンなど）
}
_WINDS = {"東": EAST, "南": SOUTH, "西": WEST, "北": NORTH}
_FLAGS = (
    "is_tsumo", "riichi", "double_riichi", "ippatsu", "rinshan", "chankan", "haitei", "houtei", "tenhou", "chiihou",
)
_RULE_FLAGS = tuple(Rules.__dataclass_fields__)


class ContentError(ValueError):
    """データの書き方の誤り"""


# ---------------------------------------------------------------- 読み込みの道具


def _load(name: str) -> Any:
    path = DATA_DIR / name
    try:
        with path.open(encoding="utf-8") as file:
            return yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as error:
        raise ContentError(f"{name} を読めません: {error}") from error


def _take(item: Mapping[str, Any], where: str, **fields: tuple[type | tuple[type, ...], Any]) -> dict[str, Any]:
    """項目を取り出す。fields は 名前 ＝（型, 既定値）。既定値が ... なら必須。知らない名前があればエラー"""
    if not isinstance(item, Mapping):
        raise ContentError(f"{where}: 項目の集まり（名前: 値）になっていません")
    unknown = set(item) - set(fields)
    if unknown:
        raise ContentError(f"{where}: 知らない項目があります {sorted(unknown)}")
    result = {}
    for name, (kind, default) in fields.items():
        if name not in item or item[name] is None:
            if default is ...:
                raise ContentError(f"{where}: 「{name}」がありません")
            result[name] = default
            continue
        value = item[name]
        if isinstance(value, bool) and kind is not bool and bool not in (kind if isinstance(kind, tuple) else (kind,)):
            raise ContentError(f"{where}: 「{name}」の型が違います（{value!r}）")
        if not isinstance(value, kind):
            raise ContentError(f"{where}: 「{name}」の型が違います（{value!r}）")
        result[name] = value
    return result


def _texts(values: Sequence[Any], where: str) -> tuple[str, ...]:
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ContentError(f"{where}: 文章の並びになっていません")
    return tuple(v.strip() for v in values)


# ---------------------------------------------------------------- 役図鑑


@dataclass(frozen=True)
class Origin:
    text: str            # 由来（事実として言えること。分かれている説は並べて書く）
    certainty: str       # 確実 / 有力 / 諸説あり / 不明


@dataclass(frozen=True)
class Hand:
    """例として載せる手（あがりの状況として書いたもの）"""

    title: str
    spec: Mapping[str, Any]          # engine.scoring.notation.make_context に渡す内容
    note: str = ""                   # 見てほしいところ
    rules: Rules = DEFAULT_RULES

    def context(self) -> WinContext:
        return make_context(**self.spec)


@dataclass(frozen=True)
class Trap:
    """ひっかけ例：その役が付きそうに見えて、付かない手"""

    hand: Hand
    why: str             # なぜ付かないか
    expect: str          # この手は実際にはどうなるか（TRAP_RESULTS の鍵）


@dataclass(frozen=True)
class Combo:
    key: str             # 相手の役のページの鍵
    why: str             # 理由（ひとこと）


@dataclass(frozen=True)
class River:
    """河（捨て牌）の例。手牌の形ではなく、捨て牌で決まる流し満貫の説明に使う"""

    title: str
    tiles: str           # 捨てた順の牌（mpsz 表記）
    ok: bool             # 条件を満たしている例か
    note: str = ""


@dataclass(frozen=True)
class YakuPage:
    key: str                         # ページの鍵（多くは役の鍵と同じ。役牌・国士無双などは、いくつかの役をまとめる）
    yaku: tuple[str, ...]            # このページが扱う役（engine.yaku_table.YAKU の鍵）
    group: str                       # GROUPS の鍵
    name: str
    reading: str
    spoken: str                      # 卓での呼び方（略称）
    short: str                       # ひとことで
    definition: tuple[str, ...]      # 成立条件（箇条書き）
    notes: tuple[str, ...]           # 補足（ルールによって異なる点など）
    kanji: str                       # 字義（漢字それぞれの意味）
    origin: Origin
    examples: tuple[Hand, ...]
    traps: tuple[Trap, ...]
    good: tuple[Combo, ...]          # 複合しやすい役
    never: tuple[Combo, ...]         # 複合しない役
    combo_note: str                  # 複合についての補足（状況で決まる役など、相手を挙げにくいもの）
    rivers: tuple[River, ...]        # 河の例（流し満貫だけ）
    tips: tuple[str, ...]            # 狙い方のコツ
    practice: str | None             # 役指定練習の鍵（一人練習で狙えない役は None）
    practice_note: str = ""          # 練習できない理由など
    han_text: str = ""               # 翻数の書き方（空なら役の表から作る）
    solo: bool = True                # 一人練習で成立しうる役か（スタンプの説明に使う）

    @property
    def is_yakuman(self) -> bool:
        return self.group == "yakuman"


def _wind(value: Any, where: str) -> int:
    if value not in _WINDS:
        raise ContentError(f"{where}: 風は 東・南・西・北 のどれかで書きます（{value!r}）")
    return _WINDS[value]


def _hand(item: Mapping[str, Any], where: str, *, extra: Mapping[str, tuple] | None = None) -> tuple[Hand, dict[str, Any]]:
    """手の書き方を読む。extra は、手のほかに一緒に書いてある項目（ひっかけ例の why など）"""
    fields: dict[str, tuple] = {
        "title": (str, ""),
        "hand": (str, ...),
        "win": (str, ...),
        "melds": (list, []),
        "dora": (str, ""),
        "ura": (str, ""),
        "seat": (str, "南"),
        "round": (str, "東"),
        "honba": (int, 0),
        "kyotaku": (int, 0),
        "note": (str, ""),
        "rules": (dict, {}),
        **{name: (bool, False) for name in _FLAGS},
        **(extra or {}),
    }
    data = _take(item, where, **fields)
    spec: dict[str, Any] = {
        "hand": data["hand"],
        "win": data["win"],
        "melds": list(_texts(data["melds"], f"{where} melds")),
        "dora": data["dora"],
        "ura": data["ura"],
        "seat_wind": _wind(data["seat"], where),
        "round_wind": _wind(data["round"], where),
        "honba": data["honba"],
        "kyotaku": data["kyotaku"],
    }
    for name in _FLAGS:
        if data[name]:
            spec[name] = True
    spec.setdefault("is_tsumo", False)
    unknown_rules = set(data["rules"]) - set(_RULE_FLAGS)
    if unknown_rules:
        raise ContentError(f"{where}: 知らないルールの項目があります {sorted(unknown_rules)}")
    try:
        rules = Rules(**{**DEFAULT_RULES.to_dict(), **data["rules"]})
    except (TypeError, ValueError) as error:
        raise ContentError(f"{where}: ルールの書き方が違います（{error}）") from error
    rest = {name: data[name] for name in (extra or {})}
    return Hand(data["title"].strip(), spec, data["note"].strip(), rules), rest


def _combos(items: Sequence[Any], where: str) -> tuple[Combo, ...]:
    result = []
    for index, item in enumerate(items):
        data = _take(item, f"{where}[{index}]", key=(str, ...), why=(str, ...))
        result.append(Combo(data["key"], data["why"].strip()))
    return tuple(result)


def _yaku_page(item: Mapping[str, Any], index: int) -> YakuPage:
    where = f"yaku.yaml[{index}]"
    key = item.get("key") if isinstance(item, Mapping) else None
    if isinstance(key, str):
        where = f"yaku.yaml（{key}）"
    data = _take(
        item,
        where,
        key=(str, ...),
        yaku=(list, None),
        group=(str, ...),
        name=(str, ""),
        reading=(str, ""),
        spoken=(str, ""),
        short=(str, ...),
        definition=(list, ...),
        notes=(list, []),
        kanji=(str, ...),
        origin=(dict, ...),
        examples=(list, []),
        traps=(list, []),
        good=(list, []),
        never=(list, []),
        combo_note=(str, ""),
        rivers=(list, []),
        tips=(list, ...),
        practice=(str, None),
        practice_note=(str, ""),
        han_text=(str, ""),
        solo=(bool, True),
    )
    keys = tuple(data["yaku"]) if data["yaku"] is not None else (data["key"],)
    for yaku_key in keys:
        if yaku_key not in YAKU:
            raise ContentError(f"{where}: 役の表に無い役です（{yaku_key!r}）")
    if data["group"] not in GROUPS:
        raise ContentError(f"{where}: group は {list(GROUPS)} のどれかです")
    first = YAKU[keys[0]] if keys else None
    name = data["name"] or (first.name if first else "")
    reading = data["reading"] or (first.reading if first else "")
    if not name or not reading:
        raise ContentError(f"{where}: 名前と読みが要ります")
    origin = _take(data["origin"], f"{where} origin", text=(str, ...), certainty=(str, ...))
    if origin["certainty"] not in CERTAINTIES:
        raise ContentError(f"{where}: 由来の確かさは {CERTAINTIES} のどれかです")

    examples = tuple(_hand(e, f"{where} examples[{i}]")[0] for i, e in enumerate(data["examples"]))
    traps = []
    for i, entry in enumerate(data["traps"]):
        hand, rest = _hand(entry, f"{where} traps[{i}]", extra={"why": (str, ...), "expect": (str, ...)})
        if rest["expect"] not in TRAP_RESULTS:
            raise ContentError(f"{where} traps[{i}]: expect は {list(TRAP_RESULTS)} のどれかです")
        traps.append(Trap(hand, rest["why"].strip(), rest["expect"]))

    rivers = []
    for i, entry in enumerate(data["rivers"]):
        raw = _take(entry, f"{where} rivers[{i}]", title=(str, ...), tiles=(str, ...), ok=(bool, ...), note=(str, ""))
        rivers.append(River(raw["title"].strip(), raw["tiles"], raw["ok"], raw["note"].strip()))

    return YakuPage(
        key=data["key"],
        yaku=keys,
        group=data["group"],
        name=name,
        reading=reading,
        spoken=data["spoken"] or (first.spoken if first else reading),
        short=data["short"].strip(),
        definition=_texts(data["definition"], f"{where} definition"),
        notes=_texts(data["notes"], f"{where} notes"),
        kanji=data["kanji"].strip(),
        origin=Origin(origin["text"].strip(), origin["certainty"]),
        examples=examples,
        traps=tuple(traps),
        good=_combos(data["good"], f"{where} good"),
        never=_combos(data["never"], f"{where} never"),
        combo_note=data["combo_note"].strip(),
        rivers=tuple(rivers),
        tips=_texts(data["tips"], f"{where} tips"),
        practice=data["practice"],
        practice_note=data["practice_note"].strip(),
        han_text=data["han_text"].strip(),
        solo=data["solo"],
    )


@cache
def yaku_pages() -> tuple[YakuPage, ...]:
    """役図鑑のページ（図鑑に並べる順）"""
    items = _load("yaku.yaml")
    if not isinstance(items, list):
        raise ContentError("yaku.yaml: 役の並び（リスト）になっていません")
    pages = tuple(_yaku_page(item, index) for index, item in enumerate(items))
    keys = [page.key for page in pages]
    if len(set(keys)) != len(keys):
        raise ContentError("yaku.yaml: 同じ鍵のページが 2 つあります")
    known = set(keys)
    for page in pages:
        for combo in (*page.good, *page.never):
            if combo.key not in known:
                raise ContentError(f"yaku.yaml（{page.key}）: 複合の相手が図鑑にありません（{combo.key!r}）")
    return pages


@cache
def yaku_page_map() -> dict[str, YakuPage]:
    return {page.key: page for page in yaku_pages()}


@cache
def page_of_yaku() -> dict[str, str]:
    """役の鍵 → その役を扱うページの鍵"""
    return {yaku_key: page.key for page in yaku_pages() for yaku_key in page.yaku}


# ---------------------------------------------------------------- 役の出やすさ


#: 出やすさの目安の区切り（あがりに占める割合）
FREQUENCY_LEVELS = (("よく出る", 0.10), ("ときどき", 0.01), ("まれ", 0.0))


@dataclass(frozen=True)
class StatSource:
    title: str
    site: str
    url: str
    published: str
    data: str            # 何を数えたものか
    games: int
    hands: int           # 局数
    wins: int            # 和了数（割合の分母）


@dataclass(frozen=True)
class YakuStat:
    count: int                 # 回数
    total: int                 # 分母（ふつうは和了数。流し満貫だけは局数）
    per: str = "和了"          # 分母の呼び方
    note: str = ""

    @property
    def rate(self) -> float:
        return self.count / self.total if self.total else 0.0

    @property
    def level(self) -> str:
        """出やすさの目安（よく出る／ときどき／まれ）"""
        return next(name for name, low in FREQUENCY_LEVELS if self.rate >= low)

    @property
    def one_in(self) -> int | None:
        """「約 n 回に 1 回」の n（1 回も無ければ None）"""
        return round(self.total / self.count) if self.count else None


@dataclass(frozen=True)
class Reference:
    """補足に使った、もう 1 つの資料"""

    title: str
    site: str
    url: str
    seen: str            # 見た日（内容が入れ替わるページのため）
    text: str            # その資料から言えること


@dataclass(frozen=True)
class YakuStats:
    source: StatSource
    pages: Mapping[str, YakuStat] = field(default_factory=dict)      # ページの鍵 → 統計
    notes: tuple[str, ...] = ()
    references: tuple[Reference, ...] = ()


@cache
def yaku_stats() -> YakuStats:
    data = _take(
        _load("yaku_stats.yaml"), "yaku_stats.yaml",
        source=(dict, ...), counts=(dict, ...), notes=(list, []), references=(list, []),
    )
    src = _take(
        data["source"], "yaku_stats.yaml source",
        title=(str, ...), site=(str, ...), url=(str, ...), published=(str, ...), data=(str, ...),
        games=(int, ...), hands=(int, ...), wins=(int, ...),
    )
    source = StatSource(**src)
    pages: dict[str, YakuStat] = {}
    for key, value in data["counts"].items():
        where = f"yaku_stats.yaml counts（{key}）"
        if isinstance(value, int) and not isinstance(value, bool):
            pages[key] = YakuStat(value, source.wins)
            continue
        entry = _take(value, where, count=(int, ...), per=(str, "和了"), note=(str, ""))
        total = source.hands if entry["per"] == "局" else source.wins
        pages[key] = YakuStat(entry["count"], total, entry["per"], entry["note"].strip())
    references = []
    for index, item in enumerate(data["references"]):
        raw = _take(
            item, f"yaku_stats.yaml references[{index}]",
            title=(str, ...), site=(str, ...), url=(str, ...), seen=(str, ...), text=(str, ...),
        )
        references.append(Reference(raw["title"], raw["site"], raw["url"], raw["seen"], raw["text"].strip()))
    return YakuStats(source, pages, _texts(data["notes"], "yaku_stats.yaml notes"), tuple(references))


# ---------------------------------------------------------------- 出典


@dataclass(frozen=True)
class Source:
    title: str
    url: str


def _sources(items: Sequence[Any], where: str) -> tuple[Source, ...]:
    result = []
    for index, item in enumerate(items):
        raw = _take(item, f"{where} sources[{index}]", title=(str, ...), url=(str, ...))
        if not raw["url"].startswith("https://"):
            raise ContentError(f"{where} sources[{index}]: URL は https:// で始めます")
        result.append(Source(raw["title"].strip(), raw["url"].strip()))
    return tuple(result)


# ---------------------------------------------------------------- 用語辞典


@dataclass(frozen=True)
class Term:
    term: str                        # 見出し語
    reading: str                     # 読み（カタカナ、または ひらがな）
    category: str                    # 分類（glossary_categories の鍵）
    meaning: str                     # 意味
    alt: str = ""                    # 別の読み・別の書き方・略称
    kanji: str = ""                  # 字義
    origin: Origin | None = None     # 由来（分からないものは書かない）
    example: str = ""                # 例（牌の書き方。画面で牌の絵にする）
    example_note: str = ""
    ruby: bool = False               # 画面の文章に出てきたとき、初出にルビを振る用語か
    see: tuple[str, ...] = ()        # 関連する見出し語

    @property
    def anchor(self) -> str:
        return self.term


@dataclass(frozen=True)
class Glossary:
    categories: Mapping[str, str]    # 分類の鍵 → 表示名（表示する順）
    terms: tuple[Term, ...]
    sources: tuple[Source, ...] = ()   # 由来を調べるのに使った資料（役図鑑の由来も同じ資料による）

    def of(self, category: str) -> tuple[Term, ...]:
        return tuple(t for t in self.terms if t.category == category)

    def find(self, term: str) -> Term | None:
        return next((t for t in self.terms if t.term == term), None)


@cache
def glossary() -> Glossary:
    data = _take(_load("terms.yaml"), "terms.yaml", categories=(dict, ...), terms=(list, ...), sources=(list, []))
    categories = {str(key): str(name) for key, name in data["categories"].items()}
    terms = []
    for index, item in enumerate(data["terms"]):
        where = f"terms.yaml[{index}]"
        if isinstance(item, Mapping) and isinstance(item.get("term"), str):
            where = f"terms.yaml（{item['term']}）"
        entry = _take(
            item, where,
            term=(str, ...), reading=(str, ...), category=(str, ...), meaning=(str, ...), alt=(str, ""), kanji=(str, ""),
            origin=(dict, None), example=(str, ""), example_note=(str, ""), ruby=(bool, False), see=(list, []),
        )
        if entry["category"] not in categories:
            raise ContentError(f"{where}: 分類は {list(categories)} のどれかです")
        origin = None
        if entry["origin"] is not None:
            raw = _take(entry["origin"], f"{where} origin", text=(str, ...), certainty=(str, ...))
            if raw["certainty"] not in CERTAINTIES:
                raise ContentError(f"{where}: 由来の確かさは {CERTAINTIES} のどれかです")
            origin = Origin(raw["text"].strip(), raw["certainty"])
        terms.append(
            Term(
                term=entry["term"].strip(),
                reading=entry["reading"].strip(),
                category=entry["category"],
                meaning=entry["meaning"].strip(),
                alt=entry["alt"].strip(),
                kanji=entry["kanji"].strip(),
                origin=origin,
                example=entry["example"].strip(),
                example_note=entry["example_note"].strip(),
                ruby=entry["ruby"],
                see=_texts(entry["see"], f"{where} see"),
            )
        )
    names = [t.term for t in terms]
    if len(set(names)) != len(names):
        doubled = sorted({n for n in names if names.count(n) > 1})
        raise ContentError(f"terms.yaml: 同じ見出し語が 2 つあります {doubled}")
    known = set(names)
    for term in terms:
        missing = [s for s in term.see if s not in known]
        if missing:
            raise ContentError(f"terms.yaml（{term.term}）: 関連語が辞典にありません {missing}")
    return Glossary(categories, tuple(terms), _sources(data["sources"], "terms.yaml"))


# ---------------------------------------------------------------- 卓で打つとき


@dataclass(frozen=True)
class GuideSection:
    key: str
    title: str
    summary: str                 # ひとことで
    steps: tuple[str, ...]       # 順番にすること
    points: tuple[str, ...]      # 覚えておくこと
    differ: tuple[str, ...]      # 卓やルールによって違うところ


@dataclass(frozen=True)
class TableGuide:
    intro: str
    sections: tuple[GuideSection, ...]
    sources: tuple[Source, ...]


@cache
def table_guide() -> TableGuide:
    data = _take(_load("table.yaml"), "table.yaml", intro=(str, ...), sections=(list, ...), sources=(list, ...))
    sections = []
    for index, item in enumerate(data["sections"]):
        where = f"table.yaml sections[{index}]"
        raw = _take(
            item, where,
            key=(str, ...), title=(str, ...), summary=(str, ...), steps=(list, ...), points=(list, []), differ=(list, []),
        )
        sections.append(
            GuideSection(
                raw["key"], raw["title"].strip(), raw["summary"].strip(),
                _texts(raw["steps"], f"{where} steps"), _texts(raw["points"], f"{where} points"), _texts(raw["differ"], f"{where} differ"),
            )
        )
    keys = [section.key for section in sections]
    if len(set(keys)) != len(keys):
        raise ContentError("table.yaml: 同じ鍵の節が 2 つあります")
    return TableGuide(data["intro"].strip(), tuple(sections), _sources(data["sources"], "table.yaml"))


# ---------------------------------------------------------------- ルールの違い


@dataclass(frozen=True)
class RuleSide:
    answer: str          # 採っている決まり
    who: str             # それを採っているルール


@dataclass(frozen=True)
class RuleItem:
    key: str
    group: str                       # RuleBook.groups の鍵
    title: str
    ask: str                         # 何を確かめるか
    sides: tuple[RuleSide, ...]
    app: str = ""                    # このアプリの扱い（まだ関係しないものは空）
    setting: str | None = None       # ルール設定（engine.rules.Rules）の項目名
    default: Any = None              # その初期値（設定と食い違っていないかをテストで確かめる）
    note: str = ""
    check: bool = False              # 卓に着く前に確かめたい項目か


@dataclass(frozen=True)
class RuleBook:
    intro: str
    surveyed: str                    # 調べた日
    names: Mapping[str, str]         # 読みくらべたルールの呼び名
    groups: Mapping[str, str]        # まとまりの鍵 → 表示名（表示する順）
    items: tuple[RuleItem, ...]
    sources: tuple[Source, ...]
    caveats: tuple[str, ...]

    def of(self, group: str) -> tuple[RuleItem, ...]:
        return tuple(item for item in self.items if item.group == group)

    @property
    def checklist(self) -> tuple[RuleItem, ...]:
        return tuple(item for item in self.items if item.check)


@cache
def rule_book() -> RuleBook:
    data = _take(
        _load("rules.yaml"), "rules.yaml",
        intro=(str, ...), surveyed=(str, ...), names=(dict, ...), groups=(dict, ...), items=(list, ...),
        sources=(list, ...), caveats=(list, []),
    )
    groups = {str(key): str(name) for key, name in data["groups"].items()}
    items = []
    for index, item in enumerate(data["items"]):
        where = f"rules.yaml items[{index}]"
        if isinstance(item, Mapping) and isinstance(item.get("key"), str):
            where = f"rules.yaml（{item['key']}）"
        raw = _take(
            item, where,
            key=(str, ...), group=(str, ...), title=(str, ...), ask=(str, ...), sides=(list, ...), app=(str, ""),
            setting=(str, None), default=((bool, int), None), note=(str, ""), check=(bool, False),
        )
        if raw["group"] not in groups:
            raise ContentError(f"{where}: group は {list(groups)} のどれかです")
        if raw["setting"] is not None and raw["setting"] not in _RULE_FLAGS:
            raise ContentError(f"{where}: ルール設定に無い項目です（{raw['setting']!r}）")
        if (raw["setting"] is None) != (raw["default"] is None):
            raise ContentError(f"{where}: setting と default は、両方書くか、両方書かないかです")
        sides = []
        for number, side in enumerate(raw["sides"]):
            pair = _take(side, f"{where} sides[{number}]", answer=(str, ...), who=(str, ...))
            sides.append(RuleSide(pair["answer"].strip(), pair["who"].strip()))
        if not sides:
            raise ContentError(f"{where}: sides が空です")
        items.append(
            RuleItem(
                raw["key"], raw["group"], raw["title"].strip(), raw["ask"].strip(), tuple(sides), raw["app"].strip(),
                raw["setting"], raw["default"], raw["note"].strip(), raw["check"],
            )
        )
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        raise ContentError("rules.yaml: 同じ鍵の項目が 2 つあります")
    return RuleBook(
        data["intro"].strip(), data["surveyed"], {str(k): str(v) for k, v in data["names"].items()}, groups,
        tuple(items), _sources(data["sources"], "rules.yaml"), _texts(data["caveats"], "rules.yaml caveats"),
    )

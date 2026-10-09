"""AI の文を、事実データと照らし合わせる（間違いを教えないため）。

AI（LLM）には、エンジンが計算した結果だけを「事実」として渡す。返ってきた文に、事実に無い
  ・数（点・符・翻・枚数・種類・向聴数・本場・%・巡目。単位の無い数も。「向聴数は 2」「ドラ 3」のような書き方も）
  ・数牌（5萬・3筒・7索・5m・ウーピン など。字牌は「東家」「白い」のように普通のことばと区別できないので見ない）
  ・役の名前（断么九・タンヤオ・三色 など。リーチ・ツモ・役牌は、打ち方のことばと区別できないので見ない）
  ・この手の点数の段階（「跳満になります」のような言い方の、満貫・跳満・倍満・三倍満・役満）
が入っていたら、それを「確かめられない主張」として返す。呼び出す側は、書き直させるか、その部分を伏せる。

照らし合わせは、文字どおりの一致で行う（「3,900」と「3900」、全角と半角、漢数字と算用数字は同じとみなす）。
事実データの文と、AI の文を、同じ読み方で読む。事実の「6〜7 翻」のような範囲は、6 翻と 7 翻の両方として読む。

文字どおりの照らし合わせなので、事実のどこかに同じ単位で出てくる数は通る（点数の決まりの「満貫 8,000 点」が
ある限り、「この手は 8,000 点」も通る）。単位の無い数を「点」として認めるのは、その局面だけの計算
（Facts.point_text。点数の式・支払いなど）に出てくる 100 以上の数だけ（基本点の 960、切り上げ前の 3,840 など）。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from engine.yaku_table import YAKU

#: 値を確かめる単位（「向聴」には、カタカナの「シャンテン」も含める）
UNITS = ("点", "符", "翻", "枚", "種", "向聴", "本場", "%", "巡")
_UNIT_ALIASES = {"シャンテン": "向聴", "種類": "種", "巡目": "巡", "ハン": "翻", "飜": "翻", "フ": "符"}
#: カタカナの単位は、あとにカタカナが続くときは単位ではない（「2 フーロ」「ハンデ」）
_KATAKANA_UNITS = ("フ", "ハン", "シャンテン")
#: 単位の無い数で、事実に無くても許す大きさ（「2 つの面子」のような数え方）
SMALL = 10
MASK = "〔?〕"
#: 点数の段階の呼び名（長いものから）
LEVEL_WORDS = ("数え役満", "三倍満", "倍満", "跳満", "満貫", "役満")

# 全角の数字・記号を半角に、肩付きの数字（2⁵ の ⁵）を「^」に置きかえる（1 文字ずつ。位置は変わらない）
_FULLWIDTH = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH.update({ord("，"): ord(","), ord("％"): ord("%"), ord("．"): ord(".")})
_FULLWIDTH.update({ord("Ｍ"): ord("M"), ord("Ｐ"): ord("P"), ord("Ｓ"): ord("S"), ord("ｍ"): ord("m"), ord("ｐ"): ord("p"), ord("ｓ"): ord("s")})
_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_PARSE_TABLE = {**_FULLWIDTH, **{ord(c): ord("^") for c in _SUPERSCRIPTS}}

_KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}

_SUITS = {"萬": "萬", "万": "萬", "マン": "萬", "ワン": "萬", "m": "萬", "M": "萬", "筒": "筒", "ピン": "筒", "p": "筒", "P": "筒",
          "索": "索", "ソー": "索", "ソウ": "索", "s": "索", "S": "索"}
# 数牌：5萬・赤5筒・234索・5m・5M（算用数字）、五萬・三索（漢数字。万は数の「万」と紛れるので、漢数字では萬・筒・索だけ）、
# ウーピン・リャンソー（カタカナの読み）。「1万点」「1万を超える」の万は、牌ではない
_TILE_DIGITS = re.compile(
    r"(?<![0-9,.])(赤)?([1-9]+)\s?(萬|万(?![点円0-9千百十]|を超|以上|以下|未満|近く)|筒|索|マン|ワン|ピン|ソー|ソウ|[mpsMPS](?![a-zA-Z]))"
)
_TILE_KANJI = re.compile(r"(赤)?([一二三四五六七八九])(萬|筒|索)")
_KATAKANA_DIGITS = {"イー": 1, "リャン": 2, "サン": 3, "スー": 4, "ウー": 5, "ロー": 6, "チー": 7, "パー": 8, "キュー": 9}
_TILE_KATAKANA = re.compile(r"(赤)?(イー|リャン|サン|スー|ウー|ロー|チー|パー|キュー)(マン|ワン|ピン|ソー|ソウ)")
_UNIT_PATTERN = "|".join(
    re.escape(word) + ("(?![ァ-ヶー])" if word in _KATAKANA_UNITS else "")
    for word in sorted([*UNITS, *_UNIT_ALIASES], key=len, reverse=True)
)
_NUMBER_UNIT = re.compile(rf"(?<![0-9.^])(\d{{1,3}}(?:,\d{{3}})+|\d+)(\.\d+)?\s?({_UNIT_PATTERN})")
_KANJI_UNIT = re.compile(rf"([〇零一二三四五六七八九十百千]+(?:万[〇零一二三四五六七八九十百千]*)?)\s?({_UNIT_PATTERN})")
_BARE_NUMBER = re.compile(r"(?<![0-9.^])(\d{1,3}(?:,\d{3})+|\d+)(?![0-9])")
# 「5万点」「1万2000点」「2万5千点」（算用数字と万）
_MAN_POINTS = re.compile(r"(?<![0-9.^])(\d+)万(?:(\d{1,4})|(\d)千(?:(\d)百)?)?\s?(点)")
# 単位のことばが先に来る書き方：「向聴数は 2」「翻数が 4」（「向聴数が 1 つ進む」のような、増え減りの数は除く）
_TOPIC_UNITS = {"向聴数": "向聴", "シャンテン数": "向聴", "翻数": "翻", "飜数": "翻", "符数": "符"}
_TOPIC = re.compile(
    r"(向聴数|シャンテン数|翻数|飜数|符数)\s?(?:は|が|も|：|:|＝|=)?\s?(\d+)(?![0-9.])(?!\s?(?:つ|段|減|増|進|下|上|多|少|戻|遠|近|回))"
)
# ドラの数：「ドラ 3」「赤ドラが 2 枚」「裏ドラ 1 つ」（ドラ表示牌のことではない）
_DORA = re.compile(
    r"((?:赤|裏|槓|カン)?ドラ)(?!表示)\s?(?:が|は|を|も)?\s?(\d+)(?![0-9.])"
    r"(?!\s?(?:翻|種|本|点|符|向聴|巡|%|萬|万|筒|索|マン|ワン|ピン|ソー|ソウ|[mpsMPS]))\s?(?:つ|個|枚)?"
)
# この手の点数の段階を言い切る書き方：「跳満になります」「満貫です」「倍満の手」
_LEVEL = re.compile(rf"(?<!流し)({'|'.join(LEVEL_WORDS)})(?=\s?(?:になる|になり|になっ|になれ|です|でした|だ[。、]|の手|のあがり|確定))")
_LEVEL_WORD = re.compile("|".join(LEVEL_WORDS))
# 範囲（「6〜7 翻」）
_RANGE = re.compile(rf"(?<![0-9.^])(\d+)\s?[〜~～]\s?(\d+)\s?({_UNIT_PATTERN})")
#: 範囲を 1 つずつ数に開くのは、この幅まで
MAX_RANGE = 20


@dataclass(frozen=True)
class Claim:
    kind: str       # "number"（単位つき）・"bare"（単位なし）・"tile"・"yaku"・"dora"（ドラの数）・"level"（点数の段階）
    value: str      # 比べる値（例: "3900点"、"3900"、"5萬"、"tanyao"、"ドラ3"、"跳満"）
    start: int      # 文の中の位置（伏せるときに使う）
    end: int
    text: str       # 文の中の書き方


@dataclass(frozen=True)
class Allowed:
    """事実データ（と質問）に出てくるもの"""

    numbers: frozenset[str]                         # 単位つきの数（例: "3900点"）
    values: frozenset[int]                          # 出てくる数すべて（単位の有無を問わない）
    tiles: frozenset[str]                           # 数牌（例: "5萬"）
    yaku: frozenset[str]                            # 役の鍵（例: "tanyao"）
    point_values: frozenset[int] = frozenset()      # その局面の計算に、単位なしで出てくる数（「点」として認める）
    dora: frozenset[str] = frozenset()              # ドラの数（例: "ドラ2"・"赤ドラ1"）
    levels: frozenset[str] = frozenset()            # その局面の計算に出てくる、点数の段階（例: "満貫"）


def _parse_copy(text: str) -> str:
    return text.translate(_PARSE_TABLE)


def kanji_number(text: str) -> int | None:
    """漢数字（三千九百、二十、一万二千 など）を数にする。読めなければ None（「二〇」のような位取りの書き方も読まない）"""
    total, section = 0, 0
    current: int | None = None
    for ch in text:
        if ch in _KANJI_DIGITS:
            if current is not None:
                return None
            current = _KANJI_DIGITS[ch]
        elif ch in _KANJI_UNITS:
            section += (1 if current is None else current) * _KANJI_UNITS[ch]
            current = None
        elif ch == "万":
            section += current or 0
            total += (section or 1) * 10_000
            section, current = 0, None
        else:
            return None
    return total + section + (current or 0)


def _int(text: str) -> int:
    return int(text.replace(",", ""))


#: 役の名前の、よく使う別の書き方・略し方（→ 役の鍵）
YAKU_ALIASES = {
    "断幺九": "tanyao", "混全帯幺九": "chanta", "純全帯幺九": "junchan", "三色": "sanshoku", "一通": "ittsu",
    "チートイ": "chiitoitsu", "トイトイ": "toitoi", "対対和": "toitoi", "ダブリー": "double_riichi",
    "国士": "kokushi", "九蓮": "chuuren", "流し満貫": "nagashi",
    "純チャン": "junchan", "イーペー": "iipeikou", "イーペーコー": "iipeikou", "リャンペー": "ryanpeikou",
}
#: 打ち方のことば（リーチする・ツモる・役牌を鳴く）と区別できない役。文の照らし合わせでは見ない
PLAIN_WORD_YAKU = frozenset({"riichi", "menzen_tsumo", "yakuhai_haku", "yakuhai_hatsu", "yakuhai_chun", "yakuhai_seat", "yakuhai_round"})


def yaku_names(*, every: bool = False) -> list[tuple[str, str]]:
    """役の名前の書き方 →役の鍵（長いものから）。

    every が False（照らし合わせ用）なら、リーチ・ツモ・役牌（PLAIN_WORD_YAKU）を入れず、
    嶺上開花・槍槓・海底摸月・河底撈魚のカタカナの呼び方（牌や場面の名前と紛れる）も入れない。
    every が True（質問に出てくる役を探す用）なら、すべての役の名前・読み・3 文字以上の呼び方を入れる。
    """
    katakana_ok = {"rinshan", "chankan", "haitei", "houtei"}
    names: dict[str, str] = {}
    for key, info in YAKU.items():
        if key in PLAIN_WORD_YAKU and not every:
            continue
        names[info.name] = key
        if key not in katakana_ok or every:
            names[info.reading.replace(" ", "")] = key
            if info.spoken and len(info.spoken) >= 3:
                names[info.spoken] = key
    names.update(YAKU_ALIASES)
    if every:
        names["役牌"] = "yakuhai_haku"
    return sorted(names.items(), key=lambda item: len(item[0]), reverse=True)


_YAKU_NAMES = yaku_names()
_YAKU_PATTERN = re.compile("|".join(re.escape(name) for name, _ in _YAKU_NAMES))
_YAKU_KEYS = dict(_YAKU_NAMES)


def claims(text: str) -> list[Claim]:
    """文の中の主張（数・数牌・役の名前・ドラの数・点数の段階）を、出てくる順に挙げる"""
    parsed = _parse_copy(text)
    found: list[Claim] = []
    taken = [False] * len(parsed)

    def take(start: int, end: int) -> bool:
        if any(taken[start:end]):
            return False
        for i in range(start, end):
            taken[i] = True
        return True

    def add(kind: str, value: str, match: re.Match) -> None:
        found.append(Claim(kind, value, match.start(), match.end(), text[match.start():match.end()]))

    for match in _LEVEL.finditer(parsed):
        if take(match.start(), match.end()):
            add("level", match.group(1), match)
    for match in _YAKU_PATTERN.finditer(parsed):
        if take(match.start(), match.end()):
            add("yaku", _YAKU_KEYS[match.group(0)], match)
    for match in _MAN_POINTS.finditer(parsed):
        if take(match.start(), match.end()):
            rest = int(match.group(2)) if match.group(2) else int(match.group(3) or 0) * 1000 + int(match.group(4) or 0) * 100
            add("number", f"{int(match.group(1)) * 10_000 + rest}点", match)
    for match in _DORA.finditer(parsed):
        if take(match.start(), match.end()):
            add("dora", f"{match.group(1).replace('カン', '槓')}{int(match.group(2))}", match)
    for match in _TOPIC.finditer(parsed):
        if take(match.start(), match.end()):
            add("number", f"{int(match.group(2))}{_TOPIC_UNITS[match.group(1)]}", match)
    for pattern, digits_of in (
        (_TILE_DIGITS, lambda m: [int(d) for d in m.group(2)]),
        (_TILE_KANJI, lambda m: [_KANJI_DIGITS[m.group(2)]]),
        (_TILE_KATAKANA, lambda m: [_KATAKANA_DIGITS[m.group(2)]]),
    ):
        for match in pattern.finditer(parsed):
            if not take(match.start(), match.end()):
                continue
            suit = _SUITS[match.group(3)]
            for digit in digits_of(match):
                add("tile", f"{digit}{suit}", match)
    for match in _NUMBER_UNIT.finditer(parsed):
        if take(match.start(), match.end()):
            unit = _UNIT_ALIASES.get(match.group(3), match.group(3))
            add("number", f"{_int(match.group(1))}{match.group(2) or ''}{unit}", match)
    for match in _KANJI_UNIT.finditer(parsed):
        if match.group(2) == "巡":
            continue                    # 「一巡」は「ひとまわり」のこと（巡目ではない）。「一巡目」は巡目で読む
        value = kanji_number(match.group(1))
        if value is not None and take(match.start(), match.end()):
            unit = _UNIT_ALIASES.get(match.group(2), match.group(2))
            add("number", f"{value}{unit}", match)
    for match in _BARE_NUMBER.finditer(parsed):
        if take(match.start(), match.end()):
            add("bare", str(_int(match.group(1))), match)
    return sorted(found, key=lambda c: (c.start, c.end))


def _ranges(text: str) -> set[str]:
    """範囲の書き方（「6〜7 翻」）を、1 つずつの数にする（{"6翻", "7翻"}）"""
    found: set[str] = set()
    for match in _RANGE.finditer(_parse_copy(text)):
        low, high = int(match.group(1)), int(match.group(2))
        if low <= high <= low + MAX_RANGE:
            unit = _UNIT_ALIASES.get(match.group(3), match.group(3))
            found.update(f"{value}{unit}" for value in range(low, high + 1))
    return found


def allowed_from(texts: Iterable[str], *, extra_texts: Iterable[str] = (), point_texts: Iterable[str] = ()) -> Allowed:
    """事実データの文（texts）から、使ってよい数・牌・役を集める。extra_texts（利用者の質問）からは、牌と役だけを足す。
    point_texts は、その局面だけの計算の文（Facts.point_text）。ここに単位なしで出てくる 100 以上の数は「点」として認め、
    ここに出てくる点数の段階（満貫・跳満…）は、この手の段階として認める。

    質問に出てきた数は足さない（「3900 点ですか？」と聞かれて、確かめずに「はい、3900 点」と答えるのを防ぐ）。
    """
    numbers: set[str] = set()
    values: set[int] = set()
    tiles: set[str] = set()
    yaku: set[str] = set()
    dora: set[str] = set()
    for text in texts:
        numbers |= _ranges(text)
        for claim in claims(text):
            if claim.kind == "number":
                numbers.add(claim.value)
                head = re.match(r"\d+", claim.value)
                assert head is not None
                values.add(int(head.group(0)))
            elif claim.kind == "bare":
                values.add(int(claim.value))
            elif claim.kind == "tile":
                tiles.add(claim.value)
            elif claim.kind == "dora":
                dora.add(claim.value)
                values.add(int(re.sub(r"\D", "", claim.value)))
            elif claim.kind == "yaku":
                yaku.add(claim.value)
    for text in extra_texts:
        for claim in claims(text):
            if claim.kind == "tile":
                tiles.add(claim.value)
            elif claim.kind == "yaku":
                yaku.add(claim.value)
    point_values: set[int] = set()
    levels: set[str] = set()
    for text in point_texts:
        point_values.update(int(c.value) for c in claims(text) if c.kind == "bare")
        point_values.update(int(re.match(r"\d+", c.value).group(0)) for c in claims(text) if c.kind == "number" and c.value.endswith("点"))
        levels.update(match.group(0) for match in _LEVEL_WORD.finditer(text))
    return Allowed(frozenset(numbers), frozenset(values), frozenset(tiles), frozenset(yaku), frozenset(point_values), frozenset(dora),
                   frozenset(levels))


_VALUE = re.compile(r"(\d+)(\.\d+)?(.*)")


def supported(claim: Claim, allowed: Allowed) -> bool:
    """その主張が、事実データで裏付けられるか。

    単位つきの数は、同じ単位で事実に出てくるもの。ただし「点」は、その局面の計算（point_texts）に単位なしで出てくる
    100 以上の数（基本点の 960、切り上げ前の 3,840 など）も認める（「基本点は 960 点」のような言い方をするため）。
    """
    if claim.kind == "number":
        if claim.value in allowed.numbers:
            return True
        match = _VALUE.fullmatch(claim.value)
        assert match is not None
        number = int(match.group(1))
        return match.group(3) == "点" and not match.group(2) and number >= 100 and number in allowed.point_values
    if claim.kind == "bare":
        return int(claim.value) <= SMALL or int(claim.value) in allowed.values
    if claim.kind == "tile":
        return claim.value in allowed.tiles
    if claim.kind == "dora":
        return claim.value in allowed.dora
    if claim.kind == "level":
        return claim.value in allowed.levels
    return claim.value in allowed.yaku


def violations(text: str, allowed: Allowed) -> list[Claim]:
    """事実に無い主張（数・数牌・役・ドラの数・点数の段階）"""
    return [claim for claim in claims(text) if not supported(claim, allowed)]


def describe(bad: Sequence[Claim]) -> str:
    """確かめられない主張を、AI に書き直しを頼むときの書き方にする（例: 「5200点」「3萬」）"""
    seen: list[str] = []
    for claim in bad:
        label = claim.text.strip() if claim.kind != "yaku" else YAKU[claim.value].name if claim.value in YAKU else claim.text
        if label not in seen:
            seen.append(label)
    return "・".join(f"「{label}」" for label in seen)


def mask(text: str, bad: Sequence[Claim]) -> str:
    """確かめられない主張の部分を〔?〕に置きかえる（重なりは 1 つにまとめる）"""
    spans = sorted({(c.start, c.end) for c in bad})
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    out, last = [], 0
    for start, end in merged:
        out.append(text[last:start])
        out.append(MASK)
        last = end
    out.append(text[last:])
    return "".join(out)

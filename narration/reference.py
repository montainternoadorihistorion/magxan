"""質問と事実に出てくる用語・役・卓での作法の説明と、質問に出てきた翻・符の点数を、アプリの中から引く。

AI が用語や役の説明を自分の知識で書くと、まちがいが混じることがある。このアプリの用語辞典（data/terms.yaml）・
役図鑑（data/yaku.yaml）・卓で打つときの手順（data/table.yaml）は、出典を確かめて書いたもの。
そこから、質問と事実に出てくるものだけを選んで、AI に「参考」として渡す。

質問に「30 符 4 翻」「満貫」のような点数の話があれば、その点数をエンジンで計算して渡す（AI に計算させない）。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import cache

from engine.content import YakuPage, glossary, page_of_yaku, table_guide, yaku_page_map
from engine.drills import combo_exists, han_label, pay_text
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.points import calculate_points
from narration.check import claims, yaku_names
from narration.facts import Facts

#: 参考に入れる数の上限（多すぎると、AI がどれを使えばよいか迷う）
MAX_TERMS = 12
MAX_PAGES = 3
MAX_GUIDES = 2
MAX_SCORES = 3
#: 事実の文のうち、用語・役を探さない見出し（どの局面にも付く決まりの説明）
_TAIL_HEADS = ("このアプリのルール", "基本")
#: 点数を計算する符の範囲（20 符は平和のツモ、25 符は七対子。ほかは 10 符単位）
MAX_FU = 130
#: 満貫以上の呼び名と、その代表の翻数・役満の倍数（長い呼び名から並べる）
LEVELS = (("数え役満", 13, 0), ("三倍満", 11, 0), ("倍満", 8, 0), ("跳満", 6, 0), ("満貫", 5, 0), ("役満", 13, 1))

_DIGITS = {ord("０") + i: ord("0") + i for i in range(10)}
_HAN_FU = re.compile(r"(\d+)\s*(?:符|フ)\s*(\d+)\s*(?:翻|ハン)|(\d+)\s*(?:翻|ハン)\s*(\d+)\s*(?:符|フ)")
_HAN_ONLY = re.compile(r"(?<![0-9符フ])(\d+)\s*(?:翻|ハン)(?!\s*\d)")

#: 卓での作法の質問だと分かることば
_MANNER_WORDS = ("発声", "作法", "マナー", "言い方", "言う", "声", "手積み", "点棒", "反則", "チョンボ", "卓では", "実際の卓")
#: 作法の節（table.yaml の鍵）を選ぶことば
_GUIDE_TOPICS = {
    "seat": ("席", "起家", "親を決め"),
    "wall": ("山", "積む", "混ぜ"),
    "deal": ("配牌", "サイコロ"),
    "dora": ("ドラをめく", "ドラ表示牌"),
    "turn": ("捨て", "ツモって", "河"),
    "call": ("鳴", "チー", "ポン", "カン"),
    "riichi": ("リーチ", "立直"),
    "win": ("あが", "ロン", "ツモあがり", "申告", "和了"),
    "points": ("点棒", "払", "お釣り"),
    "draw": ("流局", "ノーテン", "罰符"),
    "foul": ("反則", "チョンボ", "ミス", "間違"),
    "manner": ("マナー", "作法", "気持ち"),
}


def _normalize(text: str) -> str:
    return text.translate(_DIGITS)


# ---------------------------------------------------------------- 用語


@cache
def _term_words() -> tuple[tuple[str, int, bool], ...]:
    """（書き方, 用語の番号, 読みか）。長い書き方から"""
    words = []
    for index, term in enumerate(glossary().terms):
        words.append((term.term, index, False))
        if term.reading and term.reading != term.term:
            words.append((term.reading, index, True))
    return tuple(sorted(words, key=lambda item: -len(item[0])))


def terms_in(text: str, *, question: bool) -> list[int]:
    """文に出てくる用語（用語辞典の番号を、出てくる順に）。

    質問（question）なら、読み（テンパイ・スジなど）や 1 文字の用語（符・翻など）も探す。
    事実の文は長く、1 文字の語や読みが紛れやすい（「ツモ」はどの局面にも出る）ので、2 文字以上の見出し語だけを探す。
    """
    taken = [False] * len(text)
    first: dict[int, int] = {}
    for word, index, reading in _term_words():
        if not question and (reading or len(word) < 2):
            continue
        start = 0
        while (pos := text.find(word, start)) >= 0:
            end = pos + len(word)
            if not any(taken[pos:end]):
                for i in range(pos, end):
                    taken[i] = True
                first.setdefault(index, pos)
            start = end
    return [index for index, _ in sorted(first.items(), key=lambda item: item[1])]


def _term_line(index: int) -> str:
    term = glossary().terms[index]
    reading = f"（{term.reading}）" if term.reading != term.term else ""
    return f"{term.term}{reading}：{term.meaning}"


# ---------------------------------------------------------------- 役


@cache
def _every_yaku() -> tuple[re.Pattern[str], dict[str, str]]:
    names = yaku_names(every=True)
    return re.compile("|".join(re.escape(name) for name, _ in names)), dict(names)


def yaku_pages_in(text: str, *, question: bool) -> list[str]:
    """文に出てくる役の、役図鑑のページの鍵（出てくる順）。

    質問なら、リーチ・ツモ・役牌も含めて探す。事実の文では、照らし合わせと同じ読み方（check.claims）で探す。
    """
    if question:
        pattern, keys = _every_yaku()
        found = [keys[m.group(0)] for m in pattern.finditer(text)]
    else:
        found = [c.value for c in claims(text) if c.kind == "yaku"]
    pages: list[str] = []
    mapping = page_of_yaku()
    for key in found:
        page = mapping.get(key)
        if page is not None and page not in pages:
            pages.append(page)
    return pages


def _han(page: YakuPage) -> str:
    if page.han_text:
        return page.han_text
    return han_label(page) if page.yaku else ""


def _page_lines(page: YakuPage) -> list[str]:
    han = _han(page)
    lines = [f"{page.name}（{page.reading}）" + (f"・{han}" if han else "") + f"：{page.short}"]
    if page.definition:
        lines.append("条件：" + "／".join(page.definition))
    lines.extend(page.notes)
    return lines


# ---------------------------------------------------------------- 卓での作法


def guides_in(question: str) -> list[str]:
    """作法の質問なら、関係する節（table.yaml の鍵）。作法の質問でなければ空"""
    if not any(word in question for word in _MANNER_WORDS):
        return []
    keys = [key for key, words in _GUIDE_TOPICS.items() if any(word in question for word in words)]
    return (keys or ["manner"])[:MAX_GUIDES]


def _guide_lines(key: str) -> list[str]:
    section = next((s for s in table_guide().sections if s.key == key), None)
    if section is None:
        return []
    return [f"{section.title}：{section.summary}", *(f"手順：{s}" for s in section.steps),
            *(f"覚えておくこと：{p}" for p in section.points), *(f"卓やルールで違うこと：{d}" for d in section.differ)]


# ---------------------------------------------------------------- 質問に出てきた点数


def _row(han: int, fu: int, times: int, rules: Rules) -> str:
    """子のロン・子のツモ・親のロン・親のツモの点数（実際に無い組み合わせは、そう書く）"""
    parts = []
    for dealer in (False, True):
        for tsumo in (False, True):
            label = f"{'親' if dealer else '子'}の{'ツモ' if tsumo else 'ロン'}"
            if han < 5 and not times and not combo_exists(fu, han, tsumo):
                parts.append(f"{label}は、この組み合わせが無い")
                continue
            points = calculate_points(han, fu, yakuman_times=times, is_dealer=dealer, is_tsumo=tsumo, honba=0, kyotaku=0, rules=rules)
            parts.append(f"{label} {pay_text(points, tsumo=tsumo, dealer=dealer)}")
    return "・".join(parts)


def scores_in(question: str, rules: Rules = DEFAULT_RULES) -> list[str]:
    """質問に出てきた翻・符・満貫などの点数を、エンジンで計算した行（本場・供託なし）"""
    text = _normalize(question)
    lines: list[str] = []
    seen: set[tuple[int, int, int]] = set()

    def add(han: int, fu: int, times: int, head: str) -> None:
        if (han, fu, times) in seen or len(lines) >= MAX_SCORES:
            return
        seen.add((han, fu, times))
        lines.append(f"{head}：{_row(han, fu, times, rules)}。")

    for match in _HAN_FU.finditer(text):
        fu, han = (int(match.group(1)), int(match.group(2))) if match.group(1) else (int(match.group(4)), int(match.group(3)))
        if not 1 <= han <= 13:
            lines.append(f"{han} 翻：翻数は 1 以上（13 翻以上は数え役満か三倍満。ルールによって異なる）。")
            continue
        if han >= 5:
            add(han, 30, 0, f"{han} 翻（5 翻以上は、符に関係なく点数が決まる）")
        elif fu != 25 and (fu % 10 or fu < 20):
            lines.append(f"{fu} 符のあがりは無い（符の合計は 20 符以上で、10 符単位に切り上げる。七対子だけは 25 符で、切り上げない）。")
        elif fu <= MAX_FU:
            add(han, fu, 0, f"{fu} 符 {han} 翻")
    for match in _HAN_ONLY.finditer(text):
        han = int(match.group(1))
        if 5 <= han <= 13:
            add(han, 30, 0, f"{han} 翻（5 翻以上は、符に関係なく点数が決まる）")
    rest = text
    for name, han, times in LEVELS:           # 長い呼び名から（「三倍満」の中の「倍満」、「数え役満」の中の「役満」を数えない）
        if name in rest:
            level = calculate_points(han, 30, yakuman_times=times, is_dealer=False, is_tsumo=False, honba=0, kyotaku=0, rules=rules).level_name
            add(han, 30, times, name if level == name else f"{name}（このルールでは{level}）")
            rest = rest.replace(name, "　")
    return lines


# ---------------------------------------------------------------- まとめ


def reference_sections(facts: Facts, question: str = "") -> list[tuple[str, list[str]]]:
    """AI に渡す参考の節（見出し, 文）。質問に出てくるものを先に、事実に出てくるものをあとに選ぶ"""
    body = "\n".join(line for head, lines in facts.sections if head not in _TAIL_HEADS for line in (head, *lines))
    sections: list[tuple[str, list[str]]] = []
    scores = scores_in(question, facts.rules) if question else []
    if scores:
        sections.append(("質問に出てきた点数（エンジンで計算。本場・供託なし）", scores))
    pages = _merge(yaku_pages_in(question, question=True) if question else [], yaku_pages_in(body, question=False))[:MAX_PAGES]
    page_map = yaku_page_map()
    page_lines = [line for key in pages for line in _page_lines(page_map[key])]
    if page_lines:
        sections.append(("役の説明（このアプリの役図鑑より）", page_lines))
    guides = guides_in(question) if question else []
    guide_lines = [line for key in guides for line in _guide_lines(key)]
    if guide_lines:
        sections.append(("実際の卓での手順と作法（このアプリの「卓で打つとき」より）", guide_lines))
    terms = _merge(terms_in(question, question=True) if question else [], terms_in(body, question=False))[:MAX_TERMS]
    if terms:
        sections.append(("用語の意味（このアプリの用語辞典より）", [_term_line(index) for index in terms]))
    return sections


def _merge(first: Sequence, second: Iterable) -> list:
    merged = list(dict.fromkeys(first))
    for item in second:
        if item not in merged:
            merged.append(item)
    return merged


def reference_text(facts: Facts, question: str = "") -> str:
    """参考の節を、事実と同じ書き方の文にする（空なら空）"""
    lines = []
    for head, body in reference_sections(facts, question):
        lines.append(f"【参考：{head}】")
        lines.extend(body)
    return "\n".join(lines)

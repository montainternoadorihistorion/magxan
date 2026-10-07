"""「学ぶ」のページ（役図鑑・用語辞典・卓で打つとき・ルールの違い）に出す HTML づくり。

内容は data/ のファイル（engine.content が読む）。例として載せる手の役と点数は、その場で点数計算にかけて出す
（ファイルには、役や点数を書いていない）。Streamlit には依存しない（HTML の文字列を返すだけ）。
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from html import escape

from engine.content import (
    CERTAINTY_MEANINGS,
    GROUPS,
    TRAP_RESULTS,
    Glossary,
    GuideSection,
    Hand,
    Origin,
    RuleBook,
    RuleItem,
    Source,
    Term,
    Trap,
    YakuPage,
    YakuStat,
    YakuStats,
    yaku_page_map,
)
from engine.drills import han_label, level_row, rule_notes, table_row
from engine.progress import Completion, Stamp
from engine.records import TargetStat
from engine.scoring.explain import Explanation, Status, explain
from engine.tiles import TileError, parse_tiles
from engine.yaku_table import YAKU
from ui.practice_view import percent
from ui.ruby import Rubifier
from ui.tile_view import tile_img
from ui.timefmt import date_text
from ui.win_view import checks_html, chips_html, hand_html, payment_text, situation_chips, tiles_fit_html

#: 用語辞典で、役の名前をまとめる分類の鍵
YAKU_CATEGORY = "yaku"
YAKU_CATEGORY_NAME = "役の名前"
#: 出やすさの目安の色
LEVEL_CLASS = {"よく出る": "good", "ときどき": "soso", "まれ": "rare"}


def _list(items: Iterable[str], rb: Rubifier, *, ordered: bool = False, cls: str = "mj-rules") -> str:
    tag = "ol" if ordered else "ul"
    return f'<{tag} class="{cls}">' + "".join(f"<li>{rb.html(item)}</li>" for item in items) + f"</{tag}>"


def subhead(text: str, rb: Rubifier) -> str:
    return f'<div class="mj-subhead">{rb.html(text)}</div>'


def sources_html(sources: Sequence[Source], rb: Rubifier) -> str:
    """出典の一覧（題名に、そのページへのリンクを付ける）"""
    rows = "".join(
        f'<li><a href="{escape(source.url, quote=True)}" target="_blank" rel="noopener noreferrer">{rb.html(source.title)}</a></li>' for source in sources
    )
    return f'<ul class="mj-rules mj-sources">{rows}</ul>'


def certainty_html(origin: Origin) -> str:
    """由来の確かさの札"""
    cls = {"確実": "sure", "有力": "likely", "諸説あり": "mixed", "不明": "unknown"}[origin.certainty]
    return f'<span class="mj-cert mj-cert-{cls}">{escape(origin.certainty)}</span>'


def certainty_legend_html(rb: Rubifier) -> str:
    rows = "".join(
        f'<tr><td style="white-space:nowrap">{certainty_html(Origin("", name))}</td><td>{rb.html(meaning)}</td></tr>'
        for name, meaning in CERTAINTY_MEANINGS.items()
    )
    return f'<table class="mj-table">{rows}</table>'


# ---------------------------------------------------------------- 役図鑑：一覧


def han_text(page: YakuPage) -> str:
    """翻数の書き方（一覧と見出しに出す）"""
    if page.han_text:
        return page.han_text
    return han_label(page) if page.yaku else ""


def stamp_text(stamp: Stamp | None) -> str:
    if stamp is None:
        return ""
    return f"{stamp.count} 回"


def list_tag(page: YakuPage) -> str:
    """一覧に出す短い札（門前限定か、鳴くと下がるか）。翻数は、まとまりの見出しに出ている"""
    if not page.yaku:
        return ""
    info = YAKU[page.yaku[0]]
    if info.closed_only:
        return "門前"
    return "鳴↓" if info.kuisagari else ""


def list_label(page: YakuPage, stamp: Stamp | None) -> str:
    """一覧の 1 行（リンクの文字。Markdown）。読みは、名前のすぐあとに並べる"""
    tag = list_tag(page)
    tag = f"　:gray[{tag}]" if tag else ""
    done = f"　:green[✓{stamp.count}]" if stamp is not None else ""
    return f"**{page.name}**　{page.reading}{tag}{done}"


def next_label(page: YakuPage) -> str:
    """役のページのいちばん下に出す「次の役」へのリンクの文字。リンクにはルビを振れないので、読みを横に並べる"""
    return f"次の役：{page.name}　{page.reading}"


def completion_text(done: Completion) -> str:
    return f"スタンプ {done.done} / {done.total}（{percent(done.rate) if done.total else '0%'}）"


def book_intro_html(done: Completion | None, rb: Rubifier) -> str:
    """一覧の上の説明と、スタンプの集まり具合"""
    lines = ["役は 1 つも無いと、あがれない。まずは、よく出る役（立直・断么九・平和・役牌）から覚える。"]
    html = f'<div class="mj-note">{rb.html(lines[0])}</div>'
    if done is not None:
        rest = done.total - done.reachable
        html += (
            f'<div class="mj-sub">{rb.html(f"一人練習であがると、その手に付いた役にスタンプが押される。{done.total} の役のうち、{rest} は一人練習では成立しない（鳴き・カン・相手の牌が要る役）。")}</div>'
        )
    return html


# ---------------------------------------------------------------- 役図鑑：1 ページ


def result_line_html(result: Explanation, rb: Rubifier) -> str:
    """その手の結果を 1 行で（役・翻と符・点数）"""
    if result.status is Status.NOT_WINNING:
        return f'<div class="mj-result mj-bad">{rb.html("あがりの形になっていない")}</div>'
    if result.status is Status.NO_YAKU:
        return f'<div class="mj-result mj-bad">{rb.html("役がないので、あがれない")}</div>'
    best = result.best
    assert best is not None and best.points is not None
    names = "・".join(item.name for item in best.evaluation.yaku)
    dora = f"・ドラ {best.dora_han}" if best.dora_han else ""
    if best.is_yakuman:
        size = best.points.level_name
    elif best.points.level_name:
        size = f"{best.han} 翻（{best.points.level_name}）"
    else:
        size = f"{best.han} 翻 {best.fu.fu} 符"
    return (
        f'<div class="mj-result"><span>{rb.html(names + dora)}</span>'
        f'<span class="mj-result-num">{rb.html(size)}　<b>{escape(payment_text(best.points, result.ctx))}</b></span></div>'
    )


def _hand_card(hand: Hand, rb: Rubifier, *, body: Callable[[Explanation], str], cls: str, head: str, show_result: bool = True) -> str:
    """例の手 1 つぶんの札。

    HTML は、画面に出る順（題名 → 場面の札 → 手牌 → 結果 → 説明）に作る。ルビは「最初に作った文」に付くので、
    順番を変えると、画面では 2 回目に出てくる用語にルビが付いてしまう。説明（body）は、最後に呼ぶ。
    """
    result = explain(hand.context(), hand.rules)
    parts = []
    if hand.title:
        parts.append(f'<div class="mj-ex-title">{head}{rb.html(hand.title)}</div>')
    parts.append(chips_html([*situation_chips(result), *(f"ルール：{note}" for note in rule_notes(hand.rules))], rb))
    parts.append(hand_html(result, rb))
    if show_result:
        parts.append(result_line_html(result, rb))
    parts.append(body(result))
    return f'<div class="mj-ex {cls}">{"".join(parts)}</div>'


def example_html(page: YakuPage, hand: Hand, rb: Rubifier) -> str:
    """成立例 1 つ（手牌、付く役と点数、その役の条件を 1 つずつ確かめた結果）"""

    def body(result: Explanation) -> str:
        html = ""
        best = result.best
        if best is not None:
            counted = {item.key: item for item in best.evaluation.yaku}
            item = next((counted[key] for key in page.yaku if key in counted), None)
            if item is not None and item.checks:
                html += checks_html(item, rb)
        if hand.note:
            html += f'<div class="mj-sub">{rb.html(hand.note)}</div>'
        return html

    return _hand_card(hand, rb, body=body, cls="mj-ex-ok", head='<span class="mj-ex-mark good">○</span> ')


def trap_html(page: YakuPage, trap: Trap, rb: Rubifier) -> str:
    """ひっかけ例 1 つ（その役が付きそうに見えて、付かない手）"""
    hand = trap.hand
    no_call = trap.expect == "no_call"

    def body(result: Explanation) -> str:
        html = f'<div class="mj-note">{rb.html(trap.why)}</div>'
        if not no_call and len(page.yaku) == 1:
            check = result.yaku_check(page.yaku[0])
            if check is not None and not check.ok and check.checks:
                html += checks_html(check, rb)
        if no_call:         # 手の形ではなく、場面の決まりであがれない（点数計算にかけた結果は、出さない）
            html += f'<div class="mj-result mj-bad">{rb.html(TRAP_RESULTS[trap.expect])}</div>'
        if hand.note:
            html += f'<div class="mj-sub">{rb.html(hand.note)}</div>'
        return html

    return _hand_card(hand, rb, body=body, cls="mj-ex-ng", head='<span class="mj-ex-mark bad">✗</span> ', show_result=not no_call)


def river_html(title: str, tiles: str, ok: bool, note: str, rb: Rubifier) -> str:
    """河の例（流し満貫）"""
    try:
        ids = parse_tiles(tiles)
    except TileError:
        ids = []
    cells = "".join(f"<span>{tile_img(t)}</span>" for t in ids)
    mark = '<span class="mj-ex-mark good">○</span> ' if ok else '<span class="mj-ex-mark bad">✗</span> '
    sub = f'<div class="mj-sub">{rb.html(note)}</div>' if note else ""
    return f'<div class="mj-ex {"mj-ex-ok" if ok else "mj-ex-ng"}"><div class="mj-ex-title">{mark}{rb.html(title)}</div><div class="mj-river">{cells}</div>{sub}</div>'


def head_html(page: YakuPage, rb: Rubifier, *, stat: YakuStat | None) -> str:
    """ページの見出し：名前・読み・卓での呼び方・翻数・出やすさ"""
    rb.note(page.name)          # 読みを横に並べて見せるので、ルビは振らない
    chips = []
    text = han_text(page)
    if text:
        chips.append(f'<span class="mj-chip mj-chip-han">{rb.html(text)}</span>')
    chips.append(f'<span class="mj-chip">{rb.html(GROUPS[page.group])}</span>')
    if stat is not None:
        chips.append(f'<span class="mj-chip mj-freq-{LEVEL_CLASS[stat.level]}">出やすさ：{escape(stat.level)}</span>')
    spoken = ""
    if page.spoken and page.spoken != page.reading:
        spoken = f'<div class="mj-sub">{rb.html(f"卓での呼び方：{page.spoken}")}</div>'
    return (
        f'<div class="mj-yaku-head"><span class="mj-big mj-term">{escape(page.name)}</span> <span class="mj-reading mj-reading-big">{escape(page.reading)}</span></div>'
        f'{spoken}<div class="mj-chips">{"".join(chips)}</div><div class="mj-lesson">{rb.html(page.short)}</div>'
    )


def definition_html(page: YakuPage, rb: Rubifier) -> str:
    html = subhead("成立する条件", rb) + _list(page.definition, rb)
    if page.notes:
        html += subhead("補足", rb) + _list(page.notes, rb)
    return html


def combos_html(page: YakuPage, rb: Rubifier) -> str:
    """複合しやすい役・しない役"""
    pages = yaku_page_map()

    def rows(items) -> str:
        return "".join(
            f'<tr><td style="white-space:nowrap"><b>{rb.html(pages[combo.key].name)}</b></td><td>{rb.html(combo.why)}</td></tr>' for combo in items
        )

    parts = []
    if page.good:
        parts.append(subhead("複合しやすい役（同時に付く）", rb) + f'<table class="mj-table">{rows(page.good)}</table>')
    if page.never:
        parts.append(subhead("複合しない役（同時には付かない）", rb) + f'<table class="mj-table">{rows(page.never)}</table>')
    if page.combo_note:
        parts.append(f'<div class="mj-note">{rb.html(page.combo_note)}</div>')
    return "".join(parts)


def frequency_html(page: YakuPage, stats: YakuStats, rb: Rubifier) -> str:
    """出やすさの目安と、その出典"""
    stat = stats.pages.get(page.key)
    if stat is None:
        return f'<div class="mj-sub">{rb.html("出やすさ：この役の統計は、見つからなかった。")}</div>'
    source = stats.source
    if stat.count:
        rate = f"{stat.per} {stat.total:,} 回のうち {stat.count:,} 回（{_rate(stat.rate)}。約 {stat.one_in:,} 回に 1 回）"
    else:
        rate = f"{stat.per} {stat.total:,} 回のうち 0 回"
    html = (
        f'<div class="mj-note"><span class="mj-chip mj-freq-{LEVEL_CLASS[stat.level]}">{escape(stat.level)}</span> {rb.html(rate)}</div>'
        f'<div class="mj-sub">出典：<a href="{escape(source.url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(source.title)}</a>'
        f"（{escape(source.site)}、{escape(source.published)}）。{rb.html(source.data.rstrip('。') + '。')}</div>"
    )
    if stat.note:
        html += f'<div class="mj-sub">{rb.html(stat.note)}</div>'
    html += f'<div class="mj-sub">{rb.html("上級者どうしの対局の数字。打つ人や、ルール（鳴きの多さなど）によって変わるので、目安として見る。")}</div>'
    return html


def _rate(rate: float) -> str:
    """割合の書き方（小さい割合も、0% と書かない）"""
    value = rate * 100
    if value >= 10:
        return f"{value:.0f}%"
    if value >= 1:
        return f"{value:.1f}%"
    if value >= 0.01:
        return f"{value:.2f}%"
    return f"{value:.4f}%"


def tips_html(page: YakuPage, rb: Rubifier) -> str:
    return subhead("狙い方のコツ", rb) + _list(page.tips, rb)


def origin_html(page: YakuPage, rb: Rubifier) -> str:
    """読み方と、漢字の意味・由来"""
    rows = [
        f"<tr><td>読み</td><td>{escape(page.reading)}</td></tr>",
        f"<tr><td>{rb.html('字の意味')}</td><td>{rb.html(page.kanji)}</td></tr>",
        f"<tr><td>由来</td><td>{rb.html(page.origin.text)} {certainty_html(page.origin)}</td></tr>",
    ]
    return f'<table class="mj-table mj-origin">{"".join(rows)}</table>'


def stamp_html(page: YakuPage, stamp: Stamp | None, target: TargetStat | None, rb: Rubifier) -> str:
    """スタンプの状態と、役指定練習の成績"""
    if stamp is not None:
        plain = f"、そのうちツキ補正なしで {stamp.plain} 回" if stamp.plain else ""
        text = f"スタンプ：{stamp.count} 回 成立させた（はじめては {date_text(stamp.first)}{plain}）。"
        html = f'<div class="mj-review good">{rb.html(text)}</div>'
    elif page.solo:
        html = f'<div class="mj-review">{rb.html("スタンプ：まだ成立させていない。一人練習でこの役が付くあがりをすると、スタンプが押される。")}</div>'
    else:
        html = f'<div class="mj-review">{rb.html("スタンプ：この役は、一人練習では成立しない。")}</div>'
    if target is not None and target.tries:
        html += f'<div class="mj-sub">{rb.html(f"役指定練習：{target.tries} 局のうち、{target.made} 局でこの役が付いた。")}</div>'
    return html


# ---------------------------------------------------------------- 用語辞典


def _kana(text: str) -> str:
    """さがすときに、ひらがな・カタカナ、全角・半角、大文字・小文字の違いを無視する"""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in text)


def search_terms(glossary: Glossary, pages: Sequence[YakuPage], query: str) -> tuple[list[Term], list[YakuPage]]:
    """用語と役の名前を、言葉でさがす（見出し語・読み・別の言い方・意味のどこかに含まれていれば当たり）"""
    words = [_kana(word) for word in query.split() if word.strip()]
    if not words:
        return [], []

    def hit(*texts: str) -> bool:
        joined = _kana(" ".join(texts))
        return all(word in joined for word in words)

    terms = [t for t in glossary.terms if hit(t.term, t.reading, t.alt, t.meaning)]
    # 見出し語か読みに当たったものを先に
    terms.sort(key=lambda t: 0 if any(word in _kana(t.term + " " + t.reading) for word in words) else 1)
    found = [p for p in pages if hit(p.name, p.reading, p.spoken, p.short)]
    return terms, found


def term_html(term: Term, rb: Rubifier, *, category: str = "") -> str:
    """用語 1 つ（見出し語・読み・意味・例・字の意味と由来）"""
    rb.note(term.term)
    chip = f'<span class="mj-chip">{rb.html(category)}</span>' if category else ""
    parts = [
        f'<div class="mj-term-head"><b class="mj-term mj-term-word">{escape(term.term)}</b> <span class="mj-reading">{escape(term.reading)}</span> {chip}</div>',
        f'<div class="mj-note">{rb.html(term.meaning)}</div>',
    ]
    if term.alt:
        parts.append(f'<div class="mj-sub">{rb.html(term.alt)}</div>')
    if term.example:
        try:
            tiles = parse_tiles(term.example)
        except TileError:
            tiles = []
        if tiles:
            parts.append(f'<div class="mj-term-ex">{tiles_fit_html(tiles, aka=True, max_px=26)}</div>')
        if term.example_note:
            parts.append(f'<div class="mj-sub">{rb.html(term.example_note)}</div>')
    more = []
    if term.kanji:
        more.append(f"<tr><td>{rb.html('字の意味')}</td><td>{rb.html(term.kanji)}</td></tr>")
    if term.origin is not None:
        more.append(f"<tr><td>由来</td><td>{rb.html(term.origin.text)} {certainty_html(term.origin)}</td></tr>")
    if more:
        parts.append(f'<table class="mj-table mj-origin">{"".join(more)}</table>')
    if term.see:
        parts.append(f'<div class="mj-sub">{rb.html("関連：" + "・".join(term.see))}</div>')
    return f'<div class="mj-termcard">{"".join(parts)}</div>'


def yaku_term_html(page: YakuPage, rb: Rubifier) -> str:
    """役の名前 1 つ（用語辞典の中で見せる短い形。くわしくは役図鑑）"""
    rb.note(page.name)
    parts = [
        f'<div class="mj-term-head"><b class="mj-term mj-term-word">{escape(page.name)}</b> <span class="mj-reading">{escape(page.reading)}</span> '
        f'<span class="mj-chip">{rb.html(han_text(page))}</span></div>',
        f'<div class="mj-note">{rb.html(page.short)}</div>',
        f'<table class="mj-table mj-origin"><tr><td>{rb.html("字の意味")}</td><td>{rb.html(page.kanji)}</td></tr>'
        f"<tr><td>由来</td><td>{rb.html(page.origin.text)} {certainty_html(page.origin)}</td></tr></table>",
    ]
    return f'<div class="mj-termcard">{"".join(parts)}</div>'


# ---------------------------------------------------------------- 卓で打つとき


def guide_head_html(number: int, section: GuideSection, rb: Rubifier) -> str:
    """手順 1 つの見出し（番号と題名）と、ひとことのまとめ。いつも見えている部分。

    折りたたみの名前にはルビを振れないので、題名はここに書く（折りたたみの名前は「くわしい手順」だけにする）。
    """
    return (
        f'<div class="mj-guide-head"><span class="mj-guide-num">{number}</span><b>{rb.html(section.title)}</b></div>'
        f'<div class="mj-note">{rb.html(section.summary)}</div>'
    )


def guide_detail_html(section: GuideSection, rb: Rubifier) -> str:
    """手順 1 つの中身（手順・覚えておくこと・卓によって違うところ）。折りたたみの中に出す"""
    parts = [subhead("手順", rb) + _list(section.steps, rb, ordered=True, cls="mj-steps")]
    if section.points:
        parts.append(subhead("覚えておくこと", rb) + _list(section.points, rb))
    if section.differ:
        parts.append(subhead("卓やルールによって違うところ", rb) + _list(section.differ, rb))
    return "".join(parts)


def score_table_html(rb: Rubifier) -> str:
    """点数の早見表（30 符・40 符の 1〜4 翻と、満貫以上。子・親 × ロン・ツモ）"""
    parts = []
    for dealer in (False, True):
        who = "親" if dealer else "子"
        rows = [f'<tr class="mj-dim"><td>{who}</td><td class="num">ロン</td><td class="num">ツモ</td></tr>']
        for fu in (30, 40):
            ron = dict(table_row(fu, dealer=dealer, tsumo=False))
            tsumo = dict(table_row(fu, dealer=dealer, tsumo=True))
            for han in (1, 2, 3, 4):
                rows.append(
                    f'<tr><td>{rb.html(f"{fu} 符 {han} 翻")}</td><td class="num">{escape(_short(ron[han]))}</td><td class="num">{escape(_short(tsumo[han]))}</td></tr>'
                )
        ron_levels = level_row(dealer=dealer, tsumo=False)
        tsumo_levels = dict(level_row(dealer=dealer, tsumo=True))
        for name, points in ron_levels:
            rows.append(f'<tr><td>{rb.html(name)}</td><td class="num">{escape(_short(points))}</td><td class="num">{escape(_short(tsumo_levels[name]))}</td></tr>')
        parts.append(f'<table class="mj-table mj-score">{"".join(rows)}</table>')
    notes = [
        "子のツモは「子が払う点・親が払う点」。親のツモの「オール」は、子 3 人が同じ点を払うこと。",
        "5 翻 ＝ 満貫、6〜7 翻 ＝ 跳満、8〜10 翻 ＝ 倍満、11〜12 翻 ＝ 三倍満。40 符 4 翻も満貫になる。",
        "平和のツモは 20 符（400・700 ／ 700・1,300 ／ 1,300・2,600）、七対子は 25 符（ロン 1,600 ／ 3,200 ／ 6,400）。",
        "30 符 4 翻を満貫に切り上げるルール（切り上げ満貫）もある。ルールによって異なる。",
    ]
    return "".join(parts) + "".join(f'<div class="mj-sub">{rb.html(note)}</div>' for note in notes)


def _short(points: str) -> str:
    """表の中では「点」を省く（例：1,000・2,000）"""
    return points.replace(" 点オール", " オール").replace(" 点", "").replace("（満貫）", "")


# ---------------------------------------------------------------- ルールの違い


def rule_item_html(item: RuleItem, rb: Rubifier) -> str:
    """ルールの違い 1 つ（何が分かれるか、それぞれの答えと採用しているルール、このアプリの扱い）。画面に出る順に作る"""
    star = '<span class="mj-star-inline">★</span> ' if item.check else ""
    parts = [
        f'<div class="mj-term-head">{star}<b>{rb.html(item.title)}</b></div>',
        f'<div class="mj-note">{rb.html(item.ask)}</div>',
    ]
    rows = "".join(f"<tr><td>{rb.html(side.answer)}</td><td class=\"mj-sub\">{rb.html(side.who)}</td></tr>" for side in item.sides)
    parts.append(f'<table class="mj-table mj-sides">{rows}</table>')
    if item.app:
        parts.append(f'<div class="mj-sub"><span class="mj-chip mj-chip-target">このアプリ</span> {rb.html(item.app)}</div>')
    if item.note:
        parts.append(f'<div class="mj-sub">{rb.html(item.note)}</div>')
    return f'<div class="mj-termcard">{"".join(parts)}</div>'


def checklist_html(book: RuleBook, rb: Rubifier) -> str:
    """卓に着く前に確かめること（★ の項目）"""
    rows = "".join(f"<li><b>{rb.html(item.title)}</b>：{rb.html(item.ask)}</li>" for item in book.checklist)
    return f'<ul class="mj-rules">{rows}</ul>'


def rule_names_html(names: Mapping[str, str], surveyed: str, rb: Rubifier) -> str:
    """読みくらべたルールの名前と、調べた日"""
    text = f"読みくらべたルール：{'・'.join(names.values())}（{surveyed.replace('-', '/')} に調べた）。"
    return f'<div class="mj-sub">{rb.html(text)}</div>'

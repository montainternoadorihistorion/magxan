"""ドリルの画面に出す HTML づくり。

問題と正解は engine.drills が作る。ここでは、それを見せる形にするだけ（Streamlit には依存しない）。
"""
from __future__ import annotations

from collections.abc import Sequence
from html import escape

from engine.coach import Position
from engine.drills import KINDS, NEW, REVIEW, DrillProgress, Graded, Question
from engine.game import SEAT_NAMES
from engine.scoring.dora import dora_kind_of
from engine.scoring.texts import kind_text
from engine.srs import MAX_BOX, Card
from engine.tiles import EAST, kind_of
from ui.drill_session import EARLY
from ui.practice_view import percent
from ui.ruby import Rubifier
from ui.tile_view import kind_img, tile_img
from ui.timefmt import span_text
from ui.win_view import WIND_NAMES

REASON_LABELS = {REVIEW: "復習", NEW: "新しい問題", EARLY: "先取りの復習"}


def progress_text(kind: str, progress: DrillProgress, *, due: bool = True) -> str:
    """進み具合のひとこと。due が偽なら、復習の時刻になった問題の数は書かない（すぐ横に札で出すとき）"""
    if not progress.answered:
        return "まだ答えていない"
    parts = [f"{progress.answered} 回答えて、正答率 {percent(progress.accuracy)}"]
    if KINDS[kind].finite and progress.total:
        parts.append(f"定着 {progress.learned} / {progress.total} 問")
    if progress.due:
        if due:
            parts.append(f"復習 {progress.due} 問")
    elif progress.waiting:
        parts.append(f"復習待ち {progress.waiting} 問")
    return "・".join(parts)


def header_html(kind: str, reason: str, count: int, right: int, rb: Rubifier, *, test: tuple[int, int, str] | None = None) -> str:
    """問題の上に出す札：種類・出した理由・この回の数。test は確認テストの（何問目, 問題の数, 段階の見出し）"""
    chips = [f'<span class="mj-chip mj-chip-target">{rb.html(KINDS[kind].name)}</span>']
    if test is not None:
        number, total, title = test
        chips.append(f'<span class="mj-chip mj-chip-luck">{rb.html(f"確認テスト：{title}")}</span>')
        chips.append(f'<span class="mj-chip">{number} / {total} 問目</span>')
        return f'<div class="mj-chips mj-statusbar">{"".join(chips)}</div>'
    if reason in REASON_LABELS:
        cls = " mj-chip-luck" if reason != NEW else ""
        chips.append(f'<span class="mj-chip{cls}">{REASON_LABELS[reason]}</span>')
    if count:
        chips.append(f'<span class="mj-chip">この回 {count} 問・正解 {right}</span>')
    return f'<div class="mj-chips mj-statusbar">{"".join(chips)}</div>'


def prompt_html(question: Question, rb: Rubifier, *, asked: bool = False) -> str:
    """問題文。asked は、読みを答えさせる問題で、まだ答えていないとき（読みを隠しているので、ルビが無くてよい）"""
    note = f'<div class="mj-sub">{rb.html(question.note)}</div>' if question.note else ""
    rules = "".join(f'<span class="mj-chip mj-chip-luck">ルール：{rb.html(text)}</span>' for text in question.rule_notes)
    rules = f'<div class="mj-chips">{rules}</div>' if rules else ""
    cls = "mj-prompt mj-asked" if asked else "mj-prompt"
    return f'<div class="{cls}">{rb.html(question.prompt)}</div>{note}{rules}'


def river_html(tiles: Sequence[int], rb: Rubifier, *, caption: str, aka: bool = True) -> str:
    """河（捨て牌）。卓と同じく 6 枚ずつ並べる"""
    if not tiles:
        return f'<div class="mj-cap mj-river-cap">{rb.html(caption)}：まだ 1 枚も切っていない</div>'
    cells = "".join(f"<span>{tile_img(tile, aka=aka)}</span>" for tile in tiles)
    return f'<div class="mj-cap mj-river-cap">{rb.html(caption)} {len(tiles)} 枚</div><div class="mj-river">{cells}</div>'


def position_status_html(position: Position, rb: Rubifier) -> str:
    """何切るの局面：場・自風・残りのツモ・ドラ"""
    aka = position.rules.aka_dora
    seat = WIND_NAMES[position.seat_wind]
    chips = [
        rb.html(f"{WIND_NAMES[position.round_wind]}場"),
        rb.html(f"{seat}家（{'親' if position.seat_wind == EAST else '子'}）"),
        rb.html(f"残りツモ {position.draws_left} 回"),
    ]
    html = "".join(f'<span class="mj-chip">{chip}</span>' for chip in chips)
    for indicator in position.dora_indicators:
        dora = dora_kind_of(kind_of(indicator))
        html += (           # 小さい牌の絵だけだと見分けにくいので、ドラの名前も書く
            f'<span class="mj-chip mj-chip-tiles">ドラ表示牌 {tile_img(indicator, aka=aka, cls="mj-s")} → ドラ '
            f'{kind_img(dora, cls="mj-s")} {escape(kind_text(dora))}</span>'
        )
    return f'<div class="mj-chips">{html}</div>'


def danger_setup_html(question: Question, rb: Rubifier) -> str:
    """危険牌の局面：残りのツモとドラ（1 行）と、4 人の河（下家・対面・上家・自分の順）。

    手牌と「この牌を切る」が最初の画面に入るように、河は小さめの牌で出し、説明（danger_legend_html）は手牌の下に回す。
    """
    setup = question.danger
    position = question.position
    assert setup is not None and position is not None
    aka = position.rules.aka_dora
    riichi_orders = {seat: next(d.order for d in setup.rivers[seat] if d.riichi) for seat in setup.riichi if any(d.riichi for d in setup.rivers[seat])}
    first_riichi = min(riichi_orders.values(), default=10**9)
    blocks = []
    for step in (1, 2, 3, 0):
        river = setup.rivers[step]
        label = f"{SEAT_NAMES[step]}（{WIND_NAMES[setup.seat_winds[step]]}家）"
        mark = '<span class="mj-seat-riichi">リーチ</span>' if step in setup.riichi else ""
        cells = []
        for discard in river:
            classes = []
            if discard.riichi:
                classes.append("mj-sideways")
            if discard.order > first_riichi:
                classes.append("mj-new")
            cells.append(f"<span>{tile_img(discard.tile, aka=aka, cls=' '.join(classes))}</span>")
        inner = "".join(cells) if cells else '<div class="mj-cap">まだ切っていない</div>'
        body = f'<div class="mj-river mj-river-xs">{inner}</div>'
        blocks.append(f'<div class="mj-riverbox"><div class="mj-cap">{rb.html(label)} {mark}</div>{body}</div>')
    return f'<div class="mj-table4">{"".join(blocks)}</div>'


def danger_legend_html(question: Question, rb: Rubifier) -> str:
    """危険牌の局面の河の見方と、残りのツモ・ドラ（手牌の下に出す）"""
    setup = question.danger
    position = question.position
    assert setup is not None and position is not None
    legend = "横向きの牌：リーチ宣言牌。印の付いた牌：リーチのあとに切られて、通った牌（リーチした人の現物）"
    if len(setup.riichi) > 1:
        legend = "横向きの牌：リーチ宣言牌。印の付いた牌：最初のリーチのあとに切られて、通った牌（あとからリーチした人には、その人のリーチのあとに切られた牌だけが現物）"
    legend = "考え方：現物・スジ・壁・字牌の見え方で考える。" + legend
    dora = "".join(
        f' ドラ {kind_img(dora_kind_of(kind_of(t)), cls="mj-s")} {escape(kind_text(dora_kind_of(kind_of(t))))}' for t in position.dora_indicators
    )
    return f'<div class="mj-sub">{rb.html(legend)}</div><div class="mj-sub mj-inline">{rb.html(f"残りツモ {position.draws_left} 回")}{dora}</div>'


def verdict_banner_html(correct: bool, rb: Rubifier, *, text: str = "") -> str:
    """正解・不正解の札（mj-verdict は、答えた直後に画面を動かして見せる目印）"""
    if correct:
        return f'<div class="mj-headline mj-headline-short mj-verdict good"><b class="mj-stage">○ 正解</b>{"　" + rb.html(text) if text else ""}</div>'
    return f'<div class="mj-headline mj-headline-short mj-verdict bad"><b class="mj-stage">✗ ちがう</b>{"　" + rb.html(text) if text else ""}</div>'


def choices_review_html(question: Question, graded: Graded, rb: Rubifier) -> str:
    """選択肢を、正解・選んだ答えの印つきで並べる（はずれには、それが何にあたるかを添える）。

    選ばなかった正解には「選び忘れ」（いくつも選ぶ問題）か「正解」（1 つ選ぶ問題）の札を付ける。
    印の色だけでは、選んだ正解と見分けられないため。
    """
    rows = []
    for choice in question.choices:
        right = choice.key in question.correct
        picked = choice.key in graded.picked
        if right:
            mark, cls = "○", "mj-choice-right"
        elif picked:
            mark, cls = "✗", "mj-choice-wrong"
        else:
            mark, cls = "", "mj-choice-other"
        if picked:
            you = '<span class="mj-badge mj-badge-you">選んだ答え</span>'
        elif right:
            you = f'<span class="mj-badge mj-badge-miss">{"選び忘れ" if question.multi else "正解"}</span>'
        else:
            you = ""
        tile = kind_img(choice.tile, cls="mj-s") + " " if choice.tile is not None else ""
        label = rb.html(choice.label)           # 画面に出る順（選択肢 → その説明）に作る
        why = f'<div class="mj-sub">{rb.html(choice.why)}</div>' if choice.why else ""
        rows.append(
            f'<div class="mj-choice {cls}"><span class="mj-choice-mark">{mark}</span>'
            f'<div class="mj-choice-body"><span class="mj-inline">{tile}<b>{label}</b>{you}</span>{why}</div></div>'
        )
    return f'<div class="mj-choices">{"".join(rows)}</div>'


def answer_lines_html(question: Question, rb: Rubifier) -> str:
    """解説の文章"""
    return '<div class="mj-lesson">' + "<br>".join(rb.html(line) for line in question.answer) + "</div>"


def srs_note_html(kind: str, card: Card | None, correct: bool, now: int, rb: Rubifier) -> str:
    """この問題を、次にいつ出すか"""
    if card is None:
        return ""           # その場で作った問題に正解した：覚えておかない
    wait = span_text(card.due - now)
    if not correct:
        text = f"この問題は、{wait}ほどあとに、もう一度出す（正解するたびに、間隔が 1 日 → 3 日 → 7 日…と延びていく）。"
    elif card.box >= MAX_BOX:
        text = f"よく覚えている問題。次は、{wait}後。"
    elif not KINDS[kind].finite:
        text = f"前に間違えた問題。次に正解すれば、復習は終わり（次は {wait}後）。"
    else:
        text = f"次は、{wait}後にもう一度出す。"
    return f'<div class="mj-sub">{rb.html(text)}</div>'


def done_html(kind: str, progress: DrillProgress, now: int, rb: Rubifier) -> str:
    """決まった数の問題を、すべて出し終えたとき"""
    name = KINDS[kind].name
    text = f"「{name}」の問題は、ひととおり出し終えた（{progress.total} 問）。"
    if progress.next_due is not None:
        text += f"次の復習は、{span_text(progress.next_due - now)}後。"
    return f'<div class="mj-lesson">{rb.html(text)}<div class="mj-sub">{rb.html("間隔をあけて思い出すほうが、よく覚えられる。時刻になる前に、先取りで復習することもできる。")}</div></div>'


def kind_card_html(kind: str, progress: DrillProgress, rb: Rubifier) -> str:
    """種類の一覧の 1 つ（名前の下に出す説明と進み具合）"""
    info = KINDS[kind]
    stats = progress_text(kind, progress, due=False)         # 復習の時刻になった問題の数は、すぐ横の札で出す
    due = f' <span class="mj-badge">復習 {progress.due} 問</span>' if progress.due else ""
    return f'<div class="mj-sub mj-kind-note">{rb.html(info.short)}。<span class="mj-dimtext">{escape(stats)}</span>{due}</div>'

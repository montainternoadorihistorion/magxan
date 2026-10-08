"""一人練習の画面に出す HTML づくり。

エンジンが計算した事実（局面の状態、コーチの分析と評価、成績の集計）を、そのまま図と表にする。
ここでは数値を計算し直さない。Streamlit にも依存しない（HTML の文字列を返すだけ）。
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from engine.analysis.blocks import MENTSU_TYPES, PART_NAMES, TAATSU_TYPES, Part, PartType
from engine.analysis.shanten import TENPAI, shanten_meaning, shanten_text
from engine.analysis.target import SHAPELESS_KEYS, BlockKind, Plan, target_plan
from engine.analysis.ukeire import remaining_counts
from engine.coach import Analysis, Candidate, Grade, Verdict
from engine.content import yaku_page_map
from engine.luck import PRESETS, deal_candidates, draw_probability, target_goal
from engine.practice import DEAL_TENPAI_TARGETS, IPPATSU_BOOST, MAX_DRAWS, Decision, Draw, Outcome, PracticeState
from engine.records import Summary, TargetStat
from engine.scoring.decompose import Form
from engine.scoring.dora import dora_kind_of
from engine.scoring.explain import Explanation, Status
from engine.scoring.texts import kind_text
from engine.target_coach import BLOCK_NAMES, RIICHI_TARGETS, TargetAdvice, TargetGrade, TargetResult
from engine.tiles import EAST, counts34, kind_of
from ui.ruby import Rubifier
from ui.tile_view import kind_img, tile_img, tile_short_label
from ui.win_view import WIND_NAMES, checks_html, payment_text, tiles_fit_html

HINT_BEFORE, HINT_AFTER, HINT_OFF = "before", "after", "off"
HINT_LABELS = {HINT_BEFORE: "打つ前に表示", HINT_AFTER: "打った後に答え合わせ", HINT_OFF: "オフ"}
LEVEL_MIN, LEVEL_NORMAL, LEVEL_FULL = 1, 2, 3
LEVEL_LABELS = {LEVEL_FULL: "詳しい", LEVEL_NORMAL: "ふつう", LEVEL_MIN: "最小"}

GRADE_ICONS = {Grade.BEST: "✓", Grade.NARROWER: "△", Grade.FARTHER: "✗", Grade.DEAD: "✗", Grade.PASSED: "！", Grade.NO_RIICHI: "✗"}
GRADE_CLASS = {Grade.BEST: "good", Grade.NARROWER: "soso", Grade.FARTHER: "bad", Grade.DEAD: "bad", Grade.PASSED: "bad", Grade.NO_RIICHI: "bad"}
TARGET_ICONS = {TargetGrade.BEST: "✓", TargetGrade.NARROWER: "△", TargetGrade.FARTHER: "✗", TargetGrade.LOST: "✗"}
TARGET_CLASS = {TargetGrade.BEST: "good", TargetGrade.NARROWER: "soso", TargetGrade.FARTHER: "bad", TargetGrade.LOST: "bad"}
MARK_PICK = ("◎", "おすすめ")
MARK_EQUAL = ("○", "おすすめと同じ速さ")

#: ツキ補正の段階ごとの目安。tools/measure_luck.py で、機械的な打ち手（いつもコーチのおすすめを切り、聴牌したら
#: 必ずリーチ）が各 300 局打った結果。（段階, 配牌の平均向聴数, あがり率, あがったときの平均巡目）
LUCK_GUIDE = (
    ("なし", 3.55, 0.16, 14.1),
    ("弱", 2.73, 0.48, 12.6),
    ("中", 2.09, 0.73, 11.2),
    ("強", 1.63, 0.95, 7.8),
    ("最大", 1.23, 0.96, 3.6),
)


def rounded(value: float | Decimal, digits: int = 0) -> str:
    """四捨五入して書く（3.55 → 「3.6」、62.5 → 「63」、1234.5 → 「1,235」）。

    書式の指定（f"{x:.1f}"）に任せると、2 進数の誤差や「偶数への丸め」のために、手で計算した値と
    1 つずれることがある（3.55 が「3.5」、62.5 が「62」になる）。
    """
    step = Decimal(1).scaleb(-digits)        # 0 桁なら 1、1 桁なら 0.1
    return f"{Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP):,}"


def percent(value: float) -> str:
    """割合を百分率で書く。0 でも 1 でもない値を、丸めて「0%」「100%」とは書かない"""
    if 0 < value < 0.01:
        return "1% 未満"
    if 0.99 < value < 1:
        return "99% 以上"
    return f"{rounded(Decimal(str(value)) * 100)}%"


def _name(tile: int, aka: bool) -> str:
    return tile_short_label(tile, aka=aka)


def _small(tile: int, aka: bool) -> str:
    return tile_img(tile, aka=aka, cls="mj-s")


def _small_kind(kind: int) -> str:
    return kind_img(kind, cls="mj-s")


# ---------------------------------------------------------------- 状況（いちばん上）


def luck_text(deal: int, draw: int) -> str:
    """ツキ補正の強さの書き方（いつも画面に出す）"""
    if deal == 0 and draw == 0:
        return "ツキ補正なし（通常の麻雀）"
    return f"ツキ補正：配牌 {deal}・ツモ {draw}"


def status_html(state: PracticeState, rb: Rubifier) -> str:
    """場・自風・巡目・ドラ・ツキ補正の強さ"""
    aka = state.config.rules.aka_dora
    luck = state.config.luck
    seat = WIND_NAMES[state.seat_wind]
    turn = f"{state.turn} 巡目で終了" if state.finished else f"{state.turn} 巡目（残りツモ {state.draws_left} 回）"
    chips = [
        rb.html(f"{WIND_NAMES[state.config.round_wind]}場"),
        rb.html(f"{seat}家（{'親' if state.seat_wind == EAST else '子'}）"),
        rb.html(turn),
    ]
    # 札の中身は、1 つの span に入れる（札の高さをそろえて、中身を下にそろえるため。ui/layout.py の mj-status-fixed）
    html = "".join(f'<span class="mj-chip"><span>{chip}</span></span>' for chip in chips)
    for indicator in state.dora_indicators:
        dora = dora_kind_of(kind_of(indicator))
        # 小さい牌の絵だけだと、6索と7索・8筒と9筒などが見分けにくいので、名前も書く
        html += (
            f'<span class="mj-chip mj-chip-tiles"><span>ドラ表示牌 {_small(indicator, aka)} → ドラ '
            f"{_small_kind(dora)} {escape(kind_text(dora))}</span></span>"
        )
    off = " mj-chip-plain" if luck.is_off else " mj-chip-luck"
    html += f'<span class="mj-chip{off}"><span>{rb.html(luck_text(luck.deal, luck.draw))}</span></span>'
    if state.config.target:
        html += f'<span class="mj-chip mj-chip-target"><span>{rb.html(f"役指定：{target_name(state.config.target)}")}</span></span>'
    return f'<div class="mj-chips mj-statusbar mj-status-fixed">{html}</div>'


def target_name(key: str) -> str:
    """狙う役の名前（図鑑のページの名前）"""
    return yaku_page_map()[key].name


# ---------------------------------------------------------------- ひとことの案内（手牌のすぐ上）


def _headline(inner: str, cls: str = "") -> str:
    """手牌のすぐ上の案内。高さを固定してある（1 行でも 2 行でも同じ高さ。巡目によって手牌の位置が動かないように）"""
    classes = f"mj-headline {cls}".strip()
    return f'<div class="{classes}"><div class="mj-headline-in">{inner}</div></div>'


def plain_headline_html(text: str, rb: Rubifier) -> str:
    return _headline(f'<span class="mj-dimtext">{rb.html(text)}</span>')


def advice_headline_html(analysis: Analysis, rb: Rubifier, *, can_riichi: bool, lead: str = "") -> str:
    """打つ前のヒント：向聴数と、おすすめの打牌。lead は、先頭に置く札（HTML）"""
    body, cls = _advice_body(analysis, rb, can_riichi=can_riichi)
    return _headline(lead + body, cls)


def _advice_body(analysis: Analysis, rb: Rubifier, *, can_riichi: bool) -> tuple[str, str]:
    """打つ前のヒントの本文と、色の名前"""
    aka = analysis.position.rules.aka_dora
    if analysis.can_win:
        return f'<b class="mj-stage">あがりの形です。</b>{rb.html("「ツモ（あがる）」を押すと、あがれます。")}', "good"
    pick = analysis.pick
    what = f"{_small(pick.tile, aka)} <b>{escape(_name(pick.tile, aka))}</b>"
    if analysis.last_discard:
        chip = '<span class="mj-chip mj-chip-luck">最後のツモ</span> '
        if analysis.can_end_tenpai:
            return chip + f'{what} {rb.html("を切ると、聴牌したまま流局になります。")}', ""
        return chip + rb.html("聴牌にとれない手です。どれを切っても、ノーテンで流局になります。"), ""
    if pick.shanten == TENPAI and pick.total > 0:
        tail = "。リーチもできます" if can_riichi else ""
        body = f'<b class="mj-stage">{rb.html("聴牌")}にとれます</b>　{what} {rb.html(f"を切ると、待ちは {pick.kinds} 種 {pick.total} 枚{tail}")}'
    else:
        # 向聴数は「おすすめを切ったあと」のもの（形の上ではもっと近い切り方があっても、有効牌が残っていなければ勧めない）
        if pick.total > 0:
            width = f"受け入れ {pick.kinds} 種 {pick.total} 枚"
        else:
            width = "待ち牌は残っていません" if pick.shanten == TENPAI else "有効牌は残っていません"
        body = f'<b class="mj-stage">{rb.html(shanten_text(pick.shanten))}</b>　おすすめ：{what} {rb.html(f"切り（{width}）")}'
        if analysis.stalled:
            body += f'<br><span class="mj-sub">{rb.html(_stalled_text(analysis))}</span>'
    return body, ""


#: リーチが要る役を狙う局で、リーチを勧めるときの 2 行目（{name} は役の名前、{width} は待ちの広さ）
RIICHI_FOLLOW = {
    "riichi": "リーチすれば{name}が付く（{width}）",
    "ippatsu": "次のツモであがれば{name}（{width}）",
    "double_riichi": "いまリーチすれば{name}（{width}）",
}


def riichi_headline_html(analysis: Analysis, key: str, rb: Rubifier) -> str:
    """リーチが要る役（立直・一発・ダブル立直）を狙う局で、聴牌にとれるときの、打つ前のヒント：リーチして切る。

    ふつうの見出し（「聴牌にとれます。リーチもできます」）だと、リーチを押さずに切ってしまい、狙いを逃しやすい。
    """
    aka = analysis.position.rules.aka_dora
    pick = analysis.pick
    what = f"{_small(pick.tile, aka)} <b>{escape(_name(pick.tile, aka))}</b>"
    follow = RIICHI_FOLLOW[key].format(name=target_name(key), width=f"待ち {pick.kinds} 種 {pick.total} 枚")
    return _headline(f'<b class="mj-stage">「リーチ」を押して</b> {what} {rb.html("を切る")}<br><span class="mj-sub">{rb.html(follow)}</span>')


def _stalled_text(analysis: Analysis) -> str:
    """形の上ではもっと近い切り方があるのに、おすすめが別の切り方になっている理由"""
    if analysis.shanten == TENPAI:
        return "聴牌にもとれるが、その待ち牌はすべて見えていて、残り 0 枚（空聴）。"
    return f"{shanten_text(analysis.shanten)}にもとれるが、その有効牌はすべて見えていて、残り 0 枚。"


def verdict_headline_html(decision: Decision, rb: Rubifier, *, aka: bool) -> str:
    """打った後の答え合わせ（短く 1〜2 行）。くわしい説明は verdict_html"""
    verdict = decision.verdict
    tile = decision.action.tile
    assert tile is not None
    icon = f'<span class="mj-icon {GRADE_CLASS[verdict.grade]}">{GRADE_ICONS[verdict.grade]}</span>'
    body = f"{icon} {_small(tile, aka)} <b>{escape(_name(tile, aka))}</b> 切り：{rb.html(verdict.label)}"
    better = _better_html(verdict, aka)
    if better:
        body += f'<br><span class="mj-sub">{better}</span>'
    return _headline(body, GRADE_CLASS[verdict.grade])


def _better_html(verdict: Verdict, aka: bool) -> str:
    """おすすめだった打牌（おすすめどおりなら空）。リーチが要る役を狙う局でリーチしなかったときは「リーチして ○ 切り」"""
    if verdict.is_best or verdict.grade is Grade.PASSED:
        return ""
    if verdict.grade is Grade.NO_RIICHI:
        # 切った牌そのものが速さで一番なら、その牌のまま、リーチだけが足りない
        tile = verdict.chosen.tile if verdict.chosen.is_best else verdict.pick.tile
        return f"おすすめは リーチして {_small(tile, aka)} {escape(_name(tile, aka))} 切り"
    return f"おすすめは {_small(verdict.pick.tile, aka)} {escape(_name(verdict.pick.tile, aka))} 切り"


# ---------------------------------------------------------------- 河


def river_html(state: PracticeState, rb: Rubifier) -> str:
    """河（切った牌）。卓と同じく 6 枚ずつ並べ、リーチを宣言した牌は横向きにする"""
    aka = state.config.rules.aka_dora
    if not state.discards:
        return f'<div class="mj-cap">{rb.html("河（切った牌）")}：まだ切っていません</div>'
    cells = []
    for index, tile in enumerate(state.discards):
        cls = "mj-sideways" if index == state.riichi_index else ""
        cells.append(f"<span>{tile_img(tile, aka=aka, cls=cls)}</span>")
    note = "　横向きの牌でリーチ" if state.riichi_index is not None else ""
    return f'<div class="mj-cap">{rb.html("河（切った牌）")} {len(state.discards)} 枚{note}</div><div class="mj-river">{"".join(cells)}</div>'


def draw_note_html(draw: Draw, rb: Rubifier, *, aka: bool) -> str:
    """ツキ補正で入れ替わったツモの説明（補正を隠さないための表示）"""
    if not draw.luck.swapped or draw.luck.original is None:
        return ""
    return (
        f'<div class="mj-lucknote">★ {rb.html("いまのツモ")} {_small(draw.tile, aka)} は、ツキ補正で引き寄せた牌です'
        f'<span class="mj-sub">（入れ替えなければ {_small(draw.luck.original, aka)} {escape(_name(draw.luck.original, aka))} を引いていました）</span></div>'
    )


# ---------------------------------------------------------------- 切った牌の評価


def verdict_html(decision: Decision, rb: Rubifier, *, level: int, aka: bool) -> str:
    """前の打牌の評価（理由つき）"""
    verdict = decision.verdict
    tile = decision.action.tile
    assert tile is not None
    icon = f'<span class="mj-icon {GRADE_CLASS[verdict.grade]}">{GRADE_ICONS[verdict.grade]}</span>'
    head = f'<div class="mj-review-head">{icon} {rb.html(f"{decision.turn} 巡目の打牌")} {_small(tile, aka)}</div>'
    body = f'<div>{rb.html(verdict.text)}</div>'
    if level >= LEVEL_NORMAL and verdict.reasons:
        body += "<ul>" + "".join(f"<li>{rb.html(reason)}</li>" for reason in verdict.reasons) + "</ul>"
    return f'<div class="mj-review {GRADE_CLASS[verdict.grade]}">{head}{body}</div>'


# ---------------------------------------------------------------- 受け入れ表


def _accept_html(candidate: Candidate) -> str:
    cells = []
    for kind, count in candidate.acceptance.tiles:
        dead = " mj-acc-dead" if count == 0 else ""
        cells.append(f'<span class="mj-acc{dead}">{_small_kind(kind)}<span>{count}</span></span>')
    return f'<div class="mj-cand-tiles">{"".join(cells)}</div>' if cells else ""


def _candidate_row(candidate: Candidate, analysis: Analysis, rb: Rubifier, chosen_kind: int | None) -> str:
    aka = analysis.position.rules.aka_dora
    if candidate.is_pick:
        mark = MARK_PICK[0]
    elif candidate.is_best:
        mark = MARK_EQUAL[0]
    elif candidate.grade is Grade.DEAD:
        mark = "✗"
    else:
        mark = ""
    badges = ""
    if candidate.dora:
        badges += '<span class="mj-badge">ドラ</span>'
    if chosen_kind == candidate.kind:
        badges += '<span class="mj-badge mj-badge-you">切った牌</span>'
    count = f"{candidate.kinds} 種 {candidate.total} 枚"
    if candidate.grade is Grade.NARROWER:
        count += f'<span class="mj-minus">（−{candidate.tiles_loss} 枚）</span>'
    elif candidate.grade is Grade.DEAD:
        count = f"{rb.html(shanten_text(candidate.shanten))}だが残り 0 枚"
    cls = "mj-cand" + (" mj-cand-pick" if candidate.is_pick else "") + (" mj-cand-you" if chosen_kind == candidate.kind else "")
    return (
        f'<div class="{cls}"><div class="mj-cand-head"><span class="mj-cand-mark">{mark}</span>'
        f"{_small(candidate.tile, aka)}<span class=\"mj-cand-name\">{escape(_name(candidate.tile, aka))}{badges}</span>"
        f'<span class="mj-cand-num">{count}</span></div>{_accept_html(candidate)}</div>'
    )


def candidates_html(analysis: Analysis, rb: Rubifier, *, chosen_kind: int | None = None) -> str:
    """打牌候補ごとの受け入れ（どれを切ると、どの牌が有効牌になり、何枚残っているか）"""
    aka = analysis.position.rules.aka_dora
    pick = analysis.pick
    near = [c for c in analysis.candidates if c.shanten <= pick.shanten]
    far = [c for c in analysis.candidates if c.shanten > pick.shanten]
    if pick.shanten == TENPAI:
        title = "聴牌にとれる切り方（待ちの広い順）"
        noun = "待ち牌"
    elif analysis.stalled:
        title = f"{shanten_text(pick.shanten)}にとる切り方（受け入れの広い順）"
        noun = "有効牌"
    else:
        title = f"{shanten_text(pick.shanten)}のままの切り方（受け入れの広い順）"
        noun = "有効牌"
    parts = [
        f'<div class="mj-subhead">{rb.html(title)}</div>',
        f'<div class="mj-sub">{rb.html(f"小さい牌が{noun}、数字はその残り枚数（自分の手牌・河・ドラ表示牌に見えている牌は引いてある）。")}</div>',
        '<div class="mj-cands">' + "".join(_candidate_row(c, analysis, rb, chosen_kind) for c in near) + "</div>",
    ]
    if far:
        cells = []
        for candidate in far:
            you = " mj-far-you" if chosen_kind == candidate.kind else ""
            cells.append(f'<span class="mj-far{you}">{_small(candidate.tile, aka)}</span>')
        after = shanten_text(min(c.shanten for c in far))
        parts.append(f'<div class="mj-subhead">{rb.html(f"切ると遠ざかる牌（{after}になる）")}</div>')
        parts.append(f'<div class="mj-farrow">{"".join(cells)}</div>')
        parts.append(f'<div class="mj-sub">{rb.html("面子や面子の候補に使っている牌。切ると、そのまとまりがくずれる。")}</div>')
    you = "　点線の枠：切った牌" if chosen_kind is not None else ""
    parts.append(
        '<div class="mj-sub mj-legend">'
        f"{MARK_PICK[0]} おすすめ　{MARK_EQUAL[0]} おすすめと同じ速さ{you}<br>"
        + rb.html("おすすめは速さ（向聴数と受け入れ枚数）だけで決めている。役や打点は見ていない。")
        + "</div>"
    )
    return "".join(parts)


def chance_html(analysis: Analysis, rb: Rubifier, *, luck_draw: int) -> str:
    """おすすめを切ったあと、有効牌を引ける確率（残り枚数からの計算）"""
    position = analysis.position
    pick = analysis.pick
    if analysis.can_win or pick.total == 0:
        return ""
    aka = position.rules.aka_dora
    noun = "あがり牌" if pick.shanten == TENPAI else "有効牌"
    name = escape(_name(pick.tile, aka))
    if position.draws_left == 0:
        return f'<div class="mj-note">{rb.html("これが最後のツモ。切ったら流局なので、もう引けない。")}</div>'
    lines = [
        f"{name}切りのあと、{noun}は {pick.total} 枚。見えていない牌は {position.unseen} 枚。",
        f"次のツモで引く確率 ＝ {pick.total} ÷ {position.unseen} ＝ {percent(analysis.next_chance)}",
        f"残り {position.draws_left} 回のツモのうちに 1 回以上引く確率 ＝ {percent(analysis.within_chance)}",
    ]
    html = f'<div class="mj-note">{rb.html(lines[0])}</div><div class="mj-formula">{rb.html(lines[1])}<br>{rb.html(lines[2])}</div>'
    notes = ["「1 回以上引く確率」は、1 −（全部はずれる確率）。はずれる確率を、ツモの回数ぶん掛けて求める。"]
    if luck_draw > 0:
        notes.append("これは補正なしの麻雀での確率。いまはツモの補正が入っているので、実際はこれより引きやすい。")
    return html + "".join(f'<div class="mj-sub">{rb.html(note)}</div>' for note in notes)


# ---------------------------------------------------------------- 聴牌したときの待ち


def _result_parts(result: Explanation | None) -> tuple[str, str]:
    """あがったときの結果を（点数, 役の言い方）にする。あがれない場合は、役の言い方が空"""
    if result is None:
        return ("—", "")
    best = result.best
    if result.status is not Status.WIN or best is None or best.points is None:
        return ("役なし（あがれない）", "")
    points = best.points
    level = f"{points.level_name} " if points.level_name else ""
    return (f"{level}{payment_text(points, result.ctx)}", "・".join(result.spoken_yaku))


def _result_cell(parts: tuple[str, str], rb: Rubifier) -> str:
    points, yaku = parts
    if not yaku:
        cls = ' class="mj-bad"' if points != "—" else ""
        return f"<span{cls}>{rb.html(points)}</span>"
    return f'<b>{rb.html(points)}</b><div class="mj-sub">{escape(yaku)}</div>'


def waits_html(analysis: Analysis, rb: Rubifier, *, solo: bool = True) -> str:
    """おすすめを切って聴牌したときの待ちと、あがったときの点数（リーチする／しない）"""
    if not analysis.waits:
        return ""
    position = analysis.position
    aka = position.rules.aka_dora
    pick = analysis.pick
    # 画面に出る順（案内 → 待ちごとの点数 → 補足）に作る。用語のルビを、最初に出てくるところに振るため
    parts = [f'<div class="mj-note">{_small(pick.tile, aka)} {escape(_name(pick.tile, aka))} {rb.html("を切ると聴牌。ツモであがったときの点数：")}</div>']
    # あがったときの結果が同じ待ち牌は、1 つにまとめて見せる
    groups: dict[tuple[tuple[str, str], tuple[str, str]], list] = {}
    for wait in analysis.waits:
        groups.setdefault((_result_parts(wait.plain), _result_parts(wait.riichi)), []).append(wait)
    cards = []
    for (plain, riichi), waits in groups.items():
        tiles = "".join(
            f'<span class="mj-acc{" mj-acc-dead" if wait.remaining == 0 else ""}">{_small_kind(wait.kind)}<span>残り {wait.remaining} 枚</span></span>'
            for wait in waits
        )
        head = f'<div class="mj-wait-head">{rb.html("待ち")} {tiles}</div>'
        rows = (
            f'<tr><td class="mj-wait-how">リーチしない</td><td>{_result_cell(plain, rb)}</td></tr>'
            f'<tr><td class="mj-wait-how">リーチする</td><td>{_result_cell(riichi, rb)}</td></tr>'
        )
        cards.append(f'<div class="mj-cand">{head}<table class="mj-table mj-waits">{rows}</table></div>')
    parts.append(f'<div class="mj-cands">{"".join(cards)}</div>')
    parts.append(
        '<div class="mj-sub mj-legend">'
        + rb.html("リーチすると 1 翻増え、一発や裏ドラが付くこともある（上の点数には入れていない）。そのかわり、リーチのあとは手を変えられず、ツモった牌をそのまま切る。")
        + "</div>"
    )
    if solo:
        parts.append(
            '<div class="mj-sub">'
            + rb.html("一人練習には相手がいないので、放銃（相手のあがり牌を切ってしまうこと）の心配がない。聴牌したら、リーチしたほうが得。")
            + "</div>"
        )
    return "".join(parts)


# ---------------------------------------------------------------- 手牌の分け方（分解図）


def _part_class(part: Part) -> str:
    if part.type in MENTSU_TYPES:
        return "mj-part-done"
    if part.type is PartType.TOITSU:
        return "mj-part-pair"
    if part.type in TAATSU_TYPES:
        return "mj-part-wait"
    if part.type is PartType.YAOCHU:
        return "mj-part-done"
    return "mj-part-float"


def _part_caption(part: Part, form: Form, rb: Rubifier) -> str:
    name = rb.html(PART_NAMES[part.type])
    if form is Form.REGULAR and part.completing_kinds:
        needs = "・".join(kind_text(kind) for kind in part.completing_kinds)
        return f'{name}<div class="mj-need">あと {escape(needs)}</div>'
    return name


def layout_html(analysis: Analysis, rb: Rubifier, *, level: int) -> str:
    """手牌の分け方：どの牌を、面子・対子・搭子・孤立牌として見ているか"""
    aka = analysis.position.rules.aka_dora
    layout = analysis.layout
    groups = []
    for part, tiles in zip(layout.parts, analysis.layout_tiles, strict=True):
        images = "".join(tile_img(t, aka=aka) for t in tiles)
        groups.append(
            f'<div class="mj-block mj-part {_part_class(part)}"><div class="mj-block-tiles">{images}</div>'
            f'<div class="mj-cap">{_part_caption(part, layout.form, rb)}</div></div>'
        )
    parts = [f'<div class="mj-blocks">{"".join(groups)}</div>']
    if layout.form is Form.CHIITOI:
        parts.append(f'<div class="mj-note">{rb.html("七対子（対子 7 組）がいちばん近いので、対子と、対子になっていない牌に分けている。")}</div>')
    elif layout.form is Form.KOKUSHI:
        parts.append(f'<div class="mj-note">{rb.html("国士無双（13 種類の么九牌）がいちばん近いので、使える么九牌と、使えない牌に分けている。")}</div>')
    else:
        parts.append(
            '<div class="mj-sub mj-legend">'
            '<span class="mj-key mj-part-done"></span>' + rb.html("完成した面子") + "　"
            '<span class="mj-key mj-part-pair"></span>' + rb.html("対子（雀頭の候補）") + "　"
            '<span class="mj-key mj-part-wait"></span>' + rb.html("搭子（あと 1 枚で面子）") + "　"
            '<span class="mj-key mj-part-float"></span>' + rb.html("孤立牌") + "</div>"
        )
    parts.append(f'<div class="mj-sub">{rb.html("分け方は 1 通りとは限らない。ここに出しているのは、いちばん進んでいる分け方の 1 つ。")}</div>')

    if level >= LEVEL_FULL and not analysis.can_win:
        if analysis.layout_matches:
            parts.append(f'<div class="mj-formula">{rb.html("向聴数 ＝ " + layout.formula)}</div>')
            if layout.form is Form.REGULAR:
                parts.append(
                    '<div class="mj-sub">'
                    + rb.html("何もそろっていない手を 8 として、面子 1 組で 2、搭子か対子 1 組で 1 ずつ減らす。0 が聴牌。")
                    + "</div>"
                )
            if layout.formula_note:
                parts.append(f'<div class="mj-sub">{rb.html(layout.formula_note)}</div>')
        else:
            parts.append(f'<div class="mj-sub">{rb.html("同じ牌を 4 枚持っている手は、式どおりに数えられないことがある（5 枚目の牌は無いため）。")}</div>')
        others = [form for form in analysis.info.forms if form is not layout.form]
        if Form.CHIITOI in others:
            parts.append(f'<div class="mj-sub">{rb.html(f"七対子として数えても、同じ{shanten_text(analysis.shanten)}。")}</div>')
    return "".join(parts)


def shanten_html(analysis: Analysis, rb: Rubifier) -> str:
    """向聴数と、その意味"""
    if analysis.can_win:
        return f'<div class="mj-note"><b>{rb.html("和了形")}</b>：{rb.html(shanten_meaning(analysis.shanten))}</div>'
    pick = analysis.pick
    value = pick.shanten              # おすすめを切ったあとの向聴数
    html = f'<div class="mj-note"><b>{rb.html(shanten_text(value))}</b>：{rb.html(shanten_meaning(value))}</div>'
    if analysis.stalled:
        html += f'<div class="mj-sub">{rb.html(_stalled_text(analysis) + "何を引いても進まないので、形を変えて受け入れを広げるほうが速い。")}</div>'
    elif pick.total == 0:
        noun = "待ち牌" if value == TENPAI else "有効牌"
        html += f'<div class="mj-sub">{rb.html(f"ただし、どの切り方でも、{noun}は 1 枚も残っていない（すべて見えている）。")}</div>'
    return html


# ---------------------------------------------------------------- 局が終わったあと


def exhausted_html(state: PracticeState, rb: Rubifier) -> str:
    """流局したときのまとめ"""
    result = state.result
    assert result is not None
    aka = state.config.rules.aka_dora
    head = f"{MAX_DRAWS} 回ツモってあがれなかったので、流局。"
    if result.tenpai:
        waits = " ".join(f"{_small_kind(kind)}" for kind in result.waits)
        verdict = f'<div class="mj-big">{rb.html("流局（聴牌）")}</div><div class="mj-note">{rb.html("待ち")}：<span class="mj-inline">{waits}</span></div>'
        text = head + "聴牌していた。対局では、流局のとき「テンパイ」と言って手牌を見せると、聴牌していない人から点をもらえる（ノーテン罰符）。"
    else:
        stage = "" if result.shanten is None else f"・{shanten_text(result.shanten)}"
        verdict = f'<div class="mj-big">{rb.html(f"流局（ノーテン{stage}）")}</div>'
        text = head + "ノーテンは、聴牌していないこと。"
    body = f'<div class="mj-sub">{rb.html(text)}</div>'        # 画面に出る順（結果 → 説明 → 狙った役まであと何枚）に作る
    key = state.config.target
    if key and key not in SHAPELESS_KEYS:
        # 見えている牌（河・ドラ表示牌）は、もう手に入らない。それを考えて、あと何枚だったかを数える
        available = remaining_counts(state.hand, state.visible)
        plan = target_plan(counts34(state.hand), key, seat_wind=state.seat_wind, round_wind=state.config.round_wind, available=available)
        name = target_name(key)
        if plan.possible:
            body += f'<div class="mj-sub">{rb.html(f"狙った{name}の完成まで、あと {plan.missing} 枚だった。")}</div>'
        else:
            body += f'<div class="mj-sub">{rb.html(f"狙った{name}は、必要な牌が河などに見えてしまい、もう作れなかった。")}</div>'
    return f'<div class="mj-card">{verdict}{body}</div><div class="mj-hand">{tiles_fit_html(list(state.hand), aka=aka)}</div>'


def riichi_draws_html(state: PracticeState, rb: Rubifier, *, mark: bool = True) -> str:
    """リーチのあとのツモ（自動でツモ切りになったぶん）。mark が真なら、ツキ補正で引き寄せた牌に ★ を付ける"""
    if state.riichi_index is None:
        return ""
    aka = state.config.rules.aka_dora
    after = state.draws[state.riichi_index + 1:]
    if not after:
        return ""
    cells = []
    lucky = 0
    for draw in after:
        star = ""
        if mark and draw.luck.swapped:
            lucky += 1
            star = '<i class="mj-star" title="ツキ補正で引き寄せた牌">★</i>'
        cells.append(f"<span>{tile_img(draw.tile, aka=aka, cls='' if draw.auto else 'mj-win')}{star}</span>")
    won = state.result is not None and state.result.outcome == Outcome.TSUMO
    tail = f"{len(after)} 回目のツモであがり（枠つきの牌）。" if won else "あがり牌は来なかった。"
    notes = ["リーチのあとは手を変えられないので、あがり牌でなければ、そのまま切る。"]
    if lucky:
        notes.append(f"★ は、ツキ補正で引き寄せた牌（{lucky} 枚）。リーチのあとは、あがり牌を引き寄せる。")
    return (
        f'<div class="mj-cap">{rb.html(f"リーチのあとのツモ：{tail}")}</div><div class="mj-river mj-draws">{"".join(cells)}</div>'
        + "".join(f'<div class="mj-sub">{rb.html(note)}</div>' for note in notes)
    )


def deal_text(state: PracticeState) -> str:
    """配牌の補正で何が起きたか"""
    deal = state.deal
    if deal.target:
        name = target_name(deal.target)
        if deal.swaps == 0:
            return f"配牌：{name}を狙う局。配牌は、山の並びのまま。"
        before = "" if deal.original_distance is None else f"あと {deal.original_distance + 1} 枚 → "
        text = f"配牌：{name}に近づくように、配牌の {deal.swaps} 枚を山の牌と入れ替えた（役の完成まで {before}あと {deal.chosen_distance + 1} 枚）。"
        if deal.moved:
            text += f"足りない牌がツモ山に残るように、山の {deal.moved} 枚の位置も入れ替えた。"
        return text
    if deal.candidates <= 1:
        return "配牌：補正なし（山の並びのまま）。"
    head = f"配牌：候補 {deal.candidates} 個から、いちばん良いものを採用。"
    if not deal.applied:
        return head + f"元の配牌（{shanten_text(deal.original_shanten)}）がいちばん良かったので、そのまま。"
    return head + f"元の配牌は{_sp(shanten_text(deal.original_shanten))}、採用した配牌は{_sp(shanten_text(deal.chosen_shanten))}。"


def _sp(text: str) -> str:
    return f" {text}" if text[:1].isdigit() else text


def draws_text(state: PracticeState) -> str:
    """ツモの補正で何が起きたか"""
    probability = draw_probability(state.config.luck.draw)
    if probability <= 0:
        return "ツモ：補正なし（山の順番どおり）。"
    swapped = sum(1 for d in state.draws if d.luck.swapped)
    key = state.config.target
    wanted = f"{target_name(key)}に近づく牌" if key and key not in SHAPELESS_KEYS else "有効牌"
    text = f"ツモ：{len(state.draws)} 回のうち {swapped} 回、補正で{wanted}に入れ替えた（1 回ごとに {percent(probability)} の確率で抽選）。"
    if key == "ippatsu":
        text += f"一発を狙う局なので、リーチの次のツモだけ、確率を {IPPATSU_BOOST} 倍にした。"
    if key in DEAL_TENPAI_TARGETS:
        text += "最初のツモは入れ替えない（リーチの前にあがってしまうため）。"
    won = state.result is not None and state.result.outcome == Outcome.TSUMO
    if won and state.draws and state.draws[-1].luck.swapped:
        text += "あがり牌も、補正で引き寄せた牌。"
    return text


def hand_summary_html(state: PracticeState, decisions: Sequence[Decision], rb: Rubifier, *, counted: bool, hinted: bool = False) -> str:
    """終わった局のまとめ：ツキ補正で何が起きたかと、打牌の内訳。hinted は、打つ前のヒントが出た局か"""
    luck = state.config.luck
    # 画面に出る順（上の札 → 箇条書き → 注意書き）に作る。用語のルビを、最初に出てくるところに振るため
    chips = f'<span class="mj-chip {"mj-chip-plain" if luck.is_off else "mj-chip-luck"}">{rb.html(luck_text(luck.deal, luck.draw))}</span>'
    if hinted:
        chips += '<span class="mj-chip">ヒントあり</span>'
    if state.config.target:
        chips += f'<span class="mj-chip mj-chip-target">{rb.html(f"役指定：{target_name(state.config.target)}")}</span>'
    chips += f'<span class="mj-chip">局の番号 {state.config.seed}</span>'
    rows = [f"<li>{rb.html(deal_text(state))}</li>", f"<li>{rb.html(draws_text(state))}</li>"]
    aimed = [d for d in decisions if d.target is not None]
    if aimed:
        best = sum(1 for d in aimed if d.target.is_best)
        name = target_name(state.config.target)
        rows.append(f"<li>{rb.html(f'打牌：{name}を狙えた {len(aimed)} 回のうち、役にいちばん近い切り方は {best} 回（{percent(best / len(aimed))}）。')}</li>")
    elif decisions:
        best = sum(1 for d in decisions if d.verdict.is_best)
        what = "おすすめどおりの打牌（速さ・聴牌したらリーチ）" if state.config.target in RIICHI_TARGETS else "いちばん速い打牌"
        rows.append(f"<li>{rb.html(f'打牌：自分で選んだ {len(decisions)} 回のうち、{what}は {best} 回（{percent(best / len(decisions))}）。')}</li>")
    note = "" if counted else f'<div class="mj-sub">{rb.html("この局は、やり直し・番号を指定した局なので、成績には入れていない（スタンプは押す）。")}</div>'
    return f'<div class="mj-card"><div class="mj-chips">{chips}</div><ul class="mj-rules">{"".join(rows)}</ul>{note}</div>'


def review_list_html(decisions: Sequence[Decision], rb: Rubifier, *, aka: bool) -> str:
    """この局の打牌を、1 巡ずつ振り返る"""
    if not decisions:
        return f'<div class="mj-sub">{rb.html("自分で選んだ打牌はありません。")}</div>'
    head = f'<tr class="mj-dim"><td class="num">{rb.html("巡目")}</td><td>切った牌</td><td>評価</td></tr>'
    rows = []
    for decision in decisions:
        verdict = decision.verdict
        tile = decision.action.tile
        assert tile is not None
        riichi = " リーチ" if verdict.riichi else ""
        if decision.target is not None:             # 役指定練習：狙う役から見た評価
            aimed = decision.target
            icon = f'<span class="mj-icon {TARGET_CLASS[aimed.grade]}">{TARGET_ICONS[aimed.grade]}</span>'
            better = ""
            if not aimed.is_best:
                better = f'<div class="mj-sub"><span class="mj-inline">おすすめは {_small(aimed.pick.tile, aka)} {escape(_name(aimed.pick.tile, aka))}</span></div>'
            rows.append(
                f'<tr><td class="num">{decision.turn}</td><td><span class="mj-inline">{icon} {_small(tile, aka)}{riichi}</span></td>'
                f"<td>{rb.html(aimed.label)}{better}</td></tr>"
            )
            continue
        icon = f'<span class="mj-icon {GRADE_CLASS[verdict.grade]}">{GRADE_ICONS[verdict.grade]}</span>'
        better = _better_html(verdict, aka)
        if better:
            better = f'<div class="mj-sub"><span class="mj-inline">{better}</span></div>'
        rows.append(
            f'<tr><td class="num">{decision.turn}</td><td><span class="mj-inline">{icon} {_small(tile, aka)}{riichi}</span></td>'
            f"<td>{rb.html(verdict.label)}{better}</td></tr>"
        )
    return f'<table class="mj-table mj-reviewlist">{head}{"".join(rows)}</table>'


# ---------------------------------------------------------------- 設定の説明と成績


def subhead_html(title: str, text: str, rb: Rubifier) -> str:
    """設定の中の小見出しと、その説明（説明が空なら、小見出しだけ）"""
    head = f'<div class="mj-subhead mj-subhead-first">{rb.html(title)}</div>'
    return head + (f'<div class="mj-sub">{rb.html(text)}</div>' if text else "")


def note_html(text: str, rb: Rubifier) -> str:
    """入力欄のそばに置く、小さな説明文（用語の初出にはルビを振る。入力欄の名前そのものには、ルビを振れないため）"""
    return f'<div class="mj-sub">{rb.html(text)}</div>'


#: 使い方（見出し, 説明）
HELP_ITEMS = (
    ("切る", "牌をタップして選び、「この牌を切る」を押す（同じ牌をもう一度タップしても切れる）。"),
    ("あがる", "あがりの形になると、手牌の下に「ツモ（あがる）」が出る。相手がいないので、あがりはツモだけ。"),
    ("リーチ", "聴牌にとれるとき「リーチ」が出る。押すと、切っても聴牌が残る牌だけが明るく残るので、その中から選ぶ。"
     "リーチのあとは、あがり牌が来るまで自動でツモ切りになる。"),
    ("1 局の長さ", f"ツモは {MAX_DRAWS} 回まで（4 人で打つときの 1 人ぶん）。あがれなければ流局。"),
    ("白い牌", "何も描かれていない白い牌は、白（ハク）。画像が欠けているわけではない。"),
    ("コーチ", "ヒントは「打つ前に表示」「打った後に答え合わせ」「オフ」から選べる。◎ がおすすめ、○ はおすすめと同じ速さの牌"
     "（役指定練習では、狙った役への近さが同じ牌）。"),
    ("ツキ補正", "配牌とツモの「引きの良さ」を上げる。山の牌を並べ替えているだけなので、同じ牌が 5 枚になることはない。"
     "補正の強さはいつも画面の上に出ていて、成績も補正の強さごとに分けて記録する。"),
    ("役指定練習", "狙う役を 1 つ決めて打つ。配牌がその役に近くなり、ツモの補正も、その役に近づく牌を引き寄せる。"
     "コーチは、速さではなく「その役に近い切り方」を勧める。役図鑑の「この役を実戦で練習する」か、下の「設定」から始められる。"),
    ("スタンプ", "あがった手に付いた役は、役図鑑にスタンプが押される。"),
    ("記録", "打っている局・設定・成績は、このブラウザの中に残る（別の端末やブラウザには引き継がれない）。"
     "しばらく開かないと、ブラウザが消してしまうことがある。"),
)


def help_html(rb: Rubifier) -> str:
    """このページの使い方"""
    rows = "".join(f"<li><b>{rb.html(title)}</b>：{rb.html(text)}</li>" for title, text in HELP_ITEMS)
    return f'<ul class="mj-rules">{rows}</ul>'


def luck_now_html(deal: int, draw: int, rb: Rubifier, *, target: str | None = None, tenpai_deal: bool = False) -> str:
    """いまのスライダーの値が、具体的に何を意味するか。target は、役指定練習で狙う役"""
    count = deal_candidates(deal)
    probability = draw_probability(draw)
    wanted = "有効牌"
    if target is not None and (target not in SHAPELESS_KEYS or target in DEAL_TENPAI_TARGETS):
        name = target_name(target)
        goal = target_goal(deal, allow_tenpai=tenpai_deal, need_tenpai=target in DEAL_TENPAI_TARGETS)
        if goal is None:
            deal_line = "配牌：補正なし（山の並びのまま）"
        elif target in DEAL_TENPAI_TARGETS:
            deal_line = f"配牌：聴牌になるまで、配牌の牌を山の牌と入れ替える（{name}は、配牌で聴牌していないと狙えない）"
        elif goal == 0:
            deal_line = f"配牌：{name}の聴牌（完成まで あと 1 枚）になるまで、配牌の牌を山の牌と入れ替える"
        else:
            # 近さは、見出しや結果と同じ物差し（役の完成まで あと何枚）で書く。goal は聴牌までの枚数なので、1 枚足す
            deal_line = f"配牌：{name}の完成まで あと {goal + 1} 枚になるまで、配牌の牌を山の牌と入れ替える"
        if target not in SHAPELESS_KEYS:
            wanted = f"{name}に近づく牌"
    else:
        deal_line = "配牌：補正なし（山の並びのまま）" if count <= 1 else f"配牌：{count} 個の候補から、いちばん良い配牌を採用する"
    draw_line = "ツモ：補正なし（山の順番どおり）" if probability <= 0 else f"ツモ：1 回ごとに {percent(probability)} の確率で、{wanted}を次のツモに持ってくる"
    return f'<div class="mj-sub">{rb.html(deal_line)}<br>{rb.html(draw_line)}</div>'


def luck_guide_html(rb: Rubifier) -> str:
    """段階ごとの効き具合の目安"""
    rows = [
        f'<tr class="mj-dim"><td>段階</td><td class="num">{rb.html("配牌の平均")}</td><td class="num">あがり率</td>'
        f'<td class="num">{rb.html("あがる巡目")}</td></tr>',
    ]
    levels = dict(PRESETS)
    for name, shanten, rate, turn in LUCK_GUIDE:
        rows.append(
            f'<tr><td>{escape(name)}（{levels[name]}）</td><td class="num">{rounded(shanten, 1)} {rb.html("向聴")}</td>'
            f'<td class="num">{percent(rate)}</td><td class="num">{rounded(turn)} 巡目</td></tr>'
        )
    return (
        f'<table class="mj-table">{"".join(rows)}</table>'
        f'<div class="mj-sub">{rb.html("機械的な打ち手（いつもコーチのおすすめを切り、聴牌したらリーチ）が、一人練習を各 300 局打ったときの実測。")}</div>'
    )


def stats_html(summaries: Sequence[Summary], rb: Rubifier, *, aimed: int = 0) -> str:
    """成績。条件（ツキ補正の強さ・打つ前のヒントを見たか）ごとに分け、補正なし・ヒントなしのぶんを「実力」として先頭に出す。

    aimed は、役指定練習の局の数（その局は、ここには入れない。target_stats_html で、狙った役ごとに出す）。
    """
    if not summaries:
        if aimed:
            text = f"役指定なしの一人練習の記録は、まだありません（役指定練習の {aimed} 局は、下の「役指定練習」の表に出ています）。"
        else:
            text = "まだ記録がありません。1 局打ち終わると、ここに出ます。"
        return f'<div class="mj-sub">{rb.html(text)}</div>'
    rows = [
        f'<tr class="mj-dim"><td>ツキ補正</td><td class="num">局数</td><td class="num">あがり</td><td class="num">{rb.html("巡目")}</td>'
        f'<td class="num">点</td><td class="num">{rb.html("打牌")}</td></tr>',
    ]
    for summary in summaries:
        if summary.is_skill:
            label = "<b>なし（実力）</b>"
        elif summary.no_luck:
            label = "なし"
        else:
            label = rb.html(f"配牌 {summary.deal}・ツモ {summary.draw}")
        if summary.hinted:
            label += '<div class="mj-sub">ヒントあり</div>'
        turn = "—" if summary.average_turn is None else rounded(summary.average_turn, 1)
        points = "—" if summary.average_points is None else rounded(summary.average_points)
        best = "—" if summary.best_rate is None else percent(summary.best_rate)
        cls = ' class="mj-skill"' if summary.is_skill else ""
        rows.append(
            f"<tr{cls}><td>{label}</td><td class=\"num\">{summary.hands}</td><td class=\"num\">{percent(summary.win_rate)}</td>"
            f'<td class="num">{turn}</td><td class="num">{points}</td><td class="num">{best}</td></tr>'
        )
    notes = [
        "あがり＝あがった局の割合。巡目＝あがったときの平均の巡目。点＝あがったときに受け取った点の平均。",
        "打牌＝自分で選んだ打牌のうち、いちばん速い打牌（おすすめと同じ速さ）だった割合。",
        "「ヒントあり」は、打つ前のヒント（おすすめ）が 1 回でも出た局。おすすめをなぞれば良い成績になるので、行を分け、打牌の割合は数えない。",
        "ツキ補正が入った局は、補正なしの局より良い成績になる。実力として見るのは「なし（実力）」の行：補正なしで、打つ前のヒントも見ずに打った局。",
    ]
    return f'<table class="mj-table mj-stats">{"".join(rows)}</table>' + "".join(f'<div class="mj-sub">{rb.html(n)}</div>' for n in notes)


# ---------------------------------------------------------------- 役指定練習


#: 手の形を問わない役を狙うときの、ひとことの案内
SHAPELESS_TIPS = {
    "riichi": "聴牌したら「リーチ」を押して、切る牌を選ぶ。",
    "ippatsu": "聴牌したらリーチ。リーチのすぐ次のツモであがると、一発が付く。",
    "menzen_tsumo": "一人練習のあがりは、いつも門前のツモ。どんな形でも、あがれば付く。",
    "double_riichi": "いま聴牌している。最初の打牌で「リーチ」を押すと、ダブル立直になる。",
}


def shapeless_tip(state: PracticeState) -> str:
    """手の形を問わない役を狙う局の、ひとことの案内（そういう局でなければ空）。

    ダブル立直は、最初の打牌でリーチしたときだけ付く。聴牌していない局や、2 巡目より後では、そのことを言う。
    """
    target = state.config.target
    if target not in SHAPELESS_TIPS:
        return ""
    name = target_name(target)
    if target in DEAL_TENPAI_TARGETS:
        if state.turn > 1:
            return f"{name}は、最初の打牌でリーチしたときだけ付く。この局では、もう狙えない。"
        if not state.riichi_discards:
            return f"聴牌していないので、この局では{name}を狙えない。設定のツキ補正で「配牌の良さ」を上げると、配牌で聴牌するようになる。"
    return f"{name}を狙う局：{SHAPELESS_TIPS[target]}"


def coach_note_text(target: str | None) -> str:
    """設定の「コーチ」の説明：おすすめを、何で決めているか（狙う役によって変わる）"""
    if target is None:
        return "コーチのおすすめは、速さ（向聴数と受け入れ枚数）だけで決めています。役や打点との兼ね合いは、対局のコーチで扱う予定です。"
    name = target_name(target)
    if target in RIICHI_TARGETS:
        return f"コーチのおすすめは、速さ（向聴数と受け入れ枚数）で決めます。{name}を狙う局では、聴牌にとれたら「リーチして切る」を勧めます。"
    if target in SHAPELESS_KEYS:
        return f"コーチのおすすめは、速さ（向聴数と受け入れ枚数）で決めます（{name}は、手の形を問わない役なので）。"
    return f"{name}を狙う局では、コーチは、{name}への近さで切る牌を勧めます。受け入れ表は、速さだけで見たものです。"


#: 役指定練習の効き具合の目安。tools/measure_target.py で、機械的な打ち手（役を狙うコーチのおすすめを切り、狙った役が付く
#: あがりだけを取る）が各 30 局打った結果。役 →（補正が 中・強・最大 のときに、狙った役か上位の役が付いた局の割合。%）
TARGET_GUIDE: dict[str, tuple[int, int, int]] = {
    "riichi": (87, 100, 97), "ippatsu": (50, 100, 97), "menzen_tsumo": (87, 100, 100), "tanyao": (73, 93, 100),
    "pinfu": (80, 100, 100), "iipeikou": (63, 90, 100), "yakuhai": (50, 97, 100), "double_riichi": (97, 97, 97),
    "chiitoitsu": (43, 80, 100), "sanankou": (60, 97, 100), "sanshoku": (77, 97, 100), "sanshoku_doukou": (43, 93, 100),
    "ittsu": (57, 93, 100), "chanta": (63, 93, 97), "shousangen": (43, 90, 100), "honroutou": (50, 93, 100),
    "ryanpeikou": (33, 90, 100), "honitsu": (67, 93, 100), "junchan": (57, 97, 97), "chinitsu": (63, 100, 100),
    "kokushi": (60, 97, 100), "suuankou": (50, 93, 100), "daisangen": (33, 93, 100), "tsuuiisou": (33, 97, 100),
    "shousuushii": (37, 97, 100), "daisuushii": (23, 87, 100), "ryuuiisou": (53, 93, 100), "chinroutou": (43, 100, 100),
    "chuuren": (50, 97, 100),
}


def target_guide_html(key: str, rb: Rubifier) -> str:
    """狙う役を選んだときに出す、その役の練習についての説明と、効き具合の目安"""
    page = yaku_page_map()[key]
    lines = [f"{page.name}：{page.short}"]
    if page.practice_note:
        lines.append(page.practice_note)
    rates = TARGET_GUIDE.get(key)
    if rates is not None:
        lines.append(
            f"目安：ツキ補正が「中」で {rates[0]}%、「強」で {rates[1]}%、「最大」で {rates[2]}% の局で、この役が付いた"
            "（機械的な打ち手が、役を狙うコーチのおすすめどおりに、各 30 局打ったときの実測）。"
        )
    return "".join(f'<div class="mj-sub">{rb.html(line)}</div>' for line in lines)


def target_headline_html(advice: TargetAdvice, analysis: Analysis, rb: Rubifier, *, can_riichi: bool, win: TargetResult | None = None) -> str:
    """役指定練習の、打つ前のヒント：役の完成まであと何枚かと、役に近い切り方。

    win は、いまの 14 枚であがったときに、狙った役が付くかどうか（あがりの形のときだけ渡す）。
    見出しの高さが巡ごとに変わると手牌の位置が動くので、見出しは 2 行までにする。速さだけのおすすめとの違いや、
    あがりの形でも役が付かないときの「狙い続けるなら」は、target_speed_note_html で手牌の下に出す。
    """
    aka = analysis.position.rules.aka_dora
    name = advice.name
    if analysis.can_win:
        if win is not None and win.achieved:
            what = f"{name}が付きます。" if win.made else f"{name}の形ができています。"
            return _headline(f'<b class="mj-stage">あがりの形です。</b>{rb.html(what + "「ツモ（あがる）」を押すと、あがれます。")}', "good")
        if analysis.last_discard:
            return _headline(f'<b class="mj-stage">あがりの形です。</b>{rb.html(f"{name}は付きませんが、最後のツモなので、あがりましょう。")}', "good")
        # 役の付かないあがりの形（嵌張待ちの平和、高点法でほかの読み方になる、など）：あがるか、狙い続けるかを選べる
        stage = f'<b class="mj-stage">{rb.html(f"あがりの形ですが、{name}は付きません")}</b>'
        if advice.pick is None:             # もう作れない（必要な牌が見えてしまった）
            return _headline(f'{stage}<br><span class="mj-sub">{rb.html(f"{name}は、もう作れません。ツモであがりましょう。")}</span>', "soso")
        return _headline(f'{stage}<br><span class="mj-sub">{rb.html(f"ツモであがるか、{MARK_PICK[0]} を切って狙い続けるか。")}</span>', "soso")
    if not advice.possible or advice.pick is None:
        lead = f'<span class="mj-chip mj-chip-luck">{rb.html(f"{name}は、もう作れない")}</span> '
        return advice_headline_html(analysis, rb, can_riichi=can_riichi, lead=lead)
    pick = advice.pick
    what = f"{_small(pick.tile, aka)} <b>{escape(_name(pick.tile, aka))}</b>"
    width = f"{pick.kinds} 種 {pick.total} 枚"
    if pick.distance == 0:
        body = f'<b class="mj-stage">{rb.html(f"{name}の聴牌")}にとれます</b>　{what} {rb.html(f"を切ると、{name}になる待ちは {width}")}'
    else:
        body = f'<b class="mj-stage">{rb.html(f"{name}まで あと {pick.missing} 枚")}</b>　おすすめ：{what} {rb.html(f"切り（近づく牌 {width}）")}'
    return _headline(body)


def target_speed_note_html(advice: TargetAdvice, analysis: Analysis, rb: Rubifier) -> str:
    """手牌の下に 1 行で出す補足（無ければ空）。

    あがりの形でも狙った役が付かないとき：狙い続けるなら、どれを切って、役の完成まであと何枚か。
    役を狙うおすすめが、速さだけのおすすめと違うとき：速さだけなら、どれを切るか。
    """
    aka = analysis.position.rules.aka_dora
    pick = advice.pick
    if analysis.can_win:
        if pick is None or analysis.last_discard:
            return ""
        return (
            f'<div class="mj-sub mj-speed-note">{rb.html(f"{advice.name}を狙い続けるなら")} {_small(pick.tile, aka)} {escape(_name(pick.tile, aka))} '
            f'{rb.html(f"切り（{advice.name}の完成まで あと {pick.missing} 枚）。")}</div>'
        )
    if not advice.differs_from_speed:
        return ""
    speed = analysis.pick
    return (
        f'<div class="mj-sub mj-speed-note">{rb.html("速さだけなら")} {_small(speed.tile, aka)} {escape(_name(speed.tile, aka))} '
        f'{rb.html(f"切り（{shanten_text(speed.shanten)}）。役を狙うぶん、遠回りになる。")}</div>'
    )


def target_verdict_headline_html(decision: Decision, rb: Rubifier, *, aka: bool) -> str:
    """役指定練習の、打った後の答え合わせ（短く 1〜2 行）"""
    verdict = decision.target
    tile = decision.action.tile
    assert verdict is not None and tile is not None
    icon = f'<span class="mj-icon {TARGET_CLASS[verdict.grade]}">{TARGET_ICONS[verdict.grade]}</span>'
    body = f"{icon} {_small(tile, aka)} <b>{escape(_name(tile, aka))}</b> 切り：{rb.html(verdict.label)}"
    if not verdict.is_best:
        body += f"<br><span class=\"mj-sub\">おすすめは {_small(verdict.pick.tile, aka)} {escape(_name(verdict.pick.tile, aka))} 切り</span>"
    return _headline(body, TARGET_CLASS[verdict.grade])


def target_verdict_html(decision: Decision, rb: Rubifier, *, level: int, aka: bool) -> str:
    """役指定練習の、前の打牌の評価（理由つき）"""
    verdict = decision.target
    tile = decision.action.tile
    assert verdict is not None and tile is not None
    cls = TARGET_CLASS[verdict.grade]
    icon = f'<span class="mj-icon {cls}">{TARGET_ICONS[verdict.grade]}</span>'
    head = f'<div class="mj-review-head">{icon} {rb.html(f"{decision.turn} 巡目の打牌")} {_small(tile, aka)}</div>'
    body = f"<div>{rb.html(verdict.text)}</div>"
    if level >= LEVEL_NORMAL and verdict.reasons:
        body += "<ul>" + "".join(f"<li>{rb.html(reason)}</li>" for reason in verdict.reasons) + "</ul>"
    return f'<div class="mj-review {cls}">{head}{body}</div>'


def plan_html(plan: Plan, rb: Rubifier) -> str:
    """めざす形：どの組がそろっていて、どの牌が足りないか（足りない牌は、うすく出す）"""
    if not plan.possible:
        return f'<div class="mj-sub">{rb.html("必要な牌が残っていないので、めざす形がありません。")}</div>'

    def tiles_of(block) -> str:
        have = list(block.have)
        cells = []
        for kind in block.tiles:
            if kind in have:
                have.remove(kind)
                cells.append(kind_img(kind))
            else:
                cells.append(kind_img(kind, cls="mj-missing"))
        return "".join(cells)

    regular = plan.form is Form.REGULAR and all(block.kind is not BlockKind.SINGLE for block in plan.blocks)
    groups = []
    for block in plan.blocks:
        cls = "mj-part-done" if block.complete else "mj-part-wait"
        caption = ""
        if regular:
            star = "★" if block.fixed else ""
            caption = f'<div class="mj-cap">{star}{rb.html(BLOCK_NAMES[block.kind])}</div>'
        small = "" if regular else " mj-small"
        groups.append(f'<div class="mj-block mj-part {cls}{small}"><div class="mj-block-tiles">{tiles_of(block)}</div>{caption}</div>')
    parts = [f'<div class="mj-blocks{"" if regular else " mj-blocks-tight"}">{"".join(groups)}</div>']
    need = sum(count for _, count in plan.need)
    if plan.tenpai_form:
        legend = "うすい牌が、足りない牌。" if need else "足りない牌は無い（この形で聴牌）。"
        legend += "「両面」は、両側のどちらを引いてもあがりになる 2 枚。この形は、聴牌したときの形を表している。"
    else:
        legend = "うすい牌が、足りない牌。" if need else "足りない牌は無い（この形であがっている）。"
    if regular and any(block.fixed for block in plan.blocks):
        legend += "★ は、この役に必ず要る組。"
    if plan.form is Form.CHIITOI:
        legend += "七対子の形（対子 7 組）。"
    elif plan.form is Form.KOKUSHI:
        legend += "国士無双の形（13 種類の么九牌を 1 枚ずつと、そのどれか 1 枚）。"
    parts.append(f'<div class="mj-sub mj-legend">{rb.html(legend)}</div>')
    if plan.spare:
        spare = "".join(_small_kind(kind) for kind, count in plan.spare for _ in range(count))
        parts.append(f'<div class="mj-sub"><span class="mj-inline">{rb.html("めざす形に入らない牌：")} {spare}</span></div>')
    parts.append(
        f'<div class="mj-sub">{rb.html("めざす形は、いまの手牌からいちばん近い形の 1 つ。引いた牌によって変わる。見えている牌（河・ドラ表示牌）は、もう手に入らないものとして選んでいる。")}</div>'
    )
    return "".join(parts)


def target_candidates_html(advice: TargetAdvice, rb: Rubifier, *, aka: bool, chosen_kind: int | None = None) -> str:
    """役に近い切り方の表（切る牌 → 役の完成まであと何枚か → 引くと近づく牌）"""
    pick = advice.pick
    if pick is None:
        return ""
    near = [c for c in advice.candidates if c.distance == pick.distance]
    far = [c for c in advice.candidates if c.distance > pick.distance]
    rows = []
    for candidate in near:
        mark = MARK_PICK[0] if candidate.is_pick else (MARK_EQUAL[0] if candidate.is_best else "")
        badge = '<span class="mj-badge mj-badge-you">切った牌</span>' if chosen_kind == candidate.kind else ""
        cells = "".join(
            f'<span class="mj-acc{" mj-acc-dead" if count == 0 else ""}">{_small_kind(kind)}<span>{count}</span></span>' for kind, count in candidate.closer
        )
        count = f"{candidate.kinds} 種 {candidate.total} 枚"
        if not candidate.is_best:
            count += f'<span class="mj-minus">（−{pick.total - candidate.total} 枚）</span>'
        cls = "mj-cand" + (" mj-cand-pick" if candidate.is_pick else "") + (" mj-cand-you" if chosen_kind == candidate.kind else "")
        rows.append(
            f'<div class="{cls}"><div class="mj-cand-head"><span class="mj-cand-mark">{mark}</span>'
            f"{_small(candidate.tile, aka)}<span class=\"mj-cand-name\">{escape(_name(candidate.tile, aka))}{badge}</span>"
            f'<span class="mj-cand-num">{count}</span></div><div class="mj-cand-tiles">{cells}</div></div>'
        )
    title = f"{advice.name}の完成まで あと {pick.missing} 枚のままの切り方"
    parts = [
        f'<div class="mj-subhead">{rb.html(title)}</div>',
        f'<div class="mj-sub">{rb.html("小さい牌が、引くと役に近づく牌。数字は、その残り枚数。")}</div>',
        f'<div class="mj-cands">{"".join(rows)}</div>',
    ]
    if far:
        cells = []
        for candidate in far:
            you = " mj-far-you" if chosen_kind == candidate.kind else ""
            cells.append(f'<span class="mj-far{you}">{_small(candidate.tile, aka)}</span>')
        parts.append(f'<div class="mj-subhead">{rb.html(f"切ると、{advice.name}から遠ざかる牌")}</div>')
        parts.append(f'<div class="mj-farrow">{"".join(cells)}</div>')
    if any(c.shanten == TENPAI and c.distance > 0 for c in advice.candidates):
        parts.append(f'<div class="mj-sub">{rb.html(f"聴牌になる切り方でも、{advice.name}が付くあがり牌が無いものは、{advice.name}の聴牌と数えない。")}</div>')
    parts.append(
        f'<div class="mj-sub mj-legend">{MARK_PICK[0]} おすすめ　{MARK_EQUAL[0]} おすすめと同じ良さ<br>'
        + rb.html("ここで比べているのは、狙う役への近さだけ。速くあがることだけを考えた切り方は、下の受け入れ表で見られる。")
        + "</div>"
    )
    return "".join(parts)


def target_result_html(result: TargetResult, rb: Rubifier) -> str:
    """あがった局で、狙った役が付いたかどうか"""
    name = result.name
    if result.made:
        return f'<div class="mj-review good"><b>{rb.html(f"狙った{name}が付いた。")}</b></div>'
    if result.upgraded:
        text = f"{name}を狙って、その上位の役の{result.upgraded}が付いた。"
        return f'<div class="mj-review good"><b>{rb.html(text)}</b></div>'
    if result.superseded:
        text = f"{name}の形はできた。ただし、役満（{result.superseded}）があるので、{name}は数えない。"
        note = "役満のときは、ふつうの役とドラを数えない。"
        return f'<div class="mj-review good"><b>{rb.html(text)}</b><div class="mj-sub">{rb.html(note)}</div></div>'
    body = f"<b>{rb.html(f'あがったが、狙った{name}は付かなかった。')}</b>"
    if result.check is not None and result.check.checks:
        body += f'<div class="mj-sub">{rb.html(f"{name}の条件：")}</div>{checks_html(result.check, rb)}'
        if result.check.note:
            body += f'<div class="mj-sub">{rb.html(result.check.note)}</div>'
    return f'<div class="mj-review soso">{body}</div>'


def stamps_html(fresh: Sequence[str], rb: Rubifier) -> str:
    """この局のあがりで、はじめてスタンプが押された役"""
    if not fresh:
        return ""
    pages = yaku_page_map()
    names = "・".join(pages[key].name for key in fresh if key in pages)
    return f'<div class="mj-lesson"><b>{rb.html("はじめて成立させた役")}</b>：{rb.html(names)}<div class="mj-sub">{rb.html("役図鑑に、スタンプを押しました。")}</div></div>'


def target_stats_html(stats: dict[str, TargetStat], rb: Rubifier) -> str:
    """役指定練習の成績（狙った役ごと）"""
    if not stats:
        return ""
    pages = yaku_page_map()
    order = [key for key in pages if key in stats]
    head = f'<div class="mj-subhead">{rb.html("役指定練習")}</div>'       # 画面に出る順（見出し → 表 → 注意書き）に作る
    rows = ['<tr class="mj-dim"><td>狙った役</td><td class="num">局数</td><td class="num">あがり</td><td class="num">役が付いた</td></tr>']
    for key in order:
        stat = stats[key]
        rows.append(
            f'<tr><td>{rb.html(pages[key].name)}</td><td class="num">{stat.tries}</td><td class="num">{stat.wins}</td>'
            f'<td class="num">{stat.made}（{percent(stat.made_rate)}）</td></tr>'
        )
    note = "役指定練習の局は、役指定なしの一人練習の成績には入れていない。「役が付いた」は、狙った役か、その上位の役が付いた局。"
    return f'{head}<table class="mj-table mj-stats">{"".join(rows)}</table><div class="mj-sub">{rb.html(note)}</div>'

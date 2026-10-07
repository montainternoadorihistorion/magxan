"""和了の解説を画面に出すための HTML づくり。

engine.scoring.explain が計算した事実（Explanation）を、そのまま図と表にする。
ここでは数値を計算し直さない（表示する数値はすべて Explanation に入っているもの）。

    sections = explanation_sections(result)      # [(見出し, HTML), ...]

Streamlit には依存しない（HTML の文字列を返すだけ）。画面に置くのは views/ の役目。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from html import escape

from engine.melds import Meld, MeldType
from engine.scoring.context import WinContext
from engine.scoring.decompose import BlockType, Form, Interpretation
from engine.scoring.explain import Candidate, Explanation, Status
from engine.scoring.judge import Level
from engine.scoring.layout import block_tiles, meld_of_block
from engine.scoring.points import LEVEL_NAMES, PointsResult
from engine.scoring.texts import kind_text, wait_text
from engine.scoring.yaku_eval import YakuResult
from engine.tiles import EAST, sort_tiles
from engine.yaku_table import YAKU
from ui.ruby import Rubifier
from ui.tile_view import back_img, kind_img, tile_img

DETAIL_BRIEF, DETAIL_NORMAL, DETAIL_FULL = 1, 2, 3
DETAIL_LABELS = {DETAIL_BRIEF: "要点だけ", DETAIL_NORMAL: "ふつう", DETAIL_FULL: "くわしく"}

WIND_NAMES = {27: "東", 28: "南", 29: "西", 30: "北"}
_MELD_CAPTIONS = {
    MeldType.CHI: "チー",
    MeldType.PON: "ポン",
    MeldType.ANKAN: "暗槓",
    MeldType.MINKAN: "明槓",
    MeldType.KAKAN: "加槓",
}
_SITUATION_LABELS = (
    ("double_riichi", "ダブル立直"),
    ("riichi", "立直"),
    ("ippatsu", "一発"),
    ("rinshan", "嶺上開花"),
    ("chankan", "槍槓"),
    ("haitei", "海底摸月"),
    ("houtei", "河底撈魚"),
    ("tenhou", "天和"),
    ("chiihou", "地和"),
)


@dataclass(frozen=True)
class Section:
    key: str            # 画面の部品を区別するための名前
    title: str          # 見出し（空なら見出しなし）
    html: str
    heading: str = ""   # 見出しの HTML（用語にルビを振ったもの）。空なら title をそのまま使う

    @property
    def heading_html(self) -> str:
        """見出しを画面に置くための HTML（見出しが無ければ空）"""
        if not self.title:
            return ""
        return f'<h3 class="mj-h3">{self.heading or escape(self.title)}</h3>'


def _head(rb: Rubifier, title: str) -> tuple[str, str]:
    """見出しを（文字, ルビつきの HTML）にする。

    本文を作る前に呼ぶこと。ルビは「画面で最初に出てきたとき」に振るので、見出しを先に通さないと、
    見出しに出てくる用語のルビが、あとの本文のほうに付いてしまう。
    """
    return title, rb.html(title)


# ---------------------------------------------------------------- 牌の HTML


def _fmt(value: int) -> str:
    return f"{value:,}"


def tiles_fit_html(tile_ids: Sequence[int], *, aka: bool, max_px: int = 34, win_tile: int | None = None, gap_before_last: bool = False) -> str:
    """牌を 1 列に並べる。幅が足りなければ、折り返さずに牌を小さくして収める"""
    if not tile_ids:
        return ""
    columns = [f"minmax(0,{max_px}px)"] * len(tile_ids)
    if gap_before_last and len(tile_ids) > 1:
        columns.insert(-1, "8px")
    cells = []
    for index, tile in enumerate(tile_ids):
        if gap_before_last and len(tile_ids) > 1 and index == len(tile_ids) - 1:
            cells.append("<span></span>")
        cells.append(tile_img(tile, aka=aka, cls="mj-win" if tile == win_tile else ""))
    return f'<div class="mj-fit" style="grid-template-columns:{" ".join(columns)}">{"".join(cells)}</div>'


def _group_html(
    tile_ids: Iterable[int], caption: str, *, aka: bool, win_tile: int | None = None, small: bool = False, hide_ends: bool = False
) -> str:
    images = [tile_img(t, aka=aka, cls="mj-win" if t == win_tile else "") for t in tile_ids]
    if hide_ends and len(images) == 4:
        images[0] = images[3] = back_img()       # 暗槓は、卓では両端を裏向きにして見せる
    cells = "".join(images)
    size = " mj-small" if small else ""
    cap = f'<div class="mj-cap">{caption}</div>' if caption else ""
    return f'<div class="mj-block{size}"><div class="mj-block-tiles">{cells}</div>{cap}</div>'


def _meld_caption(meld: Meld) -> str:
    return _MELD_CAPTIONS[meld.type]


def hand_html(result: Explanation, rb: Rubifier) -> str:
    """卓で見える形の手牌（門前の牌、和了牌、副露、ドラ表示牌）"""
    ctx = result.ctx
    aka = result.rules.aka_dora
    closed = [t for t in sort_tiles(ctx.closed_tiles) if t != ctx.win_tile]
    how = "ツモ" if ctx.is_tsumo else "ロン"
    parts = [
        '<div class="mj-hand">',
        tiles_fit_html([*closed, ctx.win_tile], aka=aka, win_tile=ctx.win_tile, gap_before_last=True),
        f'<div class="mj-cap mj-right">{rb.html(f"右端（枠つき）が和了牌：{how}")}</div>',
    ]
    if ctx.melds:
        groups = "".join(
            _group_html(sort_tiles(m.tiles), rb.html(_meld_caption(m)), aka=aka, small=True, hide_ends=m.type is MeldType.ANKAN)
            for m in ctx.melds
        )
        parts.append(f'<div class="mj-row"><span class="mj-rowlabel">{rb.html("副露")}</span><div class="mj-blocks">{groups}</div></div>')
    indicators = []
    if ctx.dora_indicators:
        indicators.append(_group_html(ctx.dora_indicators, "ドラ表示牌", aka=aka, small=True))
    if ctx.ura_indicators:
        indicators.append(_group_html(ctx.ura_indicators, "裏ドラ表示牌", aka=aka, small=True))
    if indicators:
        parts.append(f'<div class="mj-row"><div class="mj-blocks">{"".join(indicators)}</div></div>')
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------- 状況とまとめ


def situation_chips(result: Explanation) -> list[str]:
    ctx = result.ctx
    seat = WIND_NAMES[ctx.seat_wind]
    chips = [
        f"{WIND_NAMES[ctx.round_wind]}場",
        f"{seat}家（{'親' if ctx.seat_wind == EAST else '子'}）",
        "ツモ" if ctx.is_tsumo else "ロン",
        "門前" if ctx.is_menzen else "鳴きあり",
    ]
    shown_riichi = False
    for name, label in _SITUATION_LABELS:
        if not getattr(ctx, name):
            continue
        if name == "riichi" and shown_riichi:
            continue
        if name == "double_riichi":
            shown_riichi = True
        chips.append(label)
    if ctx.honba:
        chips.append(f"{ctx.honba} 本場")
    if ctx.kyotaku:
        chips.append(f"供託 {ctx.kyotaku} 本")
    return chips


def _chips_html(chips: Iterable[str], rb: Rubifier) -> str:
    return '<div class="mj-chips">' + "".join(f'<span class="mj-chip">{rb.html(c)}</span>' for c in chips) + "</div>"


def _yaku_names(candidate: Candidate) -> str:
    return "・".join(y.name for y in candidate.evaluation.yaku)


def _han_fu_text(candidate: Candidate) -> str:
    if candidate.is_yakuman:
        return candidate.points.level_name if candidate.points else "役満"
    if candidate.interp.form is Form.KOKUSHI:
        return f"{candidate.han} 翻"
    return f"{candidate.han} 翻 {candidate.fu.fu} 符"


def payment_text(points: PointsResult, ctx: WinContext) -> str:
    """実際に払われる点（本場ぶんを含む）を短く書く。例: 3,900 点 ／ 1,000・2,000 点 ／ 2,000 点オール"""
    payments = points.payments
    if not ctx.is_tsumo:
        return f"{_fmt(payments[0].points)} 点"
    if ctx.is_dealer:
        return f"{_fmt(payments[0].points)} 点オール"
    return f"{_fmt(payments[1].points)}・{_fmt(payments[0].points)} 点"


def headline(result: Explanation) -> str:
    """採用した読み方の点数（まとめの大きな文字）"""
    best = result.best
    assert best is not None and best.points is not None
    return payment_text(best.points, result.ctx)


def summary_html(result: Explanation, rb: Rubifier) -> str:
    """いちばん上に出す結果のまとめ"""
    chips = _chips_html(situation_chips(result), rb)
    if result.status is Status.NOT_WINNING:
        body = '<div class="mj-big mj-bad">和了の形になっていない</div>' + f'<div class="mj-sub">{rb.html("4 面子 1 雀頭・七対子・国士無双のどれにもなっていない。")}</div>'
    elif result.status is Status.NO_YAKU:
        body = '<div class="mj-big mj-bad">あがれない（役なし）</div>' + f'<div class="mj-sub">{rb.html("形はできているが、役が 1 つも無い。")}</div>'
    else:
        best = result.best
        assert best is not None and best.points is not None
        points = best.points
        level = rb.wrap(points.level_name, '<span class="mj-level">', "</span>") if points.level is not Level.NONE else ""
        body = (
            f'<div class="mj-big">{escape(headline(result))} {level}</div>'
            f'<div class="mj-sub">{rb.html(_han_fu_text(best))} ／ {rb.html(_yaku_names(best))}'
            f'{" ／ ドラ " + str(best.dora_han) if best.dora_han else ""}</div>'
        )
        if len(points.payments) > 1 or points.payments[0].count > 1 or points.kyotaku_bonus:
            body += f'<div class="mj-sub">{rb.html(f"和了者が受け取る合計 {_fmt(points.total)} 点")}</div>'
    return f'<div class="mj-card mj-summary">{chips}{body}</div>'


# ---------------------------------------------------------------- ① 読み方


def _block_caption(interp: Interpretation, index: int, meld: Meld | None) -> str:
    block = interp.blocks[index]
    if block.type is BlockType.TOITSU:
        return "雀頭" if interp.form is Form.REGULAR else "対子"
    if block.type is BlockType.SHUNTSU:
        return "順子（チー）" if meld is not None else "順子"
    if block.type is BlockType.KANTSU:
        assert meld is not None
        return _meld_caption(meld)
    if meld is not None:
        return "明刻（ポン）"
    return "明刻（ロンで完成）" if block.ron_completed else "暗刻"


def reading_html(candidate: Candidate, result: Explanation, rb: Rubifier, *, small: bool = False) -> str:
    """読み方 1 つぶんの分解図"""
    ctx = result.ctx
    aka = result.rules.aka_dora
    interp = candidate.interp
    if interp.form is Form.KOKUSHI:
        return tiles_fit_html(sort_tiles(ctx.closed_tiles), aka=aka, win_tile=ctx.win_tile)
    groups = block_tiles(interp, ctx)
    cells = []
    for index, tiles in enumerate(groups):
        meld = meld_of_block(interp, ctx, index)
        caption = rb.html(_block_caption(interp, index, meld))
        cells.append(_group_html(tiles, caption, aka=aka, win_tile=ctx.win_tile if index == interp.win_index else None, small=small))
    return f'<div class="mj-blocks">{"".join(cells)}</div>'


def _candidate_result_text(candidate: Candidate, ctx: WinContext) -> str:
    if candidate.points is None:
        return "役なし（この読み方ではあがれない）"
    points = candidate.points
    level = f"{points.level_name} " if points.level is not Level.NONE and not candidate.is_yakuman else ""
    return f"{_han_fu_text(candidate)} → {level}{payment_text(points, ctx)}"


def _choice_text(result: Explanation) -> str:
    count = len(result.candidates)
    best, second = result.candidates[0], result.candidates[1]
    if second.points is None or best.points is None:
        return f"この 14 枚の読み方は {count} 通り。役が付く読み方を採用する。"
    if best.points.total > second.points.total:
        return f"この 14 枚の読み方は {count} 通り。点数が最も高くなる読み方を採用する（高点法）。"
    return f"この 14 枚の読み方は {count} 通り。点数は同じなので、どの読み方で数えてもよい。"


def decomposition_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "① 手牌の読み方")
    first = result.candidates[0]
    interp = first.interp
    parts = [reading_html(first, result, rb)]
    parts.append(f'<div class="mj-note">待ち：{rb.html(wait_text(interp, result.ctx.win_kind))}（枠つきが和了牌）</div>')
    if interp.form is Form.CHIITOI:
        parts.append(f'<div class="mj-note">{rb.html("7 組の対子でできた七対子の形。")}</div>')
    elif interp.form is Form.KOKUSHI:
        parts.append(f'<div class="mj-note">{rb.html("13 種類の么九牌（1・9・字牌）が 1 枚ずつ＋そのどれか 1 枚の、国士無双の形。")}</div>')
    else:
        parts.append(f'<div class="mj-note">{rb.html("面子 4 つと雀頭 1 つに分けられる。")}</div>')

    if result.has_alternatives:
        parts.append(f'<div class="mj-subhead">{rb.html(_choice_text(result))}</div>')
        if detail >= DETAIL_NORMAL:
            rows = []
            for number, candidate in enumerate(result.candidates, start=1):
                mark = "採用" if number == 1 and candidate.has_yaku else ""
                badge = f'<span class="mj-adopt">{mark}</span>' if mark else ""
                wait = rb.html(wait_text(candidate.interp, result.ctx.win_kind))
                rows.append(
                    f'<div class="mj-alt"><div class="mj-alt-head">読み方 {number} {badge}'
                    f'<span class="mj-alt-result">{rb.html(_candidate_result_text(candidate, result.ctx))}</span></div>'
                    f"{reading_html(candidate, result, rb, small=True)}"
                    f'<div class="mj-sub">{wait}／{rb.html(_yaku_names(candidate) or "役なし")}</div></div>'
                )
            parts.append("".join(rows))
    elif detail >= DETAIL_FULL:
        parts.append(f'<div class="mj-sub">{rb.html("この手の読み方は 1 通りだけ。")}</div>')
    return Section("reading", title, "".join(parts), heading)


# ---------------------------------------------------------------- ② 役


def _checks_html(item: YakuResult, rb: Rubifier) -> str:
    rows = []
    for check in item.checks:
        cls = "mj-ok" if check.ok else "mj-ng"
        text = rb.html(check.text)             # 画面に出る順（条件 → その内訳）に作る。初出のルビを、先に出るほうに振るため
        detail = f'<span class="mj-why">{rb.html(check.detail)}</span>' if check.detail else ""
        rows.append(f'<li class="{cls}"><span>{text}{detail}</span></li>')
    return f'<ul class="mj-checks">{"".join(rows)}</ul>'


def _named(name: str, reading: str, rb: Rubifier) -> str:
    """役の名前と、そのすぐ横に並べる読み。ルビの代わりに読みを見せるので、名前は「もう出てきた用語」として覚える"""
    rb.note(name)
    return f'<b class="mj-term">{escape(name)}</b> <span class="mj-reading">{escape(reading)}</span>'


def _yaku_row(item: YakuResult, rb: Rubifier, detail: int, *, counted: bool = True) -> str:
    name = _named(item.name, item.reading, rb)
    han = "役満" if item.is_yakuman and item.han == 13 else (f"役満 × {item.han // 13}" if item.is_yakuman else f"{item.han} 翻")
    note = f'<div class="mj-sub">{rb.html(item.note)}</div>' if item.note else ""
    checks = _checks_html(item, rb) if detail >= DETAIL_FULL else ""
    cls = "" if counted else ' class="mj-dim"'
    return f"<tr{cls}><td>{name}{note}{checks}</td><td class=\"num\">{han}</td></tr>"


def yaku_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "② 役")
    first = result.candidates[0]
    evaluation = first.evaluation
    parts: list[str] = []
    if evaluation.yaku:
        rows = "".join(_yaku_row(item, rb, detail) for item in evaluation.yaku)
        if first.is_yakuman:
            total = "役満" if evaluation.yakuman_times == 1 else f"役満 {evaluation.yakuman_times} つぶん"
        else:
            total = f"{evaluation.han} 翻"
        rows += f'<tr class="total"><td>役の合計</td><td class="num">{total}</td></tr>'
        parts.append(f'<table class="mj-table">{rows}</table>')
        if first.is_yakuman and evaluation.ignored:
            names = "・".join(y.name for y in evaluation.ignored)
            parts.append(f'<div class="mj-note">{rb.html(f"役満が成立したので、ほかの役（{names}）とドラは数えない。")}</div>')
    else:
        parts.append(f'<div class="mj-note mj-bad">{rb.html("成立している役が無い。役が 1 つも無いと、形ができていてもあがれない。")}</div>')
        for line in result.advice:
            parts.append(f'<div class="mj-note">{rb.html(line)}</div>')

    if first.near and (detail >= DETAIL_FULL or not evaluation.yaku):
        rows = []
        for item in first.near:
            failed = next((c for c in item.checks if not c.ok), None)
            name = _named(item.name, item.reading, rb)
            hint = rb.html(item.hint)              # 画面に出る順（名前 → 条件 → 足りなかった理由）に作る
            why = f'<div class="mj-sub">{rb.html(failed.detail)}</div>' if failed and failed.detail else ""
            rows.append(f'<div class="mj-near">{name}<div class="mj-near-hint">{hint}</div>{why}</div>')
        parts.append(f'<div class="mj-subhead">惜しかった役（あと少しで付いた役）</div>{"".join(rows)}')
    return Section("yaku", title, "".join(parts), heading)


# ---------------------------------------------------------------- ③ ドラ


def dora_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "③ ドラ")
    dora = result.dora
    first = result.candidates[0]
    aka = result.rules.aka_dora
    if not dora.dora_lines and not dora.ura_lines and not dora.aka_tiles:
        text = "ドラ表示牌が置かれておらず、赤い 5 も手牌に無いので、ドラは 0 翻。"
        html = f'<div class="mj-note">{rb.html(text)}</div>'
        if first.has_yaku and not first.is_yakuman:
            html += f'<div class="mj-formula">{rb.html(f"役 {first.yaku_han} 翻 ＋ ドラ 0 翻 ＝ {first.han} 翻")}</div>'
        return Section("dora", title, html, heading)
    rows = []
    for label, lines in (("ドラ表示牌", dora.dora_lines), ("裏ドラ表示牌", dora.ura_lines)):
        for line in lines:
            rows.append(
                f'<tr><td><span class="mj-inline">{escape(label)} {tile_img(line.indicator, aka=aka)} → {kind_img(line.dora_kind)}</span>'
                f'<div class="mj-sub">{escape(kind_text(line.dora_kind))} が手牌に {line.count} 枚</div></td>'
                f'<td class="num">{line.count} 翻</td></tr>'
            )
    if aka:
        tiles = "".join(tile_img(t, aka=True) for t in dora.aka_tiles)
        rows.append(
            f'<tr><td><span class="mj-inline">赤ドラ {tiles}</span><div class="mj-sub">赤い 5 が手牌に {dora.aka} 枚</div></td>'
            f'<td class="num">{dora.aka} 翻</td></tr>'
        )
    rows.append(f'<tr class="total"><td>ドラの合計</td><td class="num">{dora.total} 翻</td></tr>')
    parts = [f'<table class="mj-table">{"".join(rows)}</table>']

    if result.ctx.ura_indicators and not result.ctx.riichi:
        parts.append(f'<div class="mj-note">{rb.html("裏ドラは、立直して和了したときだけ数える。")}</div>')
    if first.is_yakuman:
        parts.append(f'<div class="mj-note">{rb.html("役満のときは、ドラは数えない。")}</div>')
    elif not first.has_yaku:
        parts.append(f'<div class="mj-note">{rb.html("ドラは役ではない。ドラが何枚あっても、役が無ければあがれない。")}</div>')
    else:
        parts.append(
            f'<div class="mj-formula">{rb.html(f"役 {first.yaku_han} 翻 ＋ ドラ {first.dora_han} 翻 ＝ {first.han} 翻")}</div>'
        )
    if detail >= DETAIL_FULL:
        parts.append(
            '<div class="mj-sub">'
            + rb.html("ドラは表示牌の「次の牌」。数牌は 1→2→…→9→1、風牌は 東→南→西→北→東、三元牌は 白→發→中→白 の順。")
            + "</div>"
        )
    return Section("dora", title, "".join(parts), heading)


# ---------------------------------------------------------------- ④ 符


def fu_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "④ 符")
    first = result.candidates[0]
    fu = first.fu
    parts: list[str] = []
    if first.interp.form is Form.KOKUSHI:
        return Section("fu", title, f'<div class="mj-note">{rb.html(fu.note)}</div>', heading)
    if first.is_yakuman:
        text = "役満は、符に関係なく点数が決まる。符は数えなくてよい。"
        return Section("fu", title, f'<div class="mj-note">{rb.html(text)}</div>', heading)
    if first.points is not None and first.points.level is not Level.NONE and first.han >= 5:
        text = f"この手は {first.han} 翻（{LEVEL_NAMES[first.points.level]}）なので、点数は符に関係なく決まる。下の符は参考。"
        parts.append(f'<div class="mj-note">{rb.html(text)}</div>')

    rows = []
    sequences = [line for line in fu.lines if line.label == "順子"]
    for line in fu.lines:
        if line.label == "順子":
            if line is not sequences[0]:
                continue      # 順子はどれも 0 符なので、1 行にまとめる
            label = "順子" if len(sequences) == 1 else f"順子 × {len(sequences)}"
            text = "・".join(item.detail for item in sequences)
        else:
            label, text = line.label, line.detail
        sub = f'<div class="mj-sub">{rb.html(text)}</div>' if text and detail >= DETAIL_NORMAL else ""
        rows.append(f'<tr><td>{rb.html(label)}{sub}</td><td class="num">{line.fu} 符</td></tr>')
    if first.interp.form is Form.REGULAR:
        if fu.fu != fu.raw_total:
            rule = "例外で 30 符にする" if fu.raw_total == 20 else "10 符単位に切り上げ"
            rows.append(f'<tr class="total"><td>合計 {fu.raw_total} 符 → {rule}</td><td class="num">{fu.fu} 符</td></tr>')
        else:
            rows.append(f'<tr class="total"><td>合計（ちょうど 10 符単位）</td><td class="num">{fu.fu} 符</td></tr>')
    parts.append(f'<table class="mj-table">{"".join(rows)}</table>')
    if fu.note:
        parts.append(f'<div class="mj-note">{rb.html(fu.note)}</div>')
    if detail >= DETAIL_FULL and first.interp.form is Form.REGULAR:
        parts.append(
            '<div class="mj-sub">'
            + rb.html(
                "刻子の符：明刻 2 符が基準。暗刻は 2 倍、么九牌（1・9・字牌）は 2 倍、槓子は 4 倍。"
                "待ちの符：嵌張・辺張・単騎は 2 符、両面・双碰は 0 符。"
            )
            + "</div>"
        )
    return Section("fu", title, "".join(parts), heading)


# ---------------------------------------------------------------- ⑤ 点数


_LIMIT_ROWS = (
    ("満貫", "5 翻（または 4 翻 40 符以上、3 翻 70 符以上）", 2000),
    ("跳満", "6〜7 翻", 3000),
    ("倍満", "8〜10 翻", 4000),
    ("三倍満", "11〜12 翻", 6000),
    ("役満", "役満の役。13 翻以上は数え役満（ルールによる）", 8000),
)


def points_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "⑤ 点数")
    points = result.best.points
    parts = [f'<div class="mj-formula">{rb.html(points.formula)}</div>']
    if detail >= DETAIL_NORMAL:
        steps = "".join(f"<li>{rb.html(step)}</li>" for step in points.steps)
        parts.append(f'<ol class="mj-steps">{steps}</ol>')
    if detail >= DETAIL_FULL:
        label = rb.html("基本点の早見（満貫以上は符を使わない）")       # 画面に出る順（見出し → 表）に作る
        rows = "".join(
            f'<tr><td>{rb.html(name)}</td><td class="mj-sub">{rb.html(cond)}</td><td class="num">{_fmt(base)}</td></tr>' for name, cond, base in _LIMIT_ROWS
        )
        parts.append(
            f'<details class="mj-details"><summary>{label}</summary>'
            f'<table class="mj-table"><tr><td></td><td class="mj-sub">条件</td><td class="num mj-sub">基本点</td></tr>{rows}</table>'
            f'<div class="mj-sub">{rb.html("満貫未満は 基本点 ＝ 符 × 2^(翻＋2)。子のロンは × 4、親のロンは × 6。ツモは、親が × 2・子が × 1 を払う。")}</div>'
            "</details>"
        )
    return Section("points", title, "".join(parts), heading)


# ---------------------------------------------------------------- ⑥ 支払い ⑦ 申告


def payment_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "⑥ 誰がいくら払うか")
    points = result.best.points
    rows = []
    for payment in points.payments:
        who = payment.payer if payment.count == 1 else f"{payment.payer} {payment.count} 人（1 人あたり）"
        honba = f'<div class="mj-sub">うち本場ぶん {_fmt(payment.honba)} 点</div>' if payment.honba else ""
        rows.append(f'<tr><td>{rb.html(who)}{honba}</td><td class="num">{_fmt(payment.points)} 点</td></tr>')
    if points.kyotaku_bonus:
        rows.append(f'<tr><td>{rb.html("供託のリーチ棒")}</td><td class="num">{_fmt(points.kyotaku_bonus)} 点</td></tr>')
    rows.append(f'<tr class="total"><td>和了者が受け取る合計</td><td class="num">{_fmt(points.total)} 点</td></tr>')
    parts = [f'<table class="mj-table">{"".join(rows)}</table>']
    if detail >= DETAIL_NORMAL:
        if result.ctx.is_tsumo:
            text = "ツモは 3 人で払う。親は子の 2 倍を払う（親がツモったときは、子 3 人が同じ額を払う）。"
        else:
            text = "ロンは、放銃した 1 人が全額を払う。ほかの 2 人は払わない。"
        parts.append(f'<div class="mj-sub">{rb.html(text)}</div>')
    return Section("payment", title, "".join(parts), heading)


def declaration_section(result: Explanation, rb: Rubifier, detail: int) -> Section:
    title, heading = _head(rb, "⑦ 卓での申告")
    parts = [f'<div class="mj-say">「{escape(result.declaration)}」</div>']
    if detail >= DETAIL_NORMAL:
        parts.append(
            '<div class="mj-sub">'
            + rb.html("発声（ロン／ツモ）→ 手牌を倒す → 役を数え上げる → 点数を言う、の順。点数は和了した人が申告する。")
            + "</div>"
        )
        if result.ctx.is_tsumo and not result.ctx.is_dealer:
            parts.append(f'<div class="mj-sub">{rb.html("子のツモは「子が払う点・親が払う点」の順に言う。")}</div>')
        if result.ctx.honba:
            parts.append(f'<div class="mj-sub">{rb.html("本場があるときは「○○は△△」と、上乗せした後の点も言う。")}</div>')
    return Section("say", title, "".join(parts), heading)


def rules_section(result: Explanation, rb: Rubifier) -> Section:
    title, heading = _head(rb, "ルールによって変わるところ")
    rows = "".join(f"<li>{rb.html(note)}</li>" for note in result.rule_notes)
    return Section("rules", title, f'<ul class="mj-rules">{rows}</ul>', heading)


# ---------------------------------------------------------------- まとめ


def library_only_section(result: Explanation, rb: Rubifier) -> Section:
    """自前の計算がライブラリと食い違ったとき。内訳は出さず、ライブラリの結果だけを見せる"""
    title, heading = _head(rb, "判定結果")
    verdict = result.judgement
    if not verdict.ok:
        text = "あがれない形" if verdict.error else ""
        return Section("library", title, f'<div class="mj-note">{rb.html(text)}</div>', heading)
    names = "・".join(YAKU[y.key].name for y in verdict.yaku)
    payment = f"{_fmt(verdict.main)} 点" if not result.ctx.is_tsumo else f"{_fmt(verdict.additional)} 点・{_fmt(verdict.main)} 点"
    html = (
        f'<div class="mj-note mj-bad">{rb.html("解説の計算と判定ライブラリの結果が一致しなかったため、内訳の表示を止めている。下は判定ライブラリの結果。")}</div>'
        f'<table class="mj-table"><tr><td>役</td><td>{rb.html(names)}</td></tr>'
        f'<tr><td>翻・符</td><td>{verdict.han} 翻 {verdict.fu} 符</td></tr>'
        f"<tr><td>支払い</td><td>{payment}</td></tr></table>"
    )
    return Section("library", title, html, heading)


def summary_section(result: Explanation, rb: Rubifier) -> Section:
    """いちばん上に置く、結果のまとめと手牌"""
    return Section("summary", "", summary_html(result, rb) + hand_html(result, rb))


def detail_sections(result: Explanation, rb: Rubifier, *, detail: int = DETAIL_FULL) -> list[Section]:
    """まとめのあとに続く解説（① 読み方 〜 ⑦ 申告）。

    ルビは「画面で最初に出てきたとき」に振る。まとめとこの解説のあいだに別の内容を置くページは、
    まとめ → あいだの内容 → この解説、の順に作る。
    """
    sections: list[Section] = []
    if not result.consistent:
        sections.append(library_only_section(result, rb))
        return sections
    if result.status is Status.NOT_WINNING:
        return sections
    sections.append(decomposition_section(result, rb, detail))
    sections.append(yaku_section(result, rb, detail))
    if result.status is Status.NO_YAKU:
        if result.dora.total:
            sections.append(dora_section(result, rb, detail))
    else:
        if detail >= DETAIL_NORMAL:
            sections.append(dora_section(result, rb, detail))
            sections.append(fu_section(result, rb, detail))
        sections.append(points_section(result, rb, detail))
        if detail >= DETAIL_NORMAL:
            sections.append(payment_section(result, rb, detail))
        sections.append(declaration_section(result, rb, detail))
    if result.rule_notes and detail >= DETAIL_NORMAL:
        sections.append(rules_section(result, rb))
    return sections


def explanation_sections(result: Explanation, *, detail: int = DETAIL_FULL, rb: Rubifier | None = None) -> list[Section]:
    """解説を、上から順に並べる部品の列にする（まとめ＋ ① 〜 ⑦）"""
    rb = rb or Rubifier()
    return [summary_section(result, rb), *detail_sections(result, rb, detail=detail)]

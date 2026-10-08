"""CPU との対局の画面に出す HTML づくり。

エンジンが計算した事実（局と試合の状態、コーチのおすすめと評価、守備の危険度と根拠、成績）を、そのまま図と表にする。
ここでは数値を計算し直さない。Streamlit にも依存しない（HTML の文字列を返すだけ）。
"""
from __future__ import annotations

from collections.abc import Sequence
from html import escape

from engine.analysis.waits import wait_kinds
from engine.defense import BASIS_NAMES, LEVEL_NAMES, Basis, TileDanger, reasons, summary
from engine.game import (
    END_NAMES,
    END_REASONS,
    HUMAN,
    NUM_PLAYERS,
    RIICHI_STICK,
    SEAT_NAMES,
    EndKind,
    Furiten,
    GameState,
    HandState,
    Move,
    Phase,
    Win,
    nine_kinds,
)
from engine.game_coach import FURITEN_SHORT, RiichiView, SafetyGrade, Stance, TurnAdvice, TurnDecision, YakuHint
from engine.game_records import (
    GOAL_DEAL_IN,
    GOAL_GAMES,
    GOAL_MISS_GAMES,
    GOAL_RANK,
    Graduation,
    Summary,
    Tally,
    rules_text,
)
from engine.rules import Rules
from engine.scoring.dora import dora_kind_of
from engine.scoring.explain import Explanation
from engine.scoring.texts import kind_text
from engine.tiles import HAKU, kind_of
from ui.practice_view import GRADE_CLASS, GRADE_ICONS, luck_text, percent, rounded
from ui.ruby import Rubifier
from ui.tile_view import kind_img, tile_img, tile_short_label
from ui.win_view import WIND_NAMES, tiles_fit_html

LEVEL_CLASS = ("lv0", "lv1", "lv2", "lv3", "lv4", "lv5")
#: この強さ以上のツキ補正で 1 位になったら、補正を下げると守備の練習になることを知らせる
STRONG_LUCK = 50
#: リーチをすすめるときの、リーチのボタンの文字（手牌の部品にも同じ文字を渡す）
MARK_RIICHI = "◎ リーチ"
#: 1 本場につき、あがった人が受け取る点（ロンなら放銃した人から 300 点、ツモなら 3 人から 100 点ずつ）
HONBA_POINTS = 300
CPU_NAMES = {"normal": "ふつう", "weak": "弱い"}
LENGTH_NAMES = {"east": "東風戦", "south": "半荘戦"}


def _small(tile: int, aka: bool) -> str:
    return tile_img(tile, aka=aka, cls="mj-s")


def _name(tile: int, aka: bool) -> str:
    return tile_short_label(tile, aka=aka)


def _pts(value: int) -> str:
    return f"{value:,}"


def _signed(value: int) -> str:
    return f"+{value:,}" if value > 0 else (f"−{-value:,}" if value < 0 else "±0")


def seat_label(hand: HandState, seat: int) -> str:
    """席の呼び方（自分から見た位置と、自風）。例：下家（南家）"""
    return f"{SEAT_NAMES[seat]}（{WIND_NAMES[hand.seat_wind(seat)]}家）"


def round_text(hand: HandState) -> str:
    start = hand.start
    return f"{WIND_NAMES[start.round_wind]} {start.round_number} 局"


# ---------------------------------------------------------------- 上の札と点数


def status_html(game: GameState, rb: Rubifier) -> str:
    """場（東 1 局など）・本場・供託・山の残り・ドラ・ツキ補正"""
    hand = game.current
    config = game.config
    aka = config.rules.aka_dora
    chips = [
        rb.html(f"{round_text(hand)}　{hand.start.honba} 本場"),
        rb.html(f"供託 {hand.kyotaku}"),
        rb.html(f"残り {hand.live_remaining} 枚"),
    ]
    html = "".join(f'<span class="mj-chip"><span>{chip}</span></span>' for chip in chips)
    luck, cpu = config.luck, config.cpu_luck
    # 札は 2 段に収める（3 段になると、手牌と「この牌を切る」が画面の下に押し出される）。
    # CPU にも補正があるときは、補正を 1 枚の札にまとめ、ドラの札を短くする
    compact = not cpu.is_off
    for indicator in hand.dora_indicators:
        dora = dora_kind_of(kind_of(indicator))
        lead = "ドラ " if compact else "ドラ表示牌 "
        arrow = "→" if compact else " → ドラ "
        html += (
            f'<span class="mj-chip mj-chip-tiles"><span>{lead}{_small(indicator, aka)}{arrow}'
            f"{kind_img(dora, cls='mj-s')} {escape(kind_text(dora))}</span></span>"
        )
    if compact:
        mine = "なし" if luck.is_off else f"{luck.deal}・{luck.draw}"
        text = f"ツキ補正：自分 {mine}／CPU {cpu.deal}・{cpu.draw}"
        html += f'<span class="mj-chip mj-chip-luck"><span>{rb.html(text)}</span></span>'
    else:
        off = " mj-chip-plain" if luck.is_off else " mj-chip-luck"
        html += f'<span class="mj-chip{off}"><span>{rb.html(luck_text(luck.deal, luck.draw))}</span></span>'
    return f'<div class="mj-chips mj-statusbar mj-status-fixed mj-game-status">{html}</div>'


def scores_html(game: GameState, rb: Rubifier, *, mark: int = 0) -> str:
    """4 人の点数（自分・下家・対面・上家の順）と、それぞれがいちばん最近に切った牌。

    手番の人と、リーチしている人に印を付ける。自分が最後に行動したあと（mark のあと）に切られた牌には、枠を付ける
    （CPU 3 人の動きが、手牌より上の、最初の画面の中で分かるように）。
    """
    hand = game.current
    aka = hand.rules.aka_dora
    active = None if hand.result is not None else hand.turn
    shown = hand.scores if hand.result is None else hand.result.scores      # 局が終わったら、精算のあとの持ち点
    new_from = discards_before(hand, mark) if mark else 10**9
    cells = []
    for seat in range(NUM_PLAYERS):
        player = hand.players[seat]
        wind = WIND_NAMES[hand.seat_wind(seat)]
        classes = ["mj-seat"]
        if seat == active:
            classes.append("mj-seat-turn")
        if seat == HUMAN:
            classes.append("mj-seat-me")
        riichi = '<span class="mj-seat-riichi">リーチ</span>' if player.in_riichi else ""
        dealer = '<span class="mj-seat-dealer">親</span>' if seat == hand.dealer else ""
        last = ""
        if player.river:
            discard = player.river[-1]
            cls = "mj-seat-tile" + (" mj-new" if discard.order >= new_from else "") + (" mj-tg" if discard.tsumogiri else "")
            last = tile_img(discard.tile, aka=aka, cls=cls)
        cells.append(
            f'<div class="{" ".join(classes)}"><div class="mj-seat-name">{rb.html(SEAT_NAMES[seat])} {escape(wind)}{dealer}</div>'
            f'<div class="mj-seat-score">{_pts(shown[seat])}</div>{riichi}{last}</div>'
        )
    rb.note("親")
    return f'<div class="mj-seats">{"".join(cells)}</div>'


# ---------------------------------------------------------------- ひとことの案内（手牌のすぐ上）


def _headline(inner: str, cls: str = "") -> str:
    """手牌のすぐ上の案内。高さは 2 行ぶんに固定してある（上の行は短く、下の行は 1 行に収め、はみ出したら「…」で切る）。
    行数が局面によって変わると、手牌の位置が上下して、押し間違いのもとになる"""
    classes = f"mj-headline mj-headline-game {cls}".strip()
    return f'<div class="{classes}"><div class="mj-headline-in">{inner}</div></div>'


def _two_lines(head: str, sub: str, rb: Rubifier) -> str:
    """上の行（HTML）と下の行（文。ルビを振る）"""
    return head + (f'<span class="mj-sub mj-headline-sub">{rb.html(sub)}</span>' if sub else "")


def plain_headline_html(text: str, rb: Rubifier) -> str:
    return _headline(f'<span class="mj-dimtext">{rb.html(text)}</span>')


def _threat_text(advice: TurnAdvice) -> str:
    """リーチしている人（1 人なら名前、2 人以上なら人数）"""
    if len(advice.threats) == 1:
        return f"{SEAT_NAMES[advice.threats[0].seat]}のリーチ"
    return f"{len(advice.threats)} 人がリーチ"


def advice_headline_html(advice: TurnAdvice, hand: HandState, rb: Rubifier, *, win: Explanation | None, can_nine: bool) -> str:
    """打つ前のヒント：おすすめの牌と、そのわけ（守備・リーチ判断を含む）。上の行に「何を切るか」、下の行に「なぜか」"""
    aka = hand.rules.aka_dora
    if win is not None and win.best is not None and win.best.points is not None:
        head = f'<b class="mj-stage">あがりの形です</b>　{rb.html("ツモで")} <b>{_pts(win.best.points.total)} 点</b>'
        return _headline(_two_lines(head, "・".join(win.spoken_yaku), rb), "good")
    pick = advice.pick
    what = f"{_small(pick, aka)} <b>{escape(_name(pick, aka))}</b> {rb.html('切り')}"
    analysis = advice.analysis
    if advice.stance is not Stance.FREE:
        level = advice.level_of[kind_of(pick)]
        safety = f"{LEVEL_NAMES[level]}・{_basis_word(advice, pick)}"
        if advice.stance is Stance.FOLD:
            head = f'<b class="mj-stage">{rb.html(_threat_text(advice))}</b>　{rb.html("オリる：")}{what}'
            sub = f"聴牌していないので守る。{safety}"
        else:
            verb = "リーチで押す：" if advice.recommend_riichi else "押す："
            head = f'<b class="mj-stage">{rb.html(_threat_text(advice))}</b>　{rb.html(verb)}{what}'
            sub = f"聴牌しているので押す。{safety}"
        return _headline(_two_lines(head, sub, rb), "soso")
    candidate = analysis.candidate(kind_of(pick))
    assert candidate is not None
    if candidate.shanten == 0 and candidate.total > 0:
        view = advice.riichi
        recommend = view is not None and view.can_riichi and view.recommend_riichi
        head = f'<b class="mj-stage">{rb.html("聴牌")}にとれます</b>　{rb.html("リーチで ") if recommend else ""}{what}'
        sub = f"待ち {candidate.kinds} 種 {candidate.total} 枚"
        if recommend:
            sub += f"・先に「{MARK_RIICHI}」を押す"
        elif view is not None and view.can_riichi:
            sub += "・ダマ（リーチしない）でもよい"
    else:
        stage = "聴牌" if candidate.shanten == 0 else f"{candidate.shanten} 向聴"
        head = f'<b class="mj-stage">{rb.html(stage)}</b>　おすすめ：{what}'
        sub = f"受け入れ {candidate.kinds} 種 {candidate.total} 枚" if candidate.total > 0 else "有効牌は残っていません"
        if can_nine:
            sub += "・九種九牌で流すこともできる"
    return _headline(_two_lines(head, sub, rb))


def _basis_short(advice: TurnAdvice, tile: int) -> str:
    row = next(r for r in advice.table if r.kind == kind_of(tile))
    return summary(row.worst)


#: 根拠の短い名前（案内の 1 行に収めるため。詳しい中身は、守備の表に出す）
BASIS_WORDS = {
    Basis.GENBUTSU: "現物",
    Basis.SUJI: "スジ",
    Basis.KABE: "壁",
    Basis.HALF_SUJI: "片スジ",
    Basis.NO_SUJI: "無スジ",
    Basis.HONOR: "字牌",
}


def _basis_word(advice: TurnAdvice, tile: int) -> str:
    row = next(r for r in advice.table if r.kind == kind_of(tile))
    return BASIS_WORDS[row.worst.basis]


def decision_headline_html(decision: TurnDecision, rb: Rubifier, *, aka: bool) -> str:
    """打った後の答え合わせ（上の行に評価、下の行におすすめ）"""
    cls, icon = _decision_mark(decision)
    tile = decision.action.tile
    assert tile is not None
    label = decision.verdict.label
    if decision.safety is not None and decision.advice.stance is Stance.FOLD:
        label = "いちばん安全な牌" if decision.safety.grade is SafetyGrade.SAFE else "もっと安全な牌があった"
    elif decision.skipped_riichi:
        label = "リーチしなかった"
    head = f'<span class="mj-icon {cls}">{icon}</span> {_small(tile, aka)} <b>{escape(_name(tile, aka))}</b> 切り：{rb.html(label)}'
    body = head
    if not decision.followed:
        pick = decision.advice.pick
        how = "「リーチ」して " if decision.advice.recommend_riichi else ""
        body += f'<span class="mj-sub mj-headline-sub">おすすめは {how}{_small(pick, aka)} {escape(_name(pick, aka))} 切り</span>'
    return _headline(body, cls)


def _decision_mark(decision: TurnDecision) -> tuple[str, str]:
    """評価の色と印。オリる局面では安全度で、それ以外は速さで決める"""
    safety = decision.safety
    if safety is not None and decision.advice.stance is Stance.FOLD:
        return ("good", "✓") if safety.grade is SafetyGrade.SAFE else ("bad", "✗")
    if decision.skipped_riichi:              # リーチをすすめたのに、ダマで切った
        return "soso", "△"
    if safety is not None and safety.grade is SafetyGrade.RISKY:
        return "soso", "△"
    grade = decision.verdict.grade
    return GRADE_CLASS[grade], GRADE_ICONS[grade]


def claim_headline_html(hand: HandState, explanation: Explanation | None, rb: Rubifier, *, bumped: bool) -> str:
    """ロンできる牌が出たとき"""
    aka = hand.rules.aka_dora
    last = hand.last_discard
    assert last is not None
    seat, discard = last
    head = f'<b class="mj-stage">ロンできます</b>　{escape(SEAT_NAMES[seat])}の {_small(discard.tile, aka)} <b>{escape(_name(discard.tile, aka))}</b>'
    if bumped:
        sub = "頭ハネ：先の順番の人だけがあがる（ロンしても無効）"
    elif explanation is not None and explanation.best is not None and explanation.best.points is not None:
        sub = f"ロンすると {_pts(explanation.best.points.total)} 点（{'・'.join(explanation.spoken_yaku)}）"
    else:
        sub = ""
    return _headline(_two_lines(head, sub, rb), "good")


# ---------------------------------------------------------------- CPU の打牌


def _discard_of(hand: HandState, seat: int, tile: int):
    return next((d for d in hand.players[seat].river if d.tile == tile), None)


def moves_since(hand: HandState, mark: int) -> list[tuple[int, str, int | None, bool]]:
    """自分が最後に行動したあとの動き。（席, 種類, 牌, ツモ切りか）の列。種類は discard・riichi・tsumo・ron・nine"""
    found = []
    for action in hand.actions[mark:]:
        if action.move in (Move.DISCARD, Move.RIICHI):
            assert action.tile is not None
            discard = _discard_of(hand, action.seat, action.tile)
            kind = "riichi" if action.move is Move.RIICHI else "discard"
            found.append((action.seat, kind, action.tile, bool(discard and discard.tsumogiri)))
        elif action.move in (Move.TSUMO, Move.RON, Move.NINE):
            kind = {Move.TSUMO: "tsumo", Move.RON: "ron", Move.NINE: "nine"}[action.move]
            found.append((action.seat, kind, None, False))
    return found


MOVE_WORDS = {"discard": "", "riichi": "リーチ", "tsumo": "ツモ！", "ron": "ロン！", "nine": "九種九牌"}


def moves_html(hand: HandState, mark: int, rb: Rubifier, *, limit: int = 6) -> str:
    """CPU の打牌（自分が最後に切ったあとの、ほかの人の動き）を 1 行に並べる"""
    moves = [m for m in moves_since(hand, mark) if m[0] != HUMAN or m[1] in ("tsumo", "ron")]
    if not moves:
        return ""
    aka = hand.rules.aka_dora
    hidden = max(0, len(moves) - limit)
    items = []
    for seat, kind, tile, tsumogiri in moves[hidden:]:
        word = MOVE_WORDS[kind]
        tile_html = _small(tile, aka) if tile is not None else ""
        if tile is not None and kind_of(tile) == HAKU:          # 白は無地の牌なので、小さい絵だけだと何も無いように見える
            tile_html += '<span class="mj-move-tg">白</span>'

        extra = '<span class="mj-move-tg">ツモ切り</span>' if tsumogiri and kind == "discard" else ""
        word_html = f'<b class="mj-move-word">{rb.html(word)}</b>' if word else ""
        items.append(f'<span class="mj-move"><span class="mj-move-who">{escape(SEAT_NAMES[seat])}</span>{word_html}{tile_html}{extra}</span>')
    lead = f'<span class="mj-sub">（その前の {hidden} 手は略）</span> ' if hidden else ""
    return f'<div class="mj-moves">{lead}{"<span class=mj-move-sep>→</span>".join(items)}</div>'


def _river_cells(hand: HandState, seat: int, *, new_from: int, aka: bool, upto: int | None = None) -> str:
    cells = []
    for discard in hand.players[seat].river:
        if upto is not None and discard.order > upto:
            break
        classes = []
        if discard.riichi:
            classes.append("mj-sideways")
        if discard.tsumogiri:
            classes.append("mj-tg")
        if discard.order >= new_from:
            classes.append("mj-new")
        cells.append(f"<span>{tile_img(discard.tile, aka=aka, cls=' '.join(classes))}</span>")
    return "".join(cells)


def discards_before(hand: HandState, mark: int) -> int:
    """mark より前の行動に含まれる打牌の数（それ以降に切られた牌に印を付ける）"""
    return sum(1 for action in hand.actions[:mark] if action.move in (Move.DISCARD, Move.RIICHI))


def table_html(hand: HandState, mark: int, rb: Rubifier) -> str:
    """4 人の河（下家・対面・上家・自分の順）。自分が最後に切ったあとに切られた牌に印を付ける"""
    aka = hand.rules.aka_dora
    new_from = discards_before(hand, mark) if mark else 10**9
    blocks = []
    for step in (1, 2, 3, 0):
        seat = (HUMAN + step) % NUM_PLAYERS
        player = hand.players[seat]
        mark_text = '<span class="mj-seat-riichi">リーチ</span>' if player.in_riichi else ""
        cells = _river_cells(hand, seat, new_from=new_from, aka=aka)
        river = f'<div class="mj-river mj-river-s">{cells}</div>' if cells else '<div class="mj-cap">まだ切っていません</div>'
        blocks.append(f'<div class="mj-riverbox"><div class="mj-cap">{rb.html(seat_label(hand, seat))} {mark_text}</div>{river}</div>')
    legend = "印の付いた牌：自分が切ったあとに切られた牌。横向き：リーチ宣言牌。薄い牌：ツモ切り" if mark else "横向き：リーチ宣言牌。薄い牌：ツモ切り"
    return f'<div class="mj-cap mj-river-cap">{rb.html("河（捨て牌）")}</div><div class="mj-table4">{"".join(blocks)}</div><div class="mj-sub">{rb.html(legend)}</div>'


def moves_each_html(hand: HandState, mark: int, rb: Rubifier) -> str:
    """CPU の打牌を 1 人ずつ（順番に、その人の河と一緒に）見せる"""
    aka = hand.rules.aka_dora
    count = discards_before(hand, mark)
    parts = []
    number = 0
    for seat, kind, tile, tsumogiri in moves_since(hand, mark):
        if seat == HUMAN and kind not in ("tsumo", "ron"):
            continue
        number += 1
        if tile is not None:
            discard = _discard_of(hand, seat, tile)
            order = discard.order if discard is not None else count
            how = "リーチ宣言牌" if kind == "riichi" else ("ツモ切り" if tsumogiri else "手出し")
            text = f"{seat_label(hand, seat)}：{_name(tile, aka)} を切った（{how}）"
            cells = _river_cells(hand, seat, new_from=order, aka=aka, upto=order)
            river = f'<div class="mj-river mj-river-s">{cells}</div>'
        else:
            text = f"{seat_label(hand, seat)}：{MOVE_WORDS[kind]}"
            river = ""
        parts.append(f'<div class="mj-step"><div class="mj-step-head"><span class="mj-guide-num">{number}</span> {rb.html(text)}</div>{river}</div>')
    if not parts:
        return ""
    return f'<div class="mj-steps-each">{"".join(parts)}</div>'


# ---------------------------------------------------------------- 見逃しの知らせ


def misses_html(hand: HandState, mark: int, rb: Rubifier) -> str:
    """自分のあがり牌が出たのに、ロンできなかったとき（役なし・フリテン）の知らせ。mark のあとの分だけ"""
    aka = hand.rules.aka_dora
    count = discards_before(hand, mark)
    lines = []
    for miss in hand.misses:
        if miss.seat != HUMAN or miss.passed:
            continue
        discard = _discard_of(hand, miss.from_seat, miss.tile)
        if discard is None or discard.order < count:
            continue
        what = f"{SEAT_NAMES[miss.from_seat]}の {_name(miss.tile, aka)} はあがり牌だったが、"
        if miss.check.furiten is not None:
            why = FURITEN_SHORT[miss.check.furiten] + "ので、ロンできなかった。"
            if miss.check.furiten is Furiten.RIVER:
                why += "フリテンでも、ツモならあがれる。"
        else:
            why = "役がないので、ロンできなかった（ツモなら門前清自摸和であがれる。リーチしていれば、ロンでもあがれた）。"
        follow = "このあと自分が切るまでは、ほかの人の捨て牌でもロンできない（同巡内フリテン）。"
        if hand.players[HUMAN].riichi_missed:
            follow = "リーチのあとなので、この局のあいだは、ロンできない（ツモならあがれる）。"
        lines.append(f'<div class="mj-alertnote">{rb.html(what + why + follow)}</div>')
    return "".join(lines)


def passed_html(hand: HandState, rb: Rubifier) -> str:
    """自分で見送ったロン（局の終わりに出す。リーチ中に見送ると、そのまま局が終わることがあるので、ここで知らせる）"""
    aka = hand.rules.aka_dora
    me = hand.players[HUMAN]
    riichi_order = me.river[me.riichi_at].order if me.riichi_at is not None and me.riichi_at < len(me.river) else None
    lines = []
    for miss in hand.misses:
        if miss.seat != HUMAN or not miss.passed:
            continue
        discard = _discard_of(hand, miss.from_seat, miss.tile)
        text = f"{SEAT_NAMES[miss.from_seat]}の {_name(miss.tile, aka)} で、ロンできたが見送った。"
        if riichi_order is not None and discard is not None and discard.order > riichi_order:
            text += "リーチのあとの見逃しなので、この局のあいだはロンできなくなった（ツモならあがれた）。"
        else:
            text += "そのあと自分が切るまでは、ほかの人の捨て牌でもロンできなかった（同巡内フリテン）。"
        lines.append(f'<div class="mj-alertnote">{rb.html(text)}</div>')
    return "".join(lines)


def furiten_note_html(hand: HandState, rb: Rubifier) -> str:
    """いま自分がフリテンなら、そのことを短く"""
    reason = hand.furiten(HUMAN)
    if reason is None:
        return ""
    return f'<div class="mj-alertnote">{rb.html("いまフリテン：" + FURITEN_SHORT[reason] + "。ロンはできないが、ツモならあがれる。")}</div>'


# ---------------------------------------------------------------- 守備


def danger_html(advice: TurnAdvice, rb: Rubifier, *, detail: bool, chosen_kind: int | None = None) -> str:
    """リーチを受けているときの、手牌の危険度と根拠（安全な順）。chosen_kind を渡すと、その牌に「切った」の印を付ける"""
    if not advice.table:
        return ""
    position = advice.analysis.position
    return danger_table_html(
        advice.table, position.tiles, rb, detail=detail, pick_kinds=(kind_of(advice.pick),), chosen_kind=chosen_kind,
        aka=position.rules.aka_dora, pick_note="◎ は、コーチのおすすめ（同じ危険度の中で、手に要らない牌）。",
    )


#: 根拠の名前の意味（守備の表を「ふつう」で出すとき、表に出てきた根拠だけを下に並べる）
BASIS_LEGEND = {
    Basis.GENBUTSU: "現物：リーチした人の河にある牌と、リーチのあとに誰かが切って通った牌。その人は、この牌ではロンできない（フリテン）。",
    Basis.SUJI: (
        "スジ：両面待ちは 3 つ離れた 2 種類（1・4、2・5、3・6、4・7、5・8、6・9）で待つ。片方が現物なら、もう片方はその両面では当たらない。"
        "4・5・6 は両側に両面があり、両側とも現物なら両スジ。"
    ),
    Basis.HALF_SUJI: "片スジ：4・5・6 で、片側だけがスジ。もう片側の両面には当たることがある。",
    Basis.KABE: "壁（ノーチャンス）：ある牌が 4 枚とも見えていると、それを使う両面は作れない（例：8萬が 4 枚見えていれば、9萬は 78萬の両面では当たらない）。",
    Basis.NO_SUJI: "無スジ：スジにも壁にも当たらない牌。両面待ちに当たることがある。",
    Basis.HONOR: "字牌：待ちは単騎と双碰だけ。見えている枚数が多いほど安全（見えていないのが 1 枚なら、単騎だけ）。",
}


def danger_table_html(
    table: Sequence[TileDanger],
    tiles: Sequence[int],
    rb: Rubifier,
    *,
    detail: bool,
    pick_kinds: Sequence[int] = (),
    chosen_kind: int | None = None,
    aka: bool = True,
    pick_note: str = "",
) -> str:
    """手牌の種類ごとの危険度と根拠の表（安全な順）。pick_kinds（おすすめ・正解）に ◎、chosen_kind に「切った」の印を付ける。

    同じ危険度の中では、◎ の牌を先に並べる（「上の行ほど安全」と読んでも、おすすめと食い違わないように）。
    """
    rows = []
    bases: set[Basis] = set()
    ordered = sorted(table, key=lambda r: (r.level, r.kind not in pick_kinds))      # sorted は安定なので、ほかの並びはそのまま
    for row in ordered:
        bases.update(danger.basis for danger in row.each)
        tile = next(t for t in tiles if kind_of(t) == row.kind)
        pick = "◎ " if row.kind in pick_kinds else ""
        if chosen_kind == row.kind:
            pick += '<span class="mj-badge mj-badge-you">切った</span> '
        each = []
        for danger in row.each:
            who = SEAT_NAMES[danger.seat]
            prefix = f"{who}に対して：" if len(row.each) > 1 else ""
            if detail:
                why = "".join(f"<li>{rb.html(line)}</li>" for line in reasons(danger, who))
                each.append(f'<div class="mj-sub">{rb.html(prefix + BASIS_NAMES[danger.basis])}</div><ul class="mj-danger-why">{why}</ul>')
            else:
                each.append(f'<div class="mj-sub">{rb.html(prefix + summary(danger))}</div>')      # 根拠の名前は、短い説明の中に入っている
        dora = '<span class="mj-badge">ドラ</span>' if row.dora else ""
        rows.append(
            f'<tr><td class="mj-danger-tile">{pick}{_small(tile, aka)}</td>'
            f'<td><span class="mj-level-chip {LEVEL_CLASS[row.level]}">{escape(row.name)}</span>{dora}{"".join(each)}</td></tr>'
        )
    note = (
        "危険度は、まだ当たりうる待ちの形から決めた目安（よく知られた安全度の順番）。確率の計算ではない。"
        "根拠（現物・スジ・壁・字牌の見えている枚数）は、見えている牌から確かめられる事実。" + pick_note
    )
    legend = ""
    if not detail:
        lines = [BASIS_LEGEND[basis] for basis in BASIS_LEGEND if basis in bases]
        if bases & {Basis.SUJI, Basis.HALF_SUJI, Basis.KABE, Basis.NO_SUJI}:
            lines.append("スジ・壁で防げるのは両面待ちだけ。嵌張・辺張・単騎・双碰には当たることがある。")
        legend = '<ul class="mj-danger-why">' + "".join(f"<li>{rb.html(line)}</li>" for line in lines) + "</ul>"
    return f'<table class="mj-table mj-danger">{"".join(rows)}</table>{legend}<div class="mj-sub">{rb.html(note)}</div>'


BETAORI_STEPS = (
    "リーチした人の現物（その人の河にある牌と、リーチのあとに誰かが切って通った牌）から切る。現物では、その人にロンされない。",
    "現物が無ければ、安全度の高い順に切る：字牌で見えていないのが少ない牌、スジ・壁の 1・9、スジの 2〜8 …。",
    "2 人以上がリーチしていたら、全員に安全な牌を選ぶ。",
    "オリると決めたら、聴牌は目指さない。あがりをあきらめて、放銃しないことを先にする（聴牌できたら、そのとき考え直す）。",
)


def betaori_html(rb: Rubifier) -> str:
    """ベタオリ（あがりをあきらめて、安全な牌だけを切る）の手順"""
    items = "".join(f"<li>{rb.html(step)}</li>" for step in BETAORI_STEPS)
    return f'<ol class="mj-steps">{items}</ol>'


# ---------------------------------------------------------------- リーチ判断


def _points_cell(value: int | None) -> str:
    return "役なし" if value is None else _pts(value)


def riichi_html(view: RiichiView, rb: Rubifier, *, aka: bool) -> str:
    """リーチとダマ（黙聴）の比べ方：待ちごとの残り枚数・形・点数"""
    rows = []
    for wait in view.waits:
        tile = f"<td>{kind_img(wait.kind, cls='mj-s')} {escape(kind_text(wait.kind))}</td><td class='num'>{wait.remaining} 枚</td>"
        if wait.remaining == 0:          # 残っていない待ち牌では、あがれない（点数は出さない）
            rows.append(f"<tr>{tile}<td>{rb.html(wait.shape)}</td><td class='num' colspan='2'>{rb.html('残りなし（あがれない）')}</td></tr>")
            continue
        rows.append(
            f"<tr>{tile}<td>{rb.html(wait.shape)}</td>"
            f"<td class='num'>{_points_cell(wait.dama_ron)}<br><span class='mj-sub'>{_points_cell(wait.dama_tsumo)}</span></td>"
            f"<td class='num'>{_points_cell(wait.riichi_ron)}<br><span class='mj-sub'>{_points_cell(wait.riichi_tsumo)}</span></td></tr>"
        )
    head = (
        f"<tr><td>{rb.html('待ち')}</td><td class='num'>残り</td><td>形</td>"
        f"<td class='num'>{rb.html('ダマ')}<br><span class='mj-sub'>ロン／ツモ</span></td>"
        f"<td class='num'>リーチ<br><span class='mj-sub'>ロン／ツモ</span></td></tr>"
    )
    lead = f"{_name(view.tile, aka)} を切ると聴牌。待ちは {view.kinds} 種 {view.live} 枚。"
    note = "点数は、あがった人が受け取る点（本場・供託・裏ドラ・一発は入れていない）。上の段がロン、下の段がツモ。"
    return (
        f'<div class="mj-note">{rb.html(lead)}</div><table class="mj-table mj-riichi-table">{head}{"".join(rows)}</table>'
        f'<div class="mj-note">{rb.html(view.advice)}</div><div class="mj-sub">{rb.html(note)}</div>'
    )


# ---------------------------------------------------------------- 役の候補


def yaku_hints_html(hints: Sequence[YakuHint], hand: HandState, rb: Rubifier) -> str:
    """見えている役の候補と、そのために切る牌・足りない牌"""
    if not hints:
        return f'<div class="mj-sub">{rb.html("いまの手から近い役の候補はありません。速さ（受け入れ）を優先して、聴牌したらリーチ。")}</div>'
    items = []
    for hint in hints:
        if hint.distance == 0:
            head = f"{hint.name}：その役の聴牌"
        else:
            head = f"{hint.name}：その役の聴牌まで、あと {hint.distance} 枚"
        spare = " ".join(kind_img(k, cls="mj-s") for k in hint.spare)
        need = " ".join(kind_img(k, cls="mj-s") for k in hint.need[:8])
        lines = f'<div class="mj-hint-head">{rb.html(head)}</div>'
        if spare:
            lines += f'<div class="mj-sub">{rb.html("その役の形に入らない牌（切る候補）")}：<span class="mj-inline">{spare}</span></div>'
        if need:
            lines += f'<div class="mj-sub">{rb.html("足りない牌")}：<span class="mj-inline">{need}</span></div>'
        items.append(f'<div class="mj-hint">{lines}</div>')
    note = "役の候補は、いまの手牌からいちばん近い形を数えたもの。実際に役が付くかは、あがったときの点数計算で決まる。"
    return "".join(items) + f'<div class="mj-sub">{rb.html(note)}</div>'


# ---------------------------------------------------------------- 打牌の評価


def decision_html(decision: TurnDecision, rb: Rubifier, *, detail: bool, aka: bool) -> str:
    """前の打牌の評価（速さ・守備・事故防止の注意）"""
    cls, icon = _decision_mark(decision)
    tile = decision.action.tile
    assert tile is not None
    head = f'<div class="mj-review-head"><span class="mj-icon {cls}">{icon}</span> {rb.html(f"{decision.number} 巡目の打牌")} {_small(tile, aka)}</div>'
    body = ""
    if decision.safety is not None:
        body += f"<div>{rb.html(decision.safety.text)}</div>"
        if decision.advice.stance is Stance.FOLD:
            body += f'<div class="mj-sub">{rb.html("速さだけで見ると：" + decision.verdict.label)}</div>'
        else:
            body += f"<div>{rb.html(decision.verdict.text)}</div>"
    else:
        body += f"<div>{rb.html(decision.verdict.text)}</div>"
    extras = list(decision.notes)
    if detail:
        extras.extend(decision.verdict.reasons)
    if extras:
        body += "<ul>" + "".join(f"<li>{rb.html(line)}</li>" for line in extras) + "</ul>"
    return f'<div class="mj-review {cls}">{head}{body}</div>'


def review_list_html(decisions: Sequence[TurnDecision], rb: Rubifier, *, aka: bool) -> str:
    """この局の打牌の振り返り（1 打牌 1 行）"""
    if not decisions:
        return f'<div class="mj-sub">{rb.html("この局で、自分で選んだ打牌はありません。")}</div>'
    rows = []
    for decision in decisions:
        cls, icon = _decision_mark(decision)
        tile = decision.action.tile
        assert tile is not None
        pick = decision.advice.pick
        how = "リーチ＋" if decision.advice.recommend_riichi else ""
        better = "" if decision.followed else f"おすすめ {how}{_small(pick, aka)}"
        label = decision.safety.text if decision.safety is not None and decision.advice.stance is Stance.FOLD else decision.verdict.label
        if decision.skipped_riichi:
            label = "リーチしなかった（リーチをすすめる聴牌）"
        rows.append(
            f'<tr><td class="num">{decision.number}</td><td><span class="mj-icon {cls}">{icon}</span> {_small(tile, aka)}</td>'
            f"<td>{rb.html(label)}{('<br>' + better) if better else ''}</td></tr>"
        )
    return f'<table class="mj-table mj-reviewlist">{"".join(rows)}</table>'


# ---------------------------------------------------------------- 局の終わり


def result_banner_html(game: GameState, rb: Rubifier) -> str:
    """局の結果（誰がどうあがったか／流局の種類）と、点の動き"""
    hand = game.current
    result = hand.result
    assert result is not None
    if result.kind.is_win:
        lines = []
        for win in result.wins:
            who = seat_label(hand, win.seat)
            how = "ツモ" if win.from_seat is None else f"ロン（{SEAT_NAMES[win.from_seat]}から）"
            lines.append(f'<div class="mj-big">{rb.html(f"{who}の{how}")}</div><div class="mj-note">{rb.html(gain_text(win))}</div>')
        if result.bumped:
            names = "・".join(SEAT_NAMES[s] for s in result.bumped)
            lines.append(f'<div class="mj-sub">{rb.html(f"{names}もロンしたが、頭ハネで無効になった。")}</div>')
        if len(result.wins) > 1:
            lines.append(f'<div class="mj-sub">{rb.html("複数ロン：本場と供託は、捨てた人から見て順番が先の人がもらう（上家取り）。")}</div>')
        cls = "good" if any(w.seat == HUMAN for w in result.wins) else ("bad" if any(w.from_seat == HUMAN for w in result.wins) else "")
        banner = f'<div class="mj-card mj-result-card {cls}">{"".join(lines)}</div>'
    elif result.kind is EndKind.EXHAUSTED:
        tenpai = [SEAT_NAMES[s] for s in range(NUM_PLAYERS) if result.tenpai[s]]
        text = "聴牌：" + "・".join(tenpai) if tenpai else "全員ノーテン"
        lines = [f'<div class="mj-big">{rb.html("流局")}</div><div class="mj-note">{rb.html(text)}</div>']
        if result.nagashi:
            names = "・".join(SEAT_NAMES[s] for s in result.nagashi)
            lines.append(f'<div class="mj-note">{rb.html(f"流し満貫：{names}（満貫のツモと同じ点。ノーテン罰符の精算はしない）")}</div>')
        elif 0 < len(tenpai) < NUM_PLAYERS:
            lines.append(f'<div class="mj-sub">{rb.html("聴牌していない人から、聴牌の人へ、合わせて 3000 点（ノーテン罰符）。")}</div>')
        banner = f'<div class="mj-card mj-result-card">{"".join(lines)}</div>'
    else:
        name = END_NAMES[result.kind]
        explain_text = {
            EndKind.NINE_TERMINALS: f"{SEAT_NAMES[result.caller] if result.caller is not None else ''}が、最初のツモで么九牌 9 種類以上の手を見せて、流した。",
            EndKind.FOUR_WINDS: "最初の 1 巡で、4 人が同じ風牌を切った。",
            EndKind.FOUR_RIICHI: "4 人のリーチが成立した。",
        }[result.kind]
        moved = "リーチ棒のほかは、点の動きは無く" if any(p.riichi_paid for p in hand.players) else "点の動きは無く"
        banner = (
            f'<div class="mj-card mj-result-card"><div class="mj-big">{rb.html(f"途中流局（{name}）")}</div>'
            f'<div class="mj-sub">{rb.html(f"{explain_text}{moved}、親が続ける（本場が 1 つ増える）。")}</div></div>'
        )
    return banner + settlement_html(hand, rb)


def gain_text(win: Win) -> str:
    """あがった人が受け取った点と、その内訳（あがりの点・本場・供託）"""
    gain = win.payments[win.seat]
    honba = HONBA_POINTS * win.ctx.honba
    kyotaku = RIICHI_STICK * win.ctx.kyotaku
    parts = [f"本場 {_pts(honba)}"] if honba else []
    if kyotaku:
        parts.append(f"供託 {_pts(kyotaku)}")
    if not parts:
        return f"{_pts(gain)} 点"
    return f"{_pts(gain)} 点（あがり {_pts(gain - honba - kyotaku)} ＋ {' ＋ '.join(parts)}）"


def settlement_html(hand: HandState, rb: Rubifier) -> str:
    """局の始めと終わりの持ち点（リーチ棒の支払いを含む）"""
    result = hand.result
    assert result is not None
    rows = []
    for step in range(NUM_PLAYERS):
        seat = (HUMAN + step) % NUM_PLAYERS
        before = hand.start.scores[seat]
        after = result.scores[seat]
        stick = '<br><span class="mj-sub">リーチ棒 −1,000</span>' if hand.players[seat].riichi_paid else ""
        rows.append(
            f'<tr><td>{rb.html(seat_label(hand, seat))}</td><td class="num">{_pts(before)} → <b>{_pts(after)}</b></td>'
            f'<td class="num">{_signed(after - before)}{stick}</td></tr>'
        )
    tail = ""
    if result.kyotaku:
        tail = f'<div class="mj-sub">{rb.html(f"卓に残った供託（リーチ棒 {result.kyotaku} 本）は、次にあがった人がもらう。")}</div>'
    return f'<table class="mj-table mj-settle">{"".join(rows)}</table>{tail}'


def reveal_html(hand: HandState, rb: Rubifier) -> str:
    """全員の手牌と待ち、河（「この河で、この待ちだった」を振り返る）"""
    aka = hand.rules.aka_dora
    result = hand.result
    winners = {w.seat: w for w in result.wins} if result is not None else {}
    blocks = []
    for step in (1, 2, 3, 0):
        seat = (HUMAN + step) % NUM_PLAYERS
        player = hand.players[seat]
        win = winners.get(seat)
        if win is not None:
            tiles = list(win.ctx.closed_tiles)
            tiles.remove(win.ctx.win_tile)
            shown = tiles_fit_html([*sorted(tiles, key=lambda t: (kind_of(t), t)), win.ctx.win_tile], aka=aka, max_px=26,
                                   win_tile=win.ctx.win_tile, gap_before_last=True)
            state = "あがり"
        elif result is not None and result.kind is EndKind.NINE_TERMINALS and result.caller == seat:
            # 九種九牌で流した人は、ツモ牌を含む 14 枚を見せる
            shown = tiles_fit_html(sorted(player.tiles, key=lambda t: (kind_of(t), t)), aka=aka, max_px=26)
            state = f"九種九牌（么九牌 {nine_kinds(player.tiles)} 種類）"
        else:
            shown = tiles_fit_html(list(player.hand), aka=aka, max_px=26)
            waits = wait_kinds(player.hand)
            state = ("聴牌・待ち " + "・".join(kind_text(k) for k in waits)) if waits else "ノーテン"
        riichi = "・リーチ" if player.riichi_paid else ""
        cells = _river_cells(hand, seat, new_from=10**9, aka=aka)
        river = f'<div class="mj-river mj-river-s">{cells}</div>' if cells else ""
        blocks.append(
            f'<div class="mj-reveal"><div class="mj-cap">{rb.html(f"{seat_label(hand, seat)}　{state}{riichi}")}</div>'
            f'<div class="mj-hand">{shown}</div>{river}</div>'
        )
    return "".join(blocks)


# ---------------------------------------------------------------- 試合の終わり


def final_html(game: GameState, tally: Tally, rb: Rubifier) -> str:
    """試合の結果（順位と最後の持ち点）と、この試合の自分の成績"""
    result = game.result
    assert result is not None
    order = game.rank_order(result.scores)
    rows = []
    for rank, seat in enumerate(order, start=1):
        me = " mj-skill" if seat == HUMAN else ""
        rows.append(f'<tr class="{me.strip()}"><td class="num">{rank} 位</td><td>{escape(SEAT_NAMES[seat])}</td><td class="num">{_pts(result.scores[seat])}</td></tr>')
    lines = [f'<div class="mj-big">{rb.html(f"対局終了：{result.ranks[HUMAN]} 位")}</div>']
    lines.append(f'<div class="mj-sub">{rb.html(END_REASONS[result.reason])}</div>')
    if result.kyotaku_to is not None:
        lines.append(f'<div class="mj-sub">{rb.html(f"卓に残っていたリーチ棒は、1 位の{SEAT_NAMES[result.kyotaku_to]}がもらった。")}</div>')
    if result.ranks[HUMAN] == 1 and max(game.config.luck.deal, game.config.luck.draw) >= STRONG_LUCK:
        lines.append(
            f'<div class="mj-sub">{rb.html("ツキ補正が強いと、CPU のリーチを受ける前にあがれることが多い。守備（オリ）を練習するなら、設定で補正を下げてみよう。")}</div>'
        )
    stats = _game_stats(game, tally)
    return (
        f'<div class="mj-card mj-result-card">{"".join(lines)}</div>'
        f'<table class="mj-table mj-stats">{"".join(rows)}</table>'
        f'<div class="mj-note">{rb.html(stats)}</div>'
    )


def _game_stats(game: GameState, tally: Tally) -> str:
    hands = len(game.hands)
    wins = deal_ins = riichi = 0
    for hand in game.hands:
        result = hand.result
        if result is None:
            continue
        wins += any(w.seat == HUMAN for w in result.wins)
        deal_ins += result.kind is EndKind.RON and any(w.from_seat == HUMAN for w in result.wins)
        riichi += hand.players[HUMAN].riichi_paid
    text = f"{hands} 局：あがり {wins} 回・放銃 {deal_ins} 回・リーチ {riichi} 回。"
    if tally.decisions:
        text += f"おすすめと同じ牌を切った割合 {percent(tally.followed / tally.decisions)}（{tally.decisions} 回中 {tally.followed} 回）。"
    if tally.defense:
        text += f"オリる局面で、いちばん安全な牌を切れた割合 {percent(tally.safe / tally.defense)}。"
    return text


# ---------------------------------------------------------------- 成績


def _condition(summary_row: Summary) -> str:
    luck = luck_text(summary_row.deal, summary_row.draw).replace("ツキ補正：", "補正 ")
    cpu = f"CPU {CPU_NAMES.get(summary_row.cpu_level, summary_row.cpu_level)}"
    if summary_row.cpu_deal or summary_row.cpu_draw:
        cpu += f"（補正 {summary_row.cpu_deal}・{summary_row.cpu_draw}）"
    hint = "・ヒントあり" if summary_row.hinted else ""
    return f"{LENGTH_NAMES.get(summary_row.length, summary_row.length)}・{cpu}・{luck}{hint}"


def stats_html(summaries: Sequence[Summary], grad: Graduation, rb: Rubifier) -> str:
    """成績（条件ごと）と、卒業の目安"""
    parts = [graduation_html(grad, rb)]
    if not summaries:
        parts.append(f'<div class="mj-sub">{rb.html("まだ、終わった対局がありません（最後まで打った対局だけを数えます）。")}</div>')
        return "".join(parts)
    rows = []
    for row in summaries:
        skill = row.plain
        label = ("実力　" if skill else "") + _condition(row)
        follow = "" if row.follow_rate is None else f"・おすすめ一致 {percent(row.follow_rate)}"
        rows.append(
            f'<tr class="{"mj-skill" if skill else ""}"><td>{rb.html(label)}<br><span class="mj-sub">'
            f'{row.games} 戦・平均順位 {rounded(row.average_rank, 2)}・1 位 {row.ranks[0]} 回</span></td>'
            f'<td class="num">{rb.html(f"和了率 {percent(row.win_rate)}")}<br>{rb.html(f"放銃率 {percent(row.deal_in_rate)}")}'
            f'<br><span class="mj-sub">平均 {_pts(round(row.average_score))} 点{follow}</span></td></tr>'
        )
    parts.append(f'<table class="mj-table mj-stats">{"".join(rows)}</table>')
    parts.append(f'<div class="mj-sub">{rb.html("「実力」は、ツキ補正 0（自分も CPU も）で、打つ前のヒントを見ずに打った対局だけ。和了率・放銃率は、局の数で割ったもの。")}</div>')
    return "".join(parts)


def graduation_html(grad: Graduation, rb: Rubifier) -> str:
    """卒業の目安（補正 0・CPU ふつう・ヒントなしの東風戦）の進み具合"""
    head = f"卒業の目安：補正 0・CPU ふつう・ヒントなしの東風戦を {GOAL_GAMES} 回"
    if grad.games == 0:
        body = "まだ数えられる対局がありません（補正を 0 にして、打つ前のヒントをオフにした東風戦が対象）。"
        return f'<div class="mj-lesson"><b>{rb.html(head)}</b><br>{rb.html(body)}</div>'
    rank = "—" if grad.average_rank is None else rounded(grad.average_rank, 2)
    deal_in = "—" if grad.deal_in_rate is None else percent(grad.deal_in_rate)
    lines = [
        f"対局数：{grad.games} / {GOAL_GAMES}（{'達成' if grad.enough else f'あと {GOAL_GAMES - grad.games} 回'}）",
        f"平均順位：{rank}（目標 {GOAL_RANK} 以下：{'達成' if grad.rank_ok else 'まだ'}）",
        f"放銃率：{deal_in}（目標 {percent(GOAL_DEAL_IN)} 以下：{'達成' if grad.deal_in_ok else 'まだ'}）",
    ]
    if grad.games < GOAL_MISS_GAMES:
        misses = f"{GOAL_MISS_GAMES} 戦そろったら判定"
    else:
        misses = "達成" if grad.misses_ok else "まだ"
    lines.append(f"役なし・フリテンの見落とし（直近 {GOAL_MISS_GAMES} 戦）：{grad.recent_misses} 回（目標 0 回：{misses}）")
    if grad.passed:
        lines.append("すべての目標を達成した。")
    body = "".join(f"<li>{rb.html(line)}</li>" for line in lines)
    note = "平均順位と放銃率は、数えた対局ぜんぶ（いまのところの値）。対局数が目標に届いたところで、そろって達成なら卒業の目安を満たす。"
    return f'<div class="mj-lesson"><b>{rb.html(head)}</b><ul class="mj-rules">{body}</ul><div class="mj-sub">{rb.html(note)}</div></div>'


def config_text(game: GameState) -> str:
    """いまの対局の条件（画面のいちばん下に出す）。初期値と違うルールがあれば、それも書く"""
    config = game.config
    words = [LENGTH_NAMES[config.length.value], f"CPU {CPU_NAMES[config.cpu_level.value]}"]
    default = Rules().to_dict()
    changed = [(name, value) for name, value in config.rules.to_dict().items() if default.get(name) != value]
    if changed:
        words.append(rules_text(changed))
    return "・".join(words)


# ---------------------------------------------------------------- 使い方


HELP_ITEMS = (
    ("流れ", "親から順に、ツモって 1 枚切る。自分が切ると、CPU 3 人の打牌がまとめて進み、また自分の番になる。"
     "CPU の打牌は手牌のすぐ下に 1 行で出る。河では、自分が切ったあとに切られた牌に印が付く。"),
    ("切る・リーチ・ツモ", "一人練習と同じ。牌をタップして選び、「この牌を切る」。聴牌にとれるときは「リーチ」、あがれるときは「ツモ（あがる）」が出る。"
     "リーチのあとのツモ切りは自動で進み、あがり牌を引いたら止まるので、「ツモ（あがる）」を押す。"),
    ("ロン", "ほかの人の捨て牌であがれるとき、手牌の下に「ロン」と「見送る」が出る。ロンできない牌（役なし・フリテン）では出ない（誤ロンにならない）。"
     "見送ると、自分が次に切るまでロンできない（リーチのあとなら、その局のあいだずっと）。"
     "あがり牌なのにロンできなかったときは、その理由を知らせる。"),
    ("守備", "誰かがリーチすると、手牌の危険度と根拠（現物・スジ・壁・字牌の見えている枚数）の表が出る。聴牌していなければ、コーチはオリ（ベタオリ）をすすめる。"),
    ("リーチ判断", "聴牌にとれるとき、リーチとダマ（リーチしない）を、役の有無・待ちの形と残り枚数・点数で比べた表が出る。"),
    ("局の終わり", "全員の手牌と待ちを公開する。あがった手は、点数計算の全過程を見られる。"),
    ("対局の終わり", "東風戦（東 1〜4 局）か半荘戦。最後まで打った対局だけを成績に入れる。決まりは雀魂の段位戦に合わせてある（ルールの違いのページも見てください）。"),
)


def help_html(rb: Rubifier) -> str:
    items = "".join(f"<li><b>{rb.html(title)}</b>：{rb.html(text)}</li>" for title, text in HELP_ITEMS)
    return f'<ul class="mj-rules">{items}</ul>'


def phase_text(hand: HandState) -> str:
    """いまの局の進み具合（画面の下の補足に出す）"""
    if hand.result is not None:
        return "局の終わり"
    if hand.phase is Phase.CLAIM:
        return "ロンの返事待ち"
    return f"{SEAT_NAMES[hand.turn]}の番"

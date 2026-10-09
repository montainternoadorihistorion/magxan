"""CPU との対局の画面に出す HTML づくり。

エンジンが計算した事実（局と試合の状態、コーチのおすすめと評価、守備の危険度と根拠、成績）を、そのまま図と表にする。
ここでは数値を計算し直さない。Streamlit にも依存しない（HTML の文字列を返すだけ）。
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from html import escape

from engine.analysis.waits import wait_kinds
from engine.call_coach import CallAdvice, CallDecision, CallGrade, CallOption, YakuStatus, call_name
from engine.defense import BASIS_NAMES, LEVEL_NAMES, Basis, TileDanger, reasons, summary
from engine.game import (
    END_NAMES,
    END_REASONS,
    HUMAN,
    NUM_PLAYERS,
    RIICHI_STICK,
    SEAT_NAMES,
    Action,
    EndKind,
    Furiten,
    Furo,
    GameState,
    HandState,
    Move,
    Phase,
    Win,
    nine_kinds,
)
from engine.game_coach import (
    FURITEN_SHORT,
    KanAdvice,
    RiichiView,
    SafetyGrade,
    Stance,
    TurnAdvice,
    TurnDecision,
    YakuHint,
    formal_tenpai,
)
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
from engine.kifu import Note
from engine.melds import MeldType, display_order
from engine.rules import Rules
from engine.scoring.dora import dora_kind_of
from engine.scoring.explain import Explanation
from engine.scoring.texts import kind_text
from engine.tiles import HAKU, kind_of
from ui.practice_view import GRADE_CLASS, GRADE_ICONS, luck_text, percent, rounded
from ui.ruby import Rubifier
from ui.tile_view import back_img, kind_img, tile_img, tile_short_label
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


def hand_title(hand: HandState) -> str:
    """局の呼び方（牌譜の局を選ぶとき）。例：東 1 局 0 本場（下家の和了）"""
    result = hand.result
    if result is None:
        tail = "打っている局"
    elif result.kind.is_win:
        tail = "・".join(f"{SEAT_NAMES[w.seat]}の{'ツモ' if w.from_seat is None else 'ロン'}" for w in result.wins)
    else:
        tail = END_NAMES[result.kind]
    return f"{round_text(hand)} {hand.start.honba} 本場（{tail}）"


# ---------------------------------------------------------------- 上の札と点数


def status_html(game: GameState, rb: Rubifier, *, auto: bool = False) -> str:
    """場（東 1 局など）・本場・供託・山の残り・ドラ・ツキ補正。auto は、自分の補正が、おまかせで決まったものか"""
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
    indicators = hand.dora_indicators
    if len(indicators) == 1:
        indicator = indicators[0]
        dora = dora_kind_of(kind_of(indicator))
        lead = "ドラ " if compact else "ドラ表示牌 "
        arrow = "→" if compact else " → ドラ "
        html += (
            f'<span class="mj-chip mj-chip-tiles"><span>{lead}{_small(indicator, aka)}{arrow}'
            f"{kind_img(dora, cls='mj-s')} {escape(kind_text(dora))}</span></span>"
        )
    else:
        # カンでドラが増えたら、ドラそのものだけを 1 枚の札に並べる（札が 3 段にならないように）
        doras = "".join(kind_img(dora_kind_of(kind_of(t)), cls="mj-s") for t in indicators)
        names = "・".join(kind_text(dora_kind_of(kind_of(t))) for t in indicators)
        html += f'<span class="mj-chip mj-chip-tiles" title="{escape("ドラ：" + names)}"><span>ドラ {doras}</span></span>'
    if compact:
        mine = ("なし" if luck.is_off else f"{luck.deal}・{luck.draw}") + ("（おまかせ）" if auto else "")
        text = f"ツキ補正：自分 {mine}／CPU {cpu.deal}・{cpu.draw}"
        html += f'<span class="mj-chip mj-chip-luck"><span>{rb.html(text)}</span></span>'
    else:
        off = " mj-chip-plain" if luck.is_off else " mj-chip-luck"
        html += f'<span class="mj-chip{off}"><span>{rb.html(luck_text(luck.deal, luck.draw, auto=auto))}</span></span>'
    return f'<div class="mj-chips mj-statusbar mj-status-fixed mj-game-status">{html}</div>'


def scores_html(game: GameState, rb: Rubifier, *, mark: int = 0, settled: bool = True) -> str:
    """4 人の点数（自分・下家・対面・上家の順）と、それぞれがいちばん最近に切った牌。

    手番の人と、リーチしている人に印を付ける。自分が最後に行動したあと（mark のあと）に切られた牌には、枠を付ける
    （CPU 3 人の動きが、手牌より上の、最初の画面の中で分かるように）。
    settled が偽なら、局が終わっていても、精算の前の持ち点を出す（あがった点を申告してもらうあいだ、答えを見せないため）。
    """
    hand = game.current
    aka = hand.rules.aka_dora
    active = None if hand.result is not None else hand.turn
    shown = hand.scores if hand.result is None or not settled else hand.result.scores      # 局が終わったら、精算のあとの持ち点
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
        # 鳴いた数（暗槓は数えない）。リーチの印と同じ場所に出す（鳴いた人はリーチできないので、重ならない）
        opened = sum(1 for f in player.furo if f.from_seat is not None)
        naki = f'<span class="mj-seat-naki">鳴き {opened}</span>' if opened else ""
        dealer = '<span class="mj-seat-dealer">親</span>' if seat == hand.dealer else ""
        last = ""
        if player.river:
            discard = player.river[-1]
            cls = "mj-seat-tile" + (" mj-new" if discard.order >= new_from else "") + (" mj-tg" if discard.tsumogiri else "")
            if discard.called_by is not None:
                cls += " mj-called"                     # 鳴かれた牌（河と同じく、とても薄くする）
            last = tile_img(discard.tile, aka=aka, cls=cls)
        cells.append(
            f'<div class="{" ".join(classes)}"><div class="mj-seat-name">{rb.html(SEAT_NAMES[seat])} {escape(wind)}{dealer}</div>'
            f'<div class="mj-seat-score">{_pts(shown[seat])}</div>{riichi}{naki}{last}</div>'
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
            why = "あがれない聴牌（役が無い）なので守る" if analysis.pick.shanten == 0 else "聴牌していないので守る"
            sub = f"{why}。{safety}"
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
        if advice.fastest is not None:
            # 鳴いた手で、役のある聴牌をすすめた。待ちの広い聴牌もあるが、役が無い
            sub += f"・{_name(advice.fastest, aka)} 切りは役なし"
        elif advice.keeps_yaku:
            sub += f"・{advice.kept_yaku or '役'}を残す"
        if recommend:
            sub += f"・先に「{MARK_RIICHI}」を押す"
        elif view is not None and view.can_riichi:
            sub += "・ダマ（リーチしない）でもよい"
    else:
        stage = "聴牌" if candidate.shanten == 0 else f"{candidate.shanten} 向聴"
        head = f'<b class="mj-stage">{rb.html(stage)}</b>　おすすめ：{what}'
        sub = f"受け入れ {candidate.kinds} 種 {candidate.total} 枚" if candidate.total > 0 else "有効牌は残っていません"
        if advice.fastest is not None:
            # 鳴いた手で、役を残すために、速さだけの牌とは違う牌をすすめた（向聴数が同じなら、受け入れの差を書く）
            fast = analysis.candidate(kind_of(advice.fastest))
            if fast is None:
                more = ""
            elif fast.shanten < candidate.shanten:
                more = "で聴牌" if fast.shanten == 0 else f"で {fast.shanten} 向聴"
            else:
                more = f"：受け入れ {fast.total - candidate.total} 枚多い"
            sub = f"{advice.kept_yaku or '役'}を残す（速さだけなら {_name(advice.fastest, aka)} 切り{more}）"
        elif advice.keeps_yaku:
            # 速さが同じ牌の中から、役を残せる牌を選んだ
            sub += f"・{advice.kept_yaku or '役'}を残す"
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


def decision_label(decision: TurnDecision, *, detailed: bool = False) -> str:
    """打牌の評価の短い呼び方（案内・振り返りの一覧・牌譜で同じものを使う）。detailed なら、かっこ書きの説明も付ける"""
    safety = decision.safety
    if safety is not None and decision.advice.stance is Stance.FOLD:
        if detailed:
            return safety.text
        return "いちばん安全な牌" if safety.grade is SafetyGrade.SAFE else "もっと安全な牌があった"
    if decision.skipped_riichi:
        return "リーチしなかった（リーチをすすめる聴牌）" if detailed else "リーチしなかった"
    if decision.lost_yaku:
        return "役が見えなくなった（鳴いた手は、役が無いとあがれない）" if detailed else "役が見えなくなった"
    if decision.yaku_detour:
        return "役が遠のいた（役まで遠回りになる）" if detailed else "役が遠のいた"
    return decision.verdict.label


def decision_headline_html(decision: TurnDecision, rb: Rubifier, *, aka: bool) -> str:
    """打った後の答え合わせ（上の行に評価、下の行におすすめ）"""
    cls, icon = _decision_mark(decision)
    tile = decision.action.tile
    assert tile is not None
    label = decision_label(decision)
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
    if decision.lost_yaku:                   # 鳴いた手で、役が見えなくなる牌を切った（このままでは、あがれない）
        return "bad", "✗"
    if decision.yaku_detour:                 # 鳴いた手で、役まで遠回りになる牌を切った
        return "soso", "△"
    if safety is not None and safety.grade is SafetyGrade.RISKY:
        return "soso", "△"
    grade = decision.verdict.grade
    return GRADE_CLASS[grade], GRADE_ICONS[grade]


def claim_headline_html(hand: HandState, explanation: Explanation | None, rb: Rubifier, *, bumped: bool, points: bool = True) -> str:
    """ロンできる牌が出たとき（捨て牌・加槓の牌）。points が偽なら、点数は書かない（点数の申告の練習のため。役だけ書く）"""
    aka = hand.rules.aka_dora
    claim = hand.claim
    assert claim is not None
    seat, tile = claim.seat, claim.tile
    word = "ロンできます" if claim.kind.value == "discard" else "槍槓でロンできます"
    head = f'<b class="mj-stage">{rb.html(word)}</b>　{escape(SEAT_NAMES[seat])}の {_small(tile, aka)} <b>{escape(_name(tile, aka))}</b>'
    if bumped:
        sub = "頭ハネ：先の順番の人だけがあがる（ロンしても無効）"
    elif explanation is not None and explanation.best is not None and explanation.best.points is not None and not points:
        sub = f"役：{'・'.join(explanation.spoken_yaku)}（点数は、あがったあとに申告する）"
    elif explanation is not None and explanation.best is not None and explanation.best.points is not None:
        sub = f"ロンすると {_pts(explanation.best.points.total)} 点（{'・'.join(explanation.spoken_yaku)}）"
    else:
        sub = ""
    return _headline(_two_lines(head, sub, rb), "good")


# ---------------------------------------------------------------- 副露


MELD_LABELS = {MeldType.CHI: "チー", MeldType.PON: "ポン", MeldType.MINKAN: "大明槓", MeldType.ANKAN: "暗槓", MeldType.KAKAN: "加槓"}


def meld_tiles(furo: Furo, seat: int) -> tuple[tuple[int, bool, bool], ...]:
    """副露 1 組を、卓に置く並び（鳴いた牌は横向き・暗槓は両端を裏向き）にする"""
    source = None if furo.from_seat is None else (furo.from_seat - seat) % NUM_PLAYERS
    return display_order(furo.meld, source, furo.added)


def meld_label(furo: Furo) -> str:
    """副露 1 組の呼び方（例：ポン 白、チー 3萬4萬5萬）"""
    meld = furo.meld
    if meld.type is MeldType.CHI:
        return "チー " + "".join(kind_text(k) for k in sorted({kind_of(t) for t in meld.tiles}))
    return f"{MELD_LABELS[meld.type]} {kind_text(meld.first_kind)}"


def melds_label(furo_list: Sequence[Furo]) -> str:
    """副露の段の頭に付ける見出し（鳴いた面子だけなら「鳴き」、暗槓だけなら「暗槓」）"""
    opened = any(f.from_seat is not None for f in furo_list)
    closed = any(f.from_seat is None for f in furo_list)
    return "鳴き・暗槓" if opened and closed else ("鳴き" if opened else "暗槓")


def melds_html(furo_list: Sequence[Furo], seat: int, *, aka: bool, rb: Rubifier | None = None) -> str:
    """副露を、卓に置く並びで小さく（河の下・局の終わりの手牌の下）。段の頭に「鳴き」などの見出しを付ける
    （河の牌と見分けられるように）"""
    if not furo_list:
        return ""
    head = melds_label(furo_list)
    groups = [f'<span class="mj-mf-label">{rb.html(head) if rb is not None else escape(head)}</span>']
    for furo in furo_list:
        cells = []
        for tile, side, back in meld_tiles(furo, seat):
            image = back_img(cls="mj-s") if back else tile_img(tile, aka=aka, cls="mj-s")
            cells.append(f'<span class="mj-mf{" mj-mf-side" if side else ""}">{image}</span>')
        label = escape(meld_label(furo))
        groups.append(f'<span class="mj-mfuro" role="img" aria-label="{label}" title="{label}">{"".join(cells)}</span>')
    return f'<div class="mj-mfuros">{"".join(groups)}</div>'


def kan_notes_html(hand: HandState, dora_seen: int | None, rb: Rubifier) -> str:
    """カンのあとの知らせ：嶺上牌を引いた（自分）・ドラが増えた（自分が最後に行動する前と比べて）"""
    lines = []
    me = hand.players[HUMAN]
    if me.rinshan and me.drawn is not None and hand.result is None:
        lines.append("カンしたので、嶺上牌（王牌から引く、カンの補充の牌）を引いた。手牌の右の「リンシャン」の牌。")
    if dora_seen is not None and len(hand.dora_indicators) > dora_seen:
        added = hand.dora_indicators[dora_seen:]
        doras = "・".join(kind_text(dora_kind_of(kind_of(t))) for t in added)
        lines.append(f"カンで、ドラが {len(added)} 枚増えた（新しいドラ：{doras}）。増えたドラは、ほかの人にも乗る。")
    return "".join(f'<div class="mj-sub">{rb.html(line)}</div>' for line in lines)


def call_headline_html(hand: HandState, advice: CallAdvice | None, rb: Rubifier) -> str:
    """鳴ける牌が出たとき（ロンはできない）。打つ前のヒントなら、おすすめを下の行に"""
    aka = hand.rules.aka_dora
    claim = hand.claim
    assert claim is not None
    moves = {a.move for a in hand.call_actions(HUMAN)}
    words = "・".join(w for m, w in ((Move.CHI, "チー"), (Move.PON, "ポン"), (Move.KAN, "カン")) if m in moves)
    head = (
        f'<b class="mj-stage">{rb.html(words)}できます</b>　{escape(SEAT_NAMES[claim.seat])}の '
        f"{_small(claim.tile, aka)} <b>{escape(_name(claim.tile, aka))}</b>"
    )
    if advice is None:
        sub = "鳴くか、見送るかを選ぶ"
    else:
        # 「おすすめ：見送る（鳴いても速くならない）」。くわしい理由は、下の「鳴きの判断」の表に出す
        how = "見送る" if advice.recommend is None else call_name(advice.recommend)
        sub = f"おすすめ：{how}（{_short_reason(advice)}）"
    return _headline(_two_lines(head, sub, rb), "call")


def _short_reason(advice: CallAdvice) -> str:
    """おすすめの理由のひとこと（案内の 1 行に収める）"""
    return advice.short or advice.reason.split("。")[0]


def call_phrase(action: Action, tile: int, *, aka: bool) -> str:
    """返事の書き方（HTML）：「[2索][3索] で [1索] をチー」「[白] をポン」「[5萬] を見送った」"""
    if action.move is Move.CHI:
        return f'{"".join(_small(t, aka) for t in action.tiles)} で {_small(tile, aka)} をチー'
    word = {Move.PON: "ポン", Move.KAN: "カン（大明槓）"}.get(action.move)
    return f"{_small(tile, aka)} を{word}" if word else f"{_small(tile, aka)} を見送った"


def call_decision_headline_html(decision: CallDecision, rb: Rubifier, *, aka: bool) -> str:
    """鳴ける牌への返事の答え合わせ（打った後に答え合わせ）。上の行に返事、下の行に評価（2 行に収める）"""
    cls, icon = CALL_MARKS[decision.grade]
    head = f'<span class="mj-icon {cls}">{icon}</span> {call_phrase(decision.action, decision.advice.tile, aka=aka)}'
    sub = decision.label
    # 評価の言葉がおすすめを言っているとき（見送るのがおすすめだった・ロンできた）は、おすすめをくり返さない
    if not decision.followed and decision.label not in ("見送るのがおすすめだった", "ロンできた"):
        how = "見送る" if decision.advice.recommend is None else call_name(decision.advice.recommend)
        sub += f"（おすすめは {how}）"
    return _headline(_two_lines(head, sub, rb), cls)


def kan_headline_html(advice: KanAdvice, hand: HandState, rb: Rubifier) -> str:
    """カンをすすめるとき（打つ前のヒント）。上の行に「カンできます　おすすめ：暗槓 ○」、下の行に、ひとことの理由"""
    aka = hand.rules.aka_dora
    word = "加槓" if advice.added else "暗槓"
    head = (
        f'<b class="mj-stage">カンできます</b>　おすすめ：{rb.html(word)} {_small(advice.tile, aka)} <b>{escape(_name(advice.tile, aka))}</b>'
    )
    return _headline(_two_lines(head, "手は遅くならない。嶺上牌を 1 枚引ける", rb))


CALL_MARKS = {CallGrade.GOOD: ("good", "✓"), CallGrade.SOSO: ("soso", "△"), CallGrade.BAD: ("bad", "✗")}


# ---------------------------------------------------------------- 鳴きの判断（比べ方の表）


def _status_text(option: CallOption) -> str:
    outlook = option.outlook
    if outlook.status is YakuStatus.SECURED:
        return "役が確定（" + "・".join(c.name for c in outlook.secured) + "）"
    if outlook.status is YakuStatus.ON_PATH:
        # まだ確定していない（遠回りせずに、作れる見込みがある）。「役あり」とは書かない
        return "役の見込みあり（" + "・".join(c.name for c in outlook.path_yaku[:2]) + "：遠回りせずに作れる）"
    if outlook.status is YakuStatus.RIICHI:
        return "聴牌すればリーチで役が付く（門前）"
    nearest = outlook.nearest
    if outlook.status is YakuStatus.DETOUR and nearest is not None:
        return f"役まで遠回り（{nearest.name}の聴牌まで、あと {max(nearest.distance, 0)} 枚）"
    return "役なし（このままでは、あがれない）"


def _speed_text(option: CallOption) -> str:
    outlook = option.outlook
    stage = "聴牌" if outlook.shanten == 0 else f"{outlook.shanten} 向聴"
    noun = "待ち" if outlook.shanten == 0 else "受け入れ"
    text = f"{stage}・{noun} {outlook.total} 枚"
    if option.fastest is not None and option.fastest < outlook.shanten:
        fastest = "聴牌" if option.fastest == 0 else f"{option.fastest} 向聴"
        lose = "役が見えなくなる" if option.fastest_status in (None, YakuStatus.NONE) else "役まで遠回りになる"
        text += f"（役を残す切り方で数えた。速さだけなら {fastest} だが、{lose}）"
    return text


def _value_text(option: CallOption) -> str:
    outlook = option.outlook
    parts = [f"{c.name} {c.han}" for c in outlook.secured]
    if outlook.can_riichi:
        parts.append("リーチ 1")
    best = max(outlook.path_yaku, key=lambda c: c.han, default=None)
    if best is not None:
        parts.append(f"{best.name} {'役満' if best.yakuman else best.han}")
    if outlook.dora:
        parts.append(f"ドラ {outlook.dora}")
    total = outlook.han
    return f"目安 {total} 翻" + (f"（{'・'.join(parts)}）" if parts else "（役なし）" if outlook.status is YakuStatus.NONE else "")


def call_html(advice: CallAdvice, rb: Rubifier, *, aka: bool) -> str:
    """鳴く・鳴かないの比べ方：役が残るか・打点の目安・速さ（向聴数と受け入れ）"""
    # 画面に出る順にルビを振る（いちばん上に出す、おすすめの文を先に）
    lead = f"おすすめ：{'見送る' if advice.recommend is None else call_name(advice.recommend)}。{advice.reason}"
    lead_html = f'<div class="mj-note">{rb.html(lead)}</div>'
    rows = []
    options = [advice.stay, *advice.calls]
    for option in options:
        if option.action is None:
            name = "見送る（鳴かない）"
            tiles = ""
        else:
            name = call_name(option.action)
            tiles = "".join(_small(t, aka) for t in option.action.tiles)
            if option.discard is not None:
                tiles += f'<br><span class="mj-sub">{rb.html("鳴いたら")} {_small(option.discard, aka)} {rb.html("切り")}</span>'
        pick = (advice.recommend is None and option.action is None) or (option.action is not None and option.action == advice.recommend)
        mark = "◎ " if pick else ""
        # 緑：役が確定・門前（リーチで付く）。橙：役の見込み・遠回り（まだ確定していない）。赤：役が見えない
        status_cls = {YakuStatus.NONE: "bad", YakuStatus.DETOUR: "soso", YakuStatus.ON_PATH: "soso"}.get(option.outlook.status, "good")
        rows.append(
            f'<tr><td>{rb.html(mark + name)}<br>{tiles}</td>'
            f'<td><span class="mj-yaku-{status_cls}">{rb.html(_status_text(option))}</span>'
            f'<br><span class="mj-sub">{rb.html(_value_text(option))}</span>'
            f'<br><span class="mj-sub">{rb.html(_speed_text(option))}</span></td></tr>'
        )
    head = f'<tr><td>{rb.html("選び方")}</td><td>{rb.html("役・打点・速さ")}</td></tr>'
    note = (
        "役：鳴いたあとに役が付けられるか。鳴くとリーチができないので、役が無いと、あがれない（「見込み」は、まだ確定していない役）。"
        "打点の目安：確定した役＋リーチ（門前のとき）＋いまの形で付く役のうち一番高いもの＋ドラ（役どうしが同時に付くかまでは見ていない、おおまかな目安）。"
        "速さ：鳴くなら、鳴いて 1 枚切ったあとの向聴数と受け入れ（残り枚数）。切る牌は、役を残せる牌を先に選ぶ。"
        "門前で 1 向聴以内なのに、鳴くと打点の目安が 2 翻以上下がるときは、見送るをすすめる（このアプリの目安）。"
    )
    return f'{lead_html}<table class="mj-table mj-call-table">{head}{"".join(rows)}</table><div class="mj-sub">{rb.html(note)}</div>'


def call_decision_html(decision: CallDecision, rb: Rubifier, *, aka: bool) -> str:
    """鳴ける牌への返事の評価（打った後に答え合わせ・振り返り）"""
    cls, icon = CALL_MARKS[decision.grade]
    phrase = call_phrase(decision.action, decision.advice.tile, aka=aka)
    head = f'<div class="mj-review-head"><span class="mj-icon {cls}">{icon}</span> {rb.html(f"{decision.number} 巡目：")}{phrase}</div>'
    body = f"<div>{rb.html(decision.label + '。' + decision.text)}</div>"
    return f'<div class="mj-review {cls}">{head}{body}</div>'


# ---------------------------------------------------------------- CPU の打牌


def _discard_of(hand: HandState, seat: int, tile: int):
    return next((d for d in hand.players[seat].river if d.tile == tile), None)


def moves_since(hand: HandState, mark: int) -> list[tuple[int, str, int | None, bool]]:
    """自分が最後に行動したあとの動き。（席, 種類, 牌, ツモ切りか）の列。
    種類は discard・riichi・tsumo・ron・nine・chi・pon・kan（大明槓）・ankan・kakan。鳴いた牌は、鳴かれた捨て牌"""
    found = []
    called = _called_tiles(hand)
    for index, action in enumerate(hand.actions[mark:], start=mark):
        if action.move in (Move.DISCARD, Move.RIICHI):
            assert action.tile is not None
            discard = _discard_of(hand, action.seat, action.tile)
            kind = "riichi" if action.move is Move.RIICHI else "discard"
            found.append((action.seat, kind, action.tile, bool(discard and discard.tsumogiri)))
        elif action.move in (Move.TSUMO, Move.RON, Move.NINE):
            kind = {Move.TSUMO: "tsumo", Move.RON: "ron", Move.NINE: "nine"}[action.move]
            found.append((action.seat, kind, None, False))
        elif action.move in (Move.CHI, Move.PON, Move.KAN) and index in called:
            found.append((action.seat, action.move.name.lower(), called[index], False))
        elif action.move in (Move.ANKAN, Move.KAKAN):
            found.append((action.seat, action.move.name.lower(), action.tile, False))
    return found


def _called_tiles(hand: HandState) -> dict[int, int]:
    """鳴きが通った行動の番号 → 鳴いた牌（ロン・ポンが優先されて通らなかった鳴きは入れない）"""
    found = {}
    last_discard = None
    for index, action in enumerate(hand.actions):
        if action.move in (Move.DISCARD, Move.RIICHI):
            last_discard = action.tile
        elif action.move in (Move.CHI, Move.PON, Move.KAN) and last_discard is not None:
            player = hand.players[action.seat]
            if any(f.meld.called_tile == last_discard and f.from_seat is not None for f in player.furo):
                found[index] = last_discard
    return found


MOVE_WORDS = {
    "discard": "", "riichi": "リーチ", "tsumo": "ツモ！", "ron": "ロン！", "nine": "九種九牌",
    "chi": "チー", "pon": "ポン", "kan": "カン", "ankan": "カン", "kakan": "カン",
}


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
        if discard.called_by is not None:
            classes.append("mj-called")
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
        melds = melds_html(player.furo, seat, aka=aka, rb=rb)
        blocks.append(f'<div class="mj-riverbox"><div class="mj-cap">{rb.html(seat_label(hand, seat))} {mark_text}</div>{river}{melds}</div>')
    called = any(d.called_by is not None for p in hand.players for d in p.river)
    legend = "印の付いた牌：自分が切ったあとに切られた牌。横向き：リーチ宣言牌。薄い牌：ツモ切り" if mark else "横向き：リーチ宣言牌。薄い牌：ツモ切り"
    if called or any(p.furo for p in hand.players):
        legend += "。とても薄い牌：鳴かれた牌（鳴いた人の副露に入った）。河の下の段：副露と暗槓（横向きの牌が、鳴いた牌。暗槓は両端が裏向き）"
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
        if kind in ("chi", "pon", "kan", "ankan", "kakan"):
            assert tile is not None
            text = f"{seat_label(hand, seat)}：{MOVE_WORDS[kind]}（{_name(tile, aka)}）"
            river = melds_html(hand.players[seat].furo, seat, aka=aka, rb=rb)
        elif tile is not None:
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
        if miss.chankan:
            continue                # 槍槓の牌（加槓・暗槓）は、ロンできなければ印を出さない（フリテンだけが理由なので、下の「いまフリテン」で分かる）
        discard = _discard_of(hand, miss.from_seat, miss.tile)
        if discard is None or discard.order < count:
            continue
        what = f"{SEAT_NAMES[miss.from_seat]}の {_name(miss.tile, aka)} はあがり牌だったが、"
        if miss.check.furiten is not None:
            why = FURITEN_SHORT[miss.check.furiten] + "ので、ロンできなかった。"
            if miss.check.furiten is Furiten.RIVER:
                why += "フリテンでも、ツモならあがれる。"
        elif hand.players[HUMAN].menzen:
            why = "役がないので、ロンできなかった（ツモなら門前清自摸和であがれる。リーチしていれば、ロンでもあがれた）。"
        else:
            why = "役がないので、ロンできなかった（鳴いた手なので、リーチもできない。役を作らないと、ツモでもあがれない）。"
        follow = "このあと自分がツモるまでは、ほかの人の捨て牌でもロンできない（同巡内フリテン）。"
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
        what = "槍槓（カンの牌でロン）" if miss.chankan else "ロン"
        text = f"{SEAT_NAMES[miss.from_seat]}の {_name(miss.tile, aka)} で、{what}できたが見送った。"
        if riichi_order is not None and miss.order > riichi_order:
            text += "リーチのあとの見逃しなので、この局のあいだはロンできなくなった（ツモならあがれた）。"
        else:
            text += "そのあと自分がツモるまでは、ほかの人の捨て牌でもロンできなかった（同巡内フリテン）。"
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
        locked_kinds=position.forbidden,
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
    locked_kinds: Sequence[int] = (),
) -> str:
    """手牌の種類ごとの危険度と根拠の表（安全な順）。pick_kinds（おすすめ・正解）に ◎、chosen_kind に「切った」の印を付ける。
    locked_kinds（鳴いた直後の喰い替えで切れない牌）には、そう添える。

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
        if row.kind in locked_kinds:
            dora += f'<span class="mj-sub">（{rb.html("いまは喰い替えで切れない")}）</span>'
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


def review_list_html(decisions: Sequence[TurnDecision], rb: Rubifier, *, aka: bool, calls: Sequence[CallDecision] = ()) -> str:
    """この局の自分の判断の振り返り（打牌と、鳴ける牌への返事。1 つ 1 行。巡目の順）"""
    if not decisions and not calls:
        return f'<div class="mj-sub">{rb.html("この局で、自分で選んだ打牌はありません。")}</div>'
    rows = []
    items: list[tuple[int, int, TurnDecision | CallDecision]] = [(d.number, 1, d) for d in decisions]
    items += [(c.number, 0, c) for c in calls if c.called or not c.followed]      # 見送りは、おすすめと違ったときだけ
    for _, _, item in sorted(items, key=lambda x: (x[0], x[1])):
        if isinstance(item, CallDecision):
            cls, icon = CALL_MARKS[item.grade]
            what = call_name(item.action) if item.called else "見送った"
            rows.append(
                f'<tr><td class="num">{item.number}</td><td><span class="mj-icon {cls}">{icon}</span> {_small(item.advice.tile, aka)}</td>'
                f"<td>{rb.html(what + '：' + item.label)}</td></tr>"
            )
            continue
        decision = item
        cls, icon = _decision_mark(decision)
        tile = decision.action.tile
        assert tile is not None
        pick = decision.advice.pick
        how = "リーチ＋" if decision.advice.recommend_riichi else ""
        better = "" if decision.followed else f"おすすめ {how}{_small(pick, aka)}"
        label = decision_label(decision, detailed=True)
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
            how = "ツモ" if win.from_seat is None else ("槍槓" if win.ctx.chankan else "ロン") + f"（{SEAT_NAMES[win.from_seat]}から）"
            lines.append(f'<div class="mj-big">{rb.html(f"{who}の{how}")}</div><div class="mj-note">{rb.html(gain_text(win))}</div>')
            if win.pao is not None:
                lines.append(f'<div class="mj-sub">{rb.html(pao_text(win))}</div>')
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
            EndKind.FOUR_KANS: "2 人以上で合わせて 4 回カンをして、そのあとの打牌が通った。",
        }[result.kind]
        moved = "リーチ棒のほかは、点の動きは無く" if any(p.riichi_paid for p in hand.players) else "点の動きは無く"
        banner = (
            f'<div class="mj-card mj-result-card"><div class="mj-big">{rb.html(f"途中流局（{name}）")}</div>'
            f'<div class="mj-sub">{rb.html(f"{explain_text}{moved}、親が続ける（本場が 1 つ増える）。")}</div></div>'
        )
    return banner + settlement_html(hand, rb)


def pao_text(win: Win) -> str:
    """責任払いの説明"""
    assert win.pao is not None
    name = {"daisangen": "大三元", "daisuushii": "大四喜"}.get(win.pao_yaku or "", "役満")
    who = SEAT_NAMES[win.pao]
    if win.from_seat is None:
        how = f"ツモなので、{name}の点は{who}が全部払った"
    elif win.from_seat == win.pao:
        how = f"{who}の放銃なので、{who}が全部払った"
    else:
        how = f"{SEAT_NAMES[win.from_seat]}の放銃なので、{name}の点は{SEAT_NAMES[win.from_seat]}と{who}が半分ずつ払った"
    return f"責任払い（包）：{name}を確定させる牌を鳴かせたのは{who}。{how}（本場の点も{who}）。"


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
            # 鳴いた手で、どの待ちでも役が付かない聴牌は、あがれない（流局のときだけ、聴牌として数える）
            formal = "（役なし。形式聴牌）" if waits and formal_tenpai(hand, seat) else ""
            state = (f"聴牌{formal}・待ち " + "・".join(kind_text(k) for k in waits)) if waits else "ノーテン"
        riichi = "・リーチ" if player.riichi_paid else ""
        cells = _river_cells(hand, seat, new_from=10**9, aka=aka)
        river = f'<div class="mj-river mj-river-s">{cells}</div>' if cells else ""
        melds = melds_html(player.furo, seat, aka=aka, rb=rb)
        blocks.append(
            f'<div class="mj-reveal"><div class="mj-cap">{rb.html(f"{seat_label(hand, seat)}　{state}{riichi}")}</div>'
            f'<div class="mj-hand">{shown}</div>{melds}{river}</div>'
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
    if tally.calls:
        text += f"鳴いた回数 {tally.calls} 回（そのうち役なしの鳴き {tally.bad_calls} 回）。"
    return text


# ---------------------------------------------------------------- 成績


def _condition(summary_row: Summary) -> str:
    luck = luck_text(summary_row.deal, summary_row.draw).replace("ツキ補正：", "補正 ")
    cpu = f"CPU {CPU_NAMES.get(summary_row.cpu_level, summary_row.cpu_level)}"
    if summary_row.cpu_deal or summary_row.cpu_draw:
        cpu += f"（補正 {summary_row.cpu_deal}・{summary_row.cpu_draw}）"
    hint = "・ヒントあり" if summary_row.hinted else ""
    rules = f"・{rules_text(summary_row.rules)}" if summary_row.rules else ""
    return f"{LENGTH_NAMES.get(summary_row.length, summary_row.length)}・{cpu}・{luck}{hint}{rules}"


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


#: 卒業の目安に数えない対局（画面に添える）
GRADUATION_EXCLUDED = "鳴きなし・ルールを変えた対局（鳴きの入る前の版で打った対局を含む）は数えない。"


def graduation_html(grad: Graduation, rb: Rubifier) -> str:
    """卒業の目安（補正 0・CPU ふつう・ヒントなし・初期のルール（鳴きあり）の東風戦）の進み具合"""
    head = f"卒業の目安：補正 0・CPU ふつう・ヒントなし・初期のルール（鳴きあり）の東風戦を {GOAL_GAMES} 回"
    if grad.games == 0:
        body = f"まだ数えられる対局がありません（補正を 0 にして、打つ前のヒントをオフにした東風戦が対象。{GRADUATION_EXCLUDED}）"
        return f'<div class="mj-lesson"><b>{rb.html(head)}</b><br>{rb.html(body)}</div>'
    rank = "—" if grad.average_rank is None else rounded(grad.average_rank, 2)
    # 目標の境目のそばでは、丸めた値と判定が食い違って見えるので、小数 1 桁と、局の数・回数も出す
    deal_in, counted = "—", ""
    if grad.deal_in_rate is not None and grad.hands:
        deal_in = f"{rounded(Decimal(grad.deal_ins * 100) / grad.hands, 1)}%"
        counted = f"{grad.hands} 局で {grad.deal_ins} 回。"
    elif grad.deal_in_rate is not None:
        deal_in = percent(grad.deal_in_rate)
    lines = [
        f"対局数：{grad.games} / {GOAL_GAMES}（{'達成' if grad.enough else f'あと {GOAL_GAMES - grad.games} 回'}）",
        f"平均順位：{rank}（目標 {GOAL_RANK} 以下：{'達成' if grad.rank_ok else 'まだ'}）",
        f"放銃率：{deal_in}（{counted}目標 {percent(GOAL_DEAL_IN)} 以下：{'達成' if grad.deal_in_ok else 'まだ'}）",
    ]
    if grad.games < GOAL_MISS_GAMES:
        misses = f"{GOAL_MISS_GAMES} 戦そろったら判定"
    else:
        misses = "達成" if grad.misses_ok else "まだ"
    lines.append(f"役なし・フリテンの見落とし（直近 {GOAL_MISS_GAMES} 戦）：{grad.recent_misses} 回（目標 0 回：{misses}）")
    if grad.games < GOAL_MISS_GAMES:
        calls = f"{GOAL_MISS_GAMES} 戦そろったら判定"
    else:
        calls = "達成" if grad.calls_ok else "まだ"
    lines.append(
        f"役なしの鳴き（直近 {GOAL_MISS_GAMES} 戦）：{grad.recent_bad_calls} 回（鳴いた回数 {grad.recent_calls} 回のうち。目標 0 回：{calls}）"
    )
    if grad.passed:
        lines.append("すべての目標を達成した。")
    body = "".join(f"<li>{rb.html(line)}</li>" for line in lines)
    note = (
        "平均順位と放銃率は、数えた対局ぜんぶ（いまのところの値）。対局数が目標に届いたところで、そろって達成なら卒業の目安を満たす。"
        + GRADUATION_EXCLUDED
    )
    return f'<div class="mj-lesson"><b>{rb.html(head)}</b><ul class="mj-rules">{body}</ul><div class="mj-sub">{rb.html(note)}</div></div>'


def graduation_text(game: GameState, *, hinted: bool, counted: bool) -> str:
    """いまの対局を、卒業判定（CPU 戦の条件）に数えるか。数えないなら、その理由も（画面のいちばん下に出す）"""
    config = game.config
    reasons = []
    if not counted:
        reasons.append("番号を指定した対局")
    if not config.luck.is_off or not config.cpu_luck.is_off:
        reasons.append("ツキ補正あり")
    if config.cpu_level.value != "normal":
        reasons.append("CPU が弱い")
    if config.length.value != "east":
        reasons.append("半荘戦")
    if config.rules != Rules():
        reasons.append("ルールを変えた")
    if hinted:
        reasons.append("打つ前のヒントを見た")
    return "この対局は、卒業判定に数える" if not reasons else f"この対局は、卒業判定に数えない（{'・'.join(reasons)}）"


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
     "見送ると、次に自分がツモるまでロンできない（このアプリは雀魂に合わせて、チー・ポンして切っても解けないことにしている。"
     "鳴いて切れば解けるルールもある。ルールによって異なる。リーチのあとなら、その局のあいだずっと）。"
     "あがり牌なのにロンできなかったときは、その理由を知らせる。"),
    ("鳴き", "ほかの人の捨て牌でチー・ポン・カンできるとき、手牌の下に「チー」「ポン」「カン」と「見送る」が出る（チーは上家の牌だけ）。"
     "チー・ポンしたら、ツモらずに 1 枚切る（カンしたら、嶺上牌をツモってから切る）。鳴いた牌と同じ牌などは、すぐには切れない（喰い替え）。"
     "鳴いた手はリーチできないので、役が無いとあがれない。"
     "コーチは、鳴く・鳴かないを、役が残るか・打点の目安・速さで比べる。"),
    ("カン", "4 枚そろったら、自分の番に「カン」（暗槓）。ポンした牌の 4 枚目なら加槓。ほかの人の捨て牌と手の中の 3 枚でもカンできる（大明槓）。"
     "カンすると、嶺上牌をツモる。ドラが 1 枚増える（暗槓はすぐ。大明槓・加槓は、次に 1 枚切ったとき。めくる時点は、ルールによって異なる）。"
     "コーチは、カンしても手が遅くならず、リーチを受けていなければ「◎ カン」にする。"),
    ("守備", "誰かがリーチすると、手牌の危険度と根拠（現物・スジ・壁・字牌の見えている枚数）の表が出る。聴牌していなければ、コーチはオリ（ベタオリ）をすすめる。"),
    ("リーチ判断", "聴牌にとれるとき、リーチとダマ（リーチしない）を、役の有無・待ちの形と残り枚数・点数で比べた表が出る。"),
    ("局の終わり", "全員の手牌と待ちを公開する。あがった手は、点数計算の全過程を見られる。牌譜で、局を 1 手ずつ振り返れる（自分の判断の評価つき）。"),
    ("なぜ？", "「なぜ？」を開くと、よくある質問のボタンが出る。押すと、アプリの計算をもとにした説明が出る"
     "（AI のキーが設定してあれば、AI が分かりやすく言い直す。数・牌・役は、アプリの計算と照らし合わせる）。"),
    ("点数の申告", "あがったら、解説の前に、点数を選ぶ（卓では、あがった人が自分で点数を言う）。"
     "打つ前のヒントを見ずに打った局の申告だけを、卒業判定に数える。設定で切れる。"),
    ("おまかせ", "設定の「おまかせ」を入れると、ヒントを見ずに打った局の評価とドリルの正答率から、ツキ補正を 1 段階ずつ自動で上げ下げする。"
     "いまの段階と、変えた理由は、設定のツキ補正のところに出る。"),
    ("対局の終わり", "東風戦（東 1〜4 局）か半荘戦。最後まで打った対局だけを成績に入れる。決まりは雀魂の段位戦に合わせてある（雀魂で確かめられなかった細かい点と、ほかのルールとの違いは、ルールの違いのページに書いた）。"),
)


def help_html(rb: Rubifier) -> str:
    items = "".join(f"<li><b>{rb.html(title)}</b>：{rb.html(text)}</li>" for title, text in HELP_ITEMS)
    return f'<ul class="mj-rules">{items}</ul>'


def phase_text(hand: HandState) -> str:
    """いまの局の進み具合（画面の下の補足に出す）"""
    if hand.result is not None:
        return "局の終わり"
    if hand.phase is Phase.CLAIM:
        return "ロン・鳴きの返事待ち"
    return f"{SEAT_NAMES[hand.turn]}の番"


# ---------------------------------------------------------------- 牌譜（局後の振り返り）


def kifu_notes(found: Sequence[tuple[int, TurnDecision | CallDecision]]) -> dict[int, Note]:
    """自分の判断の評価を、牌譜の手順に添える形にする（{行動の番号: 評価}）"""
    notes = {}
    for index, decision in found:
        if isinstance(decision, CallDecision):
            cls, icon = CALL_MARKS[decision.grade]
            text = decision.text if not decision.followed else ""
            notes[index] = Note(icon, cls, decision.label, text)
            continue
        cls, icon = _decision_mark(decision)
        label = decision_label(decision, detailed=True)
        text = ""
        if not decision.followed:
            pick = decision.advice.pick
            how = "リーチして " if decision.advice.recommend_riichi else ""
            text = f"おすすめは {how}{_name(pick, True)} 切り。" + decision.verdict.text
        notes[index] = Note(icon, cls, label, text)
    return notes

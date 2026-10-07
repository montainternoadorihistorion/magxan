"""一人練習の表示（ui/practice_view.py）のテスト。HTML の文字列として確かめる"""
from __future__ import annotations

from coach_helpers import TENPAI_PLUS_ONE, TWO_SHANTEN, held, position
from html_helpers import check_html, check_tile_images, ruby_parts, ruby_terms, text_of
from practice_helpers import TENPAI_HAND, crafted_wall, mixed_policy, start_on, tile, tsumogiri

from engine import practice
from engine.coach import analyze, judge_discard
from engine.luck import LuckSettings
from engine.practice import Decision, Outcome, PracticeConfig, discard, riichi
from engine.records import Summary, record_of, summarize
from engine.scoring.explain import explain
from engine.tiles import EAST
from ui.practice_view import (
    LEVEL_FULL,
    LEVEL_MIN,
    LEVEL_NORMAL,
    advice_headline_html,
    candidates_html,
    chance_html,
    deal_text,
    draw_note_html,
    draws_text,
    exhausted_html,
    hand_summary_html,
    help_html,
    layout_html,
    luck_guide_html,
    luck_now_html,
    luck_text,
    note_html,
    percent,
    plain_headline_html,
    review_list_html,
    riichi_draws_html,
    river_html,
    shanten_html,
    stats_html,
    status_html,
    subhead_html,
    verdict_headline_html,
    verdict_html,
    waits_html,
)
from ui.ruby import Rubifier, missing_ruby
from ui.win_view import DETAIL_FULL, detail_sections, summary_section


def rb() -> Rubifier:
    return Rubifier()


def decide(pos, code: str, *, declare: bool = False) -> Decision:
    """文字で書いた局面で、その牌を切ったときの評価"""
    analysis = analyze(pos)
    chosen = held(pos, code)
    action = riichi(chosen) if declare else discard(chosen)
    return Decision(3, action, judge_discard(analysis, chosen, riichi=declare), analysis)


# ---------------------------------------------------------------- どの局面でも壊れない


def makers_of(state, decisions, luck_draw: int, *, counted: bool, hinted: bool) -> list:
    """その局面で画面に出す部品を作る関数（Rubifier を受け取って HTML を返す）を、画面に出る順に並べる"""
    makers = [lambda r: status_html(state, r)]
    if not state.finished:
        analysis = analyze(practice.position_of(state))
        makers.append(lambda r: advice_headline_html(analysis, r, can_riichi=bool(state.riichi_discards)))
        makers.append(lambda r: draw_note_html(state.last_draw, r, aka=True))
        makers.append(lambda r: river_html(state, r))
        if decisions:
            last = decisions[-1]
            makers.append(lambda r: verdict_headline_html(last, r, aka=True))
            for level in (LEVEL_MIN, LEVEL_NORMAL, LEVEL_FULL):
                makers.append(lambda r, level=level: verdict_html(last, r, level=level, aka=True))
            makers.append(lambda r: candidates_html(last.analysis, r, chosen_kind=last.verdict.chosen.kind))
        makers.append(lambda r: waits_html(analysis, r))
        makers.append(lambda r: shanten_html(analysis, r) + candidates_html(analysis, r) + chance_html(analysis, r, luck_draw=luck_draw))
        for level in (LEVEL_NORMAL, LEVEL_FULL):
            makers.append(lambda r, level=level: layout_html(analysis, r, level=level))
    else:
        if state.result.outcome is Outcome.EXHAUSTED:
            makers.append(lambda r: exhausted_html(state, r))
        makers.append(lambda r: hand_summary_html(state, decisions, r, counted=counted, hinted=hinted))
        makers.append(lambda r: riichi_draws_html(state, r))
        makers.append(lambda r: river_html(state, r))
        makers.append(lambda r: review_list_html(decisions, r, aka=True))
    return makers


def test_every_part_renders_valid_html_on_real_hands():
    pages = 0
    for seed, settings in enumerate([LuckSettings(), LuckSettings(50, 50), LuckSettings(75, 75), LuckSettings(100, 100), LuckSettings(25, 75)] * 3):
        config = PracticeConfig(seed=seed, luck=settings)
        state = practice.start(config)
        chooser = mixed_policy(seed)
        decisions: list[Decision] = []
        while True:
            makers = makers_of(state, list(decisions), settings.draw, counted=seed % 2 == 0, hinted=seed % 3 == 0)
            ruby = rb()                      # 画面 1 枚ぶん
            page = "".join(make(ruby) for make in makers)
            check_tile_images(page)
            assert "None" not in page and "nan" not in page
            # どの部品も、それだけで出したとき、初出の用語にルビが付く（部品の中で、作る順と出る順が合っている）
            for make in makers:
                alone = make(rb())
                assert missing_ruby(ruby_parts(alone)) == [], alone[:300]
            pages += 1
            if state.finished:
                break
            action = chooser(state)
            decision = practice.assess(state, action)
            if decision is not None:
                decisions.append(decision)
            state = practice.apply(state, action)
    assert pages > 150


def test_setting_and_stats_parts_give_ruby_on_their_own():
    """設定・成績・使い方は、折りたたみの中に出す。上の画面に頼らず、その中だけで初出の用語にルビが付く"""
    rows = [
        summary(), summary(hinted=True), summary(deal=75, draw=75), summary(deal=75, draw=75, hinted=True),
    ]
    parts = {
        "成績": stats_html(rows, rb()),
        "成績（記録なし）": stats_html([], rb()),
        "強さの目安": luck_guide_html(rb()),
        "いまの強さ": luck_now_html(50, 50, rb()),
        "いまの強さ（補正なし）": luck_now_html(0, 0, rb()),
        "使い方": help_html(rb()),
        "小見出し": subhead_html("ツキ補正", "配牌とツモの「引きの良さ」を上げます。", rb()),
        "説明": note_html("配牌の候補のうち、最初から聴牌しているものは、ふつう採用しません。", rb()),
    }
    for name, html in parts.items():
        check_html(html)
        assert missing_ruby(ruby_parts(html)) == [], name


def test_ruby_is_given_once_per_page():
    """同じ用語にルビを振るのは、画面の中で 1 回だけ（部品をまたいでも）"""
    state = start_on(crafted_wall(TENPAI_HAND, "9m4s"))
    analysis = analyze(practice.position_of(state))
    ruby = rb()
    page = (
        status_html(state, ruby) + advice_headline_html(analysis, ruby, can_riichi=True) + river_html(state, ruby)
        + waits_html(analysis, ruby) + shanten_html(analysis, ruby) + candidates_html(analysis, ruby)
        + chance_html(analysis, ruby, luck_draw=50) + layout_html(analysis, ruby, level=LEVEL_FULL)
    )
    terms = ruby_terms(page)
    assert len(terms) == len(set(terms)) and {"東場", "南家", "聴牌", "巡目", "河", "向聴", "順子", "雀頭", "放銃"} <= set(terms)


def page_pieces(state, decisions, *, hint: str, level: int, history=()) -> list[tuple[str, int]]:
    """ページ（views/practice.py）と同じ順・同じ分け方で、画面の部品を作る。返すのは（HTML, 範囲）の列。

    範囲 0 は、いつも見えている部分。折りたたみの中身は、折りたたみごとに別の番号（Rubifier.fork() に通す）。
    """
    ruby = rb()
    pieces: list[tuple[str, int]] = [(status_html(state, ruby), 0)]
    scope = 0

    def folded(make) -> None:
        nonlocal scope
        scope += 1
        pieces.append((make(ruby.fork()), scope))

    if not state.finished:
        last = decisions[-1] if decisions else None
        analysis = analyze(practice.position_of(state)) if hint == "before" else None
        if analysis is not None:
            pieces.append((advice_headline_html(analysis, ruby, can_riichi=bool(state.riichi_discards)), 0))
        elif hint == "after" and last is not None:
            pieces.append((verdict_headline_html(last, ruby, aka=True), 0))
        else:
            pieces.append((plain_headline_html("自分で考えて切ってください。切ったあとに、答え合わせを表示します。", ruby), 0))
        if state.last_draw.luck.swapped:
            pieces.append((draw_note_html(state.last_draw, ruby, aka=True), 0))
        pieces.append((river_html(state, ruby), 0))
        if hint != "off" and last is not None:
            pieces.append((verdict_html(last, ruby, level=level, aka=True), 0))
            if hint == "after" and level >= LEVEL_NORMAL:
                folded(lambda r: shanten_html(last.analysis, r) + candidates_html(last.analysis, r, chosen_kind=last.verdict.chosen.kind))
        if analysis is not None and not analysis.can_win and level >= LEVEL_NORMAL:
            if analysis.waits and not analysis.last_discard:
                folded(lambda r: waits_html(analysis, r))
            if not analysis.last_discard:
                folded(lambda r: shanten_html(analysis, r) + candidates_html(analysis, r) + chance_html(analysis, r, luck_draw=state.config.luck.draw))
            folded(lambda r: layout_html(analysis, r, level=level))
    else:
        explanation = None
        if state.result.outcome == Outcome.TSUMO:
            explanation = explain(state.result.win, state.config.rules)
            banner = f'<div class="mj-headline mj-headline-short good"><b class="mj-stage">ツモあがり</b>　{state.result.turn} {ruby.html("巡目")}</div>'
            pieces.append((banner + summary_section(explanation, ruby).html, 0))
        else:
            pieces.append((exhausted_html(state, ruby), 0))
        pieces.append((hand_summary_html(state, decisions, ruby, counted=True, hinted=hint == "before"), 0))
        if state.in_riichi:
            pieces.append((riichi_draws_html(state, ruby), 0))
        pieces.append((river_html(state, ruby), 0))
        folded(lambda r: review_list_html(decisions, r, aka=True))
        if explanation is not None:
            pieces.extend((section.heading_html + section.html, 0) for section in detail_sections(explanation, ruby, detail=DETAIL_FULL))
    luck = state.config.luck
    folded(
        lambda r: subhead_html("ツキ補正", "配牌とツモの「引きの良さ」を上げます。", r) + luck_now_html(luck.deal, luck.draw, r)
        + note_html("配牌の候補のうち、最初から聴牌しているものは、ふつう採用しません。", r) + subhead_html("強さの目安", "", r) + luck_guide_html(r)
        + note_html("コーチのおすすめは、速さ（向聴数と受け入れ枚数）だけで決めています。", r)
    )
    folded(lambda r: stats_html(summarize(history), r))
    folded(lambda r: help_html(r))
    return pieces


def test_every_first_appearance_gets_ruby_on_pages_assembled_like_the_real_one():
    """用語が画面に最初に出てくるところに、ルビが付いている（あとから出てくるほうに付いてしまう作り方をしていない）"""
    checked = 0
    for seed in range(12):
        settings = [LuckSettings(), LuckSettings(75, 75), LuckSettings(100, 100, True)][seed % 3]
        hint = ("before", "after", "off")[seed % 3 if seed < 6 else (seed + 1) % 3]
        level = (LEVEL_FULL, LEVEL_NORMAL, LEVEL_MIN)[seed % 3 if seed % 2 else 0]
        state = practice.start(PracticeConfig(seed=seed, luck=settings))
        chooser = mixed_policy(seed)
        decisions: list[Decision] = []
        history = []
        while True:
            pieces = page_pieces(state, decisions, hint=hint, level=level, history=history)
            parts = [(text, has, scope) for html, scope in pieces for text, has in ruby_parts(html)]
            assert missing_ruby(parts) == [], (seed, state.turn, hint, level)
            checked += 1
            if state.finished and history:
                break
            if state.finished:
                history = [record_of(state, decisions, time=1, hinted=hint == "before")]      # 成績が入った状態でも、もう 1 回
                continue
            action = chooser(state)
            decision = practice.assess(state, action)
            if decision is not None:
                decisions.append(decision)
            state = practice.apply(state, action)
    assert checked > 100


# ---------------------------------------------------------------- 状況


def test_status_shows_round_seat_turn_dora_and_luck():
    state = practice.start(PracticeConfig(seed=20261007, luck=LuckSettings(50, 25)))
    html = status_html(state, rb())
    text = text_of(html)
    assert "東場" in text and "東家（親）" in text and "1 巡目（残りツモ 17 回）" in text
    assert "ドラ表示牌" in text and "→ ドラ" in text and "ツキ補正：配牌 50・ツモ 25" in text
    assert html.count("<img ") == 2 and "mj-chip-luck" in html         # 表示牌と、その次の牌（ドラ）

    plain = practice.start(PracticeConfig(seed=5))
    assert "ツキ補正なし（通常の麻雀）" in text_of(status_html(plain, rb())) and "mj-chip-plain" in status_html(plain, rb())
    assert practice.seat_wind_of(plain.config) != EAST and "（子）" in text_of(status_html(plain, rb()))

    finished = plain
    while not finished.finished:
        finished = practice.apply(finished, tsumogiri(finished))
    assert "18 巡目で終了" in text_of(status_html(finished, rb()))


def test_luck_text():
    assert luck_text(0, 0) == "ツキ補正なし（通常の麻雀）"
    assert luck_text(75, 0) == "ツキ補正：配牌 75・ツモ 0" and luck_text(0, 5) == "ツキ補正：配牌 0・ツモ 5"


# ---------------------------------------------------------------- ひとことの案内


def test_advice_headline_variants():
    normal = text_of(advice_headline_html(analyze(position(TWO_SHANTEN)), rb(), can_riichi=False))
    assert normal == "2 向聴　おすすめ： 東 切り（受け入れ 4 種 16 枚）"

    tenpai = analyze(position(TENPAI_PLUS_ONE))
    assert text_of(advice_headline_html(tenpai, rb(), can_riichi=True)) == "聴牌にとれます　 9萬 を切ると、待ちは 2 種 8 枚。リーチもできます"
    assert "リーチ" not in text_of(advice_headline_html(tenpai, rb(), can_riichi=False))

    win = advice_headline_html(analyze(position("123m456p789s234s44z")), rb(), can_riichi=False)
    assert text_of(win) == "あがりの形です。下の「ツモ」を押すと、あがれます。" and "good" in win

    last = analyze(position(TENPAI_PLUS_ONE, draws_left=0, can_riichi=False))
    assert text_of(advice_headline_html(last, rb(), can_riichi=False)) == "最後のツモ  9萬 を切ると、聴牌したまま流局になります。"
    hopeless = analyze(position(TWO_SHANTEN, draws_left=0, can_riichi=False))
    assert text_of(advice_headline_html(hopeless, rb(), can_riichi=False)) == "最後のツモ 聴牌にとれない手です。どれを切っても、ノーテンで流局になります。"

    dead = analyze(position("1111m2222p3333s4z5z"))            # どれを切っても、有効牌が残らない形を作るのは難しいので、表示だけ確かめる
    assert "おすすめ" in text_of(advice_headline_html(dead, rb(), can_riichi=False))
    assert text_of(plain_headline_html("コーチはオフです。", rb())) == "コーチはオフです。"


def test_advice_headline_when_the_nearest_shape_has_no_live_tiles():
    """聴牌にとれる形でも、待ち牌がすべて見えているときは、おすすめ（形を変える切り方）の向聴数で案内する"""
    stalled = analyze(position("123m456p789s13s44z9m", visible="2222s"))      # 9萬 を切れば 2索 待ちの聴牌。だが 2索 は 4 枚とも見えている
    assert stalled.stalled and (stalled.shanten, stalled.pick.shanten) == (0, 1)
    html = advice_headline_html(stalled, rb(), can_riichi=True)
    text = text_of(html)
    assert text.startswith("1 向聴　おすすめ： 1索 切り（受け入れ 8 種 27 枚）") and "リーチ" not in text
    assert "聴牌にもとれるが、その待ち牌はすべて見えていて、残り 0 枚（空聴）。" in text
    assert ruby_terms(html)[:1] == ["向聴"] and "空聴" in ruby_terms(html)
    # 表のほうも、同じ向聴数で書く。聴牌にとれる切り方は「残り 0 枚」として載せる
    line = text_of(shanten_html(stalled, rb()))
    assert line.startswith("1 向聴：聴牌まで、有効牌があと 1 枚。") and "形を変えて受け入れを広げるほうが速い" in line
    table = text_of(candidates_html(stalled, rb()))
    assert "1 向聴にとる切り方（受け入れの広い順）" in table and "聴牌だが残り 0 枚" in table and "のままの切り方" not in table


def test_verdict_headline_is_short_and_names_the_better_tile():
    best = verdict_headline_html(decide(position(TWO_SHANTEN), "1z"), rb(), aka=True)
    assert text_of(best) == "✓  東 切り：いちばん速い打牌" and "good" in best and "おすすめは" not in best
    equal = text_of(verdict_headline_html(decide(position(TWO_SHANTEN), "1m"), rb(), aka=True))
    assert equal == "✓  1萬 切り：おすすめと同じ速さ"
    narrow = verdict_headline_html(decide(position("123m456p789s2s1445z"), "2s"), rb(), aka=True)
    assert text_of(narrow) == "△  2索 切り：受け入れが 12 枚少ないおすすめは  東 切り" and "soso" in narrow
    far = verdict_headline_html(decide(position(TWO_SHANTEN), "3s"), rb(), aka=True)
    assert "✗" in text_of(far) and "聴牌から遠ざかった" in text_of(far) and "bad" in far
    passed = text_of(verdict_headline_html(decide(position("123m456p789s234s44z"), "2s"), rb(), aka=True))
    assert passed == "！  2索 切り：あがりを見送った"           # あがりを見送ったときは、別の牌を勧めない
    red = text_of(verdict_headline_html(decide(position("123m456p789s4056s4z"), "0s"), rb(), aka=True))
    assert "赤5索 切り" in red


def test_verdict_card_shows_reasons_except_at_the_minimum_level():
    decision = decide(position(TWO_SHANTEN), "3s")
    full = verdict_html(decision, rb(), level=LEVEL_NORMAL, aka=True)
    assert "3 巡目の打牌" in text_of(full) and "2 向聴から 3 向聴に遠ざかる" in text_of(full)
    assert "「34索」（両面）に使っていた牌" in text_of(full) and "<ul>" in full and 'class="mj-review bad"' in full
    brief = verdict_html(decision, rb(), level=LEVEL_MIN, aka=True)
    assert "2 向聴から 3 向聴に遠ざかる" in text_of(brief) and "<ul>" not in brief
    good = verdict_html(decide(position(TWO_SHANTEN), "1z"), rb(), level=LEVEL_FULL, aka=True)
    assert 'class="mj-review good"' in good and "<ul>" not in good            # 理由が無ければ、箇条書きも出さない


# ---------------------------------------------------------------- 河とツモ


def test_river_marks_the_riichi_tile():
    state = start_on(crafted_wall(TENPAI_HAND, "5z6z7z1s"))
    assert text_of(river_html(state, rb())) == "河（切った牌）：まだ切っていません"
    state = practice.apply(state, discard(state.drawn))
    html = river_html(state, rb())
    assert "河（切った牌） 1 枚" in text_of(html) and html.count("<img ") == 1 and "mj-sideways" not in html
    state = practice.apply(state, riichi(state.drawn))                # 2 枚目でリーチ → そのあと中をツモ切り、1索 であがり
    html = river_html(state, rb())
    assert html.count("<img ") == 3 and html.count("mj-sideways") == 1 and "横向きの牌でリーチ" in text_of(html)
    assert html.index("mj-sideways") > html.index("<img ")           # 横向きは 2 枚目

    after = riichi_draws_html(state, rb())
    assert "リーチのあとのツモ：2 回目のツモであがり（枠つきの牌）。" in text_of(after)
    assert after.count("<img ") == 2 and after.count("mj-win") == 1 and "★" not in after
    assert riichi_draws_html(start_on(crafted_wall(TENPAI_HAND, "9m4s")), rb()) == ""


def test_riichi_draws_mark_the_tiles_brought_by_luck():
    """リーチのあとのツモにも、ツキ補正で引き寄せた牌に印を付ける（補正を隠さない）"""
    for seed in range(300):
        state = practice.start(PracticeConfig(seed=seed, luck=LuckSettings(100, 100, True)))
        if not state.riichi_discards:
            continue
        state = practice.apply(state, riichi(state.riichi_discards[0]))
        lucky = sum(1 for d in state.draws[1:] if d.luck.swapped)
        if not lucky or state.result.outcome != Outcome.TSUMO:
            continue
        html = riichi_draws_html(state, rb())
        assert html.count('class="mj-star"') == lucky and f"★ は、ツキ補正で引き寄せた牌（{lucky} 枚）" in text_of(html)
        assert "★" not in riichi_draws_html(state, rb(), mark=False)          # 印を付けない設定
        assert "あがり牌も、補正で引き寄せた牌。" in draws_text(state)          # あがり牌が補正で来たことは、まとめにも書く
        check_tile_images(html)
        return
    raise AssertionError("リーチのあとに補正で引いた局が見つからない")


def test_riichi_draws_when_the_winning_tile_never_comes():
    state = start_on(crafted_wall(TENPAI_HAND, "9m5555z6666z7777z1111z2z"))
    state = practice.apply(state, riichi(tile(state, "9m")))
    html = riichi_draws_html(state, rb())
    assert "あがり牌は来なかった" in text_of(html) and html.count("<img ") == 17 and "mj-win" not in html


def test_draw_note_only_for_swapped_draws():
    plain = practice.start(PracticeConfig(seed=3))
    assert draw_note_html(plain.last_draw, rb(), aka=True) == ""
    for seed in range(200):
        state = practice.start(PracticeConfig(seed=seed, luck=LuckSettings(0, 100)))
        if state.last_draw.luck.swapped:
            html = draw_note_html(state.last_draw, rb(), aka=True)
            assert "★" in html and "ツキ補正で引き寄せた牌です" in text_of(html) and "入れ替えなければ" in text_of(html)
            assert html.count("<img ") == 2
            return
    raise AssertionError("補正で入れ替わったツモが見つからない")


# ---------------------------------------------------------------- 受け入れ表


def test_candidates_table_lists_equal_narrower_and_farther_discards():
    pos = position("123m456p789s2s1445z", dora="4z")           # 東がドラ
    html = candidates_html(analyze(pos), rb())
    text = text_of(html)
    assert "1 向聴のままの切り方（受け入れの広い順）" in text
    assert html.count('class="mj-cand mj-cand-pick"') == 1 and html.count('class="mj-cand"') == 2
    assert "○東ドラ6 種 19 枚" in text and "◎白6 種 19 枚" in text     # 速さは同じ。ドラの東は残して、白を勧める
    assert "3 種 7 枚（−12 枚）" in text                       # 2索 切りは、受け入れが少ない
    assert html.count('<span class="mj-badge">ドラ</span>') == 1
    assert "切ると遠ざかる牌（2 向聴になる）" in text and html.count('class="mj-far"') == 10
    assert "役や打点は見ていない" in text and "点線の枠" not in text and "切った牌" not in text

    reviewed = candidates_html(analyze(pos), rb(), chosen_kind=19)       # 2索 を切ったあとの答え合わせ
    assert "mj-cand-you" in reviewed and "切った牌" in text_of(reviewed) and "点線の枠：切った牌" in text_of(reviewed)
    far = candidates_html(analyze(pos), rb(), chosen_kind=30)            # 北（対子）を切った
    assert far.count("mj-far-you") == 1 and "mj-cand-you" not in far


def test_candidates_table_at_tenpai_and_with_dead_waits():
    html = candidates_html(analyze(position(TENPAI_PLUS_ONE)), rb())
    assert "聴牌にとれる切り方（待ちの広い順）" in text_of(html) and "小さい牌が待ち牌" in text_of(html)
    dead = candidates_html(analyze(position("123m456p789s13s44z9m", visible="2222s")), rb())
    assert "聴牌だが残り 0 枚" in text_of(dead) and "mj-acc-dead" in dead


def test_chance_lines_show_the_arithmetic():
    analysis = analyze(position(TWO_SHANTEN))
    text = text_of(chance_html(analysis, rb(), luck_draw=0))
    assert "東切りのあと、有効牌は 16 枚。見えていない牌は 122 枚。" in text
    assert "次のツモで引く確率 ＝ 16 ÷ 122 ＝ 13%" in text
    assert "残り 10 回のツモのうちに 1 回以上引く確率 ＝ 77%" in text
    assert "補正なしの麻雀での確率" not in text
    assert "補正なしの麻雀での確率" in text_of(chance_html(analysis, rb(), luck_draw=25))
    assert "あがり牌は 8 枚" in text_of(chance_html(analyze(position(TENPAI_PLUS_ONE)), rb(), luck_draw=0))
    assert "最後のツモ" in text_of(chance_html(analyze(position(TWO_SHANTEN, draws_left=0)), rb(), luck_draw=0))
    assert chance_html(analyze(position("123m456p789s234s44z")), rb(), luck_draw=0) == ""


def test_percent():
    values = (0, 0.004, 0.01, 0.131, 0.985, 0.99, 0.9901, 0.999, 1)
    assert [percent(v) for v in values] == ["0%", "1% 未満", "1%", "13%", "98%", "99%", "99% 以上", "99% 以上", "100%"]
    # 「100%」と書くのは、本当に確実なときだけ
    wide = analyze(position("2468m2468p2468s11z", draws_left=17))       # 受け入れ 32 枚。17 回で 1 回も引かない確率は 0.4%
    assert 0.99 < wide.within_chance < 1 and "1 回以上引く確率 ＝ 99% 以上" in text_of(chance_html(wide, rb(), luck_draw=0))


# ---------------------------------------------------------------- 待ち


def test_waits_with_the_same_result_are_shown_together():
    html = waits_html(analyze(position(TENPAI_PLUS_ONE)), rb())
    text = text_of(html)
    assert html.count('class="mj-cand"') == 1                      # 1索 でも 4索 でも同じ点なので、1 つにまとめる
    assert text.count("残り 4 枚") == 2 and "9萬 を切ると聴牌" in text
    assert "リーチしない400・700 点ツモ・ピンフ" in text and "リーチする700・1,300 点リーチ・ツモ・ピンフ" in text
    assert "放銃" in text and "一発や裏ドラ" in text
    assert "放銃" not in text_of(waits_html(analyze(position(TENPAI_PLUS_ONE)), rb(), solo=False))
    assert waits_html(analyze(position(TWO_SHANTEN)), rb()) == ""


def test_waits_with_different_results_are_shown_separately():
    # 4索 なら三色同順が付く（高目）、1索 なら付かない（安目）
    html = waits_html(analyze(position("234m234p23s789m44z9p")), rb())
    text = text_of(html)
    assert html.count('class="mj-cand"') == 2 and "サンショク" in text
    assert text.count("リーチしない") == 2
    assert "リーチしない400・700 点ツモ・ピンフ" in text                       # 安目（1索）
    assert "リーチしない1,300・2,600 点ツモ・ピンフ・サンショク" in text       # 高目（4索）
    assert "リーチする満貫 2,000・4,000 点リーチ・ツモ・ピンフ・サンショク" in text


def test_waits_show_limit_hands_and_dead_tiles():
    # 清一色の多面待ち：待ち牌によって、倍満・三倍満・数え役満と変わる
    html = waits_html(analyze(position("22334455667788m", dora="1m")), rb())
    text = text_of(html)
    assert html.count('class="mj-cand"') == 3
    assert "倍満 4,000・8,000 点" in text and "三倍満 6,000・12,000 点" in text and "数え役満 8,000・16,000 点" in text
    # 待ち牌の片方が全部見えている：その牌では、もうあがれない
    html = waits_html(analyze(position(TENPAI_PLUS_ONE, visible="1111s")), rb())
    assert html.count('class="mj-cand"') == 2 and html.count("mj-acc-dead") == 1
    assert "残り 0 枚リーチしない—リーチする—" in text_of(html) and "残り 4 枚リーチしない400・700 点" in text_of(html)
    # 待ち牌がすべて見えている聴牌は、おすすめにならないので、待ちの表も出ない
    assert waits_html(analyze(position("123m456p789s46s44z9m", visible="0555s")), rb()) == ""


# ---------------------------------------------------------------- 分解図


def test_layout_diagram_names_each_group_and_what_it_needs():
    analysis = analyze(position(TWO_SHANTEN))
    normal = layout_html(analysis, rb(), level=LEVEL_NORMAL)
    text = text_of(normal)
    assert normal.count("<img ") == 14 and normal.count('class="mj-block mj-part') == 8
    assert text.count("孤立牌") == 4 and "順子" in text and "対子あと 2筒" in text           # 図に 3 つ＋凡例に 1 つ
    assert "辺張あと 7筒" in text and "両面あと 2索・5索" in text and "両面あと 5索・8索" in text
    assert "mj-part-done" in normal and "mj-part-pair" in normal and "mj-part-wait" in normal and "mj-part-float" in normal
    assert "いちばん進んでいる分け方の 1 つ" in text and "向聴数 ＝" not in text

    full = text_of(layout_html(analysis, rb(), level=LEVEL_FULL))
    assert "向聴数 ＝ 8 − 2 × 面子 1 組 − 搭子 3 組 − 対子 1 組 ＝ 2" in full
    assert "何もそろっていない手を 8 として" in full


def test_layout_diagram_for_other_shapes():
    chiitoi = text_of(layout_html(analyze(position("1133m5577p2299s1z5z")), rb(), level=LEVEL_FULL))
    assert "七対子（対子 7 組）がいちばん近い" in chiitoi and "あと" not in chiitoi and "七対子まで：6 − 対子 6 組 ＝ 0" in chiitoi
    kokushi = text_of(layout_html(analyze(position("19m19p1s12345677z3m")), rb(), level=LEVEL_FULL))
    assert "国士無双（13 種類の么九牌）がいちばん近い" in kokushi
    both = text_of(layout_html(analyze(position("223344m556677p8s1z")), rb(), level=LEVEL_FULL))
    assert "七対子として数えても、同じ聴牌。" in both
    crowded = text_of(layout_html(analyze(position("12m46m89m13p79p2s5s1z5m")), rb(), level=LEVEL_FULL))
    assert "数えすぎ 1 組" in crowded and "4 組までしか数えない" in crowded
    win = text_of(layout_html(analyze(position("123m456p789s234s44z")), rb(), level=LEVEL_FULL))
    assert "向聴数 ＝" not in win


def test_shanten_line():
    assert text_of(shanten_html(analyze(position(TWO_SHANTEN)), rb())) == "2 向聴：聴牌まで、有効牌があと 2 枚。"
    assert text_of(shanten_html(analyze(position(TENPAI_PLUS_ONE)), rb())) == "聴牌：あと 1 枚であがり。"
    assert text_of(shanten_html(analyze(position("123m456p789s234s44z")), rb())) == "和了形：あがりの形になっている。"


# ---------------------------------------------------------------- 局が終わったあと


def exhaust(draws: str, hand: str = TENPAI_HAND):
    state = start_on(crafted_wall(hand, draws))
    while not state.finished:
        state = practice.apply(state, tsumogiri(state))
    return state


def test_exhausted_summary():
    tenpai = exhaust("9m5555z6666z7777z1111z2z")
    html = exhausted_html(tenpai, rb())
    text = text_of(html)
    assert "流局（聴牌）" in text and "待ち：" in text and "ノーテン罰符" in text and html.count("<img ") == 2 + 13
    assert ruby_terms(html)[:2] == ["流局", "聴牌"]                    # 最初に出てくる大きな見出しに、ルビを振る
    noten = exhaust("5555z6666z7777z11122z9m", hand="123m456p789s2s144z")
    text = text_of(exhausted_html(noten, rb()))
    assert "流局（ノーテン・1 向聴）" in text and "18 回ツモってあがれなかったので、流局。" in text


def test_luck_report_texts():
    plain = practice.start(PracticeConfig(seed=20261007))
    assert deal_text(plain) == "配牌：補正なし（山の並びのまま）。"
    assert draws_text(plain) == "ツモ：補正なし（山の順番どおり）。"
    lucky = practice.start(PracticeConfig(seed=20261007, luck=LuckSettings(50, 50)))
    assert deal_text(lucky) == "配牌：候補 16 個から、いちばん良いものを採用。元の配牌は 3 向聴、採用した配牌は 2 向聴。"
    assert draws_text(lucky) == "ツモ：1 回のうち 0 回、補正で有効牌に入れ替えた（1 回ごとに 12% の確率で抽選）。"
    for seed in range(200):                                    # 候補を比べても、元の配牌がいちばん良かった場合
        same = practice.start(PracticeConfig(seed=seed, luck=LuckSettings(25, 0)))
        if not same.deal.applied:
            assert "がいちばん良かったので、そのまま。" in deal_text(same)
            break
    else:
        raise AssertionError("元の配牌が採用された局が見つからない")


def test_hand_summary_and_review_list():
    state = start_on(crafted_wall(TENPAI_HAND, "5z6z7z1s"))
    decisions = []
    for make in (lambda s: discard(tile(s, "2s")), lambda s: discard(s.drawn), lambda s: discard(s.drawn)):
        action = make(state)
        decisions.append(practice.assess(state, action))
        state = practice.apply(state, action)
    html = hand_summary_html(state, decisions, rb(), counted=True)
    text = text_of(html)
    assert "ツキ補正なし（通常の麻雀）" in text and "局の番号 0" in text
    assert "打牌：自分で選んだ 3 回のうち、いちばん速い打牌は 2 回（67%）。" in text
    assert "成績には入れていない" not in text
    assert "成績には入れていない" in text_of(hand_summary_html(state, decisions, rb(), counted=False))
    assert "打牌：" not in text_of(hand_summary_html(state, [], rb(), counted=True))
    assert "ヒントあり" not in text and "ヒントあり" in text_of(hand_summary_html(state, decisions, rb(), counted=True, hinted=True))

    review = review_list_html(decisions, rb(), aka=True)
    rows = text_of(review)
    assert review.count("<tr") == 4 and "1✗ 聴牌をくずしたおすすめは" in rows
    assert rows.count("✓") == 2 and rows.count("おすすめは") == 1          # 良かった打牌には、別の牌を勧めない
    assert "自分で選んだ打牌はありません" in text_of(review_list_html([], rb(), aka=True))
    check_html(review)


# ---------------------------------------------------------------- 設定の説明と成績


def test_luck_explanations():
    assert text_of(luck_now_html(0, 0, rb())) == "配牌：補正なし（山の並びのまま）ツモ：補正なし（山の順番どおり）"
    text = text_of(luck_now_html(75, 50, rb()))
    assert "配牌：64 個の候補から、いちばん良い配牌を採用する" in text
    assert "ツモ：1 回ごとに 12% の確率で、有効牌を次のツモに持ってくる" in text
    guide = text_of(luck_guide_html(rb()))
    assert "なし（0）3.5 向聴16%14 巡目" in guide.replace("3.6", "3.5") and "最大（100）1.2 向聴96%4 巡目" in guide
    assert "各 300 局" in guide
    check_html(luck_guide_html(rb()))
    # いちばん弱い補正でも「補正なし」とは書かない（実際に候補を 2 個作って比べるので）
    weak = text_of(luck_now_html(5, 5, rb()))
    assert "配牌：2 個の候補から" in weak and "ツモ：1 回ごとに 1% の確率で" in weak


def test_setting_notes_and_help_give_ruby_on_first_appearance():
    """入力欄の名前にはルビを振れないので、そばに置く説明文のほうで振る"""
    ruby = rb()
    head = subhead_html("ツキ補正", "配牌とツモの「引きの良さ」を上げます。", ruby)
    assert text_of(head) == "ツキ補正配牌とツモの「引きの良さ」を上げます。" and ruby_terms(head) == ["配牌"]
    assert ruby_terms(note_html("配牌の候補のうち、最初から聴牌しているものは、ふつう採用しません。", ruby)) == ["聴牌"]   # 配牌は 2 回目
    assert text_of(subhead_html("コーチ", "", ruby)) == "コーチ"
    help_page = help_html(rb())
    check_html(help_page)
    assert {"聴牌", "流局", "配牌"} <= set(ruby_terms(help_page)) and len(ruby_terms(help_page)) == len(set(ruby_terms(help_page)))
    assert "白（ハク）" in text_of(help_page) and "ツモは 18 回まで" in text_of(help_page)


def summary(**kwargs) -> Summary:
    base = {"deal": 0, "draw": 0, "hinted": False, "hands": 10, "wins": 2, "win_turns": 26, "win_points": 6000, "riichi": 3, "tenpai": 5, "decisions": 100, "best": 80}
    return Summary(**{**base, **kwargs})


def test_stats_table_puts_the_plain_unhinted_game_first_as_skill():
    assert "まだ記録がありません" in text_of(stats_html([], rb()))
    rows = [
        summary(),
        summary(hinted=True, hands=3, wins=3, win_turns=21, win_points=9000, decisions=30, best=30),
        summary(deal=75, draw=75, hands=4, wins=4, win_turns=28, win_points=32000, decisions=0, best=0),
        summary(deal=75, draw=75, hinted=True, hands=2, wins=1, win_turns=5, win_points=1000, decisions=9, best=9),
    ]
    html = stats_html(rows, rb())
    text = text_of(html)
    assert html.index("なし（実力）") < html.index("配牌 75・ツモ 75") and html.count('class="mj-skill"') == 1
    assert "なし（実力）1020%13.03,00080%" in text
    assert "なしヒントあり3100%7.03,000—" in text                 # 補正なしでも、ヒントを見た局は「実力」に入れない
    assert "配牌 75・ツモ 754100%7.08,000—" in text               # 自分で選んだ打牌が無ければ「—」
    assert "配牌 75・ツモ 75ヒントあり250%5.01,000—" in text      # ヒントを見た局は、打牌の割合を数えない
    assert "実力として見るのは「なし（実力）」の行" in text and "「ヒントあり」は、打つ前のヒント" in text
    lost = text_of(stats_html([summary(wins=0, win_turns=0, win_points=0)], rb()))
    assert "なし（実力）100%——80%" in lost
    check_html(html)

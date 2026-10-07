"""ドリル（問題づくりと採点）のテスト。

正解は、点数計算・向聴数・牌効率のエンジンで確かめ直す。早見表の点は、よく知られた値を手で書いて照らす。
"""
import pytest

from engine import drills
from engine.analysis.waits import wait_kinds
from engine.coach import analyze
from engine.content import glossary, yaku_pages
from engine.drills import (
    DONE,
    KINDS,
    NEW,
    REVIEW,
    WIN_FURITEN,
    WIN_NO_SHAPE,
    WIN_NO_YAKU,
    WIN_YES,
    Choice,
    Question,
    early_item,
    furiten_kinds,
    grade,
    grade_discard,
    han_label,
    is_item,
    items_of,
    new_item,
    next_item,
    pay_text,
    progress_of,
    question,
    rule_notes,
    win_class,
)
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.decompose import Form
from engine.scoring.explain import Status, explain
from engine.srs import DAY, MAX_BOX, Card, Deck
from engine.tiles import counts34, kind_of
from engine.yaku_table import YAKU

NOW = 1_800_000_000
GENERATED = [key for key, kind in KINDS.items() if not kind.finite]
FINITE = [key for key, kind in KINDS.items() if kind.finite]
SEEDS = {"score": 120, "fu": 120, "yaku": 120, "win": 200, "wait": 120, "discard": 30}


def all_questions(kind: str) -> list[Question]:
    if KINDS[kind].finite:
        return [question(kind, item) for item in items_of(kind)]
    return [question(kind, str(seed)) for seed in range(SEEDS[kind])]


# ---------------------------------------------------------------- 全種類に共通


def test_kinds_are_listed_in_learning_order():
    assert list(KINDS) == ["reading", "han", "valid", "yaku", "win", "wait", "fu", "table", "score", "discard"]
    assert sorted(FINITE) == ["han", "reading", "table", "valid"]
    for kind in KINDS.values():
        assert kind.name and kind.short and kind.group in drills.GROUPS
    # 仕様の 7-3 にある種類（危険牌の判断だけは、相手のいる対局ができてから）
    names = {kind.name for kind in KINDS.values()}
    assert {"役の判定", "成立・不成立", "役の翻数", "符の計算", "点数計算", "何切る", "用語の読み", "点数早見"} <= names


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_question_is_well_formed(kind):
    questions = all_questions(kind)
    assert questions
    for q in questions:
        where = f"{kind}:{q.item}"
        assert q.kind == kind and q.prompt and q.answer, where
        assert all(isinstance(line, str) and line.strip() for line in q.answer), where
        if kind == "discard":
            assert not q.choices and q.position is not None and q.correct, where
            continue
        keys = [c.key for c in q.choices]
        labels = [c.label for c in q.choices]
        assert len(keys) >= 2, where
        assert len(set(keys)) == len(keys), where
        assert len(set(labels)) == len(labels), where       # 同じ見た目の選択肢が 2 つあってはいけない
        assert q.correct and q.correct <= set(keys), where
        assert q.multi or len(q.correct) == 1, where
        assert q.multi == (kind in ("yaku", "wait")), where


@pytest.mark.parametrize("kind", GENERATED)
def test_generated_questions_are_reproducible(kind):
    maker = drills._MAKERS[kind]
    for seed in ("0", "7", "123456789"):
        assert maker(seed) == maker(seed)
    assert maker("1") != maker("2")
    assert question(kind, "5") is question(kind, "5")         # 同じ問題は、作り直さない


@pytest.mark.parametrize("kind", list(KINDS))
def test_unknown_items_are_refused(kind):
    for bad in ("", "no such item", "１２", "-1", "1.5", "1" * 12):
        with pytest.raises(ValueError):
            question(kind, bad)
        assert not is_item(kind, bad)
    assert not is_item(kind, None)
    assert not is_item("nope", "1")
    with pytest.raises(ValueError):
        question("nope", "1")
    with pytest.raises(ValueError):
        items_of("nope")


def test_items_of_and_new_item():
    for kind in GENERATED:
        assert items_of(kind) == ()
        item = new_item(kind, 987_654_321_012)
        assert is_item(kind, item) and item.isdigit()
    for kind in FINITE:
        items = items_of(kind)
        assert len(items) == len(set(items)) > 30
        assert all(is_item(kind, item) for item in items)
        with pytest.raises(ValueError):
            new_item(kind, 1)


# ---------------------------------------------------------------- 採点


def _q(multi=False, correct=("a",)) -> Question:
    choices = tuple(Choice(key, key.upper()) for key in "abcd")
    return Question("yaku" if multi else "han", "x", "?", choices, frozenset(correct), multi=multi, answer=("…",))


def test_grade_single_choice():
    q = _q()
    assert grade(q, ["a"]).correct
    wrong = grade(q, {"b"})
    assert not wrong.correct
    assert [c.key for c in wrong.missed] == ["a"] and [c.key for c in wrong.extra] == ["b"]
    with pytest.raises(ValueError):
        grade(q, ["a", "b"])
    with pytest.raises(ValueError):
        grade(q, [])
    with pytest.raises(ValueError):
        grade(q, ["z"])


def test_grade_multi_needs_exactly_the_right_set():
    q = _q(multi=True, correct=("a", "c"))
    assert grade(q, ["c", "a"]).correct
    part = grade(q, ["a"])
    assert not part.correct and [c.key for c in part.missed] == ["c"] and part.extra == ()
    over = grade(q, ["a", "c", "d"])
    assert not over.correct and [c.key for c in over.extra] == ["d"] and over.missed == ()
    nothing = grade(q, [])
    assert not nothing.correct and len(nothing.missed) == 2


# ---------------------------------------------------------------- 点数早見


def answer_of(item: str) -> str:
    q = question("table", item)
    return q.choice(next(iter(q.correct))).label


#: よく知られた点数表（手で書いたもの）。子ロン・親ロン・子ツモ・親ツモ
KNOWN = {
    "cr": {30: ["1,000 点", "2,000 点", "3,900 点", "7,700 点"], 40: ["1,300 点", "2,600 点", "5,200 点", "8,000 点"]},
    "pr": {30: ["1,500 点", "2,900 点", "5,800 点", "11,600 点"], 40: ["2,000 点", "3,900 点", "7,700 点", "12,000 点"]},
    "ct": {
        30: ["300・500 点", "500・1,000 点", "1,000・2,000 点", "2,000・3,900 点"],
        40: ["400・700 点", "700・1,300 点", "1,300・2,600 点", "2,000・4,000 点"],
    },
    "pt": {
        30: ["500 点オール", "1,000 点オール", "2,000 点オール", "3,900 点オール"],
        40: ["700 点オール", "1,300 点オール", "2,600 点オール", "4,000 点オール"],
    },
}
KNOWN_LEVELS = {
    "cr": ["8,000 点", "12,000 点", "16,000 点", "24,000 点", "32,000 点"],
    "pr": ["12,000 点", "18,000 点", "24,000 点", "36,000 点", "48,000 点"],
    "ct": ["2,000・4,000 点", "3,000・6,000 点", "4,000・8,000 点", "6,000・12,000 点", "8,000・16,000 点"],
    "pt": ["4,000 点オール", "6,000 点オール", "8,000 点オール", "12,000 点オール", "16,000 点オール"],
}
KNOWN_SPECIAL = {
    "ct:20:2": "400・700 点", "ct:20:3": "700・1,300 点", "ct:20:4": "1,300・2,600 点",
    "pt:20:2": "700 点オール", "pt:20:3": "1,300 点オール", "pt:20:4": "2,600 点オール",
    "cr:25:2": "1,600 点", "cr:25:3": "3,200 点", "cr:25:4": "6,400 点",
    "pr:25:2": "2,400 点", "pr:25:3": "4,800 点", "pr:25:4": "9,600 点",
    "ct:25:3": "800・1,600 点", "ct:25:4": "1,600・3,200 点",
    "pt:25:3": "1,600 点オール", "pt:25:4": "3,200 点オール",
}


def test_table_answers_match_the_well_known_score_table():
    for situation, rows in KNOWN.items():
        for fu, row in rows.items():
            for han, expected in enumerate(row, start=1):
                assert answer_of(f"{situation}:{fu}:{han}") == expected, (situation, fu, han)
    for situation, row in KNOWN_LEVELS.items():
        for level, expected in zip(("mangan", "haneman", "baiman", "sanbaiman", "yakuman"), row, strict=True):
            assert answer_of(f"{situation}:{level}") == expected, (situation, level)
    for item, expected in KNOWN_SPECIAL.items():
        assert answer_of(item) == expected, item


def test_table_covers_the_spec_and_nothing_impossible():
    items = items_of("table")
    # 30 符・40 符の 1〜4 翻（子・親 × ロン・ツモ）と、満貫以上
    for situation in ("cr", "pr", "ct", "pt"):
        for fu in (30, 40):
            for han in (1, 2, 3, 4):
                assert f"{situation}:{fu}:{han}" in items
        for level in ("mangan", "haneman", "baiman", "sanbaiman", "yakuman"):
            assert f"{situation}:{level}" in items
    assert set(KNOWN_SPECIAL) == {item for item in items if item.split(":")[1] in ("20", "25")}
    assert len(items) == 32 + 20 + 9 + 16
    # 20 符のロン、25 符 1 翻、25 符 2 翻のツモは、実際には無い
    for impossible in ("cr:20:2", "pr:20:3", "cr:25:1", "ct:25:2", "ct:20:1"):
        assert impossible not in items
    assert not drills.combo_exists(20, 2, False) and drills.combo_exists(20, 2, True)
    assert not drills.combo_exists(25, 2, True) and drills.combo_exists(25, 2, False)


def test_table_level_names():
    expected = {5: "満貫", 6: "跳満", 7: "跳満", 8: "倍満", 9: "倍満", 10: "倍満", 11: "三倍満", 12: "三倍満", 13: "数え役満"}
    for han, name in expected.items():
        q = question("table", f"lv:{han}")
        assert q.correct == {name}
        assert [c.label for c in q.choices] == ["満貫", "跳満", "倍満", "三倍満", "数え役満"]
    assert any("ルールによって異なる" in line for line in question("table", "lv:13").answer)


def test_table_choices_look_alike_and_are_sorted():
    for q in all_questions("table"):
        if q.item.startswith("lv:"):
            continue
        labels = [c.label for c in q.choices]
        assert len(labels) == 4, q.item
        situation = q.item.split(":")[0]
        if situation == "ct":
            assert all("・" in label for label in labels), q.item
        elif situation == "pt":
            assert all(label.endswith("オール") for label in labels), q.item
        else:
            assert all("・" not in label and "オール" not in label for label in labels), q.item
        assert all("満貫" not in label and "役満" not in label for label in labels), q.item     # 呼び名で答えが分からないように
        # 「1,000 点」「300・500 点」「500 点オール」：最後の数字（親が払う点）で比べる
        amounts = [int(label.replace(",", "").replace("・", " ").split()[-2]) for label in labels]
        assert amounts == sorted(amounts), q.item
        assert all(c.why for c in q.choices), q.item


def test_table_explains_rule_differences():
    for item in ("cr:30:4", "pr:30:4", "ct:30:4", "pt:30:4"):
        assert any("切り上げ満貫" in line for line in question("table", item).answer), item
    assert "8,000 点" in " ".join(question("table", "cr:30:4").answer)
    assert "2,000・4,000 点" in " ".join(question("table", "ct:30:4").answer)
    assert not any("切り上げ満貫" in line for line in question("table", "cr:30:3").answer)


def test_table_rows_for_the_reference_table():
    assert drills.table_row(30, dealer=False, tsumo=False) == ((1, "1,000 点"), (2, "2,000 点"), (3, "3,900 点"), (4, "7,700 点"))
    assert drills.table_row(40, dealer=True, tsumo=False)[-1] == (4, "12,000 点（満貫）")
    assert [han for han, _ in drills.table_row(20, dealer=False, tsumo=True)] == [2, 3, 4]
    assert drills.table_row(20, dealer=False, tsumo=False) == ()
    assert drills.level_row(dealer=False, tsumo=False)[0] == ("満貫", "8,000 点")
    assert drills.level_row(dealer=True, tsumo=True)[-1] == ("役満", "16,000 点オール")


# ---------------------------------------------------------------- 点数計算・符・役の判定


def test_score_answers_come_from_the_scoring_engine():
    for q in all_questions("score"):
        ctx = q.ctx
        assert ctx is not None and ctx.honba == 0 and ctx.kyotaku == 0
        result = explain(ctx)
        assert result.status is Status.WIN and result.consistent
        points = result.best.points
        expected = pay_text(points, tsumo=ctx.is_tsumo, dealer=ctx.is_dealer)
        assert q.correct == {expected}, q.item
        assert len(q.choices) == 4
        assert all(c.why for c in q.choices)
        if ctx.is_tsumo and not ctx.is_dealer:
            assert all("・" in c.label for c in q.choices), q.item


def test_score_distractors_are_near_the_answer():
    seen_levels = set()
    for q in all_questions("score"):
        index = [c.key for c in q.choices].index(next(iter(q.correct)))
        seen_levels.add(index)
    assert seen_levels == {0, 1, 2, 3}          # 正解の位置（小さい順に並べたとき）が、かたよらない


def test_fu_answers_come_from_the_scoring_engine():
    values = set()
    for q in all_questions("fu"):
        result = explain(q.ctx)
        best = result.best
        assert best is not None and not best.is_yakuman and best.interp.form is not Form.KOKUSHI
        assert q.correct == {str(best.fu.fu)}, q.item
        numbers = [int(c.key) for c in q.choices]
        assert numbers == sorted(numbers) and len(numbers) == 4
        assert all(c.label == f"{c.key} 符" for c in q.choices)
        if best.interp.form is Form.CHIITOI:
            assert best.fu.fu == 25
        values.add(best.fu.fu)
    assert {25, 30, 40, 50} <= values
    # 25 符が選択肢にあっても、答えとは限らない（七対子でない手にも混ぜてある）
    with_25 = [q for q in all_questions("fu") if "25" in {c.key for c in q.choices}]
    assert any(q.correct != {"25"} for q in with_25) and any(q.correct == {"25"} for q in with_25)


def test_yaku_answers_come_from_the_scoring_engine():
    order = list(YAKU)
    sizes = set()
    for q in all_questions("yaku"):
        result = explain(q.ctx)
        best = result.best
        counted = {item.key for item in best.evaluation.yaku}
        assert q.correct == counted, q.item
        keys = [c.key for c in q.choices]
        assert keys == sorted(keys, key=order.index), q.item
        assert 6 <= len(keys) <= 8, q.item
        for choice in q.choices:
            check = result.yaku_check(choice.key)
            assert check is not None
            assert check.ok == (choice.key in counted), (q.item, choice.key)     # 条件を満たしているのに数えない役は、選択肢に入れない
            assert choice.why, (q.item, choice.key)
        sizes.add(len(counted))
    assert {1, 2, 3} <= sizes


def test_yaku_labels_name_the_wind():
    seen = set()
    for q in all_questions("yaku"):
        for choice in q.choices:
            if choice.key == "yakuhai_seat":
                assert choice.label.startswith("自風牌（") and choice.label[4] in "東南西北"
                seen.add("seat")
            if choice.key == "yakuhai_round":
                assert choice.label.startswith("場風牌（")
                seen.add("round")
    assert seen == {"seat", "round"}


# ---------------------------------------------------------------- 成立・不成立


def test_valid_items_cover_every_structural_page():
    items = items_of("valid")
    pages = {item.split(":")[0] for item in items}
    expected = {page.key for page in yaku_pages() if page.key not in drills.SITUATION_PAGES}
    assert pages == expected
    assert len(items) >= 110
    assert sum(1 for item in items if ":e" in item) >= 50 and sum(1 for item in items if ":t" in item) >= 50


def test_valid_answers_come_from_the_scoring_engine():
    for q in all_questions("valid"):
        page = next(p for p in yaku_pages() if p.key == q.page)
        result = explain(q.ctx, q.rules)
        counted = {item.key for item in result.best.evaluation.yaku} if result.status is Status.WIN else set()
        has = bool(counted & set(page.yaku))
        assert q.correct == {"yes" if has else "no"}, q.item
        if not has:         # 「付かない」の問題では、条件を満たしている役が 1 つも無い（上位の役に化けただけの例は使わない）
            for key in page.yaku:
                check = result.yaku_check(key)
                assert check is None or not check.ok, (q.item, key)
        assert page.name in q.prompt
        assert q.rule_notes == rule_notes(q.rules)


def test_valid_shows_rules_that_differ_from_the_default():
    noted = [q for q in all_questions("valid") if q.rule_notes]
    assert noted, "ルールを変えた例（喰いタンなし、など）が 1 つはあるはず"
    for q in noted:
        assert q.rules != DEFAULT_RULES


def test_rule_notes():
    assert rule_notes(DEFAULT_RULES) == ()
    assert rule_notes(Rules(kuitan=False)) == ("喰いタンなし",)
    assert rule_notes(Rules(aka_dora=False, kiriage_mangan=True, double_wind_pair_fu=2, double_yakuman=False, kazoe_yakuman=False)) == (
        "赤ドラなし", "切り上げ満貫あり", "連風牌の雀頭は 2 符", "ダブル役満なし", "数え役満なし（三倍満まで）",
    )


# ---------------------------------------------------------------- あがれる？


def test_win_answers_come_from_the_engine_and_all_classes_appear():
    classes = {}
    for q in all_questions("win"):
        ctx, river = q.ctx, q.river
        assert ctx is not None and river is not None
        kind = next(iter(q.correct))
        assert win_class(ctx, river) == kind, q.item
        assert [c.key for c in q.choices] == [WIN_YES, WIN_NO_YAKU, WIN_NO_SHAPE, WIN_FURITEN]
        status = explain(ctx).status
        in_river = furiten_kinds(ctx, river)
        if kind == WIN_YES:
            assert status is Status.WIN and (ctx.is_tsumo or not in_river), q.item
        elif kind == WIN_NO_YAKU:
            assert status is Status.NO_YAKU and not in_river, q.item      # 理由が 2 つ重なる問題は作らない
        elif kind == WIN_NO_SHAPE:
            assert status is Status.NOT_WINNING and not in_river, q.item
        else:
            assert status is Status.WIN and not ctx.is_tsumo and in_river, q.item
        assert ("ツモ" if ctx.is_tsumo else "ロン") in q.prompt
        classes.setdefault(kind, []).append(q)
    assert set(classes) == {WIN_YES, WIN_NO_YAKU, WIN_NO_SHAPE, WIN_FURITEN}
    assert all(len(found) >= 15 for found in classes.values()), {k: len(v) for k, v in classes.items()}
    # フリテンでもツモならあがれる、という問題がある
    assert any(q.ctx.is_tsumo and furiten_kinds(q.ctx, q.river) for q in classes[WIN_YES])
    # 鳴いた手・門前の手、ロン・ツモの両方がある
    assert {q.ctx.is_menzen for q in classes[WIN_NO_YAKU]} == {True, False}
    assert {q.ctx.is_tsumo for q in classes[WIN_YES]} == {True, False}
    # フリテンは、あがり牌と別の待ち牌が河にある形も出す
    assert any(q.ctx.win_kind not in furiten_kinds(q.ctx, q.river) for q in classes[WIN_FURITEN])


def test_win_rivers_use_real_spare_tiles():
    for q in all_questions("win"):
        ctx, river = q.ctx, q.river
        assert 6 <= len(river) <= 13, q.item
        used = [*ctx.all_tiles, *ctx.dora_indicators, *river]
        assert len(set(used)) == len(used), q.item          # 同じ牌を 2 回使っていない
        assert all(count <= 4 for count in counts34(used)), q.item
        assert not ctx.ura_indicators and ctx.honba == 0


def test_win_explains_the_reason():
    seen = set()
    for q in all_questions("win"):
        kind = next(iter(q.correct))
        text = " ".join(q.answer)
        if kind == WIN_FURITEN:
            assert "フリテン" in text and "ツモなら" in text
        elif kind == WIN_NO_SHAPE:
            assert "チョンボ" in text and "待ち" in text
        elif kind == WIN_NO_YAKU:
            assert "役が 1 つも無い" in text
        else:
            assert "申告" in text
        seen.add(kind)
    assert len(seen) == 4


# ---------------------------------------------------------------- 待ち・何切る


def test_wait_answers_come_from_the_shanten_engine():
    sizes = set()
    for q in all_questions("wait"):
        assert len(q.hand) == 13
        waits = wait_kinds(q.hand)
        assert q.correct == {str(k) for k in waits}, q.item
        kinds = [int(c.key) for c in q.choices]
        assert kinds == sorted(kinds) and 6 <= len(kinds) <= 9, q.item
        assert all(c.tile == int(c.key) for c in q.choices)
        counts = counts34(q.hand)
        for choice in q.choices:
            if choice.key in q.correct:
                assert choice.why, (q.item, choice.label)       # 待ちの形の名前を説明する
            else:
                assert not choice.why and counts[int(choice.key)] < 4
        sizes.add(len(waits))
    assert {1, 2, 3} <= sizes


def test_discard_answers_come_from_the_coach():
    for q in all_questions("discard"):
        position = q.position
        assert len(position.tiles) == 14 and not position.can_riichi
        analysis = analyze(position)
        assert not analysis.can_win and not analysis.last_discard
        best = {c.kind for c in analysis.best}
        assert q.correct == {str(k) for k in best}
        assert len(best) < len(analysis.candidates)             # どれを切っても同じ、という問題は出さない
        # ドラ（赤い 5・表示牌の次の牌）を切るのが正解、という問題も出さない（速さだけの問題で、打点を捨てる癖を付けないため）
        assert not any(c.dora for c in analysis.best)
        assert q.river is not None and set(q.river) <= set(position.visible)
        for tile in position.tiles:
            correct, verdict, _ = grade_discard(q, tile)
            assert correct == (kind_of(tile) in best) == verdict.is_best
        assert not any("リーチ" in reason for tile in position.tiles for reason in grade_discard(q, tile)[1].reasons)


def test_grade_discard_needs_a_discard_question():
    with pytest.raises(ValueError):
        grade_discard(question("table", "cr:30:1"), 0)


# ---------------------------------------------------------------- 翻数・読み


def test_han_labels():
    pages = {page.key: page for page in yaku_pages()}
    expected = {
        "riichi": "1 翻（門前限定）",
        "pinfu": "1 翻（門前限定）",
        "tanyao": "1 翻（鳴いても同じ）",
        "yakuhai": "1 翻（鳴いても同じ）",
        "chiitoitsu": "2 翻（門前限定）",
        "toitoi": "2 翻（鳴いても同じ）",
        "sanshoku": "2 翻（鳴くと 1 翻）",
        "ittsu": "2 翻（鳴くと 1 翻）",
        "ryanpeikou": "3 翻（門前限定）",
        "honitsu": "3 翻（鳴くと 2 翻）",
        "chinitsu": "6 翻（鳴くと 5 翻）",
        "kokushi": "役満（門前限定）",
        "suuankou": "役満（門前限定）",
        "daisangen": "役満（鳴いても成立）",
        "daisuushii": "役満（鳴いても成立）",
    }
    for key, label in expected.items():
        assert han_label(pages[key]) == label, key
        q = question("han", f"h:{key}")
        assert q.correct == {label} and len(q.choices) == 4 and q.page == key
    assert len(items_of("han")) == len([p for p in yaku_pages() if p.yaku]) == 38
    assert "h:nagashi_mangan" not in items_of("han")


def test_han_questions_follow_the_yaku_table_and_note_rule_differences():
    for q in all_questions("han"):
        page = next(p for p in yaku_pages() if p.key == q.page)
        info = YAKU[page.yaku[0]]
        label = next(iter(q.correct))
        assert ("門前限定" in label) == info.closed_only
        assert ("鳴くと" in label) == info.kuisagari
        assert label.startswith("役満") == bool(info.yakuman)
        labels = [c.label for c in q.choices]
        assert labels == sorted(labels, key=drills._han_rank)
    assert any("喰いタン" in line for line in question("han", "h:tanyao").answer)
    for key in ("kokushi", "suuankou", "chuuren", "daisuushii"):
        assert any("ダブル役満" in line and "ルールによって異なる" in line for line in question("han", f"h:{key}").answer), key
    assert not any("ダブル役満" in line for line in question("han", "h:daisangen").answer)


def test_reading_items_are_hard_words_only():
    items = drills._reading_items()
    assert len(items) >= 110
    words = {word for word, _, _, _ in items.values()}
    for must in ("立直", "自摸", "栄和", "聴牌", "向聴", "面子", "雀頭", "順子", "刻子", "槓子", "両面", "嵌張", "辺張", "単騎", "双碰",
                 "么九牌", "中張牌", "振聴", "河", "王牌", "嶺上牌"):
        assert must in words, must          # 仕様の 7-2 にある用語
    for plain in ("山", "親", "待ち", "ドラ", "受け入れ", "東・南・西・北", "4 面子 1 雀頭"):
        assert plain not in words, plain
    assert "断么九" in words and "国士無双" in words


def test_reading_answers_match_the_glossary_and_the_yaku_table():
    terms = {term.term: term for term in glossary().terms}
    pages = {page.key: page for page in yaku_pages()}
    all_readings = {reading for _, reading, _, _ in drills._reading_items().values()}
    for q in all_questions("reading"):
        answer = next(iter(q.correct))
        if q.item.startswith("t:"):
            assert answer == terms[q.term].reading and q.term == q.item[2:]
        else:
            assert answer == pages[q.page].reading.replace(" ", "")
        assert len(q.choices) == 4
        for choice in q.choices:
            assert choice.key in all_readings
            assert bool(choice.why) == (choice.key != answer)          # はずれには「どの言葉の読みか」を添える
        assert f"（{answer}）" in q.answer[0]


def test_reading_choices_are_not_always_in_the_same_place():
    places = {[c.key for c in q.choices].index(next(iter(q.correct))) for q in all_questions("reading")}
    assert places == {0, 1, 2, 3}


# ---------------------------------------------------------------- 出題の順番と進み具合


def test_next_item_reviews_first_then_new_then_done():
    items = items_of("han")
    deck = Deck()
    first, why = next_item("han", deck, NOW, pick=3)
    assert why == NEW and first in items
    assert next_item("han", deck, NOW, pick=3)[0] == first               # 同じ乱数なら同じ問題
    assert {next_item("han", deck, NOW, pick=n)[0] for n in range(60)} > {first}

    deck = deck.review(first, False, NOW)
    assert next_item("han", deck, NOW, pick=1)[1] == NEW                 # まだ復習の時刻ではない
    item, why = next_item("han", deck, NOW + 601, pick=1)
    assert (item, why) == (first, REVIEW)
    other, why = next_item("han", deck, NOW + 601, pick=1, skip={first})  # 直前に出した問題は続けて出さない
    assert why == NEW and other != first

    for item in items:
        deck = deck.review(item, True, NOW)
    assert next_item("han", deck, NOW + 60, pick=5) == (None, DONE)      # すべて出し終えて、復習待ち
    assert next_item("han", deck, NOW + 3 * DAY, pick=5)[1] == REVIEW


def test_next_item_never_repeats_a_seen_item_as_new():
    items = items_of("table")
    deck = Deck()
    shown = []
    for step in range(len(items)):
        item, why = next_item("table", deck, NOW, pick=step * 7919)
        assert why == NEW and item not in shown
        shown.append(item)
        deck = deck.review(item, True, NOW)
    assert sorted(shown) == sorted(items)


def test_next_item_for_generated_kinds():
    deck = Deck()
    item, why = next_item("score", deck, NOW, pick=424242)
    assert (item, why) == ("424242", NEW)
    deck = deck.review("77", False, NOW, keep=False).review("88", True, NOW, keep=False)
    assert next_item("score", deck, NOW + 600, pick=1) == ("77", REVIEW)
    assert next_item("score", deck, NOW + 600, pick=1, skip={"77"}) == ("1", NEW)


def test_items_that_no_longer_exist_are_skipped():
    """役図鑑の例を入れ替えると、保存してあった記録に、いまは無い問題の鍵が残る"""
    deck = Deck({"gone:t9": Card(0, NOW - 5, 1, 0, NOW - 700), "tanyao:t0": Card(0, NOW - 1, 1, 0, NOW - 700)})
    assert next_item("valid", deck, NOW, pick=1) == ("tanyao:t0", REVIEW)
    assert early_item("valid", Deck({"gone:t9": Card(0, NOW + 5, 1, 0, NOW)})) is None
    progress = progress_of("valid", deck, NOW)
    assert (progress.due, progress.seen) == (1, 1)


def test_early_item_picks_the_weakest_card():
    deck = Deck(
        {
            "h:riichi": Card(3, NOW + 500, 3, 3, NOW),
            "h:pinfu": Card(1, NOW + 900, 2, 1, NOW),
            "h:tanyao": Card(1, NOW + 700, 2, 1, NOW),
        }
    )
    assert early_item("han", deck) == "h:tanyao"
    assert early_item("han", deck, skip={"h:tanyao"}) == "h:pinfu"
    assert early_item("han", Deck()) is None


def test_progress_of_finite_and_generated_kinds():
    total = len(items_of("han"))
    deck = Deck(
        {
            "h:riichi": Card(3, NOW + 500, 3, 3, NOW),
            "h:pinfu": Card(0, NOW - 10, 2, 1, NOW - 700),
            "h:tanyao": Card(MAX_BOX, NOW + 99999, 9, 9, NOW),
            "h:ittsu": Card(1, NOW + 100, 2, 1, NOW),
        },
        answered=16,
        right=14,
    )
    progress = progress_of("han", deck, NOW)
    assert (progress.total, progress.seen, progress.learned) == (total, 4, 2)
    assert (progress.due, progress.waiting, progress.next_due) == (1, 2, NOW + 100)
    assert progress.accuracy == pytest.approx(14 / 16)

    empty = progress_of("score", Deck(), NOW)
    assert (empty.total, empty.seen, empty.due, empty.waiting, empty.next_due, empty.accuracy) == (None, 0, 0, 0, None, None)
    missed = progress_of("score", Deck().review("5", False, NOW, keep=False), NOW)
    assert (missed.due, missed.waiting, missed.next_due) == (0, 1, NOW + 600)

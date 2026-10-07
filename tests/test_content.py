"""役図鑑のデータ（data/yaku.yaml・data/yaku_stats.yaml）のテスト。

図鑑に載せる手は、すべて点数計算にかけて確かめる。
    * 成立例には、必ずその役が付く（自前の計算と判定ライブラリの両方で）
    * ひっかけ例には、その役が付かない。実際の結果（ほかの役であがれる／役なし／形になっていない）も書いたとおり
    * 「複合しやすい」と書いた組は、実際に同時に付く手がある
    * 「複合しない」と書いた組は、成立例・例題・ランダムな和了形のどれにも同時に付いていない
"""
from __future__ import annotations

from functools import cache

import pytest

from engine import content
from engine.content import ContentError
from engine.scoring.examples import EXAMPLES
from engine.scoring.explain import Explanation, Status, explain
from engine.scoring.notation import make_context
from engine.scoring.random_hand import random_win
from engine.tiles import counts34, is_yaochu_kind, kind_of, parse_tiles
from engine.yaku_table import YAKU

PAGES = content.yaku_pages()
PAGE_OF = content.page_of_yaku()
EXAMPLE_CASES = [(page, hand) for page in PAGES for hand in page.examples]
TRAP_CASES = [(page, trap) for page in PAGES for trap in page.traps]

#: 「複合しやすい」と書いた組のうち、図鑑の成立例に出てこないものを、ここの手で確かめる
COMBO_DEMOS: dict[tuple[str, str], dict] = {
    ("chanta", "honitsu"): dict(hand="123m789m111z12m44z", win="3m"),
    ("chanta", "sanshoku"): dict(hand="123m123p12s789m44z", win="3s"),
    ("chanta", "shousangen"): dict(hand="77z123m78p", win="9p", melds=["pon 555z", "pon 666z"]),
    ("chiitoitsu", "honitsu"): dict(hand="1199m3355m77m11z2z", win="2z"),
    ("chinitsu", "iipeikou"): dict(hand="112233m456m789m9m", win="9m"),
    ("chinitsu", "tanyao"): dict(hand="223344m567m678m5m", win="5m"),
    ("honitsu", "honroutou"): dict(hand="111z33z44z", win="3z", melds=["pon 111m", "pon 999m"]),
    ("honitsu", "shousangen"): dict(hand="77z123m45m", win="6m", melds=["pon 555z", "pon 666z"]),
    ("honitsu", "toitoi"): dict(hand="111z33z44z", win="3z", melds=["pon 111m", "pon 999m"]),
    ("honroutou", "yakuhai"): dict(hand="111z33z44z", win="3z", melds=["pon 111m", "pon 999m"]),
    ("iipeikou", "junchan"): dict(hand="112233m789p7899s", win="9s"),
    ("ittsu", "riichi"): dict(hand="123456789m24s44z", win="3s", riichi=True),
    ("junchan", "riichi"): dict(hand="123m789m123p89s11s", win="7s", riichi=True),
    ("menzen_tsumo", "ryanpeikou"): dict(hand="112233m778899p5s", win="5s", is_tsumo=True),
    ("riichi", "sanankou"): dict(hand="222m444p888s34m11p", win="5m", riichi=True),
    ("rinshan", "sankantsu"): dict(
        hand="34s99m", win="5s", melds=["minkan 2222m", "ankan 6666p", "kakan 7777s"], is_tsumo=True, rinshan=True
    ),
    ("sanankou", "sankantsu"): dict(hand="34s99m", win="5s", melds=["ankan 2222m", "ankan 6666p", "ankan 8888s"]),
    ("sanankou", "yakuhai"): dict(hand="555z222m444p34m11p", win="5m"),
    ("sankantsu", "toitoi"): dict(hand="999s3z", win="3z", melds=["minkan 2222m", "ankan 6666p", "kakan 7777s"]),
    ("sanshoku_doukou", "toitoi"): dict(hand="333s99p77z", win="9p", melds=["pon 333m", "pon 333p"]),
    ("shousangen", "toitoi"): dict(hand="77z222m99p", win="9p", melds=["pon 555z", "pon 666z"]),
    ("tanyao", "toitoi"): dict(hand="222m66s55p", win="5p", melds=["pon 888m", "pon 333s"]),
}
SOUTH_SEAT = {"seat_wind": 28, "round_wind": 27}


def _id(case) -> str:
    page, item = case
    hand = item if isinstance(item, content.Hand) else item.hand
    return f"{page.key}:{hand.title}"


@cache
def _explain(page_key: str, group: str, index: int) -> Explanation:
    page = content.yaku_page_map()[page_key]
    hand = page.examples[index] if group == "examples" else page.traps[index].hand
    return explain(hand.context(), hand.rules)


def _counted_pages(result: Explanation) -> set[str]:
    """数えている役の、ページの鍵"""
    if result.status is not Status.WIN:
        return set()
    return {PAGE_OF[item.key] for item in result.candidates[0].evaluation.yaku}


# ---------------------------------------------------------------- ページの構成


def test_every_yaku_has_exactly_one_page():
    covered = [key for page in PAGES for key in page.yaku]
    assert sorted(covered) == sorted(YAKU)
    assert len(PAGES) == 39
    assert [p.key for p in PAGES if not p.yaku] == ["nagashi_mangan"]


def test_groups_match_the_han_of_the_yaku():
    han_of_group = {"han1": 1, "han2": 2, "han3": 3, "han6": 6}
    order = list(content.GROUPS)
    assert [order.index(p.group) for p in PAGES] == sorted(order.index(p.group) for p in PAGES)   # 図鑑の順に並んでいる
    for page in PAGES:
        infos = [YAKU[key] for key in page.yaku]
        if page.group == "yakuman":
            assert infos and all(info.yakuman for info in infos), page.key
        elif page.group == "other":
            assert not infos
        else:
            assert infos and all(info.han_closed == han_of_group[page.group] and not info.yakuman for info in infos), page.key


def test_names_and_readings_come_from_the_yaku_table():
    for page in PAGES:
        if len(page.yaku) == 1:
            info = YAKU[page.yaku[0]]
            assert (page.name, page.reading) == (info.name, info.reading)
        assert page.name and page.reading and page.spoken
        assert page.short.endswith("。") and page.kanji.endswith("。") and page.origin.text.endswith("。")
        assert all(line.endswith("。") for line in (*page.notes, *page.tips)), page.key
        assert page.origin.certainty in content.CERTAINTIES


def test_every_page_has_definition_examples_traps_and_tips():
    for page in PAGES:
        assert len(page.definition) >= 2, page.key
        assert page.tips, page.key
        if page.yaku:
            assert len(page.examples) >= 2, page.key
            assert len(page.traps) >= 2, page.key
            assert all(trap.why.endswith("。") for trap in page.traps), page.key
        else:
            assert len(page.rivers) >= 2 and {river.ok for river in page.rivers} == {True, False}
        titles = [hand.title for hand in (*page.examples, *(t.hand for t in page.traps))]
        assert all(titles) and len(set(titles)) == len(titles), page.key


def test_practice_keys():
    for page in PAGES:
        assert page.practice in (None, page.key), page.key
        if page.practice is None:
            assert page.practice_note, page.key          # 練習できない理由を書いてある
        if not page.solo:
            assert page.practice is None, page.key


def test_rule_differences_are_stated():
    """流派で扱いが分かれる役は、ページの補足にそのことが書いてある"""
    for key in ("riichi", "ippatsu", "tanyao", "yakuhai", "rinshan", "chankan", "chiitoitsu", "sankantsu", "chiihou", "kokushi",
                "suuankou", "daisangen", "daisuushii", "ryuuiisou", "chuuren", "suukantsu", "nagashi_mangan"):
        page = content.yaku_page_map()[key]
        assert any("ルールによって異なる" in note for note in page.notes), key


# ---------------------------------------------------------------- 成立例・ひっかけ例


@pytest.mark.parametrize("case", EXAMPLE_CASES, ids=_id)
def test_example_has_the_yaku(case):
    page, hand = case
    result = _explain(page.key, "examples", page.examples.index(hand))
    assert result.consistent, result.mismatches
    assert result.status is Status.WIN
    counted = {item.key for item in result.best.evaluation.yaku}
    assert counted & set(page.yaku), f"{page.name} が付いていない（付いた役: {sorted(counted)}）"


@pytest.mark.parametrize("case", TRAP_CASES, ids=_id)
def test_trap_does_not_have_the_yaku(case):
    page, trap = case
    result = _explain(page.key, "traps", page.traps.index(trap))
    assert result.consistent, result.mismatches
    assert page.key not in _counted_pages(result), f"ひっかけ例に {page.name} が付いている"
    if trap.expect != "no_call":
        assert result.status.value == trap.expect


def test_trap_results_are_named():
    assert set(content.TRAP_RESULTS) == {"win", "no_yaku", "not_winning", "no_call"}
    assert {status.value for status in Status} < set(content.TRAP_RESULTS)


@pytest.mark.parametrize("case", [c for c in EXAMPLE_CASES if len(c[0].yaku) == 1], ids=_id)
def test_yaku_check_explains_examples(case):
    page, hand = case
    result = _explain(page.key, "examples", page.examples.index(hand))
    check = result.yaku_check(page.yaku[0])
    assert check.key == page.yaku[0] and check.ok
    assert check.checks and all(c.ok for c in check.checks)


@pytest.mark.parametrize("case", [c for c in TRAP_CASES if len(c[0].yaku) == 1], ids=_id)
def test_yaku_check_explains_traps(case):
    """ひっかけ例では、足りない条件が 1 つ以上示される（上位の役や役満に置き換わる例では、そのことが note に入る）"""
    page, trap = case
    result = _explain(page.key, "traps", page.traps.index(trap))
    check = result.yaku_check(page.yaku[0])
    if result.status is Status.NOT_WINNING:
        assert check is None
        return
    assert check.key == page.yaku[0]
    if check.ok:
        assert check.note
    else:
        failed = [c for c in check.checks if not c.ok]
        assert failed and all(c.detail for c in failed)


# ---------------------------------------------------------------- 複合


@cache
def _sample_results() -> tuple[Explanation, ...]:
    """いろいろな和了形（図鑑の成立例、複合の確認用の手、点数計算ラボの例題、ランダムな和了形）"""
    results = [_explain(page.key, "examples", index) for page in PAGES for index in range(len(page.examples))]
    results += [_explain(page.key, "traps", index) for page in PAGES for index in range(len(page.traps))]
    results += [explain(make_context(**{**SOUTH_SEAT, **spec})) for spec in COMBO_DEMOS.values()]
    results += [explain(example.context(), example.rules) for example in EXAMPLES]
    for kind in ("any", "big", "open", "menzen"):
        results += [explain(random_win(seed, kind)) for seed in range(250)]
    return tuple(results)


def test_combo_targets_are_sound():
    for page in PAGES:
        good = [c.key for c in page.good]
        never = [c.key for c in page.never]
        assert page.key not in good + never, page.key
        assert len(set(good + never)) == len(good + never), f"{page.key}: 同じ相手が 2 回出てくる"
        assert all(c.why for c in (*page.good, *page.never))
        assert page.good or page.never or page.combo_note, page.key
    for page in PAGES:                       # 片方が「しやすい」、もう片方が「しない」と書いていないか
        for combo in page.good:
            other = content.yaku_page_map()[combo.key]
            assert page.key not in [c.key for c in other.never], (page.key, combo.key)


def test_good_combos_really_occur():
    seen = {frozenset((a, b)) for result in _sample_results() for a in _counted_pages(result) for b in _counted_pages(result) if a != b}
    for (a, b), spec in COMBO_DEMOS.items():
        result = explain(make_context(**{**SOUTH_SEAT, **spec}))
        assert result.consistent and {a, b} <= _counted_pages(result), (a, b, sorted(_counted_pages(result)))
    missing = [(page.key, combo.key) for page in PAGES for combo in page.good if frozenset((page.key, combo.key)) not in seen]
    assert not missing


def test_never_combos_do_not_occur():
    never = {frozenset((page.key, combo.key)) for page in PAGES for combo in page.never}
    for result in _sample_results():
        counted = sorted(_counted_pages(result))
        for i, a in enumerate(counted):
            for b in counted[i + 1:]:
                assert frozenset((a, b)) not in never, (a, b)


def test_yaku_check_agrees_with_counted_yaku():
    """どの役を尋ねても、成立条件の内訳（yaku_check）は、数えている役と食い違わない"""
    for result in _sample_results():
        if not result.candidates:
            continue
        first = result.candidates[0]
        counted = {item.key for item in first.evaluation.yaku}
        ignored = {item.key for item in first.evaluation.ignored}
        for key in YAKU:
            check = result.yaku_check(key)
            assert check.key == key
            if key in counted:
                assert check.ok
            elif key in ignored:
                assert check.ok and check.note
            else:
                assert not check.ok or check.note, (key, check)


# ---------------------------------------------------------------- 流し満貫の河


def test_rivers():
    page = content.yaku_page_map()["nagashi_mangan"]
    for river in page.rivers:
        tiles = parse_tiles(river.tiles)
        assert 17 <= len(tiles) <= 18                       # 1 人が 1 局に捨てるのは、多くて 18 枚
        assert max(counts34(tiles)) <= 4
        assert all(is_yaochu_kind(kind_of(t)) for t in tiles) == river.ok


# ---------------------------------------------------------------- 出やすさ


def test_stats_cover_every_page():
    stats = content.yaku_stats()
    assert set(stats.pages) == {page.key for page in PAGES}
    source = stats.source
    assert source.url.startswith("https://") and source.title and source.site and source.published
    assert 0 < source.wins < source.hands
    for key, stat in stats.pages.items():
        assert 0 < stat.count <= stat.total, key
        assert stat.total == (source.hands if stat.per == "局" else source.wins)
        assert stat.level in [name for name, _ in content.FREQUENCY_LEVELS]
    assert all(ref.url.startswith("https://") and ref.seen and ref.text.endswith("。") for ref in stats.references)


def test_frequency_levels():
    stats = content.yaku_stats().pages
    levels = {key: stat.level for key, stat in stats.items()}
    assert levels["riichi"] == levels["tanyao"] == levels["pinfu"] == levels["yakuhai"] == "よく出る"
    assert levels["honitsu"] == levels["chiitoitsu"] == levels["sanshoku"] == "ときどき"
    assert levels["chinitsu"] == levels["kokushi"] == levels["nagashi_mangan"] == "まれ"
    assert stats["riichi"].one_in == 2 and stats["chiitoitsu"].one_in == 35
    assert content.YakuStat(0, 100).one_in is None and content.YakuStat(0, 100).level == "まれ"
    assert content.YakuStat(10, 100).level == "よく出る" and content.YakuStat(1, 100).level == "ときどき"


# ---------------------------------------------------------------- 読み込みの誤り検出


def _page(**changes) -> dict:
    base = {
        "key": "riichi",
        "group": "han1",
        "short": "説明。",
        "definition": ["条件 1", "条件 2"],
        "kanji": "字義。",
        "origin": {"text": "由来。", "certainty": "確実"},
        "tips": ["コツ。"],
    }
    base.update(changes)
    return base


def test_loader_accepts_a_minimal_page():
    page = content._yaku_page(_page(), 0)
    assert (page.name, page.reading, page.spoken) == ("立直", "リーチ", "リーチ")
    assert page.yaku == ("riichi",) and page.practice is None and page.solo


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": 1},                                             # 知らない項目
        {"group": "han9"},                                          # 無いまとまり
        {"key": "no_such_yaku"},                                    # 役の表に無い
        {"short": 3},                                               # 型が違う
        {"definition": ["ok", ""]},                                 # 空の文章
        {"origin": {"text": "由来。", "certainty": "たぶん"}},       # 確かさの書き方
        {"origin": {"text": "由来。"}},                              # 必須の項目が無い
        {"examples": [{"hand": "123m", "win": "1m", "extra": 1}]},   # 例の中の知らない項目
        {"examples": [{"hand": "123m"}]},                            # あがり牌が無い
        {"examples": [{"hand": "123m", "win": "1m", "seat": "中"}]},  # 風の書き方
        {"examples": [{"hand": "123m", "win": "1m", "rules": {"no_such_rule": True}}]},
        {"examples": [{"hand": "123m", "win": "1m", "rules": {"double_wind_pair_fu": 3}}]},
        {"traps": [{"hand": "123m", "win": "1m", "why": "理由。", "expect": "maybe"}]},
        {"traps": [{"hand": "123m", "win": "1m", "expect": "win"}]},  # 理由が無い
        {"good": [{"key": "pinfu"}]},                                # 理由が無い
        {"yaku": [], "name": ""},                                    # 役の無いページは、名前と読みが要る
    ],
)
def test_loader_rejects_mistakes(changes):
    with pytest.raises(ContentError):
        content._yaku_page(_page(**changes), 0)


def test_loader_rejects_non_mapping():
    with pytest.raises(ContentError):
        content._yaku_page(["riichi"], 0)
    with pytest.raises(ContentError):
        content._load("no_such_file.yaml")

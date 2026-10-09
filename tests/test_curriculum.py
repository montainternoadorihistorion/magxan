"""カリキュラム（engine/curriculum.py・data/curriculum.yaml）と、確認テスト（ui/drill_session.py の test モード・ページ）のテスト"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from component_helpers import choose
from html_helpers import page_html, page_parts
from streamlit.testing.v1 import AppTest

from engine.content import yaku_page_map
from engine.curriculum import (
    CURRICULUM_FILE,
    CurriculumError,
    Progress,
    StepRecord,
    curriculum,
    exam_items,
    load_progress,
    merge_progress,
    parse_curriculum,
    progress_from_data,
    step_of,
)
from engine.drills import question
from ui.components.browser_store import initial_state
from ui.drill_session import MODE_TEST, DrillSession
from ui.progress_store import CURRICULUM_NAME, read_curriculum
from ui.ruby import missing_ruby

ROOT = Path(__file__).resolve().parent.parent
STORE_STATE = "mjdojo_store::state"
RAW = yaml.safe_load(CURRICULUM_FILE.read_text(encoding="utf-8"))


class FakeStore(dict):
    ready = True
    available = True

    def get(self, name):
        return super().get(name)

    def set(self, name, value):
        self[name] = value

    def remove(self, name):
        self.pop(name, None)


def test_four_steps_with_decreasing_luck():
    steps = curriculum()
    assert [s.key for s in steps] == ["step1", "step2", "step3", "step4"]
    assert [s.luck for s in steps] == [75, 50, 25, 0]               # 強 → 中 → 弱 → なし（仕様の 8 章）
    for step in steps:
        assert step.goals and step.size == 10 and step.passing == 8
    assert "立直" in steps[0].focus and "押し引き" in steps[3].focus


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_every_test_question_can_be_made(seed):
    for step in curriculum():
        items = exam_items(step, seed)
        assert len(items) == step.size and len(set(items)) == len(items)
        for kind, item in items:
            assert question(kind, item).prompt
    assert exam_items(curriculum()[0], 5) == exam_items(curriculum()[0], 5)       # 同じ seed なら同じ問題


@pytest.mark.parametrize("seed", range(12))
def test_test_questions_use_only_what_was_taught(seed):
    """その場で作る問題は、その段階までに学んだ役の手だけ（1 つ目の段階の点数計算は、20 符・30 符の満貫未満の手だけ）"""
    from engine.scoring.explain import explain
    from engine.scoring.judge import Level

    pages = yaku_page_map()
    taught: set[str] = set()
    for step in curriculum():
        taught |= {key for page in step.learn["yaku"] for key in pages[page].yaku}
        for kind, item in exam_items(step, seed):
            if kind not in ("score", "yaku", "win"):
                continue
            q = question(kind, item)
            best = explain(q.ctx, q.rules).best
            if best is None:
                continue
            assert {y.key for y in best.evaluation.yaku} <= taught, (step.key, kind, item, [y.key for y in best.evaluation.yaku])
            if step.key == "step1" and kind == "score":
                assert best.fu.fu in (20, 30) and best.points.level is Level.NONE


def test_test_parts_with_conditions_are_checked():
    with pytest.raises(CurriculumError, match="見つかりません"):
        parse_curriculum(broken(("steps", 0, "test", "parts", 3, "yaku"), ["no_such_yaku"]))
    with pytest.raises(CurriculumError, match="符"):
        parse_curriculum(broken(("steps", 0, "test", "parts", 3, "fu"), [15]))


def broken(path: tuple, value) -> dict:
    data = copy.deepcopy(RAW)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


@pytest.mark.parametrize(("path", "value", "message"), [
    (("steps", 0, "luck"), 120, "luck"),
    (("steps", 1, "luck"), 90, "弱く"),
    (("steps", 0, "learn", "yaku"), ["no_such_yaku"], "見つかりません"),
    (("steps", 0, "learn", "lab"), ["Z-9"], "見つかりません"),
    (("steps", 0, "test", "pass"), 11, "合格の数"),
    (("steps", 0, "test", "parts", 0, "from"), ["han:h:no_such"], "ドリルに無い"),
    (("steps", 0, "test", "parts", 0, "from"), ["nosuchkind:*"], "種類:鍵"),
    (("steps", 0, "play", "practice"), ["toitoi"], "役指定練習で選べない"),
    (("steps", 0, "extra"), 1, "知らない項目"),
])
def test_mistakes_in_the_data_are_reported(path, value, message):
    with pytest.raises(CurriculumError, match=message):
        parse_curriculum(broken(path, value))


def test_progress_unlocks_the_next_step():
    progress = Progress()
    assert progress.current.key == "step1" and progress.unlocked("step1") and not progress.unlocked("step2")
    failed = progress.with_result("step1", 7, 10, now=1000)
    assert not failed.passed("step1") and failed.record("step1") == StepRecord(None, 7, 1, 7, 1000)
    passed = failed.with_result("step1", 9, 10, now=2000)
    assert passed.passed("step1") and passed.unlocked("step2") and passed.current.key == "step2"
    again = passed.with_result("step1", 5, 10, now=3000)                # 合格のあとに受け直しても、合格は残る
    assert again.record("step1") == StepRecord(2000, 9, 3, 5, 3000)
    done = again
    for number, step in enumerate(curriculum()[1:], start=4):
        done = done.with_result(step.key, 10, 10, now=number * 1000)
    assert done.finished and done.current.key == "step4"
    with pytest.raises(ValueError):
        progress.with_result("step9", 1, 10, now=1)


def test_progress_round_trip_and_merge():
    progress = Progress().with_result("step1", 9, 10, now=2000).with_result("step2", 6, 10, now=3000)
    assert progress_from_data(progress.to_data()) == progress
    assert load_progress("x") == Progress() and load_progress(None) == Progress()
    data = progress.to_data()
    data["steps"]["step9"] = [None, 1, 1, 1, 1]                         # 知らない段階・壊れた記録は読み飛ばす
    data["steps"]["step3"] = [None, -1, 1, 1, 1]
    assert progress_from_data(data) == progress
    other = Progress().with_result("step1", 10, 10, now=1500).with_result("step2", 8, 10, now=4000)
    merged = merge_progress(progress, other)
    assert merged.record("step1") == StepRecord(1500, 10, 1, 9, 2000)      # 合格は早いほう、最後の結果は新しいほう
    assert merged.record("step2") == StepRecord(4000, 8, 1, 8, 4000)


def test_drill_session_runs_a_test_and_records_it():
    store = FakeStore()
    session_state: dict = {}
    clock = iter(range(10_000, 20_000, 7))
    drills = DrillSession(session_state, store, now=lambda: next(clock))
    step = step_of("step1")
    items = exam_items(step, 11)
    drills.start_test("step1", items)
    assert drills.mode == MODE_TEST and drills.test["index"] == 0 and (drills.kind, drills.item) == items[0]
    for number, (kind, item) in enumerate(items):
        q = question(kind, item)
        keys = sorted(q.correct) if number < 8 else [next(c.key for c in q.choices if c.key not in q.correct)]
        assert drills.answer(keys)
        drills.next()
    done = drills.test_done
    assert done == {"step": "step1", "right": 8, "total": 10, "passed": True}
    assert drills.kind is None and drills.test is None
    assert read_curriculum(store).passed("step1") and CURRICULUM_NAME in store
    # 途中でやめたら、記録しない
    drills.start_test("step2", exam_items(step_of("step2"), 3))
    drills.leave()
    assert drills.test is None and not read_curriculum(store).record("step2").tries


# ---------------------------------------------------------------- ページ


def open_page(known: dict | None = None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.session_state[STORE_STATE] = initial_state(known or {})
    at.switch_page("views/curriculum.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at: AppTest) -> str:
    import re
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", page_html(at)))


def test_page_shows_the_steps_and_starts_a_test():
    at = open_page()
    body = text(at)
    assert "いまの段階" in body and "前の段階の合格が必要" in body
    labels = [e.label for e in at.expander]
    assert labels[0].startswith("1. よく出る 1 翻役と、点数の流れ（いまの段階）") and len(labels) == 4
    assert "確認テストを受ける" in [b.label for b in at.button]
    links = [e.proto.label for e in at.get("page_link")]
    assert "役図鑑：立直" in links and "点数計算ラボ：G-1 3 翻 30 符 ＝ 3900" in links and "一人練習：断么九を狙う（役指定練習）" in links
    assert missing_ruby(page_parts(at)) == []
    next(b for b in at.button if b.key == "cu_b_test_step1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["dr_mode"] == MODE_TEST
    at.switch_page("views/drill.py").run()          # ページの中の st.switch_page は、画面なしのテストでは次の実行に引き継がれない
    body = text(at)
    assert "確認テスト：よく出る 1 翻役と、点数の流れ" in body and "1 / 10 問目" in body and "確認テストをやめる" in [b.label for b in at.button]
    # 10 問とも正解して、結果を見る
    for _ in range(10):
        state = at.session_state["dr_test"]
        kind, item = state["items"][state["index"]]
        choose(at, sorted(question(kind, item).correct), key="dr_choices")
        label = "結果を見る" if state["index"] == 9 else "次の問題"
        next(b for b in at.button if b.label == label).click().run()
        assert not at.exception, [e.value for e in at.exception]
    body = text(at)
    assert "○ 合格" in body and "10 問中 10 問正解" in body and "次は「2〜3 翻の役と、鳴き」。" in body
    stored = at.session_state[STORE_STATE]["known"][CURRICULUM_NAME]
    assert load_progress(stored).passed("step1")
    back = open_page(at.session_state[STORE_STATE]["known"])
    assert "2. 2〜3 翻の役と、鳴き（いまの段階）" in [e.label for e in back.expander]


def test_quitting_or_leaving_a_test_is_told():
    at = open_page()
    next(b for b in at.button if b.key == "cu_b_test_step1").click().run()
    at.switch_page("views/drill.py").run()
    assert "確認テスト：" in text(at)
    # ほかのページへ行ってカリキュラムに戻ると、テストの途中であることと、続ける・やめるが出る
    at.switch_page("views/curriculum.py").run()
    assert "の途中です（1 / 10 問目）" in text(at) and "確認テストをやめる" in [b.label for b in at.button]
    links = [e.proto.label for e in at.get("page_link")]
    assert "確認テストの続きをする" in links
    # 続きをして、「確認テストをやめる」を押すと、カリキュラムに戻る印と、知らせが残る
    at.switch_page("views/drill.py").run()
    next(b for b in at.button if b.label == "確認テストをやめる").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.value for t in at.title] == ["カリキュラム"]                   # カリキュラムのページに戻る
    assert "確認テストをやめました" in " ".join(i.value for i in at.info) and "の途中です" not in text(at)
    assert not read_curriculum_known(at).record("step1").tries                  # 途中でやめたテストは、記録に残さない


def read_curriculum_known(at: AppTest):
    known = at.session_state[STORE_STATE]["known"]
    return load_progress(known.get(CURRICULUM_NAME))


def test_choosing_another_drill_during_a_test_tells_that_the_test_ended():
    at = open_page()
    next(b for b in at.button if b.key == "cu_b_test_step1").click().run()
    at.switch_page("views/drill.py").run()
    at.query_params["k"] = "fu"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("確認テストをやめました" in t.value for t in at.toast) and "確認テスト：" not in text(at)

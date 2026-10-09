"""カリキュラム（仕様の 8 章）：段階ごとの到達目標・学ぶところ・確認テストと、その進み具合。

内容は data/curriculum.yaml に書く。確認テストの問題は、ドリルの問題（engine.drills.question）をそのまま使う。
段階は順に進む：前の段階の確認テストに合格すると、次の段階が開く（いつでも、前の段階の復習はできる）。

進み具合（Progress）は、段階ごとに「合格した時刻・いちばん良かった正解数・受けた回数・最後の正解数」を持つ。
文字と数だけでできているので、そのまま JSON にしてブラウザ内保存と、書き出したファイルに残せる。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from engine.analysis.target import TARGET_KEYS
from engine.content import glossary, table_guide, yaku_page_map
from engine.drills import KINDS, is_item, items_of, new_item, question
from engine.rng import Rng
from engine.scoring.examples import EXAMPLES_BY_KEY
from engine.scoring.explain import explain
from engine.scoring.judge import Level

CURRICULUM_FILE = Path(__file__).resolve().parent.parent / "data" / "curriculum.yaml"
PROGRESS_VERSION = 1
ANY = "*"
_MAX_TIME = 10**11
_MAX_COUNT = 10**6
#: その場で作る問題を、条件（yaku・fu）に合うまで作り直す回数の上限
MAX_TRIES = 400


class CurriculumError(ValueError):
    """カリキュラムのデータの書き間違い"""


@dataclass(frozen=True)
class TestPart:
    count: int                          # この部分から出す問題の数
    pool: tuple[str, ...]               # 問題の元（「種類:鍵」。鍵が * なら、その種類から選ぶ）
    #: その場で作る問題（点数計算・役の判定・あがれる？）で、手に付いてよい役（役の鍵）。None なら、どの役でもよい。
    #: まだ学んでいない役が付く手を、確認テストに出さないため
    yaku: frozenset[str] | None = None
    #: その場で作る点数計算の問題で、手の符（空なら、どの符でもよい）。書いたときは、満貫に届かない手だけを出す
    #: （符の数え方は 3 つ目の段階で学ぶので、それより前は、よくある 20 符・30 符の手だけにする）
    fu: tuple[int, ...] = ()

    def fits(self, kind: str, item: str) -> bool:
        """その場で作った問題が、この部分の条件に合うか"""
        if self.yaku is None and not self.fu:
            return True
        made = question(kind, item)
        if made.ctx is None:
            return True
        best = explain(made.ctx, made.rules).best
        if best is None:
            return True                 # あがれない手（役なし・形ちがい）は、役の知識が要らない
        if self.yaku is not None and any(item.key not in self.yaku for item in best.evaluation.yaku):
            return False
        return not (self.fu and (best.points is None or best.fu.fu not in self.fu or best.points.level is not Level.NONE))


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    luck: int                           # この段階で打つときのツキ補正
    focus: str
    goals: tuple[str, ...]
    learn: Mapping[str, tuple[str, ...]]    # yaku・term・lab・guide・drill → 鍵の並び
    practice: tuple[str, ...]           # 一人練習（役指定練習の役。空はふつうの一人練習）
    game: str                           # CPU との対局でする練習（無ければ空）
    parts: tuple[TestPart, ...]
    passing: int                        # 合格に要る正解の数
    graduation: bool = False            # CPU との対局を、卒業判定に数える設定で始めるか

    @property
    def size(self) -> int:
        """確認テストの問題の数"""
        return sum(part.count for part in self.parts)


LEARN_KINDS = ("yaku", "term", "lab", "guide", "drill")


def _list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CurriculumError(f"{where}: 文字の並びにします")
    return tuple(v.strip() for v in value)


def _check_learn(kind: str, key: str, where: str) -> None:
    ok = {
        "yaku": lambda: key in yaku_page_map(),
        "term": lambda: glossary().find(key) is not None,
        "lab": lambda: key in EXAMPLES_BY_KEY,
        "guide": lambda: any(s.key == key for s in table_guide().sections),
        "drill": lambda: key in KINDS,
    }[kind]()
    if not ok:
        raise CurriculumError(f"{where}: 「{key}」が見つかりません（{kind}）")


def _check_question(source: str, where: str) -> None:
    kind, _, item = source.partition(":")
    if kind not in KINDS or not item:
        raise CurriculumError(f"{where}: 問題は「種類:鍵」で書きます（{source!r}）")
    if item != ANY and not is_item(kind, item):
        raise CurriculumError(f"{where}: ドリルに無い問題です（{source!r}）")


def _step(data: Any, index: int) -> Step:
    where = f"curriculum.yaml steps[{index}]"
    if not isinstance(data, dict):
        raise CurriculumError(f"{where}: 項目の集まりにします")
    known = {"key", "title", "luck", "focus", "goals", "learn", "play", "test"}
    if set(data) - known:
        raise CurriculumError(f"{where}: 知らない項目があります {sorted(set(data) - known)}")
    key, title, focus = data.get("key"), data.get("title"), data.get("focus")
    if not all(isinstance(v, str) and v.strip() for v in (key, title, focus)):
        raise CurriculumError(f"{where}: key・title・focus は文字にします")
    luck = data.get("luck")
    if not isinstance(luck, int) or isinstance(luck, bool) or not 0 <= luck <= 100:
        raise CurriculumError(f"{where}: luck は 0〜100 にします")
    goals = _list(data.get("goals"), f"{where} goals")
    if not goals:
        raise CurriculumError(f"{where}: 到達目標（goals）がありません")
    learn_data = data.get("learn") or {}
    if not isinstance(learn_data, dict) or set(learn_data) - set(LEARN_KINDS):
        raise CurriculumError(f"{where}: learn の項目は {LEARN_KINDS} です")
    learn = {kind: _list(learn_data.get(kind), f"{where} learn.{kind}") for kind in LEARN_KINDS}
    for kind, keys in learn.items():
        for key_ in keys:
            _check_learn(kind, key_, f"{where} learn.{kind}")
    play = data.get("play") or {}
    if not isinstance(play, dict) or set(play) - {"practice", "game", "graduation"}:
        raise CurriculumError(f"{where}: play の項目は practice・game・graduation です")
    graduation = play.get("graduation", False)
    if not isinstance(graduation, bool):
        raise CurriculumError(f"{where}: play.graduation は true か false にします")
    practice = _list(play.get("practice"), f"{where} play.practice")
    for target in practice:
        if target and target not in TARGET_KEYS:
            raise CurriculumError(f"{where}: 役指定練習で選べない役です（{target!r}）")
    game = play.get("game", "")
    if not isinstance(game, str):
        raise CurriculumError(f"{where}: play.game は文字にします")
    test = data.get("test")
    if not isinstance(test, dict) or set(test) - {"pass", "parts"}:
        raise CurriculumError(f"{where}: test には pass と parts を書きます")
    parts = []
    for number, part in enumerate(test.get("parts") or []):
        if not isinstance(part, dict) or set(part) - {"count", "from", "yaku", "fu"}:
            raise CurriculumError(f"{where} test.parts[{number}]: count と from（と、yaku・fu）を書きます")
        count = part.get("count")
        pool = _list(part.get("from"), f"{where} test.parts[{number}].from")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or not pool:
            raise CurriculumError(f"{where} test.parts[{number}]: count は 1 以上、from は 1 つ以上")
        for source in pool:
            _check_question(source, f"{where} test.parts[{number}]")
        if all(not s.endswith(f":{ANY}") for s in pool) and len(set(pool)) < count:
            raise CurriculumError(f"{where} test.parts[{number}]: 問題の元が、出す数より少ない")
        allowed = None
        if "yaku" in part:
            pages = _list(part.get("yaku"), f"{where} test.parts[{number}].yaku")
            for page in pages:
                _check_learn("yaku", page, f"{where} test.parts[{number}].yaku")
            allowed = frozenset(key for page in pages for key in yaku_page_map()[page].yaku)
        fu = part.get("fu", [])
        if not isinstance(fu, list) or not all(isinstance(v, int) and not isinstance(v, bool) and 20 <= v <= 110 for v in fu):
            raise CurriculumError(f"{where} test.parts[{number}].fu: 符（20〜110）の並びにします")
        parts.append(TestPart(count, pool, allowed, tuple(fu)))
    passing = test.get("pass")
    total = sum(p.count for p in parts)
    if not parts or not isinstance(passing, int) or isinstance(passing, bool) or not 1 <= passing <= total:
        raise CurriculumError(f"{where}: 合格の数（pass）は 1〜問題の数（{total}）にします")
    return Step(key.strip(), title.strip(), luck, focus.strip(), goals, learn, practice, game.strip(), tuple(parts), passing, graduation)


def parse_curriculum(data: Any) -> tuple[Step, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        raise CurriculumError("curriculum.yaml: steps に段階を並べます")
    steps = tuple(_step(item, index) for index, item in enumerate(data["steps"]))
    if len({s.key for s in steps}) != len(steps):
        raise CurriculumError("curriculum.yaml: 同じ鍵の段階が 2 つあります")
    if any(a.luck < b.luck for a, b in zip(steps, steps[1:], strict=False)):
        raise CurriculumError("curriculum.yaml: ツキ補正は、段階が進むほど弱く（同じか小さく）します")
    return steps


@cache
def curriculum(path: Path = CURRICULUM_FILE) -> tuple[Step, ...]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise CurriculumError(f"{path.name} を読めません: {error}") from error
    return parse_curriculum(data)


def step_of(key: str) -> Step | None:
    return next((s for s in curriculum() if s.key == key), None)


# ---------------------------------------------------------------- 確認テスト


def exam_items(step: Step, seed: int) -> tuple[tuple[str, str], ...]:
    """確認テストの問題（種類, 鍵）の並び。seed ごとに選び直す（同じ seed なら同じ問題）"""
    rng = Rng(seed, f"curriculum:{step.key}")
    picked: list[tuple[str, str]] = []
    for part in step.parts:
        fixed = [s for s in part.pool if not s.endswith(f":{ANY}")]
        anys = [s for s in part.pool if s.endswith(f":{ANY}")]
        chosen: list[tuple[str, str]] = []
        order = list(fixed)
        rng.shuffle(order)
        for source in order[: part.count]:
            kind, _, item = source.partition(":")
            chosen.append((kind, item))
        while len(chosen) < part.count and anys:
            kind = rng.choice(anys).partition(":")[0]
            if KINDS[kind].finite:
                options = [item for item in items_of(kind) if (kind, item) not in chosen]
                if not options:
                    break
                chosen.append((kind, rng.choice(options)))
            else:
                # 条件（まだ学んでいない役が付かない・符）に合う手になるまで、作り直す
                tries = (new_item(kind, rng.below(10**9)) for _ in range(MAX_TRIES))
                item = next((made for made in tries if (kind, made) not in chosen and part.fits(kind, made)), None)
                if item is None:
                    raise CurriculumError(f"{step.key}: 条件に合う問題を作れません（{kind}）")
                chosen.append((kind, item))
        picked.extend(chosen)
    return tuple(picked)


# ---------------------------------------------------------------- 進み具合


@dataclass(frozen=True)
class StepRecord:
    passed: int | None = None       # はじめて合格した時刻（UNIX 秒。まだなら None）
    best: int = 0                   # いちばん良かった正解数
    tries: int = 0                  # 受けた回数
    last: int = 0                   # 最後の正解数
    at: int = 0                     # 最後に受けた時刻

    def to_list(self) -> list[int | None]:
        return [self.passed, self.best, self.tries, self.last, self.at]

    @classmethod
    def from_list(cls, data: object) -> StepRecord:
        if not isinstance(data, list) or len(data) != 5:
            raise ValueError("段階の記録の形が違います")
        passed, best, tries, last, at = data
        numbers = (best, tries, last, at)
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in numbers):
            raise ValueError("段階の記録の値がおかしい")
        if passed is not None and (not isinstance(passed, int) or isinstance(passed, bool) or not 0 <= passed <= _MAX_TIME):
            raise ValueError("合格の時刻がおかしい")
        if not (0 <= best <= 1000 and 0 <= tries <= _MAX_COUNT and 0 <= last <= 1000 and 0 <= at <= _MAX_TIME):
            raise ValueError("段階の記録の値がおかしい")
        return cls(passed, best, tries, last, at)


@dataclass(frozen=True)
class Progress:
    steps: Mapping[str, StepRecord] = field(default_factory=dict)

    def record(self, key: str) -> StepRecord:
        return self.steps.get(key, StepRecord())

    def passed(self, key: str) -> bool:
        return self.record(key).passed is not None

    def unlocked(self, key: str) -> bool:
        """その段階に進めるか（最初の段階か、前の段階に合格している）"""
        steps = curriculum()
        index = next((i for i, s in enumerate(steps) if s.key == key), None)
        return index is not None and (index == 0 or self.passed(steps[index - 1].key))

    @property
    def current(self) -> Step:
        """いまの段階（まだ合格していない、いちばん前の段階。すべて合格していれば、最後の段階）"""
        steps = curriculum()
        return next((s for s in steps if not self.passed(s.key)), steps[-1])

    @property
    def finished(self) -> bool:
        return all(self.passed(s.key) for s in curriculum())

    def with_result(self, key: str, right: int, total: int, now: int) -> Progress:
        """確認テストの結果を入れる"""
        step = step_of(key)
        if step is None or not 0 <= right <= total:
            raise ValueError("確認テストの結果がおかしい")
        old = self.record(key)
        passed = old.passed if old.passed is not None else (now if right >= step.passing else None)
        steps = dict(self.steps)
        steps[key] = StepRecord(passed, max(old.best, right), old.tries + 1, right, now)
        return Progress(steps)

    def to_data(self) -> dict[str, Any]:
        return {"v": PROGRESS_VERSION, "steps": {key: record.to_list() for key, record in self.steps.items()}}


def progress_from_data(data: object) -> Progress:
    """保存した形から作る。壊れた 1 件は読み飛ばす（知らない段階の鍵も捨てる）"""
    if not isinstance(data, dict) or data.get("v") != PROGRESS_VERSION or not isinstance(data.get("steps"), dict):
        return Progress()
    known = {s.key for s in curriculum()}
    steps = {}
    for key, value in data["steps"].items():
        if key not in known:
            continue
        try:
            steps[key] = StepRecord.from_list(value)
        except ValueError:
            continue
    return Progress(steps)


def load_progress(text: str | None) -> Progress:
    if not text:
        return Progress()
    try:
        return progress_from_data(json.loads(text))
    except (ValueError, RecursionError):
        return Progress()


def dump_progress(progress: Progress) -> str:
    return json.dumps(progress.to_data(), ensure_ascii=False, separators=(",", ":"))


def merge_progress(mine: Progress, theirs: Progress) -> Progress:
    """2 つの記録を合わせる（合格は早いほう、正解数・回数は多いほう、最後の結果は新しいほう）"""
    steps: dict[str, StepRecord] = {}
    for key in {*mine.steps, *theirs.steps}:
        a, b = mine.record(key), theirs.record(key)
        passed_times = [t for t in (a.passed, b.passed) if t is not None]
        latest = a if a.at >= b.at else b
        steps[key] = StepRecord(min(passed_times) if passed_times else None, max(a.best, b.best), max(a.tries, b.tries), latest.last, latest.at)
    return Progress(steps)

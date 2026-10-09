"""カリキュラムのページの部品（HTML の文字を作るだけ。Streamlit には触れない）"""
from __future__ import annotations

from engine.curriculum import Progress, Step, curriculum
from engine.luck import PRESETS
from ui.ruby import Rubifier
from ui.timefmt import date_text

LUCK_NAMES = {level: name for name, level in PRESETS}


def luck_name(level: int) -> str:
    return LUCK_NAMES.get(level, f"{level}")


def status_text(step: Step, progress: Progress) -> tuple[str, str]:
    """段階の状態の札：（文字, 札の色の class）"""
    if progress.passed(step.key):
        return "合格", "mj-chip-plain"
    if step.key == progress.current.key:
        return "いまの段階", "mj-chip-target"
    if progress.unlocked(step.key):
        return "受けられる", ""
    return "前の段階の合格が必要", ""


def overview_html(progress: Progress, rb: Rubifier) -> str:
    """段階の一覧（番号・見出し・補正・状態）"""
    rows = []
    for number, step in enumerate(curriculum(), start=1):
        label, cls = status_text(step, progress)
        rows.append(
            f'<tr><td class="num">{number}</td><td>{rb.html(step.title)}</td><td style="white-space:nowrap">{rb.html(luck_name(step.luck))}</td>'
            f'<td><span class="mj-chip {cls}">{rb.html(label)}</span></td></tr>'
        )
    head = '<tr class="mj-dim"><td></td><td>段階</td><td>補正</td><td>状態</td></tr>'
    return f'<table class="mj-table">{head}{"".join(rows)}</table>'


def step_body_html(step: Step, progress: Progress, rb: Rubifier) -> str:
    """段階の中身：学ぶこと・到達目標・確認テストのしくみと、これまでの結果"""
    record = progress.record(step.key)
    # 文章は、画面に出る順に作る（用語のルビを、最初に出てくるところに振るため）
    lines = [
        f'<div class="mj-note"><b>{rb.html("学ぶこと")}</b>：{rb.html(step.focus)}</div>',
        f'<div class="mj-note"><b>{rb.html("ツキ補正")}</b>：{rb.html(f"{luck_name(step.luck)}（配牌・ツモの良さ {step.luck}）")}</div>',
    ]
    goals = "".join(f"<li>{rb.html(goal)}</li>" for goal in step.goals)
    lines += [
        f'<div class="mj-subhead">{rb.html("到達目標")}</div><ul class="mj-rules">{goals}</ul>',
        f'<div class="mj-subhead">{rb.html("確認テスト")}</div>',
        f'<div class="mj-sub">{rb.html(f"ドリルの問題から {step.size} 問。{step.passing} 問以上の正解で合格。問題は、受けるたびに選び直す。")}</div>',
    ]
    if record.tries:
        result = f"これまで {record.tries} 回。いちばん良かったのは {record.best} 問正解、最後は {record.last} 問正解。"
        if record.passed is not None:
            result += f"{date_text(record.passed)} に合格。"
        lines.append(f'<div class="mj-sub">{rb.html(result)}</div>')
    return "".join(lines)


def test_result_html(done: dict, rb: Rubifier) -> str:
    """終えたばかりの確認テストの結果の札"""
    step = next((s for s in curriculum() if s.key == done.get("step")), None)
    if step is None:
        return ""
    right, total, passed = done["right"], done["total"], done["passed"]
    if passed:
        steps = curriculum()
        index = steps.index(step)
        if index + 1 < len(steps):
            following = steps[index + 1]
            after = (f"次は「{following.title}」。この段階のツキ補正は「{luck_name(following.luck)}」"
                     "（一人練習・CPU との対局の設定で選ぶか、おまかせにする）。")
        else:
            after = "すべての段階に合格しました。卒業判定のページで、ゴールまでの残りを確かめてください。"
        head = f'<b class="mj-stage">○ 合格</b>　{rb.html(f"{total} 問中 {right} 問正解")}'
        body = f"確認テスト「{step.title}」に合格しました。{after}"
        cls = "good"
    else:
        head = f'<b class="mj-stage">✗ もう少し</b>　{rb.html(f"{total} 問中 {right} 問正解（合格は {step.passing} 問以上）")}'
        body = "間違えた問題は、ドリルの復習で、間隔をあけてもう一度出ます。学ぶところを見直してから、また受けてください。"
        cls = "bad"
    return f'<div class="mj-headline mj-headline-short {cls}">{head}</div><div class="mj-sub">{rb.html(body)}</div>'

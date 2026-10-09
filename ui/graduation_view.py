"""卒業判定の表示（HTML の文字を作るだけ。Streamlit には触れない）"""
from __future__ import annotations

from engine.graduation import Condition, Report
from ui.ruby import Rubifier

#: 条件ごとの短い呼び方（見出しの前に付ける）
SHORT_NAMES = {
    "yaku": "役",
    "points": "点数",
    "calls": "鳴きとフリテン",
    "defense": "守り",
    "manners": "発声と作法",
    "record": "対局の成績",
}


def summary_html(report: Report, rb: Rubifier) -> str:
    """いちばん上のまとめ（6 つのうち、いくつ満たしたか）"""
    total = len(report.conditions)
    if report.passed:
        head = f'<b class="mj-stage">○ 卒業</b>　{rb.html(f"{total} つの条件を、すべて満たしています。")}'
        body = "友人と卓を囲む準備ができました。打つ場所のルールは、卓に着く前に確かめてください（「ルールの違い」のページ）。"
        return f'<div class="mj-headline mj-headline-short good">{head}</div><div class="mj-sub">{rb.html(body)}</div>'
    head = f'<b class="mj-stage">{rb.html("満たした条件")}　{report.done} / {total}</b>'
    body = "すべて満たすと卒業。条件ごとに、いまの値と目標、練習する場所を出す。"
    legend = (f'<span class="mj-mark mj-mark-ok">✓</span> {rb.html("満たした")}　'
              f'<span class="mj-mark mj-mark-ng">✗</span> {rb.html("まだ（目標に届いていない）")}　'
              f'<span class="mj-mark mj-mark-wait">…</span> {rb.html("判定に要る記録が、まだ足りない")}')
    return f'<div class="mj-headline mj-headline-short">{head}</div><div class="mj-sub">{rb.html(body)}</div><div class="mj-sub">{legend}</div>'


def condition_html(number: int, condition: Condition, rb: Rubifier) -> str:
    """条件 1 つぶん：見出し（満たしたか）と、目標ごとのいまの値"""
    cls = "mj-chip-plain" if condition.passed else ""
    label = "○ 達成" if condition.passed else f"{condition.done} / {len(condition.checks)}"
    # 文章は、画面に出る順に作る（用語のルビを、最初に出てくるところに振るため）
    head = (f'<div class="mj-subhead">{number}. {rb.html(SHORT_NAMES.get(condition.key, ""))}　'
            f'<span class="mj-chip {cls}">{rb.html(label)}</span></div>')
    title = f'<div class="mj-note">{rb.html(condition.title)}</div>'
    lines = []
    for check in condition.checks:
        mark = ('<span class="mj-mark mj-mark-ok">✓</span>' if check.passed
                else '<span class="mj-mark mj-mark-ng">✗</span>' if check.ready else '<span class="mj-mark mj-mark-wait">…</span>')
        lines.append(f'<li>{mark}<div>{rb.html(f"{check.name}：{check.status}")}<br>'
                     f'<span class="mj-sub">{rb.html(f"目標：{check.goal}")}</span></div></li>')
    return f'{head}{title}<ul class="mj-checklist">{"".join(lines)}</ul>'


#: 判定のしかた（ページの下に出す）
NOTES = (
    "ドリルは、種類ごとの直近の答えで見る。前に間違えていても、いま答えられれば良い。答えるまでの速さは測らない（「即答」かどうかは見ない）。",
    "あがったときの点数の申告は、一人練習と CPU 戦で、あがった手の点数を、解説を見る前に選ぶもの（設定で切れる）。"
    "打つ前のヒントを見ずに打った局（やり直し・番号を指定した局を除く）の申告だけを数える（ヒントの表には、聴牌したときの点数が出るため）。",
    "CPU 戦の条件は、ツキ補正 0（自分も CPU も）・CPU ふつう・打つ前のヒントなし・初期のルール（鳴きあり）の東風戦だけを数える。"
    "放銃率と平均順位は直近 30 回、役なしの鳴きと見落としは直近 10 回。",
    "CPU 戦の目標値は、CPU 同士の対局で測った値をもとに決めた（CPU ふつうが、CPU ふつう 3 人と東風戦を 300 回打つと、"
    "平均順位 2.49・放銃率 11.3%）。",
)


def notes_html(rb: Rubifier) -> str:
    return '<ul class="mj-rules">' + "".join(f"<li>{rb.html(note)}</li>" for note in NOTES) + "</ul>"

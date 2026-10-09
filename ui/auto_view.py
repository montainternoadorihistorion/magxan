"""おまかせ補正の表示（一人練習・CPU 戦の設定の中。HTML の文字を作るだけ。Streamlit には触れない）"""
from __future__ import annotations

from engine.auto_luck import (
    DOWN_AT,
    DRILL_RECENT,
    MIN_DRILLS,
    MIN_GAMES,
    MIN_HANDS,
    RECENT_GAMES,
    RECENT_HANDS,
    UP_BELOW,
    AutoDecision,
    level_name,
    reason,
)
from ui.ruby import Rubifier
from ui.timefmt import date_text

PRACTICE, GAME = "practice", "game"
#: （局の呼び方, 数える言葉, 判断に使うものの説明）
MODES = {
    PRACTICE: ("局", "局", f"打つ前のヒントを見ずに打った局（直近 {RECENT_HANDS} 局まで。役指定練習の局は除く）の、"
                         "いちばん速い打牌（おすすめと同じ速さ）を選べた割合"),
    GAME: ("対局", "回", f"打つ前のヒントを見ずに打った対局（直近 {RECENT_GAMES} 対局まで）の、コーチの評価がいちばん良かった打牌の割合"
                        "（リーチを受けてオリる局面では、いちばん安全な牌。ほかは、おすすめと同じ速さの牌）"),
}
NEED = {PRACTICE: MIN_HANDS, GAME: MIN_GAMES}


def rule_lines(mode: str) -> list[str]:
    """おまかせのしくみ（設定の中に、箇条書きで出す）"""
    unit, counter, play = MODES[mode]
    down, up = round(DOWN_AT * 100), round(UP_BELOW * 100)
    return [
        f"新しい{unit}を始めるときに、補正を 1 段階ずつ動かす（強・中・弱・なし）。",
        f"見るのは 2 つ。{play}と、ドリルの直近の正答率（種類ごとに直近 {DRILL_RECENT} 問まで。合わせて {MIN_DRILLS} 問以上答えていれば）。",
        f"どちらも {down}% 以上なら 1 段階下げ、{up}% より低いものがあれば 1 段階上げる。"
        f"段階を変えたあとは、その補正で、ヒントを見ずに打った{unit}が {NEED[mode]} {counter}たまるまで判断しない。",
    ]


def rule_text(mode: str) -> str:
    return "".join(rule_lines(mode))


def auto_html(preview: AutoDecision, last: tuple[AutoDecision, int] | None, rb: Rubifier, *, mode: str, hint_before: bool) -> str:
    """おまかせの、いまの段階・次の判断の見込み・前回の変更・しくみ。

    preview は、いまの成績で判断した結果（auto_preview）。last は、前に段階を変えたときの判断と時刻。
    hint_before は、ヒントのタイミングが「打つ前に表示」か（そのあいだの局は数えない）。
    """
    unit, counter, _ = MODES[mode]
    level = preview.before
    lines = [f'<div class="mj-note"><b>{rb.html("おまかせ")}</b>：{rb.html(f"いまの段階は「{level_name(level)}」（配牌・ツモの良さ {level}）。")}</div>']
    if hint_before:
        lines.append(
            f'<div class="mj-note mj-bad">{rb.html(f"いまはヒントを「打つ前に表示」にしているので、{unit}を数えません（おすすめを見ながら打つと、評価が良くなるため）。下の「コーチ」で「打った後に答え合わせ」か「オフ」にすると、数えます。")}</div>'
        )
    lines.append(f'<div class="mj-sub">{rb.html(reason(preview, unit=unit, counter=counter, ahead=True))}</div>')
    if last is not None:
        decision, time = last
        lines.append(f'<div class="mj-sub">{rb.html(f"前回の変更（{date_text(time)}）：{reason(decision, unit=unit, counter=counter)}")}</div>')
    lines.append('<ul class="mj-rules mj-sub">' + "".join(f"<li>{rb.html(line)}</li>" for line in rule_lines(mode)) + "</ul>")
    return "".join(lines)


def news_text(decision: AutoDecision) -> str:
    """段階を変えたときの知らせ（短く。画面の下に、少しのあいだ出す）"""
    verb = "下げました" if decision.changed < 0 else "上げました"
    return f"おまかせ：ツキ補正を「{level_name(decision.before)}」から「{level_name(decision.level)}」に{verb}（理由は、設定のツキ補正のところ）。"

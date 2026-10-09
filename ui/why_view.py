"""「なぜ？」の折りたたみ：局面について質問する。

    よくある質問    押すと、アプリの計算をつないだ答え（テンプレート）を出す。AI のキーがあれば、AI が分かりやすく言い直す
                    （数・牌・役は、計算と照らし合わせる。合わなければ、計算をそのまま出す）。
    自分で質問      AI が、アプリの計算と、用語辞典・役図鑑などを根拠に答える（キーが要る）。
                    計算と照らし合わせられない数などは〔?〕で伏せる。

同じ局面の同じ質問は、前の答えを使う（AI を何度も呼ばない）。
"""
from __future__ import annotations

import re
from html import escape

import streamlit as st

from narration.facts import Facts
from narration.service import AI, ERROR, MASKED, NOTE_FALLBACK, TEMPLATE, Answer, ask, narrate
from ui.ai_access import AiAccess
from ui.components.choices import Option, choice_buttons
from ui.ruby import Rubifier

WHY_TITLE = "なぜ？（この局面について質問する）"
SOURCE_LABELS = {
    TEMPLATE: "アプリの計算より",
    AI: "AI の説明（数・牌・役は、アプリの計算と照らし合わせ済み）",
    MASKED: "AI の説明（計算と照らし合わせられない部分は〔?〕）",
}
README_HINT = "AI のキーの入れ方は、README の「AI による解説（任意）」にあります。"


#: 行の途中で割らない、ひとまとまりの書き方（牌の名前「赤5萬」、「残り 3 枚」、「3,900 点」など）
_TOGETHER = re.compile(r"(赤?[1-9]+(?:萬|筒|索)|残り \d+ 枚|\d[\d,]* (?:点|符|翻|枚|種|向聴|巡目))")


def keep_together(html: str) -> str:
    """文の中の牌の名前や数と単位を、行の途中で割れないようにする（文字の部分だけ。タグの中には触れない）"""
    parts = re.split(r"(<[^>]+>)", html)
    return "".join(part if part.startswith("<") else _TOGETHER.sub(r'<span class="mj-nw">\1</span>', part) for part in parts)


def answer_html(answer: Answer, rb: Rubifier) -> str:
    """答えのカード（出どころの札・本文・ひとこと）"""
    if answer.source == ERROR:
        return f'<div class="mj-card mj-qa mj-qa-error"><div class="mj-note">{rb.html(answer.note)}</div></div>'
    lines = []
    for line in answer.text.splitlines():
        lines.append(f'<div class="mj-qa-line">{keep_together(rb.html(line))}</div>' if line.strip() else '<div class="mj-qa-gap"></div>')
    label = SOURCE_LABELS.get(answer.source, "")
    model = f'<span class="mj-qa-model">{escape(answer.model)}</span>' if answer.by_ai and answer.model else ""
    note = f'<div class="mj-sub mj-qa-note">{rb.html(answer.note)}</div>' if answer.note else ""
    cls = "mj-qa-ai" if answer.by_ai else "mj-qa-template"
    return (
        f'<div class="mj-card mj-qa {cls}"><div class="mj-qa-label">{rb.html(label)}{model}</div>'
        f'<div class="mj-qa-body">{"".join(lines)}</div>{note}</div>'
    )


def _intro(access: AiAccess) -> str:
    if access.available:
        return ("よくある質問を選ぶと、アプリの計算をもとに説明します（AI が言い直します。数・牌・役は計算と照らし合わせます）。"
                "下の欄に、自分で質問を書くこともできます。")
    return "よくある質問を選ぶと、アプリの計算をもとに説明します。"


def _passphrase_form(access: AiAccess, key: str, rb: Rubifier) -> None:
    st.html(f'<div class="mj-sub">{rb.html("自分で書いた質問には AI が答えます。このアプリでは、AI を使うのに合言葉が要ります。")}</div>')
    if access.locked_out:
        st.html(f'<div class="mj-sub">{rb.html("合言葉を何度も間違えたので、いまは受け付けていません。ページを開き直してください。")}</div>')
        return
    with st.form(key=f"{key}_unlock", border=False):
        phrase = st.text_input("合言葉", type="password", key=f"{key}_phrase")
        remember = st.checkbox(
            "この端末で覚える", key=f"{key}_remember", disabled=not access.can_remember,
            help=None if access.can_remember else "いまは、この端末のブラウザに記録を残せないので、覚えられません。",
        )
        if st.form_submit_button("AI を使う"):
            if access.unlock(phrase or "", remember=remember) or access.locked_out:
                st.rerun()              # 開いた（または、もう受け付けない）ことを、すぐ画面に出す
            else:
                st.error("合言葉が違います。")


def _free_question(facts: Facts, access: AiAccess, key: str, rb: Rubifier) -> None:
    settings = access.settings
    if settings is None:
        st.html(f'<div class="mj-sub">{rb.html("AI の設定ファイル（data/ai.yaml）を読めなかったので、AI は使いません。" + access.settings_error)}</div>')
        return
    if not access.has_key:
        st.html(f'<div class="mj-sub">{rb.html("自分で書いた質問に答えるには、AI のキーが要ります（いまは、よくある質問だけ使えます）。" + README_HINT)}</div>')
        return
    if not access.unlocked:
        _passphrase_form(access, key, rb)
        return
    budget = access.budget
    limit = settings.limits.question_chars
    with st.form(key=f"{key}_form", border=False):
        question = st.text_input(
            "自分で質問する", max_chars=limit, key=f"{key}_text",
            placeholder="例：なぜ 2萬 ではなく、この牌なの？", help=f"{limit} 文字まで。AI が、この局面の計算をもとに答えます。",
        )
        sent = st.form_submit_button("AI に聞く", disabled=budget.left <= 0)
    if sent and question and question.strip():
        with st.spinner("AI が考えています…"):
            answer = ask(facts, question, access.client(), settings, budget)
        st.session_state[f"{key}_free"] = {"facts": facts.key, "question": question.strip(), "answer": answer}
    last = st.session_state.get(f"{key}_free")
    if isinstance(last, dict) and last.get("facts") == facts.key:
        st.html(f'<div class="mj-sub">{rb.html("質問：" + last["question"])}</div>' + answer_html(last["answer"], rb))
    st.html(f'<div class="mj-sub">{rb.html(f"AI は、この接続であと {budget.left} 回使えます（ページを開き直すと、元に戻ります）。")}</div>')
    if access.needs_passphrase and access.remembered:
        # 人に貸す端末などで、覚えた合言葉を消せるように
        st.button("この端末で覚えた合言葉を消す", key=f"{key}_b_forget", on_click=access.forget)


def _picked(facts: Facts, key: str) -> str | None:
    """いまの局面で選んである、よくある質問の鍵（局面が変わったら、選んでいないことにする）"""
    memo = st.session_state.get(f"{key}_pick")
    if isinstance(memo, dict) and memo.get("facts") == facts.key and facts.suggestion(str(memo.get("key"))) is not None:
        return str(memo["key"])
    return None


def _answer(facts: Facts, picked: str, access: AiAccess, *, retry: bool = False) -> Answer:
    """よくある質問の答え。前に作ったものがあれば、それを使う（retry のときだけ、作り直す）。

    AI を使えなかった答え（通信の失敗など）も控えておく。控えないと、画面を描き直すたび（牌を選ぶたび）に
    AI を呼び直して、待たされたり回数を使ったりする。作り直すのは、利用者が「もう一度 AI に聞く」を押したときだけ。
    """
    suggestion = facts.suggestion(picked)
    assert suggestion is not None
    memo = f"{facts.key}|{picked}"
    answer = access.recall(memo)
    if answer is not None and not retry:
        return answer
    client = access.client()
    settings = access.settings
    if client is None or settings is None:
        # AI を使えないときの答え（アプリの計算）は、控えない。控えると、合言葉を入れて AI を使えるようになったあとも、
        # 同じ質問では、ずっとアプリの計算の答えが出てしまう
        return Answer(suggestion.text, TEMPLATE)
    with st.spinner("AI が説明を書いています…"):
        answer = narrate(facts, suggestion, client, settings, access.budget)
    access.keep(memo, answer)
    return answer


def _can_retry(answer: Answer, access: AiAccess) -> bool:
    """AI を使えずにアプリの計算を出した答えで、もう一度 AI に聞けるか（照らし合わせで外したときは、聞き直さない）"""
    return answer.source == TEMPLATE and bool(answer.note) and answer.note != NOTE_FALLBACK and access.available and access.budget.left > 0


def why_box(facts: Facts | None, *, key: str, access: AiAccess, rb: Rubifier, title: str = WHY_TITLE, expanded: bool = False) -> None:
    """「なぜ？」の折りたたみを出す。facts が無い（質問できる局面ではない）ときは何も出さない。

    よくある質問は、ルビを振れる自前の選択肢（ui.components.choices）で並べる。折りたたみの名前にはルビを振れないので、
    title には用語（打牌・聴牌など）を入れない。
    """
    if facts is None or not facts.suggestions:
        return
    with st.expander(title, expanded=expanded, key=f"{key}_x"):
        inner = rb.fork()
        st.html(f'<div class="mj-sub">{inner.html(_intro(access))}</div>')
        picked = _picked(facts, key)
        rev_key = f"{key}_rev"
        retry_key = f"{key}_retry"

        def on_pick(keys: list[str]) -> None:
            st.session_state[f"{key}_pick"] = {"facts": facts.key, "key": keys[0]}
            st.session_state[rev_key] = (st.session_state.get(rev_key, 0) + 1) % 100_000

        # 番号には局面の鍵も混ぜる。局面が変わったら、前の局面で選んだ質問の印を消す（答えは、選び直したときに出す）
        rev = (st.session_state.get(rev_key, 0) * 1_000_003 + int(facts.key[:8], 16)) % 1_000_000_000
        choice_buttons(
            [Option(s.key, inner.parts(s.question)) for s in facts.suggestions], key=f"{key}_choices",
            rev=rev, on_pick=on_pick, layout="chips", selected=[picked] if picked else [],
        )
        if picked is not None:
            memo = f"{facts.key}|{picked}"
            answer = _answer(facts, picked, access, retry=st.session_state.pop(retry_key, None) == memo)
            st.html(answer_html(answer, inner))
            if _can_retry(answer, access):
                st.button("もう一度 AI に聞く", key=f"{key}_b_retry", on_click=lambda: st.session_state.__setitem__(retry_key, memo))
        _free_question(facts, access, key, inner)

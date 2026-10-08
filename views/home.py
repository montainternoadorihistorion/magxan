"""ホーム"""
import streamlit as st

from ui.ruby import Rubifier
from ui.version import APP_NAME, APP_PHASE, APP_VERSION

rb = Rubifier()      # 用語のルビは、この画面で最初に出てきたときだけ振る。文章は画面の上から順に作る


def _list(items: list[str], ruby: Rubifier) -> str:
    return '<ul class="mj-rules">' + "".join(f"<li>{ruby.rich(item)}</li>" for item in items) + "</ul>"


def _head(text: str) -> None:
    st.html(f'<div class="mj-subhead mj-home-head">{rb.html(text)}</div>')


def _link(page: str, label: str, icon: str) -> None:
    """各ページへのリンク。押せることが分かるように、枠のあるボタンの形で出す（形は ui/layout.py の st-key-hm_link_…）"""
    with st.container(key=f"hm_link_{page.rsplit('/', 1)[-1].removesuffix('.py')}"):
        st.page_link(page, label=label, icon=icon)


st.title(APP_NAME)
st.caption(f"版 {APP_VERSION} ／ {APP_PHASE}")

st.html(
    '<div class="mj-note">'
    + rb.rich(
        "友人と卓を囲んで、楽しく打てるようになるための練習場です。**打つ**（CPU と対局・一人練習・点数計算）と、"
        "**学ぶ**（役図鑑・用語辞典・ドリル・卓での手順）を行き来しながら、少しずつ進めてください。"
    )
    + "</div>"
)

# ---------------------------------------------------------------- 打つ
_head("打つ")
_link("views/game.py", "CPU と対局", ":material/groups:")
st.html(
    _list(
        [
            "CPU 3 人と、**東風戦**を通しで打つ（半荘戦も選べる）。**ポン・チー・カン**もある（設定で、門前だけにもできる）",
            "対局中のコーチ：おすすめの打牌、役の候補、リーチとダマの比べ方。鳴けるときは、**鳴く・鳴かないの比べ方**（役が残るか・打点・速さ）。"
            "リーチを受けたら、牌ごとの**危険度と根拠**（現物・スジ・壁・字牌）と、ベタオリの手順",
            "局が終わると、CPU 全員の手牌と待ちを見られる（「この河で、この待ちだった」）。**牌譜**で、局を 1 手ずつ振り返れる（自分の判断の評価つき）。"
            "ツキ補正は、自分と CPU で別々に決められる",
        ],
        rb,
    )
)
_link("views/practice.py", "一人練習", ":material/playing_cards:")
st.html(
    _list(
        [
            "配牌からツモと打牌をくり返し、**どれを切ると聴牌に近づくか**を練習する。コーチが、向聴数・受け入れ・おすすめの打牌を出す",
            "**ツキ補正**で、配牌とツモの引きの良さを上げられる（強さはいつも画面に出て、成績も補正ごとに分けて記録）",
            "**役指定練習**：狙う役を 1 つ決めると、配牌とツモがその役に近づき、コーチも「その役に近い切り方」を勧める",
        ],
        rb,
    )
)
_link("views/score_lab.py", "点数計算ラボ", ":material/calculate:")
st.html(
    _list(
        [
            "あがった手の点数を、読み方 → 役 → ドラ → 符 → 点数 → 支払い → 申告 の順に、計算の途中まですべて表示する",
            "例題 43 題、ランダムな手、自分で入力した手。ルール（喰いタン・赤ドラなど）を変えて、計算の違いも見られる",
        ],
        rb,
    )
)

# ---------------------------------------------------------------- 学ぶ
_head("学ぶ")
_link("views/yaku_book.py", "役図鑑", ":material/menu_book:")
st.html(
    _list(
        [
            "すべての役の、条件・成立する例・**ひっかけ**（付きそうで付かない例）・複合・狙い方のコツ・名前の由来",
            "一人練習で成立させた役には**スタンプ**が付く。「この役を実戦で練習する」から、役指定練習を始められる",
        ],
        rb,
    )
)
_link("views/glossary.py", "用語辞典", ":material/dictionary:")
st.html(_list(["麻雀の言葉の、読み・意味・由来。言葉でさがせる（ひらがな・カタカナ・漢字のどれでも）"], rb))
_link("views/drill.py", "ドリル", ":material/quiz:")
st.html(
    _list(
        [
            "用語の読み、役の翻数、成立・不成立、役の判定、あがれる？、待ち、符、点数早見、点数計算、何切る、危険牌",
            "間違えた問題は、**間隔をあけてもう一度**出す（10 分 → 1 日 → 3 日 → 7 日 …）",
        ],
        rb,
    )
)
_link("views/table_guide.py", "卓で打つとき", ":material/table_restaurant:")
st.html(_list(["実際の卓での手順：席決め、山と配牌、発声（ポン・チー・カン・リーチ・ロン・ツモ）、点棒のやり取り、作法と反則"], rb))
_link("views/rules.py", "ルールの違い", ":material/rule:")
st.html(_list(["打つ場所によって違うルールの一覧と、**卓に着く前に確かめること**"], rb))

# ---------------------------------------------------------------- 記録
_head("記録")
_link("views/records.py", "記録と保存", ":material/save:")
st.html(_list(["成績・スタンプ・ドリルの記録を、ファイルに保存したり、読み込んだりできる（記録は、このブラウザの中にある）"], rb))

PLAN = (
    ("Phase 5", "AI による解説と自由質問、カリキュラム、おまかせ補正、卒業判定（すべての条件をまとめて）"),
)

with st.expander("このあとの予定", key="hm_x_plan"):
    inner = rb.fork()      # 折りたたみの中身は、別に数える（閉じていると読まれないので）
    rows = "".join(f'<tr><td style="white-space:nowrap">{name}</td><td>{inner.html(text)}</td></tr>' for name, text in PLAN)
    st.html(f'<table class="mj-table"><tr class="mj-dim"><td>段階</td><td>内容</td></tr>{rows}</table>')

st.page_link("views/device_check.py", label="実機チェック（端末の画面と反応の確認）", icon=":material/smartphone:")

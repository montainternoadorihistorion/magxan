"""用語の読み。

麻雀の用語は漢字の読みが難しいので、画面では最初に出てきたときにルビ（読みがな）を振る。
ここはその元になる「用語 → 読み」の表。

    * 用語辞典（data/terms.yaml）で ruby: true としてある見出し語
    * 役の名前（役の表 yaku_table.py から）
    * 辞典の見出しにはなっていないが、文章に出てくる語（下の _EXTRA）
"""
from __future__ import annotations

from engine.content import glossary
from engine.yaku_table import YAKU

#: 辞典では 1 つの項目（東場・東家）にまとめて説明している語と、役の表に無い役の名前
_EXTRA: dict[str, str] = {
    "南場": "ナンバ",
    "西場": "シャーバ",
    "北場": "ペーバ",
    "南家": "ナンチャ",
    "西家": "シャーチャ",
    "北家": "ペーチャ",
    "人和": "レンホー",          # このアプリでは役にしない（ルールの違いのページと、地和のページに出てくる）
    "四喜和": "スーシーホー",    # 小四喜と大四喜の古い呼び名（出典の統計は、この名前でまとめて数えている）
    # 1 文字の用語（河＝ホー・翻＝ハン）を含むが、読みの違う語。ここに無いと「河底牌」の「河」に「ホー」と振ってしまう
    "河底牌": "ホウテイパイ",
    "河底": "ホウテイ",
    "翻牌": "ファンパイ",
    "四倍満": "ヨンバイマン",    # 数え役満を役満にしないルールでの呼び名（「倍満」の部分にだけ読みが付かないように）
    "打点": "ダテン",            # あがったときの点数の高さ（カリキュラム・鳴きの判断のコーチに出てくる）
}


def _build() -> dict[str, str]:
    readings = {term.term: term.reading for term in glossary().terms if term.ruby}
    for term, reading in _EXTRA.items():
        readings.setdefault(term, reading)
    for info in YAKU.values():
        if " " not in info.name:          # 「役牌 白」のように空白を含む名前は、用語「役牌」のルビで足りる
            readings.setdefault(info.name, info.reading.replace(" ", ""))
    return readings


#: 用語 → 読み（カタカナ）
READINGS: dict[str, str] = _build()

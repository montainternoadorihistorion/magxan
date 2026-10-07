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

#: 辞典では 1 つの項目（東場・東家）にまとめて説明している語
_EXTRA: dict[str, str] = {
    "南場": "ナンバ",
    "西場": "シャーバ",
    "北場": "ペーバ",
    "南家": "ナンチャ",
    "西家": "シャーチャ",
    "北家": "ペーチャ",
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

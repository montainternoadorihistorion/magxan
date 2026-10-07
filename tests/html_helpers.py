"""HTML の文字列を確かめるための道具（タグの対応、牌の画像、読める文字の取り出し）"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOID_TAGS = {"img", "br"}


class _Checker(HTMLParser):
    """タグの開き閉じが対応していることを確かめる"""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs)["src"])
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.problems.append(f"閉じタグ </{tag}> が対応していない")


def check_html(html: str) -> list[str]:
    """タグが対応していることを確かめ、使われている画像の場所を返す"""
    checker = _Checker()
    checker.feed(html)
    assert not checker.problems and not checker.stack, (checker.problems, checker.stack)
    return checker.images


def check_tile_images(html: str) -> None:
    """HTML の中の牌の画像が、すべて実在することを確かめる"""
    for src in check_html(html):
        assert (ROOT / "static" / "tiles" / src.rsplit("/", 1)[1]).is_file(), src


def text_of(html: str) -> str:
    """HTML から、読める文字だけを取り出す（ルビの読みとタグを除く）"""
    return re.sub(r"<[^>]+>", "", re.sub(r"<rt>.*?</rt>", "", html))


def ruby_terms(html: str) -> list[str]:
    """ルビが振られている用語（振られた順。同じ用語が 2 回あれば 2 回入る）"""
    return re.findall(r"<ruby>([^<]+)<rt>", html)


def headings_of(html: str) -> list[str]:
    """解説の見出し（<h3 class="mj-h3">）の文字。ルビの読みは除く"""
    return [text_of(inner) for inner in re.findall(r'<h3 class="mj-h3">(.*?)</h3>', html, flags=re.DOTALL)]


def page_html(at) -> str:
    """画面なしのテスト（AppTest）で、st.html で出した内容をつなげたもの。共通のスタイルは除く"""
    html = "".join(element.proto.body for element in at.get("html"))
    return re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)


class _RubyParts(HTMLParser):
    """HTML を、画面に出る順の（文字, 読みが付いているか）の列にする"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[tuple[str, bool]] = []
        self.stack: list[str] = []      # 開いているタグ（読み付きのものは "+"、読みそのものは "rt"、読まないものは "-"）

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        if tag == "ruby" or {"mj-term", "mj-asked"} & set((dict(attrs).get("class") or "").split()):
            # ルビを振った用語、読みをすぐ横に並べて書いた名前、読みを答えさせる問題の文（わざと読みを隠している）
            self.stack.append("+")
        elif tag in ("rt", "style", "script"):
            self.stack.append("rt" if tag == "rt" else "-")
        else:
            self.stack.append("")

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if data and "rt" not in self.stack and "-" not in self.stack:
            self.parts.append((data, "+" in self.stack))


def ruby_parts(html: str) -> list[tuple[str, bool]]:
    """HTML を、画面に出る順の（文字, 読みが付いているか）の列にする（ui.ruby.missing_ruby に渡す形）"""
    parser = _RubyParts()
    parser.feed(html)
    return parser.parts


#: 文字そのものが内容になっている部品（AppTest の type）
_TEXT_TYPES = {"title", "header", "subheader", "caption", "markdown", "info", "success", "warning", "error", "text"}
#: 開かないと中身が読まれない入れ物（中身は、別の範囲として扱う）
_FOLDED_TYPES = {"expander", "popover"}
#: 開くまで選択肢が画面に出ない部品（選んである値は入力欄の中に出るので、ルビを振れない。すぐ下の説明文で読みを見せる）
_DROPDOWN_TYPES = {"selectbox", "multiselect"}


def _component_texts(proto) -> list[tuple[str, bool]]:
    """ブラウザの中で描く自前の部品に渡した文字（選択肢の部品には、ルビつきの文字を渡している）"""
    try:
        data = json.loads(proto.json) if proto.json else {}
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    texts: list[tuple[str, bool]] = []

    def add(name: str) -> None:
        if isinstance(data.get(name), str) and data[name]:
            texts.append((data[name], False))

    if proto.component_name == "mjdojo_choices":
        for option in data.get("options") or []:
            texts.extend((text, bool(reading)) for text, reading in option.get("parts") or [] if text)
        if data.get("multi"):               # 案内文と確定ボタンは、いくつも選ぶ問題のときだけ出る
            add("prompt")
            add("confirmLabel")
    elif proto.component_name == "mjdojo_tile_hand":
        add("prompt")
        add("confirmLabel")
    elif proto.component_name == "mjdojo_copy_button":
        add("label")
    return texts


def page_parts(at) -> list[tuple[str, bool, int]]:
    """画面なしのテスト（AppTest）の画面を、出る順の（文字, 読みが付いているか, 範囲）の列にする（ui.ruby.missing_ruby に渡す形）。

    st.html で出した内容だけでなく、ルビを振れない場所の文字（ボタン・入力欄・折りたたみ・リンクの名前、案内の文）も入れる。
    そこに出てくる用語は、先に読みつきで出ていなければ「振り忘れ」になる。
    範囲 0 は、いつも見えている部分。折りたたみの中身は、折りたたみごとに別の番号（名前は、外側の範囲）。
    """
    parts: list[tuple[str, bool, int]] = []
    counter = 0

    def add(text: object, scope: int, has_ruby: bool = False) -> None:
        if isinstance(text, str) and text.strip():
            parts.append((text, has_ruby, scope))

    def walk(node, scope: int) -> None:
        nonlocal counter
        kind = getattr(node, "type", "")
        children = getattr(node, "children", None)
        if children is not None:
            inner = scope
            if kind in _FOLDED_TYPES:
                add(getattr(node, "label", ""), scope)
                counter += 1
                inner = counter
            for child in children.values():
                walk(child, inner)
            return
        proto = getattr(node, "proto", None)
        if kind == "html":
            body = re.sub(r"<style>.*?</style>", "", proto.body, flags=re.DOTALL)
            parts.extend((text, has, scope) for text, has in ruby_parts(body))
        elif kind == "bidi_component":
            parts.extend((text, has, scope) for text, has in _component_texts(proto))
        elif kind == "page_link":
            add(proto.label, scope)
        elif kind == "progress":
            add(proto.text, scope)
        elif kind in _TEXT_TYPES:
            add(getattr(node, "value", ""), scope)
        else:
            visibility = getattr(getattr(proto, "label_visibility", None), "value", 0)
            if visibility == 0:                       # 見えている名前だけ（隠した名前は、画面に出ない）
                add(getattr(node, "label", ""), scope)
            add(getattr(node, "placeholder", ""), scope)
            if kind not in _DROPDOWN_TYPES:           # 開くまで選択肢が出ない部品は、名前だけ
                for option in getattr(node, "options", None) or []:
                    add(option, scope)

    walk(at.main, 0)
    return parts

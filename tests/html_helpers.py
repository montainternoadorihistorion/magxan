"""HTML の文字列を確かめるための道具（タグの対応、牌の画像、読める文字の取り出し）"""
from __future__ import annotations

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
        if tag == "ruby" or "mj-term" in (dict(attrs).get("class") or "").split():
            self.stack.append("+")      # ルビを振った用語、または、読みをすぐ横に並べて書いた名前
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

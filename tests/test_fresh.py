"""コードの更新に気づいて、古いモジュールを捨てる仕組み（ui/fresh.py）のテスト"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ui.fresh import drop_stale_modules, process_start_time, source_stamp

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("engine", "ui")


def make_tree(tmp_path: Path) -> Path:
    for name, text in {
        "engine/__init__.py": "",
        "engine/tiles.py": "X = 1\n",
        "engine/scoring/judge.py": "Y = 2\n",
        "ui/__init__.py": "",
        "ui/components/hand/hand.js": "// js\n",
        "ui/__pycache__/x.pyc": "ignored",
        "views/home.py": "import streamlit\n",
        "notes.txt": "ignored",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def loaded() -> dict:
    """読み込み済みモジュールの表（のつもりの辞書）"""
    names = ["engine", "engine.tiles", "engine.scoring.judge", "ui", "ui.layout", "streamlit", "enginex", "ui_extra", "views.home"]
    return {name: object() for name in names}


def touch(path: Path, seconds_later: float = 5.0) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + int(seconds_later * 1e9)))


def test_stamp_lists_own_sources_only(tmp_path):
    root = make_tree(tmp_path)
    names = [entry[0] for entry in source_stamp(root, PACKAGES)]
    assert names == ["engine/__init__.py", "engine/scoring/judge.py", "engine/tiles.py", "ui/__init__.py", "ui/components/hand/hand.js"]


def test_nothing_is_dropped_when_nothing_changed(tmp_path):
    root = make_tree(tmp_path)
    holder: dict = {}
    modules = loaded()
    before = dict(modules)
    assert drop_stale_modules(root, PACKAGES, holder, modules, started_at=time.time() + 60) == []     # 最初の表示（ふつうの起動）
    assert drop_stale_modules(root, PACKAGES, holder, modules, started_at=time.time() + 60) == []     # 2 回目
    assert modules == before


def test_own_modules_are_dropped_after_a_file_changes(tmp_path):
    root = make_tree(tmp_path)
    holder: dict = {}
    modules = loaded()
    drop_stale_modules(root, PACKAGES, holder, modules, started_at=time.time() + 60)

    touch(root / "engine" / "tiles.py")
    dropped = drop_stale_modules(root, PACKAGES, holder, modules, started_at=time.time() + 60)
    assert sorted(dropped) == ["engine", "engine.scoring.judge", "engine.tiles", "ui", "ui.layout"]
    assert sorted(modules) == ["enginex", "streamlit", "ui_extra", "views.home"]      # よその物や、名前が似ているだけの物は残す
    assert drop_stale_modules(root, PACKAGES, holder, modules, started_at=time.time() + 60) == []     # 次の表示では、もう捨てない


def test_added_removed_and_asset_files_count_as_changes(tmp_path):
    root = make_tree(tmp_path)
    holder: dict = {}
    drop_stale_modules(root, PACKAGES, holder, loaded(), started_at=time.time() + 60)

    (root / "engine" / "new_module.py").write_text("Z = 3\n")
    assert drop_stale_modules(root, PACKAGES, holder, loaded(), started_at=time.time() + 60)
    (root / "engine" / "new_module.py").unlink()
    assert drop_stale_modules(root, PACKAGES, holder, loaded(), started_at=time.time() + 60)
    touch(root / "ui" / "components" / "hand" / "hand.js")           # 画面部品の JavaScript が変わった
    assert drop_stale_modules(root, PACKAGES, holder, loaded(), started_at=time.time() + 60)
    touch(root / "views" / "home.py")                                 # ページの本体は Streamlit が読み直すので、対象外
    touch(root / "notes.txt")
    assert drop_stale_modules(root, PACKAGES, holder, loaded(), started_at=time.time() + 60) == []


def test_first_display_drops_modules_if_files_changed_after_the_server_started(tmp_path):
    """見張りを入れて最初の表示。サーバーの起動よりあとに書き換わったファイルがあれば、古いモジュールが残っている"""
    root = make_tree(tmp_path)
    modules = loaded()
    long_ago = time.time() - 3600
    assert sorted(drop_stale_modules(root, PACKAGES, {}, modules, started_at=long_ago)) == [
        "engine", "engine.scoring.judge", "engine.tiles", "ui", "ui.layout",
    ]
    # 起動した時刻が分からない環境では、最初の表示では何もしない
    modules = loaded()
    assert drop_stale_modules(root, PACKAGES, {}, modules, started_at=None) == []
    assert len(modules) == len(loaded())


def test_process_start_time_is_in_the_past():
    started = process_start_time()
    if started is not None:              # Linux 以外では求められない
        assert 0 < time.time() - started < 7 * 24 * 3600


def test_real_tree_has_a_stamp_and_app_uses_the_guard():
    stamp = source_stamp(ROOT, PACKAGES)
    names = {entry[0] for entry in stamp}
    assert {"engine/tiles.py", "ui/fresh.py", "ui/components/tile_hand/tile_hand.js"} <= names
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    guard = app.index("drop_stale_modules")
    assert guard < app.index("from ui.layout import")       # 自作モジュールを読み込む前に、見張りを通す

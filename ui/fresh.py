"""コードが更新されたとき、古いまま残っている自作モジュールを捨てる。

Streamlit は、だれも接続していないあいだにファイルが書き換わっても気づかない。
ページの本体（app.py と views/）は次の表示で読み直されるが、すでに読み込み済みのモジュール
（engine/ と ui/）は、古い内容のまま使われ続ける。

Streamlit Community Cloud への反映（GitHub に push → サーバーがファイルを書き換える）は、
ふつう、だれも画面を開いていないときに起きる。すると「新しいページが、古いモジュールを呼ぶ」状態になり、
引数が合わないなどのエラーになる（実際に起きた: 新しく足した引数を、古い関数が受け取れなかった）。

そこで、表示のたびに自作モジュールのファイルの更新時刻を見て、前回から変わっていたら
読み込み済みの自作モジュールをすべて捨てる。捨てたモジュールは、このあとの import で読み直される。
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable, MutableMapping
from pathlib import Path

SUFFIXES = (".py", ".js", ".css", ".html")
_STAMP = "stamp"
_UNKNOWN = object()


def source_stamp(root: Path, packages: Iterable[str]) -> tuple:
    """自作モジュールのファイルの一覧と更新時刻（これが変わったら、コードが更新されたとみなす）"""
    entries = []
    for package in packages:
        for path in sorted((root / package).rglob("*")):
            if path.suffix in SUFFIXES and "__pycache__" not in path.parts and path.is_file():
                stat = path.stat()
                entries.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def process_start_time() -> float | None:
    """このサーバー（プロセス）が起動した時刻。分からない環境では None（Linux でだけ求められる）"""
    try:
        with open("/proc/self/stat", encoding="ascii") as file:
            fields = file.read().rsplit(")", 1)[1].split()
        ticks_after_boot = int(fields[19])          # 起動してから何刻みあとにプロセスが始まったか（stat の 22 番目の項目）
        with open("/proc/uptime", encoding="ascii") as file:
            seconds_since_boot = float(file.read().split()[0])
        return time.time() - seconds_since_boot + ticks_after_boot / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def drop_stale_modules(
    root: Path,
    packages: Iterable[str],
    holder: MutableMapping,
    modules: MutableMapping | None = None,
    started_at: object = _UNKNOWN,
) -> list[str]:
    """コードが更新されていたら、読み込み済みの自作モジュールを捨てる。捨てた名前を返す。

    更新されたとみなすのは次のどちらか。
      * 前回の表示のときと、ファイルの一覧か更新時刻が違う
      * 前回の記録が無く（この見張りを入れて最初の表示）、サーバーの起動よりあとに書き換わったファイルがある

    holder      前回の状態を覚えておく入れ物（サーバーが動いているあいだ残るもの）
    modules     読み込み済みモジュールの表（既定は sys.modules）
    started_at  サーバーが起動した時刻（既定は自分で調べる。テストで差し替えられるように引数にしてある）
    """
    packages = tuple(packages)
    modules = sys.modules if modules is None else modules
    stamp = source_stamp(root, packages)
    previous = holder.get(_STAMP)
    holder[_STAMP] = stamp
    if previous == stamp:
        return []
    if previous is None:
        started = process_start_time() if started_at is _UNKNOWN else started_at
        newest = max((mtime_ns for _, mtime_ns, _ in stamp), default=0) / 1e9
        if not isinstance(started, (int, float)) or newest <= started:
            return []       # 起動してから書き換わったファイルは無い（ふつうの起動）
    prefixes = tuple(f"{package}." for package in packages)
    stale = [name for name in list(modules) if name in packages or name.startswith(prefixes)]
    for name in stale:
        del modules[name]
    return stale

"""エンジンが Streamlit に依存していないことのテスト"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"


def test_engine_sources_do_not_mention_streamlit():
    for path in ENGINE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import streamlit" not in text and "from streamlit" not in text, path
        assert "from ui" not in text and "import ui" not in text, path


def test_importing_engine_does_not_load_streamlit():
    modules = sorted(p.stem for p in ENGINE.glob("*.py") if p.stem != "__init__")
    code = (
        "import sys, importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module('engine.' + name)\n"
        "assert 'streamlit' not in sys.modules, 'engine が streamlit を読み込んでいる'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr

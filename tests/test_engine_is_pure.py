"""エンジン（engine/）と AI の解説（narration/）が Streamlit に依存していないことのテスト"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
NARRATION = ROOT / "narration"
PURE = (ENGINE, NARRATION)


def test_engine_sources_do_not_mention_streamlit():
    for folder in PURE:
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "import streamlit" not in text and "from streamlit" not in text, path
            assert "from ui" not in text and "import ui" not in text, path


def test_engine_does_not_use_narration():
    """エンジンは、AI の解説を知らない（解説は、エンジンの結果を使う側）"""
    for path in ENGINE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from narration" not in text and "import narration" not in text, path


def test_importing_engine_does_not_load_streamlit():
    modules = sorted(
        ".".join(p.relative_to(ROOT).with_suffix("").parts) for folder in PURE for p in folder.rglob("*.py") if p.stem != "__init__"
    )
    assert "engine.scoring.explain" in modules and "narration.service" in modules
    code = (
        "import sys, importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "assert 'streamlit' not in sys.modules, 'engine か narration が streamlit を読み込んでいる'\n"
        "assert 'anthropic' not in sys.modules, 'AI の SDK は、AI を呼ぶときだけ読み込む'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr

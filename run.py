"""Launch TimeClock. Works with any Python: if the dependencies are missing, it re-runs itself in the
project's .venv (creating it and installing requirements.txt the first time)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
DEPS = ("numpy", "PIL", "astral", "tzlocal")


def deps_ok():
    return all(importlib.util.find_spec(m) for m in DEPS)


if __name__ == "__main__":
    if not deps_ok():
        if Path(sys.executable).resolve() == VENV_PY.resolve():
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
        else:
            if not VENV_PY.exists():
                print("First run: creating .venv and installing requirements...")
                subprocess.check_call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
                subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
            sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))
    sys.path.insert(0, str(ROOT))
    from timeclock.gui import main
    main()

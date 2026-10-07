"""Start the web app from any working directory: python run_app.py."""

from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(root / "app.py"), *sys.argv[1:]],
        cwd=root,
    ))

from pathlib import Path
import sys

# 允许直接执行 run_ui.py，不要求先安装成 Python 包。
SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from hrv_app.ui_app import run_app

if __name__ == "__main__":
    run_app()

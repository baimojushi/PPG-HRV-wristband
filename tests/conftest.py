from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "desktop" / "src"
sys.path.insert(0, str(SRC))

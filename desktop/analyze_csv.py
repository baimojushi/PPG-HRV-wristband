from pathlib import Path
import argparse
import json
import sys

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from hrv_app.engine import AnalysisEngine
from hrv_app.legacy_csv import load_csv_into_engine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="读取历史 PPG CSV，自动完成 NN 清洗、HRV 时域/频域与可信度分析。"
    )
    parser.add_argument("csv", type=Path, help="历史 CSV 路径")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="可选：把最终分析摘要写入 JSON"
    )
    args = parser.parse_args()

    engine = AnalysisEngine()
    load_csv_into_engine(args.csv, engine)

    summary = engine.summary_dict()
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)

    if args.json:
        args.json.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

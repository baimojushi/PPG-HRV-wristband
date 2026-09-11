"""ECG/public-data validation framework for the v0.4.1 interval core."""

from .runner import run_record, write_report
from .types import BenchmarkRecord, RecordMetrics

__all__ = ["BenchmarkRecord", "RecordMetrics", "run_record", "write_report"]

"""Research-only fixed-eight S2 API. No application integration."""
from .api import evaluate_csv_bytes, evaluate_csv_text, evaluate_rows

__version__ = "1.0.0"
__all__ = ["evaluate_csv_bytes", "evaluate_csv_text", "evaluate_rows"]

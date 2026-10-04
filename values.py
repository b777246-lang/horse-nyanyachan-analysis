"""CSV/DB共通の値変換。"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
import pandas as pd
from config import KOL_JOCKEY_ALIASES

def normalize_jockey(value):
    if pd.isna(value):
        return ""
    name = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))
    return KOL_JOCKEY_ALIASES.get(name, name)

def decimal_value(value):
    try:
        number = Decimal(unicodedata.normalize("NFKC", str(value)).strip())
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None

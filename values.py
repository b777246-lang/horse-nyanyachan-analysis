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


def parse_racetrack(race_str):
    race_str = str(race_str).strip()
    if not race_str:
        return ""
    char = race_str[0]
    mapping = {
        "東": "東京",
        "中": "中山",
        "福": "福島",
        "京": "京都",
        "阪": "阪神",
        "新": "新潟",
        "札": "札幌",
        "函": "函館",
        "小": "小倉",
        "名": "中京",
    }
    return mapping.get(char, char)

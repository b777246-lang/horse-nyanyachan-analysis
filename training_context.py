"""Read pre-race final-workout courses supplied with the Web input."""
from pathlib import Path
import re
import unicodedata

import pandas as pd


def normalize_trainer(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"^\((?:栗|美)\)\s*", "", text)
    return re.sub(r"\s+", "", text)


def normalize_training_course(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    if text.endswith("坂"):
        return "坂路"
    if "CW" in text or text.endswith("W"):
        return "ウッド"
    return ""


def load_training_courses(source):
    if source is None:
        return {}
    if hasattr(source, "seek"):
        source.seek(0)
    try:
        frame = pd.read_csv(source, encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)
        frame = pd.read_csv(source, encoding="cp932", dtype=str)
    required = {"レースID+馬番", "調教コース"}
    if not required <= set(frame.columns):
        raise ValueError("調教CSVに レースID+馬番・調教コース 列が必要です。")
    result = {}
    for _, row in frame.iterrows():
        entry_id = str(row.get("レースID+馬番", "") or "").strip()
        if not re.fullmatch(r"\d{18}", entry_id):
            continue
        course = normalize_training_course(row.get("調教コース", ""))
        if not course:
            continue
        if entry_id in result and result[entry_id] != course:
            raise ValueError("同じ出走IDに異なる調教コースがあります: " + entry_id)
        result[entry_id] = course
    return result


def default_training_path(source_name, directory="."):
    match = re.fullmatch(r"(\d{8})\.csv", Path(str(source_name)).name)
    return Path(directory) / f"{match.group(1)}training.csv" if match else None

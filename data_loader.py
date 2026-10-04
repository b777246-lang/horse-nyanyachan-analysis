"""CSV入出力の境界。Streamlitや判定処理には依存しない。"""
import glob
import os
import re
from pathlib import Path
import pandas as pd

def load_course_data():
    course_stats = {}
    try:
        df = pd.read_csv("arms及びarms2及びTUA指数の全てが一位.csv", encoding="cp932")
        course_stats["triple"] = df
    except Exception:
        pass

    csv_files = glob.glob("*指数*位のコース別成績.csv")
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        try:
            df = pd.read_csv(filename, encoding="cp932")
            course_stats[filename] = df
        except Exception:
            pass
    return course_stats

def jockey_from_main_row(row):
    # ヘッダーなし元CSV: 16列目=レースID、17列目=騎手。
    value = row.get("jockey", row.get(16, ""))
    return "" if pd.isna(value) else str(value).strip()


def latest_csv(directory=".", *, comments=False):
    pattern = r"\d{8}comment\.csv" if comments else r"\d{8}\.csv"
    candidates = sorted(p for p in Path(directory).iterdir() if p.is_file() and re.fullmatch(pattern, p.name))
    return candidates[-1] if candidates else None


def read_main_csv(source):
    try:
        return pd.read_csv(source, encoding="cp932", header=None, dtype=str)
    except Exception:
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_csv(source, encoding="utf-8", header=None, dtype=str)


def load_comments(source):
    comments = {}
    if source is not None:
        try:
            frame = pd.read_csv(source, encoding="cp932", header=None)
            for _, row in frame.iterrows():
                values = [str(v).strip() for v in row.values if pd.notna(v)]
                if len(values) >= 6 and values[2] and values[5]:
                    comments[values[2]] = values[5]
        except Exception:
            pass
    return comments


MAIN_COLUMNS = (
    'race', 'condition', 'surface', 'distance', 'frame', 'horse_no', 'push_mark',
    'horse_name', 'arms', 'arms2', 'TUA', 'S', 'F', 'fup', 'kol_odds', 'race_id', 'jockey',
)


def normalize_main_frame(frame):
    """CSVの列位置をここで一度だけ名前に変換する。追加列は保持する。"""
    frame = frame.rename(columns={i: name for i, name in enumerate(MAIN_COLUMNS)}).copy()
    missing = [name for name in MAIN_COLUMNS[:14] if name not in frame.columns]
    if missing:
        raise ValueError('メインCSVの必須列が不足しています: ' + ', '.join(missing))
    for name in MAIN_COLUMNS[14:]:
        if name not in frame.columns:
            frame[name] = ''
    return frame

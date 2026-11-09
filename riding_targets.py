"""Shared pre-race riding-target rules backed by date-scoped JRA history."""
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
import unicodedata


VERSION = "riding-targets-1.0.0"
CONTINUING_KEY = "continuing_jockey_target"
CHANGE_KEY = "new_jockey_target"
CONTINUING_COMMENT = "★継続騎乗特注★"
CHANGE_COMMENT = "★テン乗り特注★"
ACTUAL_STATUSES = ("FINISHED", "DEMOTED", "DNF", "DISQUALIFIED")
EXCLUDED_CHANGE_VENUES = frozenset({"福島", "新潟", "小倉"})


@dataclass(frozen=True)
class RidingTargetMatch:
    key: str
    comment: str
    score: int = 0


def _text(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _jockey(value):
    name = re.sub(r"\s+", "", _text(value))
    return {
        "ルメール": "C.ルメール", "レーン": "D.レーン",
        "C.デム": "C.デムーロ", "モレイラ": "J.モレイラ", "キング": "R.キング",
    }.get(name, name)


def _decimal(value):
    try:
        number = Decimal(_text(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _class_group(value):
    name = _text(value).upper().replace("クラス", "")
    if "未勝利" in name:
        return "lower"
    if any(token in name for token in ("1勝", "2勝")):
        return "lower"
    if "3勝" in name:
        return "both"
    if (any(token in name for token in ("オープン", "OPEN", "OP", "リステッド", "G1", "G2", "G3"))
            or name == "L" or name.startswith("L(")):
        return "upper"
    return None


def evaluate_riding_targets(row, previous):
    """Evaluate only from confirmed pre-race fields and one confirmed prior start."""
    fup = _decimal(row.get("fup", row.get("厩舎finish-up", row.get("厩舎F-UP2"))))
    if fup is None or not Decimal("6") <= fup <= Decimal("7") or not previous:
        return ()
    current_jockey, previous_jockey = _jockey(row.get("jockey", row.get("騎手"))), _jockey(previous.get("jockey"))
    finish = previous.get("finish_position")
    if not current_jockey or not previous_jockey or not isinstance(finish, int):
        return ()
    group = _class_group(row.get("class_name", row.get("条件")))
    matches = []
    if current_jockey == previous_jockey:
        if group in {"upper", "both"} and 2 <= finish <= 5:
            matches.append(RidingTargetMatch(CONTINUING_KEY, CONTINUING_COMMENT))
    elif (group in {"lower", "both"} and finish != 1
          and row.get("venue") not in EXCLUDED_CHANGE_VENUES):
        matches.append(RidingTargetMatch(CHANGE_KEY, CHANGE_COMMENT))
    return tuple(matches)


def load_previous_starts(db_path, entrants, *, maximum_gap_days=7):
    """Read the latest actual JRA start before each entrant date, never current/future rows."""
    path = Path(db_path).resolve()
    if not path.is_file() or Path(str(path) + "-wal").exists():
        return {}, "history_db_unavailable"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"race_horses", "races"} <= tables:
            kind = "source"
        elif {"history", "metadata"} <= tables:
            kind = "snapshot"
            columns = {row[1] for row in db.execute("PRAGMA table_info(history)")}
            if "jockey" not in columns:
                return {}, "history_snapshot_without_jockey"
            snapshot_metadata = dict(db.execute("SELECT key,value FROM metadata"))
        else:
            return {}, "history_schema_unsupported"
        result = {}
        for entrant in entrants:
            entry_id = str(entrant.get("entry_id", ""))
            horse_id = str(entrant.get("horse_id", ""))
            day = str(entrant.get("race_date", ""))
            if not re.fullmatch(r"\d{18}", entry_id) or not re.fullmatch(r"\d{10}", horse_id) or not re.fullmatch(r"\d{8}", day):
                continue
            if kind == "source":
                sql = """SELECT h.target_id,h.race_id,r.race_date,h.jockey,
                                h.finish_position,h.finish_status
                         FROM race_horses h JOIN races r USING(race_id)
                         WHERE h.horse_registration_number=? AND r.race_date<?
                           AND h.finish_status IN (?,?,?,?)
                         ORDER BY r.race_date DESC,h.target_id DESC LIMIT 1"""
            else:
                sql = """SELECT target_id,race_id,race_date,jockey,finish_position,finish_status
                         FROM history WHERE horse_registration_number=? AND race_date<?
                           AND finish_status IN (?,?,?,?)
                         ORDER BY race_date DESC,target_id DESC LIMIT 1"""
            record = db.execute(sql, (horse_id, day, *ACTUAL_STATUSES)).fetchone()
            if record:
                previous = dict(record)
                result[entry_id] = previous
        target_days = sorted({str(item.get("race_date", "")) for item in entrants
                              if re.fullmatch(r"\d{8}", str(item.get("race_date", "")))})
        for day in target_days:
            if kind == "source":
                latest = db.execute("SELECT MAX(race_date) FROM races WHERE race_date<?", (day,)).fetchone()[0]
            else:
                latest = snapshot_metadata.get("source_latest_prior_date")
            if not latest:
                return {}, "history_freshness_unknown"
            from datetime import datetime
            if not 0 < (datetime.strptime(day, "%Y%m%d") - datetime.strptime(latest, "%Y%m%d")).days <= maximum_gap_days:
                return {}, "history_db_stale"
        return result, None


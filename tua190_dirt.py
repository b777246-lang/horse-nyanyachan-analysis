"""Research-only TUA190 dirt condition, independent from the fixed S2 eight."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3

from s2_shared.adapter import convert_bytes


CONDITION_ID = 'TUA190_DIRT'
VERSION = 'tua190-dirt-1.0.1'
RESEARCH_ONLY = True
PROSPECTIVE_READY = False
PROSPECTIVE_VERIFIED = False
ACTUAL_STATUSES = ('FINISHED', 'DEMOTED', 'DNF', 'DISQUALIFIED')
FLAT_SURFACES = ('芝', 'ダ')
MAX_HISTORY_GAP_DAYS = 7
_FILE_HASH_CACHE = {}


def _sha_file(path):
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    if key in _FILE_HASH_CACHE:
        return _FILE_HASH_CACHE[key]
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    value = digest.hexdigest()
    _FILE_HASH_CACHE.clear()
    _FILE_HASH_CACHE[key] = value
    return value


def _decimal(raw):
    try:
        value = Decimal(raw)
        return value if value.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _competition_ranks(horses, code):
    values = []
    for horse in horses:
        item = horse.get('indexes', {}).get(code, {})
        value = _decimal(item.get('raw_value')) if item.get('state') == 'observed' else None
        if value is None:
            return None, 'registered_index_invalid_ranking_incomplete:' + code
        values.append((horse['entry_id'], value))
    counts = Counter(value for _, value in values)
    ordered = sorted(values, key=lambda item: item[1], reverse=True)
    ranks, previous, rank = {}, None, None
    for position, (entry_id, value) in enumerate(ordered, 1):
        if position == 1 or value != previous:
            rank = position
        ranks[entry_id] = {'rank': rank, 'tie_size': counts[value], 'value': value}
        previous = value
    return ranks, None


class HistoryReader:
    """Read either the source analysis DB or a TUA190 lightweight snapshot."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError('履歴DBが見つかりません: ' + str(self.path))
        self.bytes = self.path.stat().st_size
        self.mtime_ns = self.path.stat().st_mtime_ns
        if Path(str(self.path) + '-wal').exists():
            raise ValueError('履歴DBにWALが存在するため、単一ファイルの同一性を保証できません。')
        self.sha256 = _sha_file(self.path)
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')
        tables = {row[0] for row in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if {'race_horses', 'races'} <= tables:
            self.kind = 'source_analysis_db'
            self.first_date = self.db.execute('SELECT MIN(race_date) FROM races').fetchone()[0]
        elif {'history', 'metadata'} <= tables:
            self.kind = 'tua190_history_snapshot'
            metadata = dict(self.db.execute('SELECT key,value FROM metadata'))
            if metadata.get('schema_version') != 'tua190-history-1':
                raise ValueError('TUA190履歴軽量DBのschema_versionが不正です。')
            self.metadata = metadata
            self.first_date = metadata.get('source_first_date')
        else:
            raise ValueError('対応する履歴DB形式ではありません。')

    def close(self):
        self.db.close()

    def latest_before(self, day):
        if self.kind == 'source_analysis_db':
            return self.db.execute(
                'SELECT MAX(race_date) FROM races WHERE race_date < ?', (day,)
            ).fetchone()[0]
        return self.db.execute(
            'SELECT MAX(race_date) FROM history WHERE race_date < ?', (day,)
        ).fetchone()[0]

    def history(self, horse_id, day):
        if self.kind == 'source_analysis_db':
            sql = '''SELECT h.target_id,h.race_id,r.race_date,r.surface,
                            h.finish_position,h.popularity,h.finish_status
                     FROM race_horses h JOIN races r USING(race_id)
                     WHERE h.horse_registration_number=? AND r.race_date<?
                       AND h.finish_status IN (?,?,?,?)
                     ORDER BY r.race_date DESC,h.target_id DESC'''
        else:
            sql = '''SELECT target_id,race_id,race_date,surface,finish_position,
                            popularity,finish_status
                     FROM history WHERE horse_registration_number=? AND race_date<?
                       AND finish_status IN (?,?,?,?)
                     ORDER BY race_date DESC,target_id DESC'''
        return [dict(row) for row in self.db.execute(sql, (horse_id, day, *ACTUAL_STATUSES))]

    def identity(self):
        return {'path': str(self.path), 'kind': self.kind, 'sha256': self.sha256,
                'bytes': self.bytes, 'mtime_ns': self.mtime_ns,
                'source_first_date': self.first_date}

    def verify_unchanged(self):
        stat = self.path.stat()
        if stat.st_size != self.bytes or stat.st_mtime_ns != self.mtime_ns:
            raise ValueError('判定中に履歴DBが変更されました。')
        if _sha_file(self.path) != self.sha256:
            raise ValueError('判定中に履歴DBのSHA-256が変化しました。')


def _history_completeness(first_date, target_day, age):
    if not first_date or age is None:
        return False, 'history_coverage_unknown'
    # JRA age is the age in the target calendar year. A flat debut can occur at age 2.
    earliest_possible_year = int(target_day[:4]) - int(age) + 2
    if int(first_date[:4]) > earliest_possible_year:
        return False, 'history_before_database_possible'
    return True, None


def evaluate_csv_bytes(raw, history_db_path):
    """Return one audit row for every CSV horse. Never changes fixed-eight output."""
    converted = convert_bytes(raw)
    base = {
        'schema': 'tua190-dirt-audit-1', 'condition_id': CONDITION_ID,
        'condition_version': VERSION, 'research_only': RESEARCH_ONLY,
        'prospective_ready': PROSPECTIVE_READY,
        'prospective_verified': PROSPECTIVE_VERIFIED,
    }
    if not converted['complete']:
        return {**base, 'status': 'INVALID_INPUT', 'validation_errors': converted['errors'],
                'history_db': None, 'audit': [], 'summary': {}}
    reader = HistoryReader(history_db_path)
    try:
        document = converted['document']
        dates = sorted({race['date'] for race in document['races']})
        earliest = dates[0]
        latest_prior = reader.latest_before(earliest)
        if latest_prior is None:
            freshness = {'state': 'INSUFFICIENT', 'reason': 'no_history_before_target',
                         'latest_prior_race_date': None}
        else:
            target_dt = datetime.strptime(earliest, '%Y%m%d')
            gap = (target_dt - datetime.strptime(latest_prior, '%Y%m%d')).days
            # Prospective audits freeze the exact DB identity used for judgment.
            # Do not require results held after the operator's chosen history cutoff;
            # accept the normal interval between JRA meeting weekends uniformly.
            allowed_gap = MAX_HISTORY_GAP_DAYS
            freshness = {'state': 'CURRENT' if gap <= allowed_gap else 'STALE',
                         'reason': None if gap <= allowed_gap else 'history_db_stale',
                         'latest_prior_race_date': latest_prior, 'gap_days': gap,
                         'maximum_gap_days': allowed_gap}
        audits = []
        for race in document['races']:
            tua_ranks, tua_error = _competition_ranks(race['horses'], 'tua')
            s_ranks, s_error = _competition_ranks(race['horses'], 's')
            for horse in race['horses']:
                raw_columns = horse['raw_columns']
                try:
                    age = int(raw_columns[18]) if raw_columns[18].strip() else None
                except ValueError:
                    age = None
                tua = horse['indexes']['tua']['raw_value']
                s_value = horse['indexes']['s']['raw_value']
                details = {
                    'surface': race['surface'], 'tua_raw': tua, 's_raw': s_value,
                    'tua_rank': tua_ranks[horse['entry_id']]['rank'] if tua_ranks else None,
                    's_rank': s_ranks[horse['entry_id']]['rank'] if s_ranks else None,
                    'age': age, 'previous': None, 'career_jra_flat_before': None,
                    'thresholds': {'tua_min': '190', 'tua_rank_max': 3,
                                   's_rank_max': 8, 'career_max': 25, 'age_max': 6},
                }
                failures, uncertain = [], []
                if race['surface'] != 'ダ':
                    state, reasons = 'OUT_OF_SCOPE', ['surface_not_dirt']
                else:
                    if tua_error or s_error:
                        uncertain.append(tua_error or s_error)
                    if _decimal(tua) is None or _decimal(tua) < Decimal('190'):
                        failures.append('tua_below_190')
                    if details['tua_rank'] is None or details['tua_rank'] > 3:
                        if not tua_error:
                            failures.append('tua_rank_over_3')
                    if details['s_rank'] is None or details['s_rank'] > 8:
                        if not s_error:
                            failures.append('s_rank_over_8')
                    if age is None:
                        uncertain.append('age_unknown')
                    elif age > 6:
                        failures.append('age_over_6')
                    if freshness['state'] != 'CURRENT':
                        uncertain.append(freshness['reason'])
                    else:
                        history = reader.history(horse['horse_id'], race['date'])
                        flat_history = [row for row in history if row['surface'] in FLAT_SURFACES]
                        details['career_jra_flat_before'] = len(flat_history)
                        complete, coverage_reason = _history_completeness(
                            reader.first_date, race['date'], age
                        )
                        if not complete:
                            uncertain.append(coverage_reason)
                        if not history:
                            uncertain.append('no_previous_start')
                        else:
                            previous = history[0]
                            details['previous'] = previous
                            if previous['finish_position'] is None or previous['popularity'] is None:
                                uncertain.append('previous_finish_or_popularity_unknown')
                        if len(flat_history) > 25:
                            failures.append('career_over_25')
                        if history and history[0]['finish_position'] in (1, 2):
                            failures.append('previous_finish_1_or_2')
                        if history and history[0]['popularity'] == 1:
                            failures.append('previous_popularity_1')
                    state = 'NO_MATCH' if failures else ('UNCONFIRMED' if uncertain else 'MATCH')
                    reasons = failures + uncertain
                audits.append({
                    'race_id': race['race_id'], 'date': race['date'],
                    'venue': race['venue'], 'race_no': race['race_no'],
                    'entry_id': horse['entry_id'], 'horse_id': horse['horse_id'],
                    'horse_no': horse['horse_no'], 'horse_name_raw': horse['horse_name_raw'],
                    'condition_id': CONDITION_ID, 'state': state,
                    'and_passed': state == 'MATCH', 'reasons': list(dict.fromkeys(reasons)),
                    'details': details,
                })
        states = Counter(row['state'] for row in audits)
        reader.verify_unchanged()
        return {**base, 'status': 'EVALUATED', 'validation_errors': [],
                'history_db': reader.identity(), 'freshness': freshness,
                'audit': audits, 'summary': {'rows': len(audits), **dict(states)}}
    finally:
        reader.close()

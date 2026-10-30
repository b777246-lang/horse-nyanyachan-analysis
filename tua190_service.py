"""TUA190_DIRT非表示接続。固定8条件や既存表示・出力に結果を混ぜない。"""
from collections import Counter
from contextlib import closing
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3

STATE_KEY = '_tua190_internal_audit'


def _fallback(converted, reason, *, invalid=False):
    rows = []
    for race in (converted.get('document') or {}).get('races', []):
        for horse in race['horses']:
            state = 'INVALID_INPUT' if invalid else ('OUT_OF_SCOPE' if race['surface'] != 'ダ' else 'UNCONFIRMED')
            rows.append(dict(race_id=race['race_id'], entry_id=horse['entry_id'],
                             horse_id=horse['horse_id'], horse_no=horse['horse_no'],
                             condition_id='TUA190_DIRT', state=state, and_passed=None,
                             reasons=['surface_not_dirt' if state == 'OUT_OF_SCOPE' else reason]))
    return dict(condition_id='TUA190_DIRT', status='INVALID_INPUT' if invalid else 'UNCONFIRMED',
                research_only=True, prospective_ready=False, prospective_verified=False,
                audit=rows, summary=dict(Counter(row['state'] for row in rows)),
                validation_errors=converted.get('errors', []), reason=reason)


def _validate_snapshot(path, raw, document):
    """共通判定器の前にWeb受渡しDBの日付・全頭・原CSVとの対応を検証する。"""
    dates = {race['date'] for race in document['races']}
    if len(dates) != 1:
        raise ValueError('multiple_target_dates_not_supported')
    day = next(iter(dates))
    if Path(str(path) + '-wal').exists():
        raise ValueError('history_wal_present')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('history_integrity_error')
        meta = dict(db.execute('SELECT key,value FROM metadata'))
        if meta.get('schema_version') != 'tua190-history-1':
            raise ValueError('history_schema_mismatch')
        if meta.get('target_date') != day or meta.get('input_dates') != day:
            raise ValueError('history_target_date_mismatch')
        if meta.get('input_csv_sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('history_input_sha256_mismatch')
        wanted = {h['horse_id'] for race in document['races'] for h in race['horses']}
        covered = {r[0] for r in db.execute('SELECT horse_registration_number FROM requested_horses')}
        if wanted != covered or meta.get('requested_horses') != str(len(wanted)):
            raise ValueError('history_entrant_coverage_mismatch')
        if db.execute('SELECT 1 FROM history WHERE race_date >= ? LIMIT 1', (day,)).fetchone():
            raise ValueError('history_contains_current_or_future_results')
        latest = meta.get('source_latest_prior_date')
        if not latest:
            raise ValueError('history_freshness_unknown')
        target = datetime.strptime(day, '%Y%m%d')
        gap = (target - datetime.strptime(latest, '%Y%m%d')).days
        allowed = 7
        if not 0 < gap <= allowed:
            raise ValueError('history_db_stale')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_tua190_audit(content, state, *, snapshot_path=None):
    """最新入力だけを保持。毎回検証し、DBの置換・失敗時に古いMATCHを残さない。"""
    if content is None:
        state.pop(STATE_KEY, None)
        return None
    record = dict(input_sha256=hashlib.sha256(content).hexdigest(), status='UNCONFIRMED',
                  research_only=True, prospective_ready=False, prospective_verified=False,
                  history_path=None, history_sha256=None, report=None, error=None)
    converted = {}
    try:
        from s2_shared.adapter import convert_bytes
        converted = convert_bytes(content)
        if not converted['complete']:
            record['report'] = _fallback(converted, 'csv_validation_failed', invalid=True)
        else:
            dates = {race['date'] for race in converted['document']['races']}
            if len(dates) != 1:
                raise ValueError('multiple_target_dates_not_supported')
            path = Path(snapshot_path) if snapshot_path is not None else (
                Path(__file__).resolve().parent / f'tua190_history_{next(iter(dates))}.sqlite')
            record['history_path'] = str(path.resolve())
            if not path.is_file():
                raise ValueError('history_db_missing')
            before = _validate_snapshot(path, content, converted['document'])
            from tua190_dirt import evaluate_csv_bytes
            report = evaluate_csv_bytes(content, path)
            if (report['research_only'] is not True or report['prospective_ready'] is not False
                    or report['prospective_verified'] is not False):
                raise ValueError('research_flags_invalid')
            after = _validate_snapshot(path, content, converted['document'])
            if before != after:
                raise ValueError('history_changed_during_evaluation')
            record['history_sha256'] = after
            record['report'] = report
        record['status'] = record['report']['status']
    except Exception as exc:
        record['error'] = dict(type=type(exc).__name__, message=str(exc))
        record['report'] = _fallback(converted, str(exc))
    state[STATE_KEY] = record
    return record

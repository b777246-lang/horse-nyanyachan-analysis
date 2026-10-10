"""UI-independent cushion statistics shared by Web and Desktop."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import sqlite3
from pathlib import Path

BAND_LABELS = ('6.4以下', '6.5～7.4', '7.5～8.4', '8.5～9.4', '9.5～10.4', '10.5～11.4', '11.5以上')
CUSHION_SOURCES = frozenset({'JRA_PDF_VERIFIED', 'CSV_PROVIDED'})
FINISH_STATUSES = frozenset({'FINISHED', 'DEMOTED', 'DNF', 'DISQUALIFIED'})


def normalize_horse_id(value):
    value = str(value).strip()
    if len(value) != 10 or not value.isascii() or not value.isdigit():
        raise ValueError('血統登録番号は10桁の数字で指定してください')
    return value


def normalize_date(value):
    value = str(value)
    datetime.strptime(value, '%Y%m%d')
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ValueError('日付はYYYYMMDDで指定してください')
    return value


def cushion_band(value):
    """Reject extra decimal precision rather than rounding the original value."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('クッション値が数値ではありません') from exc
    if not number.is_finite() or number <= 0 or number * 10 != (number * 10).to_integral_value():
        raise ValueError('クッション値は正の数・小数第1位までで指定してください')
    for band, upper in enumerate(('6.4', '7.4', '8.4', '9.4', '10.4', '11.4'), 1):
        if number <= Decimal(upper):
            return band
    return 7


def readonly_connection(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def aggregate_history(rows, horse_ids, race_date, cushion_value, *, official_only=False, track=None, distance=None):
    """All requested horses survive; missing returns invalidate that ROI only.

    DNF and DISQUALIFIED count as non-placing starts, with actual returns.
    Unknown/contradictory finish data are reported, never silently accepted.
    """
    day = normalize_date(race_date)
    ids = list(dict.fromkeys(normalize_horse_id(v) for v in horse_ids))
    band = cushion_band(cushion_value) if cushion_value is not None else None
    results = {horse: dict(horse_id=horse, band=band, starts=0, first=0, second=0, third=0,
                           unplaced=0, dnf=0, disqualified=0, win_missing=0, place_missing=0,
                           win_total_yen=0.0, place_total_yen=0.0, source_counts={}, issues=[]) for horse in ids}
    seen = set()
    for row in rows:
        row = dict(row)
        horse = row['horse_registration_number']
        if horse not in results or row['race_date'] >= day or row['surface'] != '芝' or band is None:
            continue
        result = results[horse]
        identity = row['target_id']
        if identity in seen:
            raise ValueError(f'過去走IDの重複: {identity}')
        seen.add(identity)
        if row['cushion_value'] is None:
            continue
        try:
            past_band = cushion_band(row['cushion_value'])
        except ValueError:
            result['issues'].append({'target_id': identity, 'reason': 'invalid_cushion'})
            continue
        if past_band != band or (track is not None and row['venue'] != track) or (distance is not None and row['distance'] != distance):
            continue
        source = row['cushion_status']
        if source not in CUSHION_SOURCES or (official_only and source != 'JRA_PDF_VERIFIED'):
            continue
        if row['bet_eligible'] == 0 and row['finish_status'] in {'CANCELLED', 'EXCLUDED'}:
            continue
        status, position = row['finish_status'], row['finish_position']
        valid_position = isinstance(position, int) and not isinstance(position, bool) and position > 0
        if row['bet_eligible'] != 1 or status not in FINISH_STATUSES or (status in {'FINISHED', 'DEMOTED'} and not valid_position) or (status in {'DNF', 'DISQUALIFIED'} and position is not None):
            result['issues'].append({'target_id': identity, 'reason': 'invalid_finish'})
            continue
        result['starts'] += 1
        bucket = {1: 'first', 2: 'second', 3: 'third'}.get(position, 'unplaced')
        result[bucket] += 1
        result['dnf'] += status == 'DNF'
        result['disqualified'] += status == 'DISQUALIFIED'
        result['source_counts'][source] = result['source_counts'].get(source, 0) + 1
        for kind in ('win', 'place'):
            value = row[f'{kind}_return_yen']
            try:
                payout = Decimal(str(value))
                valid = payout.is_finite() and payout >= 0 and payout == payout.to_integral_value()
            except InvalidOperation:
                valid = False
            if not valid:
                result[f'{kind}_missing'] += 1
                result['issues'].append({'target_id': identity, 'reason': f'invalid_{kind}_return'})
            else:
                result[f'{kind}_total_yen'] += float(payout)
    for result in results.values():
        n = result['starts']
        result['finish_counts'] = f"{result['first']}-{result['second']}-{result['third']}-{result['unplaced']}/{n}"
        for name, hits in [('win_rate', result['first']), ('quinella_rate', result['first'] + result['second']), ('place_rate', result['first'] + result['second'] + result['third'])]:
            result[name] = 100 * hits / n if n else None
        for kind in ('win', 'place'):
            result[f'{kind}_roi'] = result[f'{kind}_total_yen'] / n if n and not result[f'{kind}_missing'] else None
        result['reason'] = 'cushion_unavailable' if band is None else ('no_matching_history' if not n else None)
    return list(results.values())


def get_cushion_stats(snapshot_path, horse_ids, race_date, cushion_value, **filters):
    ids = list(dict.fromkeys(normalize_horse_id(v) for v in horse_ids))
    day = normalize_date(race_date)
    connection = readonly_connection(snapshot_path)
    try:
        metadata = dict(connection.execute('SELECT key,value FROM metadata'))
        if metadata.get('schema_version') != '1':
            raise ValueError('未対応の軽量DB形式です')
        if day > metadata['target_date']:
            raise ValueError('この軽量DBの対象日より後の日付は検索できません。再生成してください')
        rows = []
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            rows.extend(connection.execute(f"SELECT * FROM history WHERE horse_registration_number IN ({','.join('?' for _ in batch)}) AND race_date < ?", (*batch, day)).fetchall())
        results = aggregate_history(rows, ids, day, cushion_value, **filters)
        covered = {r[0] for r in connection.execute('SELECT horse_registration_number FROM requested_horses')}
        for result in results:
            if result['horse_id'] not in covered:
                result['reason'] = 'horse_not_in_snapshot'
        return {'metadata': metadata, 'horses': results}
    finally:
        connection.close()

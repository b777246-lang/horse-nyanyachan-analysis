"""UI-independent sire statistics; use the existing finish/payout/band rules."""
from pathlib import Path
from cushion_stats import (aggregate_history, cushion_band, normalize_date,
                           normalize_horse_id, readonly_connection)

SCHEMA_VERSION = 'sire-1'


def normalize_sire(value):
    # Do not merge names by fuzzy matching, case folding or transliteration.
    return '' if value is None else str(value).strip()


def aggregate_sire_rows(rows, day, value, *, official_only=False):
    rows = [dict(row) for row in rows]
    ids = list(dict.fromkeys(row['horse_registration_number'] for row in rows))
    parts = aggregate_history(rows, ids, day, value, official_only=official_only)
    total = {key: 0 for key in ('starts', 'first', 'second', 'third', 'unplaced',
                                'dnf', 'disqualified', 'win_missing', 'place_missing',
                                'win_total_yen', 'place_total_yen')}
    total.update(source_counts={}, issues=[])
    for part in parts:
        for key in tuple(total):
            if key not in ('source_counts', 'issues'):
                total[key] += part[key]
        total['issues'].extend(part['issues'])
        for source, count in part['source_counts'].items():
            total['source_counts'][source] = total['source_counts'].get(source, 0) + count
    n = total['starts']
    total['finish_counts'] = f"{total['first']}-{total['second']}-{total['third']}-{total['unplaced']}/{n}"
    for key, hits in (('win_rate', total['first']),
                      ('quinella_rate', total['first'] + total['second']),
                      ('place_rate', total['first'] + total['second'] + total['third'])):
        total[key] = 100 * hits / n if n else None
    for kind in ('win', 'place'):
        total[kind + '_roi'] = total[kind + '_total_yen'] / n if n and not total[kind + '_missing'] else None
    return total


def get_sire_stats(snapshot_path, entrants, race_date, cushion_value, *, venue,
                   distance, surface='芝', official_only=False):
    """Retain every entrant; distinguish unknown, uncovered and a genuine zero."""
    day = normalize_date(race_date)
    band = cushion_band(cushion_value) if cushion_value is not None else None
    distance = int(distance)
    with_snapshot = Path(snapshot_path)
    db = readonly_connection(with_snapshot)
    try:
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        if metadata.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('種牡馬専用軽量DBを選択してください')
        if day != metadata['target_date']:
            raise ValueError('種牡馬DBと出馬表の対象日が一致しません。対応するDBを生成してください')
        results, memo = [], {}
        for entrant in sorted(entrants, key=lambda x: int(x['horse_no'])):
            result = dict(entrant, sire_name=normalize_sire(entrant.get('sire_name')), stats=None, reason=None)
            try:
                horse_id = normalize_horse_id(entrant.get('horse_id', ''))
            except ValueError:
                result['reason'] = 'invalid_horse_id'
                results.append(result)
                continue
            covered = db.execute('SELECT sire_name FROM entrant_sires WHERE horse_registration_number=?', (horse_id,)).fetchone()
            if covered is None:
                result['reason'] = 'horse_not_in_snapshot'
            elif result['sire_name'] and result['sire_name'] != covered['sire_name']:
                result['reason'] = 'sire_mismatch'
            else:
                result['sire_name'] = covered['sire_name'] or ''
                if surface != '芝':
                    result['reason'] = 'surface_not_supported'
                elif not result['sire_name']:
                    result['reason'] = 'sire_unknown'
                elif band is None:
                    result['reason'] = 'cushion_unavailable'
                else:
                    sire = result['sire_name']
                    scope = db.execute('SELECT 1 FROM scopes WHERE sire_name=? AND venue=? AND distance=?',
                                       (sire, venue, distance)).fetchone()
                    if scope is None:
                        result['reason'] = 'course_not_in_snapshot'
                    else:
                        if sire not in memo:
                            rows = db.execute('''SELECT * FROM sire_history WHERE sire_name=?
                                AND venue=? AND distance=? AND cushion_band=? AND race_date<?''',
                                (sire, venue, distance, band, day)).fetchall()
                            memo[sire] = aggregate_sire_rows(rows, day, cushion_value, official_only=official_only)
                        result['stats'] = memo[sire]
            results.append(result)
        return {'metadata': metadata, 'horses': results, 'band': band}
    finally:
        db.close()
